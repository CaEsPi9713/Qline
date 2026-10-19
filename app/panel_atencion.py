"""Datos del panel de atención: qué turno tiene cada ventanilla ahora.

El turno actual se toma de Redis (ventanilla:{id}:actual). Si Redis no lo tiene
o no responde, se busca en MongoDB un turno de esa ventanilla en estado
'en_atencion' o 'llamado', para que el operador pueda terminar su trabajo
aunque el estado temporal se haya perdido. MongoDB decide siempre el estado.
"""

from app.atencion import _iso
from app.constantes import (
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    VENTANILLAS,
    clave_ventanilla_actual,
)
from app.redis_client import get_redis

COLECCION = "turnos"


def _actual_en_redis(ventanilla: str):
    try:
        return get_redis().get(clave_ventanilla_actual(ventanilla)), ""
    except Exception as e:
        return None, f"Redis no disponible: {e}"


def _fila(turno: dict) -> dict:
    ts = turno.get("timestamps") or {}
    return {
        "codigo": turno["codigo"],
        "estado": turno["estado"],
        "prioridad": turno.get("prioridad"),
        "llamado": _iso(ts.get("llamado")),
        "inicio_atencion": _iso(ts.get("inicio_atencion")),
        "puede_iniciar": turno["estado"] == ESTADO_LLAMADO,
        "puede_finalizar": turno["estado"] == ESTADO_EN_ATENCION,
    }


def estado_ventanillas(db) -> tuple[list[dict], list[str]]:
    """Devuelve (ventanillas con su turno actual, avisos). Nunca lanza por Redis."""
    col = db[COLECCION]
    avisos: list[str] = []
    ventanillas = []
    for v in VENTANILLAS:
        codigo, aviso = _actual_en_redis(v)
        if aviso and aviso not in avisos:
            avisos.append(aviso)
        turno = col.find_one({"codigo": codigo}) if codigo else None
        # Redis apunta a un turno que ya terminó (o no existe): no es un turno activo.
        if turno is not None and turno.get("estado") not in (ESTADO_LLAMADO, ESTADO_EN_ATENCION):
            avisos.append(f"{v}: Redis apunta a {codigo}, que en MongoDB está '{turno.get('estado')}'.")
            turno = None
        if turno is None:
            for estado in (ESTADO_EN_ATENCION, ESTADO_LLAMADO):
                turno = col.find_one({"ventanilla": v, "estado": estado})
                if turno is not None:
                    break
        ventanillas.append({"id": v, "turno": _fila(turno) if turno else None})
    return ventanillas, avisos
