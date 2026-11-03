"""
Asignación de ventanillas a operadores (entrega a sucursal · Fase 4).

El supervisor (o el administrador) decide en qué ventanilla trabaja cada operador, de modo que el operador no
elige: solo llama y atiende. Reglas:

- Una ventanilla por operador y un operador por ventanilla (índice único parcial en `usuarios.ventanilla_asignada`
  y comprobación previa para dar un mensaje claro).
- Solo se asigna a operadores activos y solo ventanillas activas del catálogo.
- No se reasigna ni se quita una ventanilla mientras tenga un turno `llamado` o `en_atencion`: primero se finaliza.
- Asignar una ventanilla no cierra la sesión del operador (no cambia sus privilegios).
"""
from typing import Optional

from pymongo.errors import DuplicateKeyError, PyMongoError

from app import auth
from app.auth import AuthError, COLECCION_USUARIOS, ESTADO_ACTIVO, ROL_OPERADOR
from app.constantes import ESTADO_EN_ATENCION, ESTADO_LLAMADO
from app.ventanillas import ventanillas_activas

COLECCION_TURNOS = "turnos"
ESTADOS_EN_CURSO = [ESTADO_LLAMADO, ESTADO_EN_ATENCION]
MENSAJE_SIN_VENTANILLA = "No tiene una ventanilla asignada. Pida a su supervisor que le asigne una."


def turnos_en_curso(db) -> dict:
    """{ventanilla: (código, estado)} de los turnos `llamado` o `en_atencion`, en una sola consulta."""
    try:
        docs = db[COLECCION_TURNOS].find({"estado": {"$in": ESTADOS_EN_CURSO}}, {"codigo": 1, "estado": 1, "ventanilla": 1})
        return {d["ventanilla"]: (d.get("codigo"), d.get("estado")) for d in docs if d.get("ventanilla")}
    except PyMongoError as exc:
        raise AuthError("No es posible consultar los turnos en este momento.", 503) from exc


def ventanilla_de(db, usuario: str) -> Optional[str]:
    doc = auth.obtener_usuario(db, usuario)
    return (doc or {}).get("ventanilla_asignada")


def listar(db) -> dict:
    """Operadores activos con su ventanilla y ventanillas activas con su operador, ambos con el turno en curso."""
    en_curso = turnos_en_curso(db)
    try:
        operadores = list(db[COLECCION_USUARIOS].find({"rol": ROL_OPERADOR, "estado": ESTADO_ACTIVO}))
    except PyMongoError as exc:
        raise AuthError("No es posible consultar los usuarios en este momento.", 503) from exc
    catalogo = list(ventanillas_activas(db))
    de_ventanilla = {o.get("ventanilla_asignada"): o["usuario"] for o in operadores if o.get("ventanilla_asignada")}
    filas_operadores = []
    for o in sorted(operadores, key=lambda x: x["usuario"]):
        v = o.get("ventanilla_asignada")
        filas_operadores.append({"usuario": o["usuario"], "ventanilla": v, "turno": en_curso.get(v)[0] if v in en_curso else None,
                                 "libres": [c for c in catalogo if c == v or c not in de_ventanilla]})
    filas_ventanillas = [{"codigo": c, "operador": de_ventanilla.get(c), "turno": en_curso.get(c)} for c in catalogo]
    return {"operadores": filas_operadores, "ventanillas": filas_ventanillas}


def _operador_activo(db, usuario: str) -> dict:
    doc = auth.buscar_usuario(db, usuario)
    if doc.get("rol") != ROL_OPERADOR:
        raise AuthError("Solo se asignan ventanillas a operadores.", 409)
    if doc.get("estado") != ESTADO_ACTIVO:
        raise AuthError("El operador no está activo; habilite primero su cuenta.", 409)
    return doc


def _exigir_libre_de_turno(db, ventanilla: str, operador: str) -> None:
    en_curso = turnos_en_curso(db).get(ventanilla)
    if en_curso:
        raise AuthError(f"{ventanilla} tiene el turno {en_curso[0]} en curso; finalícelo en el panel antes de cambiar "
                        f"la asignación de {operador}.", 409)


def asignar_ventanilla(db, operador: str, ventanilla: str, por: str) -> dict:
    """Asigna (o reasigna) la ventanilla del operador."""
    doc = _operador_activo(db, operador)
    codigo = ventanilla.strip().upper() if isinstance(ventanilla, str) else ""
    if codigo not in ventanillas_activas(db):
        raise AuthError(f"La ventanilla {codigo or '(vacía)'} no existe o está desactivada.", 400)
    actual = doc.get("ventanilla_asignada")
    if actual == codigo:
        return {"usuario": doc["usuario"], "ventanilla": codigo, "cambio": False}
    if actual:
        _exigir_libre_de_turno(db, actual, doc["usuario"])
    ocupante = db[COLECCION_USUARIOS].find_one({"ventanilla_asignada": codigo, "usuario": {"$ne": doc["usuario"]}})
    if ocupante:
        raise AuthError(f"{codigo} ya está asignada a {ocupante['usuario']}. Quítesela primero.", 409)
    try:
        auth.aplicar_cambio(db, doc, {"ventanilla_asignada": codigo}, "asignar_ventanilla", por, cerrar_sesiones=False)
    except DuplicateKeyError as exc:
        raise AuthError(f"{codigo} acaba de asignarse a otro operador. Actualice la pantalla.", 409) from exc
    return {"usuario": doc["usuario"], "ventanilla": codigo, "cambio": True}


def quitar_ventanilla(db, operador: str, por: str) -> dict:
    """Deja al operador sin ventanilla (no puede llamar ni atender hasta que se le asigne otra)."""
    doc = _operador_activo(db, operador)
    actual = doc.get("ventanilla_asignada")
    if not actual:
        raise AuthError("El operador no tiene ventanilla asignada.", 409)
    _exigir_libre_de_turno(db, actual, doc["usuario"])
    auth.aplicar_cambio(db, doc, {"ventanilla_asignada": None}, "quitar_ventanilla", por, cerrar_sesiones=False)
    return {"usuario": doc["usuario"], "ventanilla": None, "cambio": True}
