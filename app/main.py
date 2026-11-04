"""
MongoDB Web Admin (versión FastAPI) - base de pruebas para el proyecto QLine.
Equivalente a la versión PHP: listar/crear colecciones y CRUD de documentos.
"""
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from bson import ObjectId, json_util
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app import atencion
from app import asignaciones
from app import auth
from app import vista_operador
from app import cola as cola_redis
from app import eventos
from app.excepciones import ErrorAtencion, VentanillaNoAsignada
from app.panel_atencion import estado_ventanillas
from app.redis_atencion import liberar_turno
from app.consulta_qr import QRError, consultar_por_token
from app import formato
from app.qr import construir_url_qr, generar_qr_svg
from app.rutas_eventos import registrar as registrar_rutas_eventos
from app.schemas import TurnoEnAtencion, TurnoFinalizado
from app.emitir import EmisionError, emitir_turno
from app.consultar import ConsultaError, consultar_turno
from app.llamado import LlamadoError, llamar_siguiente_turno
from app.constantes import (ESTADOS, MOTIVOS_CIERRE, NOTA_CIERRE_MAX, PRIORIDADES, SERVICIO_ID, SERVICIO_NOMBRE,
                            PATRON_VENTANILLA, VENTANILLAS)
from app.redis_client import get_redis, verificar_conexion as verificar_redis
from app import salud as salud_app
from app.ventanillas import codigos_para_consulta, siguiente_codigo_ventanilla, ventanillas_activas
from app.errores import registrar_errores
from app.turnos_schema import TurnoValidationError, validar_documento_turno
from app.historial import exportar_historial_turnos, obtener_historial_turnos
from app.dashboard import calcular_metricas_dashboard, exportar_metricas_dashboard
from app.pantalla_publica import pantalla as _pantalla


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

MONGO_USER = os.getenv("MONGO_USER", "")
MONGO_PASS = os.getenv("MONGO_PASS", "")
MONGO_DB = os.getenv("MONGO_DB", "")
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))

# Prefijo público cuando la app se publica en una subruta (ej. /proyecto/qline).
# Apache lo quita antes de pasar la petición a la app; aquí solo se usa para
# construir los enlaces y redirecciones que ve el navegador.
_bp = os.getenv("BASE_PATH", "").strip().strip("/")
BASE = f"/{_bp}" if _bp else ""

MENSAJE_USUARIOS_APARTE = "Los usuarios se gestionan en la pantalla de usuarios y acceso: aquí no se editan, para no tocar contraseñas ni roles a mano."

MENSAJES = {
    "insertado": "Documento insertado correctamente.",
    "actualizado": "Documento actualizado correctamente.",
    "eliminado": "Documento eliminado correctamente.",
    "ventanilla_creada": "Ventanilla {codigo} registrada y activada correctamente (P09).",
    "ventanilla_desactivada": "Ventanilla desactivada correctamente (P09).",
    "ventanilla_reactivada": "Ventanilla reactivada correctamente (P09).",
    "sucursal_creada": "Sucursal y ventanillas aprovisionadas correctamente.",
    "sucursal_actualizada": "Sucursal y capacidad de ventanillas actualizadas correctamente.",
    "sucursal_desactivada": "Sucursal desactivada correctamente.",
    "sucursal_reactivada": "Sucursal reactivada correctamente.",
}


@asynccontextmanager
async def _lifespan(app_):
    """Al arrancar: suscribe la pantalla pública al Hub de eventos (TT-013, HU-009) e inicia el barrido de abandono (HU-008)."""
    from app.tiempo_real import hub
    import json as _json
    _orig_repartir = hub._repartir

    def _repartir_con_pantalla(mensaje: str) -> None:
        _orig_repartir(mensaje)
        try:
            evento = _json.loads(mensaje)
            if isinstance(evento, dict):
                _pantalla.procesar_evento(evento)
        except Exception:
            pass

    hub._repartir = _repartir_con_pantalla

    # HU-008: barrido periódico que marca como abandonados los turnos llamados cuyo plazo venció.
    from app.integracion_s3 import crear_barrido_abandono
    barrido = crear_barrido_abandono()
    app_.state.barrido = barrido
    if barrido is not None:
        barrido.iniciar()
    try:
        yield
    finally:
        if barrido is not None:
            barrido.detener()
        hub._repartir = _orig_repartir


# Sin documentación interactiva ni esquema OpenAPI públicos: no hay motivo para exponerlos en la sucursal.
app = FastAPI(title="MongoDB Web Admin", lifespan=_lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

def _version_css() -> int:
    """Fecha de modificación de style.css: cambia el enlace y obliga al navegador a recargarlo."""
    try:
        return int((BASE_DIR.parent / "static" / "style.css").stat().st_mtime)
    except OSError:
        return 0


templates.env.globals["css_version"] = _version_css()
templates.env.globals["motivos_cierre"] = MOTIVOS_CIERRE
templates.env.globals["nota_cierre_max"] = NOTA_CIERRE_MAX
templates.env.globals["base"] = BASE   # las páginas de error no reciben contexto
registrar_errores(app, templates)
formato.registrar(templates.env)             # filtros de fecha y hora para las pantallas

# --- Control de acceso por rol -------------------------------------------------------------------
# Páginas del cliente, la pantalla de sala, la consulta por QR y /salud no piden sesión. Lo demás sí.
# El supervisor y el administrador también pueden abrir las páginas del operador: la guía /demo las recorre
# y ellos supervisan la operación. Para volver a dejarlas solo al operador basta cambiar OPERACION.
ROLES_OPERACION = (auth.ROL_OPERADOR, auth.ROL_SUPERVISOR, auth.ROL_ADMINISTRADOR)
ROLES_SUPERVISION = (auth.ROL_SUPERVISOR, auth.ROL_ADMINISTRADOR)
ROLES_ADMIN = (auth.ROL_ADMINISTRADOR,)


def _exigir(*roles):
    return [Depends(auth.requiere_rol(*roles, obtener_db=lambda: get_db()))]


OPERACION = _exigir(*ROLES_OPERACION)
SUPERVISION = _exigir(*ROLES_SUPERVISION)
SOLO_ADMIN = _exigir(*ROLES_ADMIN)

registrar_rutas_eventos(app, get_db=lambda: get_db(), dependencias_diagnostico=SOLO_ADMIN)


@app.get("/ws-prueba", dependencies=SOLO_ADMIN, response_class=HTMLResponse)
def prueba_tiempo_real(request: Request):
    """Verifica en el navegador si el WebSocket y los eventos de Redis funcionan por el proxy."""
    return templates.TemplateResponse(request, "ws_prueba.html", {"base": BASE})

_client = None


def get_db():
    """Cliente único reutilizable (PyMongo maneja su propio pool de conexiones)."""
    global _client
    if _client is None:
        uri = (
            f"mongodb://{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASS)}"
            f"@{MONGO_HOST}:{MONGO_PORT}/{quote_plus(MONGO_DB)}"
            f"?authSource={quote_plus(MONGO_DB)}"
        )
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _client[MONGO_DB]


def nombre_valido(nombre: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", nombre))


def a_json_bonito(doc: dict) -> str:
    return json_util.dumps(doc, indent=2, ensure_ascii=False, json_options=json_util.RELAXED_JSON_OPTIONS)


def json_a_documento(texto: str) -> dict:
    texto = texto.strip()
    if not texto:
        raise ValueError("Debe ingresar un documento JSON.")
    doc = json_util.loads(texto)
    if not isinstance(doc, dict):
        raise ValueError("El JSON debe ser un objeto { ... }.")
    doc.pop("_id", None)
    return doc


def a_object_id(valor: str) -> ObjectId:
    try:
        return ObjectId(valor.strip())
    except (InvalidId, TypeError, AttributeError):
        raise ValueError("ID no válido.")


def ir(coleccion: str, **params) -> RedirectResponse:
    extra = "".join(f"&{k}={quote_plus(v)}" for k, v in params.items())
    return RedirectResponse(f"{BASE}/administracion?coleccion={quote_plus(coleccion)}{extra}", status_code=303)



def _parsear_iso_o_fecha(valor):
    """Convierte strings ISO o valores existentes a datetime UTC."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, str):
        val = valor.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return None


def normalizar_timestamps_turno(doc: dict) -> None:
    """Asegura que los timestamps en el documento sean datetime UTC para MongoDB."""
    if "timestamps" in doc and isinstance(doc["timestamps"], dict):
        for k in ("creado", "llamado", "inicio_atencion", "finalizado", "abandonado"):
            val = doc["timestamps"].get(k)
            if val is not None:
                parsed = _parsear_iso_o_fecha(val)
                doc["timestamps"][k] = parsed


def render(request: Request, coleccion: str = "", editar: str = "", error: str = "",
           ok: str = "", json_texto: str = None, filtro_estado: str = "", ventanilla: str = ""):
    plantilla_turnos = json.dumps({
        "codigo": "A-099",
        "servicio": SERVICIO_ID,
        "prioridad": "normal",
        "estado": "pendiente",
        "ventanilla": None,
        "operador": None,
        "timestamps": {
            "creado": datetime.now(timezone.utc).isoformat(),
            "llamado": None,
            "inicio_atencion": None,
            "finalizado": None,
            "abandonado": None,
        },
        "metricas": {
            "espera_seg": None,
            "atencion_seg": None,
        },
    }, indent=2)

    contexto = {
        "usuario_mongo": MONGO_USER, "base": BASE, "base_datos": MONGO_DB, "coleccion": coleccion,
        "colecciones": [], "documentos": [], "doc_editar": None, "id_editar": "",
        "mensaje": MENSAJES.get(ok, "").replace("{codigo}", ventanilla if re.fullmatch(PATRON_VENTANILLA, ventanilla) else "nueva"),
        "error": error, "json_texto": json_texto,
        "filtro_estado": filtro_estado, "plantilla_turnos": plantilla_turnos,
        "proximo_codigo_ventanilla": siguiente_codigo_ventanilla(), "usuarios_pendientes": 0,
    }
    try:
        db = get_db()
        contexto["colecciones"] = sorted(db.list_collection_names())
        from app.ventanillas import listar_ventanillas
        contexto["ventanillas_gestion"] = listar_ventanillas(db, solo_activas=False)
        contexto["proximo_codigo_ventanilla"] = siguiente_codigo_ventanilla(db)
        contexto["usuarios_pendientes"] = auth.contar_pendientes(db)
        from app.sucursales import listar_sucursales
        contexto["sucursales_gestion"] = listar_sucursales(db, solo_activas=False)
        if coleccion and editar and coleccion == auth.COLECCION_USUARIOS:
            contexto["error"] = MENSAJE_USUARIOS_APARTE
        elif coleccion and editar:
            try:
                doc = db[coleccion].find_one({"_id": a_object_id(editar)})
                if doc is None:
                    raise ValueError("Documento no encontrado.")
                contexto["doc_editar"] = a_json_bonito(doc)
                contexto["id_editar"] = editar
            except Exception as e:
                contexto["error"] = f"Error cargando documento: {e}"
        if coleccion:
            query = {}
            if coleccion == "turnos" and filtro_estado:
                query["estado"] = filtro_estado
            cursor = db[coleccion].find(query).sort("_id", -1).limit(50)
            documentos = []
            for d in cursor:
                resumen_turno = None
                if coleccion == "turnos" and isinstance(d, dict):
                    resumen_turno = {
                        "codigo": d.get("codigo"),
                        "prioridad": d.get("prioridad"),
                        "estado": d.get("estado"),
                        "ventanilla": d.get("ventanilla"),
                    }
                if coleccion == auth.COLECCION_USUARIOS and isinstance(d, dict):
                    d = {**d, "hash": "[oculto]"}            # nunca se muestra, ni siquiera al administrador
                documentos.append({
                    "id": str(d.get("_id", "")),
                    "json": a_json_bonito(d),
                    "resumen_turno": resumen_turno,
                })
            contexto["documentos"] = documentos
    except Exception as e:
        contexto["error"] = contexto["error"] or f"Error de MongoDB: {e}"
    return templates.TemplateResponse(request, "administracion.html", contexto)



@app.get("/demo", dependencies=SUPERVISION, response_class=HTMLResponse)
def guia_demo(request: Request):
    """Guía ordenada para recorrer el flujo completo de la demo (Seguimientos 2 y 3)."""
    redis_estado = verificar_redis()
    mongo_estado = {"ok": False, "turnos": 0, "error": ""}
    try:
        mongo_estado.update(ok=True, turnos=get_db()["turnos"].count_documents({}))
    except Exception as e:
        mongo_estado["error"] = str(e)[:150]
    cola_tam = None
    if redis_estado.get("ok"):
        try:
            cola_tam = cola_redis.tamano_cola()
        except RedisError:
            cola_tam = None
    # Hacia dónde apuntan los QR y si el abandono automático está corriendo: lo que más falla al preparar la demo.
    qr_base = construir_url_qr("123e4567-e89b-42d3-a456-426614174000").rsplit("/turno/qr/", 1)[0]
    barrido = getattr(request.app.state, "barrido", None)
    return templates.TemplateResponse(
        request, "demo.html",
        {"base": BASE, "redis": redis_estado, "mongo": mongo_estado, "cola_tam": cola_tam,
         "qr_base": qr_base, "qr_local": any(h in qr_base for h in ("localhost", "127.0.0.1", "0.0.0.0")),
         "barrido_activo": bool(barrido and barrido.activo),
         "barrido_intervalo": getattr(barrido, "intervalo_seg", 0) if barrido else 0},
    )


@app.get("/redis/estado", dependencies=SOLO_ADMIN)
def redis_estado():
    """Estado de la conexión a Redis (TT-006). Solo «ok»: host, puerto, versión y errores quedan en el servidor."""
    return {"ok": bool(verificar_redis().get("ok"))}


@app.get("/salud")
def salud(request: Request):
    """Estado de la aplicación, Redis y MongoDB, sin detalles de infraestructura (S4-M06)."""
    cuerpo, status = salud_app.comprobar(
        lambda: get_db(), lambda: get_redis(), getattr(request.app.state, "barrido", None))
    return JSONResponse(cuerpo, status_code=status)


@app.get("/api/cola", dependencies=OPERACION)
def api_cola():
    """Turnos disponibles en orden de atención (HU-004). Solo lectura."""
    try:
        return {"ok": True, "turnos": cola_redis.ver_cola()}
    except RedisError as e:
        return JSONResponse({"ok": False, "error": f"Redis no disponible: {e}"}, status_code=503)


def _ventanilla_permitida(request: Request, pedida: str) -> str:
    """
    Ventanilla sobre la que puede actuar quien hace la petición. El operador siempre usa la que le asignó su
    supervisor (si pide otra, se rechaza); el supervisor y el administrador pueden actuar sobre cualquiera.
    """
    pedida = (pedida or "").strip()
    usuario = request.state.usuario
    if usuario["rol"] != auth.ROL_OPERADOR:
        return pedida
    asignada = usuario.get("ventanilla_asignada")
    if not asignada:
        raise VentanillaNoAsignada(asignaciones.MENSAJE_SIN_VENTANILLA)
    if pedida and pedida != asignada:
        raise VentanillaNoAsignada(f"Su ventanilla es {asignada}; no puede operar {pedida}.")
    return asignada


def _ventanilla_de_trabajo(request: Request, pedida: str) -> str:
    """
    Ventanilla de la vista de trabajo. El operador siempre trabaja en la asignada (sin ella, VentanillaNoAsignada).
    El supervisor y el administrador eligen una activa con `?ventanilla=`; sin elegir devuelve "" (vista de supervisión).
    """
    usuario = request.state.usuario
    if usuario["rol"] == auth.ROL_OPERADOR:
        asignada = usuario.get("ventanilla_asignada")
        if not asignada:
            raise VentanillaNoAsignada(asignaciones.MENSAJE_SIN_VENTANILLA)
        return asignada
    pedida = (pedida or "").strip()
    return pedida if pedida in ventanillas_activas(get_db()) else ""


@app.get("/api/operador/estado", dependencies=OPERACION)
def api_estado_operador(request: Request, ventanilla: str = ""):
    """Todo lo que necesita la vista del operador en una sola respuesta (turno en curso, cola y sus números)."""
    destino = _ventanilla_de_trabajo(request, ventanilla)
    if not destino:
        return JSONResponse({"ok": False, "error": "Indique una ventanilla válida."}, status_code=400, headers=_SIN_CACHE)
    try:
        estado = vista_operador.estado_operador(get_db(), destino, request.state.usuario["usuario"])
    except Exception:                                    # noqa: BLE001 · sin detalles internos hacia el navegador
        return JSONResponse({"ok": False, "error": "No se pudo consultar el estado en este momento."},
                            status_code=503, headers=_SIN_CACHE)
    return JSONResponse({"ok": True, **estado}, headers=_SIN_CACHE)


def _vista_trabajo(request: Request, ventanilla, es_operador: bool, msg: str, error: str):
    """Pantalla de trabajo: el turno en curso con sus acciones y la cola en vivo, de una ventanilla."""
    usuario = request.state.usuario["usuario"]
    estado = None
    if ventanilla:
        try:
            estado = vista_operador.estado_operador(get_db(), ventanilla, usuario)
        except Exception:                                # noqa: BLE001
            estado = vista_operador.estado_vacio(ventanilla, usuario, "MongoDB no responde: los datos no están disponibles.")
    try:
        activas = list(ventanillas_activas(get_db()))
    except Exception:                                    # noqa: BLE001
        activas = list(VENTANILLAS)
    return templates.TemplateResponse(
        request, "operador.html",
        {"base": BASE, "servicio": SERVICIO_NOMBRE, "ventanilla": ventanilla, "estado": estado, "es_operador": es_operador,
         "ventanillas": activas, "mensaje": msg, "error": error, "usuario_actual": usuario,
         "sin_ventanilla_msg": asignaciones.MENSAJE_SIN_VENTANILLA},
        headers=_SIN_CACHE)


def _llamar(request: Request, ventanilla: str):
    """(resultado, error, status) para las rutas de llamada. Queda anotado qué usuario llamó el turno."""
    try:
        ventanilla = _ventanilla_permitida(request, ventanilla)
        if not ventanilla:                       # solo el supervisor y el administrador llegan aquí sin ventanilla
            return None, "Indique la ventanilla desde la que llama.", 422
        return llamar_siguiente_turno(get_db(), ventanilla, operador=request.state.usuario["usuario"]), "", 200
    except VentanillaNoAsignada as e:
        return None, e.mensaje, e.status_code
    except cola_redis.ColaError as e:
        return None, str(e), 400
    except LlamadoError as e:
        return None, str(e), e.status
    except RedisError as e:
        return None, f"Redis no disponible: {e}", 503


@app.post("/api/llamar", dependencies=OPERACION)
def api_llamar(request: Request, ventanilla: str = Form("")):
    """Llamar al siguiente turno desde una ventanilla (HU-005). El operador llama desde la que tiene asignada."""
    res, error, status = _llamar(request, ventanilla)
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=status)
    return {"ok": True, **res}


@app.post("/api/turnos/emitir")
async def api_emitir_turno(request: Request):
    """Emitir un nuevo turno para Atención General (HU-001)."""
    prioridad = ""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                prioridad = body.get("prioridad", "")
        except Exception:
            return JSONResponse({"ok": False, "error": "Cuerpo JSON inválido."}, status_code=400)
    else:
        try:
            form = await request.form()
            prioridad = form.get("prioridad", "")
        except Exception:
            return JSONResponse({"ok": False, "error": "Datos de formulario inválidos."}, status_code=400)

    try:
        resultado = emitir_turno(get_db(), prioridad)
        _publicar_evento(eventos.TURNO_EMITIDO, resultado["codigo"], "pendiente", prioridad=resultado.get("prioridad"))
        return {"ok": True, "turno": resultado}
    except EmisionError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)
    except RedisError:
        return JSONResponse({"ok": False, "error": "Redis no disponible temporalmente."}, status_code=503)
    except PyMongoError:
        return JSONResponse({"ok": False, "error": "MongoDB no disponible temporalmente."}, status_code=503)


@app.get("/emitir", response_class=HTMLResponse)
def vista_emitir(request: Request, error: str = ""):
    """Formulario web para emitir turno (HU-001)."""
    return templates.TemplateResponse(
        request,
        "emitir.html",
        {
            "base": BASE,
            "servicio": SERVICIO_NOMBRE,
            "error": error,
            "prioridad_seleccionada": "normal",
        },
    )


@app.post("/emitir", response_class=HTMLResponse)
def accion_emitir(request: Request, prioridad: str = Form("")):
    """Procesar emisión de turno desde formulario web (HU-001)."""
    try:
        turno = emitir_turno(get_db(), prioridad)
        _publicar_evento(eventos.TURNO_EMITIDO, turno["codigo"], "pendiente", prioridad=turno.get("prioridad"))
        qr_svg = generar_qr_svg(turno["qr_url"]) if turno.get("qr_url") else ""
        return templates.TemplateResponse(
            request,
            "turno_confirmado.html",
            {
                "base": BASE,
                "turno": turno,
                "servicio": SERVICIO_NOMBRE,
                "qr_url": turno.get("qr_url", ""),
                "qr_svg": qr_svg,
            },
        )
    except EmisionError as e:
        return templates.TemplateResponse(
            request,
            "emitir.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": str(e),
                "prioridad_seleccionada": prioridad,
            },
            status_code=e.status,
        )
    except (RedisError, PyMongoError):
        return templates.TemplateResponse(
            request,
            "emitir.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": "El servicio no se encuentra disponible temporalmente. Por favor intente de nuevo más tarde.",
                "prioridad_seleccionada": prioridad,
            },
            status_code=503,
        )


# --- HU-001: Modo quiosco para clientes (ampliación S3) ----------------------

@app.get("/quiosco", response_class=HTMLResponse)
def vista_quiosco(request: Request, error: str = ""):
    """Vista de emisión simplificada tipo quiosco (HU-001): sin navegación interna ni administrativa."""
    return templates.TemplateResponse(
        request,
        "quiosco.html",
        {
            "base": BASE,
            "servicio": SERVICIO_NOMBRE,
            "error": error,
            "prioridad_seleccionada": "normal",
        },
    )


@app.post("/quiosco", response_class=HTMLResponse)
def accion_quiosco(request: Request, prioridad: str = Form("")):
    """Procesar emisión desde el quiosco reutilizando el backend existente de HU-001."""
    try:
        turno = emitir_turno(get_db(), prioridad)
        _publicar_evento(eventos.TURNO_EMITIDO, turno["codigo"], "pendiente", prioridad=turno.get("prioridad"))
        qr_svg = generar_qr_svg(turno["qr_url"]) if turno.get("qr_url") else ""
        return templates.TemplateResponse(
            request,
            "quiosco_confirmado.html",
            {
                "base": BASE,
                "turno": turno,
                "servicio": SERVICIO_NOMBRE,
                "qr_url": turno.get("qr_url", ""),
                "qr_svg": qr_svg,
            },
        )
    except EmisionError as e:
        return templates.TemplateResponse(
            request,
            "quiosco.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": str(e),
                "prioridad_seleccionada": prioridad,
            },
            status_code=e.status,
        )
    except (RedisError, PyMongoError):
        return templates.TemplateResponse(
            request,
            "quiosco.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": "El servicio no se encuentra disponible temporalmente. Por favor solicite asistencia.",
                "prioridad_seleccionada": prioridad,
            },
            status_code=503,
        )


# --- HU-002: consulta de turnos (solo lectura) -------------------------------

@app.get("/api/turnos/{codigo}")
def api_consultar_turno(codigo: str):
    """Devuelve estado de MongoDB y posicion de Redis si sigue pendiente."""
    try:
        return {"ok": True, "turno": consultar_turno(get_db(), codigo)}
    except ConsultaError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)
    except PyMongoError:
        return JSONResponse(
            {"ok": False, "error": "MongoDB no disponible temporalmente."},
            status_code=503,
        )


def _mostrar_consulta(request: Request, codigo: str = ""):
    """Comparte plantilla entre buscador y enlace directo por codigo."""
    turno = None
    error = ""
    status = 200
    if codigo.strip():
        try:
            turno = consultar_turno(get_db(), codigo)
        except ConsultaError as e:
            error = str(e)
            status = e.status
        except PyMongoError:
            error = "MongoDB no disponible temporalmente."
            status = 503

    return templates.TemplateResponse(
        request,
        "consultar.html",
        {
            "base": BASE,
            "servicio": SERVICIO_NOMBRE,
            "codigo": codigo,
            "turno": turno,
            "error": error,
        },
        status_code=status,
    )


@app.get("/consultar", response_class=HTMLResponse)
def vista_consultar(request: Request, codigo: str = ""):
    """Formulario de busqueda; GET /consultar?codigo=A-001."""
    return _mostrar_consulta(request, codigo)


# --- HU-013: consulta del turno desde el QR (solo lectura) ---------------------

_SIN_CACHE = {"Cache-Control": "no-store"}
_TITULO_QR = {
    400: "Código QR no válido",
    404: "Turno no encontrado",
    503: "No podemos consultar su turno ahora",
}


@app.get("/api/turnos/qr/{token}")
def api_turno_por_qr(token: str):
    """Estado y posición del turno asociado a un QR (UUID v4). Solo lectura."""
    try:
        return JSONResponse({"ok": True, "turno": consultar_por_token(get_db(), token)}, headers=_SIN_CACHE)
    except QRError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status, headers=_SIN_CACHE)


@app.get("/turno/qr/{token}", response_class=HTMLResponse)
def vista_turno_por_qr(request: Request, token: str):
    """Página móvil a la que lleva el QR del ticket: se actualiza sola, sin recargar."""
    contexto = {"base": BASE, "token": token, "turno": None, "error": "", "reintentar": False,
                "servicio_nombre": SERVICIO_NOMBRE}
    status = 200
    try:
        contexto["turno"] = consultar_por_token(get_db(), token)
    except QRError as e:
        status = e.status
        contexto.update(error=str(e), error_titulo=_TITULO_QR.get(e.status, "No se pudo mostrar el turno"),
                        reintentar=e.status == 503)
    return templates.TemplateResponse(request, "turno_qr.html", contexto, status_code=status, headers=_SIN_CACHE)


@app.get("/turno/{codigo}", response_class=HTMLResponse)
def vista_turno(request: Request, codigo: str):
    """Enlace directo a la consulta de un turno concreto."""
    return _mostrar_consulta(request, codigo)


@app.post("/cola/llamar", dependencies=OPERACION)
def cola_llamar(request: Request, ventanilla: str = Form("")):
    res, error, _ = _llamar(request, ventanilla)
    if error:
        return RedirectResponse(f"{BASE}/cola?error={quote_plus(error)}", status_code=303)
    if res["codigo"] is None:
        msg = res["mensaje"]
    else:
        msg = f"{res['ventanilla']} llamó al turno {res['codigo']} ({res['prioridad']})."
    return RedirectResponse(f"{BASE}/cola?msg={quote_plus(msg)}", status_code=303)


@app.get("/cola", dependencies=OPERACION, response_class=HTMLResponse)
def ver_cola(request: Request, msg: str = "", error: str = "", ventanilla: str = ""):
    es_operador = request.state.usuario["rol"] == auth.ROL_OPERADOR
    try:
        destino = _ventanilla_de_trabajo(request, ventanilla)
    except VentanillaNoAsignada:
        destino = None                                   # el operador sin ventanilla ve el aviso en la vista de trabajo
    if es_operador or destino:
        return _vista_trabajo(request, destino, es_operador, msg, error)
    turnos = []
    redis_responde = True
    try:
        turnos = cola_redis.ver_cola()
    except RedisError as e:
        redis_responde = False
        error = error or f"Redis no disponible: {e}"
    # Ventanillas que ya tienen un turno: no se les puede llamar otro (una a la vez).
    ocupadas = {}
    ventanillas_operativas = list(VENTANILLAS)
    try:
        ventanillas_estado, _ = estado_ventanillas(get_db(), usar_redis=redis_responde)
        ocupadas = {v["id"]: v["turno"]["codigo"] for v in ventanillas_estado if v["turno"]}
        ventanillas_operativas = list(ventanillas_activas(get_db()))
    except Exception:
        ocupadas = {}
    return templates.TemplateResponse(
        request, "cola.html",
        {"base": BASE, "servicio": SERVICIO_NOMBRE, "turnos": turnos, "error": error,
         "mensaje": msg, "ventanillas": ventanillas_operativas, "ocupadas": ocupadas},
    )


@app.exception_handler(ErrorAtencion)
def _error_atencion(request: Request, exc: ErrorAtencion):
    """Errores controlados del ciclo de atención: nunca un 500 sin explicar."""
    return JSONResponse({"ok": False, "error": exc.mensaje}, status_code=exc.status_code)


def _publicar_evento(tipo: str, codigo: str, estado: str, ventanilla: str = None, prioridad: str = None) -> None:
    """Avisa en vivo un cambio de estado (TT-013). De mejor esfuerzo: nunca rompe ni deshace la operación."""
    try:
        eventos.publicar(tipo, codigo=codigo, estado=estado, ventanilla=ventanilla, prioridad=prioridad)
    except Exception:
        pass


def _confirmar_presencia(codigo: str) -> None:
    """El cliente se presentó: su Hash temporal deja de vencer. Si Redis falla, no se deshace la atención."""
    try:
        cola_redis.confirmar_presencia(codigo)
    except RedisError:
        pass


@app.post("/api/atencion/iniciar", dependencies=OPERACION, response_model=TurnoEnAtencion)
def api_iniciar_atencion(request: Request, codigo: str = Form(...), ventanilla: str = Form(...)):
    """Iniciar la atención de un turno llamado: llamado -> en_atencion (HU-006)."""
    ventanilla = _ventanilla_permitida(request, ventanilla)
    resultado = atencion.iniciar_atencion(get_db()["turnos"], codigo, ventanilla)
    _confirmar_presencia(resultado["codigo"])
    _publicar_evento(eventos.ATENCION_INICIADA, resultado["codigo"], "en_atencion", resultado.get("ventanilla"))
    return resultado


@app.post("/api/atencion/finalizar", dependencies=OPERACION, response_model=TurnoFinalizado)
def api_finalizar_atencion(request: Request, codigo: str = Form(...), ventanilla: str = Form(...),
                           motivo: str = Form(""), nota: str = Form("")):
    """Finalizar la atención: en_atencion -> atendido y liberar Redis (HU-007)."""
    ventanilla = _ventanilla_permitida(request, ventanilla)
    resultado = atencion.finalizar_atencion(
        get_db()["turnos"], codigo, ventanilla,
        al_finalizar=lambda c: liberar_turno(c, ventanilla.strip()),
        motivo=motivo, nota=nota,
    )
    _publicar_evento(eventos.ATENCION_FINALIZADA, resultado["codigo"], "atendido", resultado.get("ventanilla"))
    return resultado


def _redirigir_panel(**params) -> RedirectResponse:
    extra = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return RedirectResponse(f"{BASE}/panel?{extra}", status_code=303)


@app.get("/panel", dependencies=OPERACION, response_class=HTMLResponse)
def panel_atencion(request: Request, msg: str = "", error: str = ""):
    """Panel de atención de todas las ventanillas (supervisión). El operador trabaja en /cola con la suya."""
    if request.state.usuario["rol"] == auth.ROL_OPERADOR:
        consulta = request.url.query
        return RedirectResponse(f"{BASE}/cola" + (f"?{consulta}" if consulta else ""), status_code=303)
    ventanillas, avisos = [], []
    try:
        ventanillas, avisos = estado_ventanillas(get_db())
    except Exception as e:
        error = error or f"MongoDB no disponible: {e}"
    return templates.TemplateResponse(
        request, "panel.html",
        {"base": BASE, "servicio": SERVICIO_NOMBRE, "ventanillas": ventanillas,
         "avisos": avisos, "mensaje": msg, "error": error},
    )


@app.post("/panel/iniciar", dependencies=OPERACION)
def panel_iniciar(request: Request, codigo: str = Form(...), ventanilla: str = Form(...)):
    try:
        ventanilla = _ventanilla_permitida(request, ventanilla)
        r = atencion.iniciar_atencion(get_db()["turnos"], codigo, ventanilla)
    except ErrorAtencion as e:
        return _redirigir_panel(error=e.mensaje)
    _confirmar_presencia(r["codigo"])
    _publicar_evento(eventos.ATENCION_INICIADA, r["codigo"], "en_atencion", r.get("ventanilla"))
    return _redirigir_panel(msg=f"{r['ventanilla']}: atención iniciada para {r['codigo']}.")


@app.post("/panel/finalizar", dependencies=OPERACION)
def panel_finalizar(request: Request, codigo: str = Form(...), ventanilla: str = Form(...),
                    motivo: str = Form(""), nota: str = Form("")):
    try:
        ventanilla = _ventanilla_permitida(request, ventanilla)
        r = atencion.finalizar_atencion(
            get_db()["turnos"], codigo, ventanilla,
            al_finalizar=lambda c: liberar_turno(c, ventanilla.strip()),
            motivo=motivo, nota=nota,
        )
    except ErrorAtencion as e:
        return _redirigir_panel(error=e.mensaje)
    _publicar_evento(eventos.ATENCION_FINALIZADA, r["codigo"], "atendido", r.get("ventanilla"))
    msg = f"{r['ventanilla']}: atención de {r['codigo']} finalizada ({r['atencion_seg']} s)."
    if r["redis_liberado"] is False:
        msg += " Aviso: no se pudo limpiar el estado en Redis."
    return _redirigir_panel(msg=msg)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    """Portada (UI-02). La administración de MongoDB vive en /administracion."""
    return templates.TemplateResponse(request, "index.html", {"base": BASE})


@app.get("/acerca", response_class=HTMLResponse)
def acerca(request: Request):
    """Propósito del proyecto, equipo y repositorio (P06)."""
    return templates.TemplateResponse(request, "acerca.html", {"base": BASE})


# --- Inicio de sesión del personal ---------------------------------------------------------------

def _pagina_acceso(request: Request, plantilla: str, status: int = 200, **contexto):
    return templates.TemplateResponse(request, plantilla, {"base": BASE, **contexto}, status_code=status,
                                      headers={"Cache-Control": "no-store"})


def _cookie_sesion(respuesta, request: Request, doc: dict) -> None:
    respuesta.set_cookie(value=auth.crear_token(doc), **auth.atributos_cookie(auth.es_https(request), BASE or "/"))


@app.get("/login", response_class=HTMLResponse)
def vista_login(request: Request, siguiente: str = "", salio: str = ""):
    """Formulario de ingreso del personal. Con sesión abierta lleva directo a la página del rol."""
    usuario = auth.usuario_de_la_peticion(request, get_db())
    if usuario is not None:
        return RedirectResponse(BASE + (auth.siguiente_seguro(siguiente) or auth.INICIO_POR_ROL[usuario["rol"]]), status_code=303)
    return _pagina_acceso(request, "login.html", siguiente=auth.siguiente_seguro(siguiente), salio=bool(salio))


@app.post("/login", response_class=HTMLResponse)
def iniciar_sesion(request: Request, usuario: str = Form(""), clave: str = Form(""), siguiente: str = Form("")):
    destino = auth.siguiente_seguro(siguiente)
    if not auth.origen_permitido(request):
        return _pagina_acceso(request, "login.html", 403, error="La solicitud no se originó en esta página.",
                              usuario=usuario, siguiente=destino)
    try:
        doc = auth.autenticar(get_db(), usuario, clave)
    except auth.AuthError as e:
        return _pagina_acceso(request, "login.html", e.status, error=str(e), usuario=usuario, siguiente=destino)
    respuesta = RedirectResponse(BASE + (destino or auth.INICIO_POR_ROL[doc["rol"]]), status_code=303)
    _cookie_sesion(respuesta, request, doc)
    return respuesta


@app.get("/registro", response_class=HTMLResponse)
def vista_registro(request: Request):
    return _pagina_acceso(request, "registro.html")


@app.post("/registro", response_class=HTMLResponse)
def registrar_usuario(request: Request, usuario: str = Form(""), clave: str = Form(""), confirmacion: str = Form("")):
    """Solicitud de acceso: queda pendiente y sin rol hasta que el administrador la habilite."""
    if not auth.origen_permitido(request):
        return _pagina_acceso(request, "registro.html", 403, error="La solicitud no se originó en esta página.", usuario=usuario)
    if clave != confirmacion:
        return _pagina_acceso(request, "registro.html", 400, error="Las contraseñas no coinciden.", usuario=usuario)
    try:
        nuevo = auth.registrar_solicitud(get_db(), usuario, clave)
    except auth.AuthError as e:
        return _pagina_acceso(request, "registro.html", e.status, error=str(e), usuario=usuario)
    return _pagina_acceso(request, "registro.html", 201, enviado=nuevo["usuario"])


@app.post("/salir")
def cerrar_sesion(request: Request):
    """Cierra la sesión de este navegador (no las de otros dispositivos)."""
    respuesta = RedirectResponse(f"{BASE}/login?salio=1", status_code=303)
    respuesta.delete_cookie(auth.NOMBRE_COOKIE, path=BASE or "/")
    return respuesta


@app.get("/administracion", dependencies=SOLO_ADMIN, response_class=HTMLResponse)
def administracion(request: Request, coleccion: str = "", editar: str = "", ok: str = "", filtro_estado: str = "",
                   ventanilla: str = ""):
    return render(request, coleccion.strip(), editar.strip(), ok=ok, filtro_estado=filtro_estado.strip(),
                  ventanilla=ventanilla)


@app.post("/crear_coleccion", dependencies=SOLO_ADMIN)
def crear_coleccion(request: Request, nombre_coleccion: str = Form("")):
    nombre = nombre_coleccion.strip()
    if not nombre_valido(nombre):
        return render(request, error="Nombre de colección no válido. Use letras, números, guion o guion bajo.")
    try:
        get_db().create_collection(nombre)
        return ir(nombre)
    except Exception as e:
        return render(request, error=f"Error creando colección: {e}")


@app.post("/insertar", dependencies=SOLO_ADMIN)
def insertar(request: Request, coleccion: str = "", json_doc: str = Form("", alias="json")):
    if coleccion == auth.COLECCION_USUARIOS:
        return render(request, coleccion, error=MENSAJE_USUARIOS_APARTE, json_texto=json_doc)
    try:
        doc = json_a_documento(json_doc)
        if coleccion == "turnos":
            normalizar_timestamps_turno(doc)
            validar_documento_turno(doc)
        get_db()[coleccion].insert_one(doc)
        return ir(coleccion, ok="insertado")
    except TurnoValidationError as e:
        return render(request, coleccion, error=f"Validación de turno falló (TT-002): {e}", json_texto=json_doc)
    except Exception as e:
        return render(request, coleccion, error=f"Error insertando: {e}", json_texto=json_doc)


@app.post("/actualizar", dependencies=SOLO_ADMIN)
def actualizar(request: Request, coleccion: str = "", id: str = Form(""),
               json_doc: str = Form("", alias="json")):
    if coleccion == auth.COLECCION_USUARIOS:
        return render(request, coleccion, error=MENSAJE_USUARIOS_APARTE)
    try:
        doc = json_a_documento(json_doc)
        if coleccion == "turnos":
            normalizar_timestamps_turno(doc)
            validar_documento_turno(doc)
        get_db()[coleccion].update_one({"_id": a_object_id(id)}, {"$set": doc})
        return ir(coleccion, ok="actualizado")
    except TurnoValidationError as e:
        return render(request, coleccion, editar=id, error=f"Validación de turno falló (TT-002): {e}", json_texto=json_doc)
    except Exception as e:
        return render(request, coleccion, editar=id, error=f"Error actualizando: {e}")


@app.post("/eliminar", dependencies=SOLO_ADMIN)
def eliminar(request: Request, coleccion: str = "", id: str = Form("")):
    if coleccion == auth.COLECCION_USUARIOS:
        return render(request, coleccion, error=MENSAJE_USUARIOS_APARTE)
    try:
        get_db()[coleccion].delete_one({"_id": a_object_id(id)})
        return ir(coleccion, ok="eliminado")
    except Exception as e:
        return render(request, coleccion, error=f"Error eliminando: {e}")


# --- Asignación de ventanillas a operadores (supervisor y administrador) ---------------------------

MENSAJES_ASIGNACION = {
    "asignada": "{usuario} atenderá en la ventanilla {ventanilla}.",
    "quitada": "{usuario} quedó sin ventanilla.",
}


def _vista_asignaciones(request: Request, status: int = 200, mensaje: str = "", error: str = ""):
    try:
        datos = asignaciones.listar(get_db())
    except auth.AuthError as e:
        datos, error, status = {"operadores": [], "ventanillas": []}, error or str(e), e.status
    return templates.TemplateResponse(
        request, "supervisor_asignaciones.html",
        {"base": BASE, **datos, "mensaje": mensaje, "error": error,
         "es_admin": request.state.usuario["rol"] == auth.ROL_ADMINISTRADOR},
        status_code=status, headers={"Cache-Control": "no-store"})


def _resultado_asignacion(request: Request, aviso: str, funcion, **datos):
    try:
        res = funcion(get_db(), por=request.state.usuario["usuario"], **datos)
    except auth.AuthError as e:
        return _vista_asignaciones(request, e.status, error=str(e))
    destino = f"{BASE}/supervisor/asignaciones?ok={aviso}&usuario={res['usuario']}&ventanilla={res['ventanilla'] or ''}"
    return RedirectResponse(destino, status_code=303)


@app.get("/supervisor/asignaciones", dependencies=SUPERVISION, response_class=HTMLResponse)
def vista_asignaciones(request: Request, ok: str = "", usuario: str = "", ventanilla: str = ""):
    nombre = usuario if auth.PATRON_USUARIO.fullmatch(usuario) else "el operador"
    codigo = ventanilla if re.fullmatch(PATRON_VENTANILLA, ventanilla) else ""
    mensaje = MENSAJES_ASIGNACION.get(ok, "").format(usuario=nombre, ventanilla=codigo)
    return _vista_asignaciones(request, mensaje=mensaje)


@app.post("/supervisor/asignaciones/asignar", dependencies=SUPERVISION)
def asignar_ventanilla_operador(request: Request, operador: str = Form(""), ventanilla: str = Form("")):
    return _resultado_asignacion(request, "asignada", asignaciones.asignar_ventanilla, operador=operador, ventanilla=ventanilla)


@app.post("/supervisor/asignaciones/quitar", dependencies=SUPERVISION)
def quitar_ventanilla_operador(request: Request, operador: str = Form("")):
    return _resultado_asignacion(request, "quitada", asignaciones.quitar_ventanilla, operador=operador)


# --- Gestión de usuarios y acceso (administrador) --------------------------------------------------

MENSAJES_USUARIOS = {
    "habilitado": "Se habilitó a {usuario} con el rol {rol}.",
    "deshabilitado": "Se deshabilitó a {usuario}: su sesión deja de valer en la siguiente petición.",
    "rol": "Ahora {usuario} tiene el rol {rol}.",
    "clave": "Se restableció la contraseña de {usuario} y se cerraron sus sesiones.",
}


def _vista_usuarios(request: Request, status: int = 200, mensaje: str = "", error: str = ""):
    try:
        usuarios = auth.listar_usuarios(get_db())
    except auth.AuthError as e:
        usuarios, error, status = [], error or str(e), e.status
    return templates.TemplateResponse(
        request, "admin_usuarios.html",
        {"base": BASE, "usuarios": usuarios, "roles": auth.ROLES, "yo": request.state.usuario["usuario"],
         "mensaje": mensaje, "error": error},
        status_code=status, headers={"Cache-Control": "no-store"})


def _resultado_usuarios(request: Request, aviso: str, funcion, **datos):
    """Aplica una acción sobre un usuario: si sale bien redirige con el aviso; si no, muestra el motivo en la misma pantalla."""
    try:
        res = funcion(get_db(), por=request.state.usuario["usuario"], **datos)
    except auth.AuthError as e:
        return _vista_usuarios(request, e.status, error=str(e))
    return RedirectResponse(f"{BASE}/admin/usuarios?ok={aviso}&usuario={res['usuario']}&rol={res.get('rol', '')}", status_code=303)


@app.get("/admin/usuarios", dependencies=SOLO_ADMIN, response_class=HTMLResponse)
def vista_usuarios(request: Request, ok: str = "", usuario: str = "", rol: str = ""):
    plantilla = MENSAJES_USUARIOS.get(ok, "")
    nombre = usuario if auth.PATRON_USUARIO.fullmatch(usuario) else "el usuario"
    return _vista_usuarios(request, mensaje=plantilla.format(usuario=nombre, rol=rol if rol in auth.ROLES else ""))


@app.post("/admin/usuarios/habilitar", dependencies=SOLO_ADMIN)
def habilitar_usuario(request: Request, usuario: str = Form(""), rol: str = Form("")):
    return _resultado_usuarios(request, "habilitado", auth.habilitar_usuario, usuario=usuario, rol=rol)


@app.post("/admin/usuarios/deshabilitar", dependencies=SOLO_ADMIN)
def deshabilitar_usuario(request: Request, usuario: str = Form("")):
    return _resultado_usuarios(request, "deshabilitado", auth.deshabilitar_usuario, usuario=usuario)


@app.post("/admin/usuarios/rol", dependencies=SOLO_ADMIN)
def cambiar_rol_usuario(request: Request, usuario: str = Form(""), rol: str = Form("")):
    return _resultado_usuarios(request, "rol", auth.cambiar_rol, usuario=usuario, rol=rol)


@app.post("/admin/usuarios/clave", dependencies=SOLO_ADMIN)
def restablecer_clave_usuario(request: Request, usuario: str = Form(""), clave: str = Form("")):
    return _resultado_usuarios(request, "clave", auth.restablecer_clave, usuario=usuario, clave=clave)


# --- P09: Onboarding y Gestión Dinámica de Ventanillas (Carlos Espinoza) -----

@app.get("/api/ventanillas", dependencies=SUPERVISION)
def api_listar_ventanillas(solo_activas: bool = False):
    """Lista las ventanillas registradas en el sistema institucional (P09)."""
    try:
        from app.ventanillas import listar_ventanillas
        return {"ok": True, "ventanillas": listar_ventanillas(get_db(), solo_activas=solo_activas)}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/ventanillas", dependencies=SOLO_ADMIN)
def api_registrar_ventanilla(
    nombre: str = Form(""),
    tipo: str = Form("general"),
):
    """Registra una ventanilla nueva en MongoDB; el código es siempre el siguiente consecutivo (V-04, V-05, ...) (P09)."""
    try:
        from app.ventanillas import VentanillaError, registrar_ventanilla
        return registrar_ventanilla(get_db(), nombre=nombre, tipo=tipo)
    except VentanillaError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/ventanillas/crear", dependencies=SOLO_ADMIN)
def web_crear_ventanilla(
    request: Request,
    nombre: str = Form(""),
    tipo: str = Form("general"),
):
    """Endpoint web para dar de alta una ventanilla desde la interfaz de administración (P09)."""
    try:
        from app.ventanillas import registrar_ventanilla
        res = registrar_ventanilla(get_db(), nombre=nombre, tipo=tipo)
        return RedirectResponse(f"{BASE}/administracion?ok=ventanilla_creada&ventanilla={res['codigo']}", status_code=303)
    except Exception as e:
        return render(request, error=f"Error registrando ventanilla: {e}")


@app.post("/ventanillas/desactivar", dependencies=SOLO_ADMIN)
def web_desactivar_ventanilla(
    request: Request,
    codigo: str = Form(""),
):
    """Endpoint web para desactivar una ventanilla validando que no tenga turnos activos (P09)."""
    try:
        from app.ventanillas import desactivar_ventanilla
        desactivar_ventanilla(get_db(), codigo=codigo)
        return RedirectResponse(f"{BASE}/administracion?ok=ventanilla_desactivada", status_code=303)
    except Exception as e:
        return render(request, error=f"Error desactivando ventanilla: {e}")


@app.post("/ventanillas/reactivar", dependencies=SOLO_ADMIN)
def web_reactivar_ventanilla(
    request: Request,
    codigo: str = Form(""),
):
    """Endpoint web para reactivar una ventanilla inactiva (P09)."""
    try:
        from app.ventanillas import reactivar_ventanilla
        reactivar_ventanilla(get_db(), codigo=codigo)
        return RedirectResponse(f"{BASE}/administracion?ok=ventanilla_reactivada", status_code=303)
    except Exception as e:
        return render(request, error=f"Error reactivando ventanilla: {e}")


# --- Mantenimiento de Sucursales y Capacidad (RFC-004) -----------------------

@app.get("/api/admin/sucursales", dependencies=SOLO_ADMIN)
def api_listar_sucursales(solo_activas: bool = False):
    """Retorna el catálogo de sucursales con métricas de capacidad (RFC-004)."""
    try:
        from app.sucursales import listar_sucursales
        sucursales = listar_sucursales(get_db(), solo_activas=solo_activas)
        return {"ok": True, "sucursales": sucursales}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.get("/api/admin/sucursales/{codigo}", dependencies=SOLO_ADMIN)
def api_obtener_sucursal(codigo: str):
    """Detalle de una sucursal y el estado de sus ventanillas (RFC-004)."""
    try:
        from app.sucursales import obtener_sucursal
        res = obtener_sucursal(get_db(), codigo=codigo)
        if not res:
            return JSONResponse({"ok": False, "error": f"Sucursal '{codigo}' no encontrada."}, status_code=404)
        return {"ok": True, "sucursal": res}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@app.post("/api/admin/sucursales", dependencies=SOLO_ADMIN)
def api_crear_sucursal(payload: dict = Body(...)):
    """Crea una sucursal y aprovisiona automáticamente sus ventanillas en MongoDB (RFC-004)."""
    try:
        from app.sucursales import crear_sucursal_con_ventanillas
        res = crear_sucursal_con_ventanillas(
            get_db(),
            codigo=payload.get("codigo", ""),
            nombre=payload.get("nombre", ""),
            direccion=payload.get("direccion", ""),
            telefono=payload.get("telefono", ""),
            cantidad_ventanillas=int(payload.get("cantidad_ventanillas", 3)),
            prefijo_ventanilla=payload.get("prefijo_ventanilla", "V"),
            objetivo_max_espera_seg=int(payload.get("objetivo_max_espera_seg", 300)),
            tasa_minima_cumplimiento=float(payload.get("tasa_minima_cumplimiento", 80.0)),
        )
        return JSONResponse(res, status_code=201)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.put("/api/admin/sucursales/{codigo}", dependencies=SOLO_ADMIN)
def api_actualizar_sucursal(codigo: str, payload: dict = Body(...)):
    """Modifica parámetros de la sucursal o ajusta la capacidad de ventanillas (RFC-004)."""
    try:
        from app.sucursales import actualizar_sucursal
        res = actualizar_sucursal(
            get_db(),
            codigo=codigo,
            nombre=payload.get("nombre"),
            direccion=payload.get("direccion"),
            telefono=payload.get("telefono"),
            cantidad_ventanillas=payload.get("cantidad_ventanillas"),
            estado=payload.get("estado"),
            objetivo_max_espera_seg=payload.get("objetivo_max_espera_seg"),
            tasa_minima_cumplimiento=payload.get("tasa_minima_cumplimiento"),
        )
        return res
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/admin/sucursales/{codigo}/desactivar", dependencies=SOLO_ADMIN)
def api_desactivar_sucursal(codigo: str):
    """Desactiva una sucursal validando previamente que no tenga turnos en atención (RFC-004)."""
    try:
        from app.sucursales import desactivar_sucursal_segura
        res = desactivar_sucursal_segura(get_db(), codigo=codigo)
        return res
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.post("/api/admin/sucursales/{codigo}/activar", dependencies=SOLO_ADMIN)
def api_activar_sucursal(codigo: str):
    """Reactiva una sucursal previamente inactiva (RFC-004)."""
    try:
        from app.sucursales import reactivar_sucursal
        res = reactivar_sucursal(get_db(), codigo=codigo)
        return res
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)


@app.get("/admin/sucursales", dependencies=SOLO_ADMIN, response_class=HTMLResponse)
def vista_admin_sucursales(request: Request, ok: str = "", error: str = ""):
    """Pantalla administrativa para gestionar sucursales y ventanillas configurables (RFC-004)."""
    try:
        from app.sucursales import listar_sucursales
        db = get_db()
        sucursales = listar_sucursales(db)
        return templates.TemplateResponse(
            request,
            "admin_sucursales.html",
            {
                "base": BASE,
                "sucursales": sucursales,
                "mensaje": MENSAJES.get(ok, ""),
                "error": error,
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "admin_sucursales.html",
            {
                "base": BASE,
                "sucursales": [],
                "mensaje": "",
                "error": f"Error cargando catálogo de sucursales: {e}",
            },
            status_code=500,
        )


@app.post("/admin/sucursales/crear", dependencies=SOLO_ADMIN)
def web_crear_sucursal(
    request: Request,
    codigo: str = Form(""),
    nombre: str = Form(""),
    direccion: str = Form(""),
    telefono: str = Form(""),
    cantidad_ventanillas: int = Form(3),
    prefijo_ventanilla: str = Form("V"),
    objetivo_max_espera_seg: int = Form(300),
):
    """Acción web para crear sucursal y aprovisionar ventanillas."""
    try:
        from app.sucursales import crear_sucursal_con_ventanillas
        crear_sucursal_con_ventanillas(
            get_db(),
            codigo=codigo,
            nombre=nombre,
            direccion=direccion,
            telefono=telefono,
            cantidad_ventanillas=int(cantidad_ventanillas),
            prefijo_ventanilla=prefijo_ventanilla,
            objetivo_max_espera_seg=int(objetivo_max_espera_seg),
        )
        return RedirectResponse(f"{BASE}/admin/sucursales?ok=sucursal_creada", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{BASE}/admin/sucursales?error={quote_plus(str(e))}", status_code=303)


@app.post("/admin/sucursales/actualizar", dependencies=SOLO_ADMIN)
def web_actualizar_sucursal(
    request: Request,
    codigo: str = Form(""),
    nombre: str = Form(""),
    cantidad_ventanillas: int = Form(3),
):
    """Acción web para actualizar metadatos o capacidad de ventanillas de una sucursal."""
    try:
        from app.sucursales import actualizar_sucursal
        actualizar_sucursal(
            get_db(),
            codigo=codigo,
            nombre=nombre or None,
            cantidad_ventanillas=int(cantidad_ventanillas) if cantidad_ventanillas else None,
        )
        return RedirectResponse(f"{BASE}/admin/sucursales?ok=sucursal_actualizada", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{BASE}/admin/sucursales?error={quote_plus(str(e))}", status_code=303)


@app.post("/admin/sucursales/desactivar", dependencies=SOLO_ADMIN)
def web_desactivar_sucursal(
    request: Request,
    codigo: str = Form(""),
):
    """Acción web para pausar o desactivar una sucursal."""
    try:
        from app.sucursales import desactivar_sucursal_segura
        desactivar_sucursal_segura(get_db(), codigo=codigo)
        return RedirectResponse(f"{BASE}/admin/sucursales?ok=sucursal_desactivada", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{BASE}/admin/sucursales?error={quote_plus(str(e))}", status_code=303)


@app.post("/admin/sucursales/activar", dependencies=SOLO_ADMIN)
def web_activar_sucursal(
    request: Request,
    codigo: str = Form(""),
):
    """Acción web para reactivar una sucursal inactiva."""
    try:
        from app.sucursales import reactivar_sucursal
        reactivar_sucursal(get_db(), codigo=codigo)
        return RedirectResponse(f"{BASE}/admin/sucursales?ok=sucursal_reactivada", status_code=303)
    except Exception as e:
        return RedirectResponse(f"{BASE}/admin/sucursales?error={quote_plus(str(e))}", status_code=303)


# --- HU-010: Historial y Auditoría (Carlos Espinoza) -------------------------

@app.get("/api/historial", dependencies=SUPERVISION)
def api_historial(
    estado: str = "",
    ventanilla: str = "",
    prioridad: str = "",
    codigo: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    limite: int = 100,
    salto: int = 0,
):
    """Consulta turnos históricos con filtros, rango de fechas y métricas calculadas (HU-010 / S4-M04)."""
    try:
        return obtener_historial_turnos(
            get_db(),
            estado=estado.strip() or None,
            ventanilla=ventanilla.strip() or None,
            prioridad=prioridad.strip() or None,
            codigo=codigo.strip() or None,
            fecha_desde=fecha_desde.strip() or None,
            fecha_hasta=fecha_hasta.strip() or None,
            limite=limite,
            salto=salto,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error al consultar historial: {e}"}, status_code=500)


@app.get("/api/historial/descargar", dependencies=SUPERVISION)
def api_descargar_historial(
    estado: str = "",
    ventanilla: str = "",
    prioridad: str = "",
    codigo: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
):
    """Descarga en archivo JSON todos los registros del historial filtrados por estado, ventanilla, prioridad o rango de fechas (HU-010 / S4-M04)."""
    try:
        f_desde = fecha_desde.strip() or None
        f_hasta = fecha_hasta.strip() or None
        datos = exportar_historial_turnos(
            get_db(),
            estado=estado.strip() or None,
            ventanilla=ventanilla.strip() or None,
            prioridad=prioridad.strip() or None,
            codigo=codigo.strip() or None,
            fecha_desde=f_desde,
            fecha_hasta=f_hasta,
        )
        contenido = json.dumps(datos, indent=2, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        partes_nombre = ["historial_turnos"]
        if f_desde:
            partes_nombre.append(f"desde_{f_desde.replace('-', '')}")
        if f_hasta:
            partes_nombre.append(f"hasta_{f_hasta.replace('-', '')}")
        partes_nombre.append(timestamp)
        nombre_archivo = f"{'_'.join(partes_nombre)}.json"
        return Response(
            content=contenido,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
            },
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error al exportar historial: {e}"}, status_code=500)



@app.get("/historial", dependencies=SUPERVISION, response_class=HTMLResponse)
def vista_historial(
    request: Request,
    estado: str = "",
    ventanilla: str = "",
    prioridad: str = "",
    codigo: str = "",
    fecha_desde: str = "",
    fecha_hasta: str = "",
    limite: int = 50,
    salto: int = 0,
):
    """Vista de supervisión y auditoría del historial de turnos con paginación y filtros por rango de fechas (HU-010 / S4-M04)."""
    try:
        limite = max(10, min(limite, 200))
        salto = max(0, salto)
        res = obtener_historial_turnos(
            get_db(),
            estado=estado.strip() or None,
            ventanilla=ventanilla.strip() or None,
            prioridad=prioridad.strip() or None,
            codigo=codigo.strip() or None,
            fecha_desde=fecha_desde.strip() or None,
            fecha_hasta=fecha_hasta.strip() or None,
            limite=limite,
            salto=salto,
        )
        return templates.TemplateResponse(
            request,
            "historial.html",
            {
                "base": BASE,
                "turnos": res["turnos"],
                "total": res["total"],
                "limite": limite,
                "salto": salto,
                "pagina_actual": res.get("pagina_actual", 1),
                "total_paginas": res.get("total_paginas", 1),
                "filtros": res["filtros"],
                "estados_disponibles": ESTADOS,
                "ventanillas_disponibles": codigos_para_consulta(get_db()),
                "prioridades_disponibles": PRIORIDADES,
                "error": "",
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "historial.html",
            {
                "base": BASE,
                "turnos": [],
                "total": 0,
                "limite": limite,
                "salto": salto,
                "pagina_actual": 1,
                "total_paginas": 1,
                "filtros": {
                    "estado": estado,
                    "ventanilla": ventanilla,
                    "prioridad": prioridad,
                    "codigo": codigo,
                    "fecha_desde": fecha_desde,
                    "fecha_hasta": fecha_hasta,
                },
                "estados_disponibles": ESTADOS,
                "ventanillas_disponibles": VENTANILLAS,
                "prioridades_disponibles": PRIORIDADES,
                "error": f"Error cargando historial de MongoDB: {e}",
            },
            status_code=500,
        )


# --- HU-011: Dashboard y Métricas SLA (Carlos Espinoza) ----------------------

@app.get("/api/dashboard", dependencies=SUPERVISION)
def api_dashboard(sla_espera: int = 300, fecha_desde: str = "", fecha_hasta: str = ""):
    """Indicadores operacionales y métricas SLA calculadas con aggregation pipelines (HU-011)."""
    try:
        return calcular_metricas_dashboard(get_db(), sla_espera_max_seg=sla_espera,
                                           fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error calculando métricas: {e}"}, status_code=500)


@app.get("/api/dashboard/descargar", dependencies=SUPERVISION)
def api_descargar_dashboard(sla_espera: int = 300, fecha_desde: str = "", fecha_hasta: str = ""):
    """Descarga en archivo JSON los indicadores y el cumplimiento de SLA actual (HU-011)."""
    try:
        datos = exportar_metricas_dashboard(get_db(), sla_espera_max_seg=sla_espera,
                                            fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        contenido = json.dumps(datos, indent=2, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"dashboard_sla_{sla_espera}s_{timestamp}.json"
        return Response(
            content=contenido,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
            },
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error al exportar dashboard: {e}"}, status_code=500)



@app.get("/dashboard", dependencies=SUPERVISION, response_class=HTMLResponse)
def vista_dashboard(request: Request, sla_espera: int = 300, fecha_desde: str = "", fecha_hasta: str = ""):
    """Panel visual para supervisores con KPIs de espera, atención y SLA (HU-011)."""
    try:
        metricas = calcular_metricas_dashboard(get_db(), sla_espera_max_seg=sla_espera,
                                               fecha_desde=fecha_desde, fecha_hasta=fecha_hasta)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "base": BASE,
                "metricas": metricas,
                "error": "",
            },
        )
    except Exception as e:
        metricas_vacias = {
            "totales": {"esperando": 0, "llamados": 0, "en_atencion": 0, "atendidos": 0, "abandonados": 0, "total_turnos": 0},
            "promedios": {"espera_seg": 0.0, "atencion_seg": 0.0},
            "ventanillas": {"total_configuradas": len(VENTANILLAS), "activas": 0, "detalle": [{"ventanilla": v, "ocupada": False, "turnos_en_proceso": 0} for v in VENTANILLAS]},
            "sla": {"objetivo_max_espera_seg": sla_espera, "total_evaluados": 0, "cumplen": 0, "incumplen": 0, "porcentaje_cumplimiento": 100.0, "tasa_minima_requerida": 80.0, "estado": "CUMPLIDO"},
            "graficos": {"afluencia_horaria": [], "rendimiento_ventanillas": [], "distribucion_espera": {"hasta_2min": 0, "de_2_a_5min": 0, "de_5_a_10min": 0, "mas_de_10min": 0}, "porcentajes_espera": {}, "cumplimiento_5min_pct": 100.0},
            "por_fecha": {"zona": "", "rango": {"desde": "", "hasta": ""}, "max_dias": 14, "dias": [], "total_turnos": 0, "aviso": ""},
            "kpis_avanzados": {"tasa_abandono": 0.0, "tasa_atencion": 0.0, "turnos_en_proceso": 0, "ocupacion_ventanillas_pct": 0.0, "max_espera_seg": 0.0, "min_espera_seg": 0.0, "max_espera_formateada": "0s", "min_espera_formateada": "0s", "promedio_espera_formateado": "0s", "promedio_atencion_formateado": "0s"},
            "diagnostico": {"semaforo": "verde", "estado_operativo": "FLUIDO", "alertas": [], "recomendaciones": [], "hora_pico": None, "ventanilla_lider": None, "cumplimiento_5min_pct": 100.0},
        }
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "base": BASE,
                "metricas": metricas_vacias,
                "error": f"Error conectando a MongoDB para calcular métricas: {e}",
            },
            status_code=500,
        )


# --- HU-009: Pantalla pública de llamados (Aaron Benavides) ------------------

def _obtener_llamados_actuales() -> list[dict]:
    """MongoDB decide el estado real; memoria como respaldo si MongoDB falla."""
    try:
        mongo = _pantalla.consultar_desde_mongo(get_db())
    except Exception:
        mongo = None
    # MongoDB vacío significa que no hay activos; no revivir caché obsoleta.
    if mongo is not None:
        return mongo
    return _pantalla.llamados_vigentes()


def _contar_en_espera():
    """Cantidad de turnos pendientes (dato agregado, sin códigos ni personas); None si MongoDB no responde."""
    try:
        return get_db()["turnos"].count_documents({"estado": "pendiente", "servicio": SERVICIO_ID})
    except Exception:
        return None


@app.get("/api/llamados")
def api_llamados():
    """Listado de llamados activos para pantalla de sala (HU-009), con la cantidad de turnos en espera."""
    return {"ok": True, "llamados": _obtener_llamados_actuales(), "en_espera": _contar_en_espera()}


@app.get("/pantalla", response_class=HTMLResponse)
def vista_pantalla(request: Request):
    """Vista pública de llamados, sin datos personales (HU-009)."""
    return templates.TemplateResponse(
        request, "pantalla.html",
        {"base": BASE, "llamados": _obtener_llamados_actuales(), "en_espera": _contar_en_espera(),
         "servicio": SERVICIO_NOMBRE},
    )
