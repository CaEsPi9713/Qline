"""
Autenticación y control de acceso por rol (entrega a sucursal · Fase 1).

- Contraseñas: solo se guarda un hash scrypt con sal propia; nunca la contraseña.
- Usuarios: colección `usuarios` (usuario único, rol, estado, ventanilla asignada).
  Quien se registra queda `pendiente` y sin rol; el administrador lo habilita y le asigna el rol.
- Sesión: cookie firmada con HMAC-SHA256. En cada petición se vuelve a leer el usuario en MongoDB,
  de modo que deshabilitarlo o cambiarle el rol surte efecto de inmediato.
- Bloqueo temporal tras varios intentos fallidos y mensajes que no revelan si el usuario existe.

Solo usa la biblioteca estándar. No importa `app.main` (evita importaciones circulares).
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Request
from pymongo.errors import DuplicateKeyError, PyMongoError

log = logging.getLogger("qline.auth")

COLECCION_USUARIOS = "usuarios"

ROL_OPERADOR = "operador"
ROL_SUPERVISOR = "supervisor"
ROL_ADMINISTRADOR = "administrador"
ROLES = (ROL_OPERADOR, ROL_SUPERVISOR, ROL_ADMINISTRADOR)

ESTADO_PENDIENTE = "pendiente"
ESTADO_ACTIVO = "activo"
ESTADO_DESHABILITADO = "deshabilitado"
ESTADOS_USUARIO = (ESTADO_PENDIENTE, ESTADO_ACTIVO, ESTADO_DESHABILITADO)

# Solo letras de la A a la Z (mayúsculas o minúsculas): sin números, tildes, espacios ni símbolos.
PATRON_USUARIO = re.compile(r"[A-Za-z]{3,30}\Z")
LARGO_MIN_CLAVE = 8
LARGO_MAX_CLAVE = 128

# scrypt: 16 MiB de memoria por cálculo, razonable para un servidor pequeño.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_LARGO = 2 ** 14, 8, 1, 32

MAX_INTENTOS = 5
BLOQUEO_SEG = 300

NOMBRE_COOKIE = "qline_sesion"
DURACION_SESION_SEG = 8 * 3600

MENSAJE_CREDENCIALES = "Usuario o contraseña incorrectos."

# Solicitudes de registro sin resolver que se aceptan a la vez (evita llenar la colección desde el formulario público).
MAX_PENDIENTES = 100

# Página a la que lleva el inicio de sesión según el rol.
INICIO_POR_ROL = {ROL_OPERADOR: "/cola", ROL_SUPERVISOR: "/dashboard", ROL_ADMINISTRADOR: "/administracion"}


class AuthError(Exception):
    """Error controlado de autenticación o de alta de usuario; `status` es el HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 400):
        super().__init__(mensaje)
        self.status = status


class NoAutenticado(Exception):
    """No hay una sesión válida: la página debe llevar a /login."""


class SinPermiso(Exception):
    """Hay sesión, pero el rol del usuario no alcanza para esta página."""

    def __init__(self, usuario: dict, roles: tuple):
        super().__init__(f"El rol {usuario.get('rol')!r} no puede entrar; se requiere {roles}.")
        self.usuario = usuario
        self.roles = roles


# --- Contraseñas ----------------------------------------------------------------------------------

def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desb64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _scrypt(clave: str, sal: bytes, n: int, r: int, p: int, largo: int) -> bytes:
    return hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=largo, maxmem=64 * 1024 * 1024)


def validar_clave(clave: str, usuario: str = "") -> None:
    """Política mínima: entre 8 y 128 caracteres y distinta del usuario."""
    if not isinstance(clave, str) or len(clave) < LARGO_MIN_CLAVE:
        raise AuthError(f"La contraseña debe tener al menos {LARGO_MIN_CLAVE} caracteres.")
    if len(clave) > LARGO_MAX_CLAVE:
        raise AuthError(f"La contraseña no puede superar {LARGO_MAX_CLAVE} caracteres.")
    if usuario and clave.strip().lower() == usuario.lower():
        raise AuthError("La contraseña no puede ser igual al nombre de usuario.")


def hashear_clave(clave: str) -> str:
    """`scrypt$N$r$p$sal$hash`: los parámetros viajan con el hash para poder endurecerlos después."""
    sal = secrets.token_bytes(16)
    derivada = _scrypt(clave, sal, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_LARGO)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(sal)}${_b64(derivada)}"


def verificar_clave(clave: str, almacenado: str) -> bool:
    """Compara en tiempo constante. Un hash ilegible o de otro formato nunca coincide."""
    try:
        esquema, n, r, p, sal, esperado = almacenado.split("$")
        if esquema != "scrypt":
            return False
        esperado_b = _desb64(esperado)
        derivada = _scrypt(clave, _desb64(sal), int(n), int(r), int(p), len(esperado_b))
    except (ValueError, TypeError, AttributeError):
        return False
    return hmac.compare_digest(derivada, esperado_b)


# Hash de relleno para que un usuario inexistente tarde lo mismo que uno real.
_HASH_FALSO = hashear_clave(secrets.token_urlsafe(16))


# --- Usuarios -------------------------------------------------------------------------------------

def normalizar_usuario(usuario) -> str:
    if not isinstance(usuario, str):
        raise AuthError("Ingrese un nombre de usuario.")
    nombre = usuario.strip()
    if not PATRON_USUARIO.fullmatch(nombre):
        raise AuthError("El usuario solo puede tener letras, mayúsculas o minúsculas, de 3 a 30: "
                        "sin números, espacios, tildes ni caracteres especiales.")
    return nombre.lower()               # «Ana» y «ana» son la misma cuenta: se guarda y se compara en minúsculas


_con_indice: set = set()


def asegurar_indices(db) -> None:
    """Índices únicos de usuario y de ventanilla asignada (una vez por proceso). Si MongoDB no deja crearlos, el código igual revisa duplicados."""
    clave = id(db)
    if clave in _con_indice:
        return
    try:
        db[COLECCION_USUARIOS].create_index("usuario", unique=True, name="idx_usuarios_usuario_unico")
        # Una ventanilla pertenece a un solo operador, aunque dos supervisores asignen a la vez.
        db[COLECCION_USUARIOS].create_index(
            "ventanilla_asignada", unique=True, name="idx_usuarios_ventanilla_unica",
            partialFilterExpression={"ventanilla_asignada": {"$type": "string"}})
        _con_indice.add(clave)
    except PyMongoError as exc:
        log.warning("No se pudo crear el índice único de usuarios: %s", exc)


def crear_usuario(db, usuario: str, clave: str, rol: Optional[str] = None, estado: str = ESTADO_PENDIENTE,
                  habilitado_por: Optional[str] = None) -> dict:
    """
    Da de alta un usuario. El registro público usa los valores por defecto (pendiente, sin rol);
    solo el administrador, o el script que crea al primer administrador, pasa rol y estado.
    """
    nombre = normalizar_usuario(usuario)
    validar_clave(clave, nombre)
    if rol is not None and rol not in ROLES:
        raise AuthError(f"Rol no válido: {rol!r}.")
    if estado not in ESTADOS_USUARIO:
        raise AuthError(f"Estado no válido: {estado!r}.")
    if estado == ESTADO_ACTIVO and rol is None:
        raise AuthError("Un usuario activo necesita un rol.")

    asegurar_indices(db)
    col = db[COLECCION_USUARIOS]
    if col.find_one({"usuario": nombre}, {"_id": 1}) is not None:
        raise AuthError("Ese nombre de usuario ya está en uso.", 409)
    ahora = datetime.now(timezone.utc)
    doc = {
        "usuario": nombre, "hash": hashear_clave(clave), "rol": rol, "estado": estado,
        "ventanilla_asignada": None, "version_sesion": 1,
        "intentos_fallidos": 0, "bloqueado_hasta": None, "ultimo_acceso": None,
        "creado_en": ahora, "actualizado_en": ahora, "habilitado_por": habilitado_por,
    }
    try:
        col.insert_one(doc)
    except DuplicateKeyError as exc:
        raise AuthError("Ese nombre de usuario ya está en uso.", 409) from exc
    except PyMongoError as exc:
        raise AuthError("No es posible registrar el usuario en este momento.", 503) from exc
    return publico(doc)


def registrar_solicitud(db, usuario: str, clave: str) -> dict:
    """Registro público: queda pendiente y sin rol. Se limita cuántas solicitudes pueden esperar a la vez."""
    try:
        pendientes = db[COLECCION_USUARIOS].count_documents({"estado": ESTADO_PENDIENTE})
    except PyMongoError as exc:
        raise AuthError("No es posible registrar el usuario en este momento.", 503) from exc
    if pendientes >= MAX_PENDIENTES:
        raise AuthError("Hay demasiadas solicitudes pendientes. Pida al administrador que las revise.", 429)
    return crear_usuario(db, usuario, clave)


def asegurar_administrador(db, usuario: str, clave: str, restablecer: bool = False) -> str:
    """
    Crea al administrador (lo usa scripts/crear_admin.py, la única forma de tener el primero) o, con `restablecer`,
    le pone una contraseña nueva, lo deja activo y sin bloqueo y cierra sus sesiones. Devuelve "creado" o "restablecido".
    Nunca convierte en administrador a un usuario que ya existe con otro rol: eso lo hace el administrador desde la app.
    """
    nombre = normalizar_usuario(usuario)
    existente = db[COLECCION_USUARIOS].find_one({"usuario": nombre})
    if existente is None:
        crear_usuario(db, nombre, clave, rol=ROL_ADMINISTRADOR, estado=ESTADO_ACTIVO, habilitado_por="scripts.crear_admin")
        return "creado"
    if not restablecer:
        raise AuthError(f"El usuario {nombre!r} ya existe. Use --restablecer para cambiarle la contraseña.", 409)
    if existente.get("rol") != ROL_ADMINISTRADOR:
        raise AuthError(f"El usuario {nombre!r} existe pero no es administrador; no se modifica desde el script.", 409)
    validar_clave(clave, nombre)
    db[COLECCION_USUARIOS].update_one(
        {"_id": existente["_id"]},
        {"$set": {"hash": hashear_clave(clave), "estado": ESTADO_ACTIVO, "intentos_fallidos": 0, "bloqueado_hasta": None,
                  "actualizado_en": datetime.now(timezone.utc)},
         "$inc": {"version_sesion": 1}})
    return "restablecido"


# --- Gestión de usuarios (la hace el administrador desde /admin/usuarios) ---------------------------

def listar_usuarios(db, ahora: Optional[datetime] = None) -> list:
    """Todos los usuarios sin el hash: primero las solicitudes pendientes, luego activos y deshabilitados."""
    ahora = ahora or datetime.now(timezone.utc)
    orden = {ESTADO_PENDIENTE: 0, ESTADO_ACTIVO: 1, ESTADO_DESHABILITADO: 2}
    try:
        docs = list(db[COLECCION_USUARIOS].find({}))
    except PyMongoError as exc:
        raise AuthError("No es posible consultar los usuarios en este momento.", 503) from exc
    filas = []
    for d in docs:
        bloqueado = _como_utc(d.get("bloqueado_hasta"))
        filas.append({**publico(d), "bloqueado": bool(bloqueado and bloqueado > ahora),
                      "habilitado_por": d.get("habilitado_por"), "ultimo_cambio": d.get("ultimo_cambio")})
    return sorted(filas, key=lambda f: (orden.get(f["estado"], 3), f["usuario"]))


def buscar_usuario(db, usuario: str) -> dict:
    nombre = usuario.strip().lower() if isinstance(usuario, str) else ""
    try:
        doc = db[COLECCION_USUARIOS].find_one({"usuario": nombre}) if nombre else None
    except PyMongoError as exc:
        raise AuthError("No es posible consultar los usuarios en este momento.", 503) from exc
    if doc is None:
        raise AuthError("No existe ese usuario.", 404)
    return doc


def _administradores_activos(db) -> int:
    return db[COLECCION_USUARIOS].count_documents({"rol": ROL_ADMINISTRADOR, "estado": ESTADO_ACTIVO})


def aplicar_cambio(db, doc: dict, cambios: dict, accion: str, por: str, cerrar_sesiones: bool = True) -> None:
    """
    Guarda el cambio y anota quién lo hizo. Por defecto cierra las sesiones abiertas del usuario (cambios de acceso);
    un cambio que no toca sus privilegios, como asignarle una ventanilla, pasa `cerrar_sesiones=False`.
    """
    ahora = datetime.now(timezone.utc)
    actualizacion = {"$set": {**cambios, "actualizado_en": ahora, "ultimo_cambio": {"accion": accion, "por": por, "en": ahora}}}
    if cerrar_sesiones:
        actualizacion["$inc"] = {"version_sesion": 1}
    try:
        db[COLECCION_USUARIOS].update_one({"_id": doc["_id"]}, actualizacion)
    except PyMongoError as exc:
        raise AuthError("No es posible guardar el cambio en este momento.", 503) from exc


def _validar_rol(rol) -> None:
    if rol not in ROLES:
        raise AuthError("Elija un rol válido: operador, supervisor o administrador.", 400)


def habilitar_usuario(db, usuario: str, rol: str, por: str) -> dict:
    """Aprueba una solicitud (o reactiva a un usuario deshabilitado) y le asigna el rol."""
    _validar_rol(rol)
    doc = buscar_usuario(db, usuario)
    if doc.get("estado") == ESTADO_ACTIVO:
        raise AuthError("El usuario ya está activo. Para cambiarle el rol use «Cambiar rol».", 409)
    aplicar_cambio(db, doc, {"estado": ESTADO_ACTIVO, "rol": rol, "habilitado_por": por,
                       "intentos_fallidos": 0, "bloqueado_hasta": None, "ventanilla_asignada": None},
             "habilitar", por)
    return {"usuario": doc["usuario"], "rol": rol}


def deshabilitar_usuario(db, usuario: str, por: str) -> dict:
    """Quita el acceso: la sesión abierta deja de valer en la petición siguiente."""
    doc = buscar_usuario(db, usuario)
    if doc["usuario"] == por:
        raise AuthError("No puede deshabilitar su propia cuenta.", 409)
    if doc.get("estado") == ESTADO_DESHABILITADO:
        raise AuthError("El usuario ya está deshabilitado.", 409)
    if doc.get("rol") == ROL_ADMINISTRADOR and doc.get("estado") == ESTADO_ACTIVO and _administradores_activos(db) <= 1:
        raise AuthError("Debe quedar al menos un administrador activo.", 409)
    # Su ventanilla queda libre para otro operador (si tenía un turno en curso, un supervisor lo finaliza desde el panel).
    aplicar_cambio(db, doc, {"estado": ESTADO_DESHABILITADO, "ventanilla_asignada": None}, "deshabilitar", por)
    return {"usuario": doc["usuario"]}


def cambiar_rol(db, usuario: str, rol: str, por: str) -> dict:
    """Cambia el rol de un usuario activo. Al cambiar de rol se libera la ventanilla asignada."""
    _validar_rol(rol)
    doc = buscar_usuario(db, usuario)
    if doc["usuario"] == por:
        raise AuthError("No puede cambiar su propio rol.", 409)
    if doc.get("estado") != ESTADO_ACTIVO:
        raise AuthError("Solo se cambia el rol de usuarios activos; habilite primero la cuenta.", 409)
    if doc.get("rol") == rol:
        raise AuthError(f"El usuario ya tiene el rol {rol}.", 409)
    if doc.get("rol") == ROL_ADMINISTRADOR and _administradores_activos(db) <= 1:
        raise AuthError("Debe quedar al menos un administrador activo.", 409)
    aplicar_cambio(db, doc, {"rol": rol, "ventanilla_asignada": None}, "cambiar_rol", por)
    return {"usuario": doc["usuario"], "rol": rol}


def restablecer_clave(db, usuario: str, clave: str, por: str) -> dict:
    """Pone una contraseña nueva, quita el bloqueo y cierra todas las sesiones del usuario."""
    doc = buscar_usuario(db, usuario)
    validar_clave(clave, doc["usuario"])
    aplicar_cambio(db, doc, {"hash": hashear_clave(clave), "intentos_fallidos": 0, "bloqueado_hasta": None},
             "restablecer_clave", por)
    return {"usuario": doc["usuario"]}


def contar_pendientes(db) -> int:
    try:
        return db[COLECCION_USUARIOS].count_documents({"estado": ESTADO_PENDIENTE})
    except PyMongoError:
        return 0


def siguiente_seguro(valor) -> str:
    """Destino tras iniciar sesión: solo una ruta propia de la aplicación; cualquier otra cosa se descarta."""
    if isinstance(valor, str) and re.fullmatch(r"/[A-Za-z0-9_\-./?=&%]*", valor) and not valor.startswith("//"):
        return valor
    return ""


def publico(doc: dict) -> dict:
    """El usuario sin el hash ni los campos internos: lo único que se puede mostrar o enviar al navegador."""
    return {k: doc.get(k) for k in ("usuario", "rol", "estado", "ventanilla_asignada", "creado_en", "ultimo_acceso")}


def obtener_usuario(db, usuario: str) -> Optional[dict]:
    try:
        return db[COLECCION_USUARIOS].find_one({"usuario": str(usuario).strip().lower()})
    except PyMongoError:
        return None


def autenticar(db, usuario: str, clave: str, ahora: Optional[datetime] = None) -> dict:
    """
    Valida usuario y contraseña. Devuelve el documento del usuario (con `_id` y `version_sesion`).
    Los errores de credenciales usan siempre el mismo mensaje; los avisos de cuenta pendiente,
    deshabilitada o bloqueada solo se dan cuando la contraseña es correcta (salvo el bloqueo).
    """
    ahora = ahora or datetime.now(timezone.utc)
    nombre = usuario.strip().lower() if isinstance(usuario, str) else ""
    clave = clave if isinstance(clave, str) else ""
    try:
        doc = db[COLECCION_USUARIOS].find_one({"usuario": nombre}) if nombre else None
    except PyMongoError as exc:
        raise AuthError("No es posible iniciar sesión en este momento.", 503) from exc

    if doc is None:
        verificar_clave(clave, _HASH_FALSO)             # misma demora que con un usuario real
        raise AuthError(MENSAJE_CREDENCIALES, 401)

    bloqueado = _como_utc(doc.get("bloqueado_hasta"))
    if bloqueado and bloqueado > ahora:
        minutos = max(1, int((bloqueado - ahora).total_seconds() // 60) + 1)
        raise AuthError(f"Demasiados intentos fallidos. Intente de nuevo en {minutos} min.", 429)

    if not verificar_clave(clave, doc.get("hash", "")):
        _registrar_fallo(db, doc, ahora)
        raise AuthError(MENSAJE_CREDENCIALES, 401)

    if doc.get("estado") == ESTADO_PENDIENTE:
        raise AuthError("Su cuenta está pendiente de aprobación. El administrador debe habilitarla.", 403)
    if doc.get("estado") != ESTADO_ACTIVO or doc.get("rol") not in ROLES:
        raise AuthError("Su acceso está deshabilitado. Consulte al administrador.", 403)

    try:
        db[COLECCION_USUARIOS].update_one(
            {"_id": doc["_id"]},
            {"$set": {"intentos_fallidos": 0, "bloqueado_hasta": None, "ultimo_acceso": ahora}})
    except PyMongoError:
        log.warning("No se pudo registrar el último acceso de %s", nombre)
    return doc


def _registrar_fallo(db, doc: dict, ahora: datetime) -> None:
    intentos = int(doc.get("intentos_fallidos") or 0) + 1
    cambios = {"intentos_fallidos": intentos}
    if intentos >= MAX_INTENTOS:
        cambios.update(intentos_fallidos=0, bloqueado_hasta=ahora + timedelta(seconds=BLOQUEO_SEG))
    try:
        db[COLECCION_USUARIOS].update_one({"_id": doc["_id"]}, {"$set": cambios})
    except PyMongoError:
        log.warning("No se pudo registrar el intento fallido de %s", doc.get("usuario"))


def _como_utc(valor) -> Optional[datetime]:
    if not isinstance(valor, datetime):
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


# --- Sesión (cookie firmada) ----------------------------------------------------------------------

_secreto_local: Optional[bytes] = None


def secreto_configurado() -> bool:
    return bool(os.getenv("SECRETO_SESION", "").strip())


def _secreto() -> bytes:
    """`SECRETO_SESION` del entorno. Sin él se usa uno aleatorio por proceso: las sesiones no sobreviven a un reinicio."""
    global _secreto_local
    valor = os.getenv("SECRETO_SESION", "").strip()
    if valor:
        return valor.encode("utf-8")
    if _secreto_local is None:
        log.warning("SECRETO_SESION no está definido: se usa un secreto temporal y las sesiones se pierden al reiniciar.")
        _secreto_local = secrets.token_bytes(32)
    return _secreto_local


def _firma(cuerpo: str) -> str:
    return _b64(hmac.new(_secreto(), cuerpo.encode("ascii"), hashlib.sha256).digest())


def crear_token(doc: dict, ahora: Optional[float] = None, duracion: int = DURACION_SESION_SEG) -> str:
    emitido = int(ahora if ahora is not None else time.time())
    carga = {"u": doc["usuario"], "v": int(doc.get("version_sesion") or 1), "exp": emitido + duracion}
    cuerpo = _b64(json.dumps(carga, separators=(",", ":")).encode("utf-8"))
    return f"{cuerpo}.{_firma(cuerpo)}"


def leer_token(token: str, ahora: Optional[float] = None) -> Optional[dict]:
    """Devuelve la carga si la firma es válida y no caducó; en cualquier otro caso, None."""
    try:
        cuerpo, firma = token.split(".")
        if not hmac.compare_digest(firma, _firma(cuerpo)):
            return None
        carga = json.loads(_desb64(cuerpo))
        if not isinstance(carga, dict) or float(carga["exp"]) < (ahora if ahora is not None else time.time()):
            return None
        return carga if isinstance(carga.get("u"), str) else None
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        return None


def atributos_cookie(secure: bool, path: str = "/") -> dict:
    """Atributos de `Response.set_cookie` para la sesión: inaccesible desde JavaScript y sin envío entre sitios."""
    return {"key": NOMBRE_COOKIE, "max_age": DURACION_SESION_SEG, "httponly": True, "samesite": "lax",
            "secure": secure, "path": path or "/"}


def es_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"


def usuario_de_la_peticion(request: Request, db) -> Optional[dict]:
    """El usuario de la sesión, releído de MongoDB: solo si sigue activo, con rol y misma versión de sesión."""
    token = request.cookies.get(NOMBRE_COOKIE)
    carga = leer_token(token) if token else None
    if carga is None:
        return None
    doc = obtener_usuario(db, carga["u"])
    if (doc is None or doc.get("estado") != ESTADO_ACTIVO or doc.get("rol") not in ROLES
            or int(doc.get("version_sesion") or 1) != carga.get("v")):
        return None
    return doc


def cerrar_sesiones(db, usuario: str) -> None:
    """Invalida todas las sesiones abiertas del usuario (cambio de contraseña, rol o deshabilitación)."""
    db[COLECCION_USUARIOS].update_one({"usuario": usuario}, {"$inc": {"version_sesion": 1}})


# --- Origen de las peticiones que modifican datos (CSRF) -------------------------------------------

def origen_permitido(request: Request) -> bool:
    """
    Una petición que modifica datos debe venir de esta misma página.
    1. Si el navegador envía `Sec-Fetch-Site` (todos los actuales), manda: solo se acepta `same-origin` (o `none`,
       una acción del propio usuario). Lo calcula el navegador con la dirección que ve el usuario, por eso sirve
       detrás de Apache y también cuando la página pide `no-referrer`, caso en el que `Origin` llega como `null`.
    2. Si no, se compara `Origin` (o `Referer`) con el servidor; `null` se rechaza.
    3. Un cliente sin ninguna de esas cabeceras no es un navegador siguiendo un enlace de otro sitio y se deja pasar
       (la cookie ya es SameSite=Lax).
    """
    from urllib.parse import urlsplit
    sitio = request.headers.get("sec-fetch-site", "").strip().lower()
    if sitio:
        return sitio in ("same-origin", "none")
    # Detrás de Apache el Host puede ser el interno (127.0.0.1:puerto): también vale el dominio público configurado.
    permitidos = {(request.headers.get(c) or "").split(",")[0].strip().lower() for c in ("x-forwarded-host", "host")}
    publica = os.getenv("PUBLIC_BASE_URL", "").strip()
    if publica:
        permitidos.add(urlsplit(publica).netloc.lower())
    permitidos.discard("")
    for cabecera in ("origin", "referer"):
        valor = request.headers.get(cabecera)
        if valor:
            if valor == "null":
                return False
            return urlsplit(valor).netloc.lower() in permitidos
    return True


# --- Dependencias de FastAPI ----------------------------------------------------------------------

def requiere_rol(*roles: str, obtener_db=None):
    """
    Dependencia para proteger una ruta: `Depends(requiere_rol("operador"))`.
    Lanza `NoAutenticado` (sin sesión) o `SinPermiso` (rol insuficiente); la aplicación los traduce a
    redirección a /login o a la página 403. `obtener_db` es la función que entrega la base de datos.
    """
    for r in roles:
        if r not in ROLES:
            raise ValueError(f"Rol desconocido: {r!r}")

    def dependencia(request: Request) -> dict:
        if obtener_db is None:
            raise RuntimeError("requiere_rol necesita obtener_db")
        usuario = usuario_de_la_peticion(request, obtener_db())
        if usuario is None:
            raise NoAutenticado()
        if usuario["rol"] not in roles:
            raise SinPermiso(publico(usuario), roles)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not origen_permitido(request):
            raise SinPermiso(publico(usuario), roles)
        request.state.usuario = publico(usuario)
        return usuario
    dependencia.roles = roles               # permite a las pruebas y al inventario de rutas saber qué exige
    return dependencia
