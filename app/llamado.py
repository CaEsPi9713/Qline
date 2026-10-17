"""
Llamar al siguiente turno (HU-005).

Redis decide quién es el siguiente (ZPOPMIN atómico) y MongoDB registra el
cambio de estado. Si MongoDB falla después de extraer el turno, se devuelve a
la cola para no perderlo ni dejar estados parciales.
"""
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app import cola
from app.constantes import ESTADO_LLAMADO, ESTADO_PENDIENTE

COLECCION = "turnos"


class LlamadoError(Exception):
    """Fallo controlado; `status` es el código HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 500):
        super().__init__(mensaje)
        self.status = status


def llamar_siguiente_turno(db, ventanilla: str) -> dict:
    """
    Devuelve {"codigo": None, ...} si no hay turnos; si no, los datos del turno
    llamado. Lanza LlamadoError / ColaError / RedisError en los fallos.
    """
    res = cola.extraer_siguiente(ventanilla)  # ColaError si la ventanilla es inválida
    if res is None:
        return {"codigo": None, "mensaje": "No hay turnos en espera."}
    codigo, score = res

    try:
        ahora = datetime.now(timezone.utc)
        doc = db[COLECCION].find_one_and_update(
            {"codigo": codigo, "estado": ESTADO_PENDIENTE},
            {"$set": {
                "estado": ESTADO_LLAMADO,
                "ventanilla": ventanilla,
                "timestamps.llamado": ahora,
            }},
            return_document=ReturnDocument.AFTER,
        )
        if doc is not None:
            creado = (doc.get("timestamps") or {}).get("creado")
            if isinstance(creado, datetime):
                if creado.tzinfo is None:
                    creado = creado.replace(tzinfo=timezone.utc)
                db[COLECCION].update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"metricas.espera_seg": round((ahora - creado).total_seconds())}},
                )
    except PyMongoError as e:
        cola.devolver_a_cola(codigo, score, ventanilla)
        raise LlamadoError(f"MongoDB no disponible; el turno {codigo} volvió a la cola: {e}", 503)

    if doc is None:
        # En Redis pero no es un turno pendiente en MongoDB: inconsistencia.
        cola.liberar_ventanilla(ventanilla)
        raise LlamadoError(
            f"El turno {codigo} estaba en la cola pero no figura como 'pendiente' en MongoDB; "
            "se descartó de la cola.", 409)

    return {
        "codigo": codigo,
        "ventanilla": ventanilla,
        "prioridad": doc.get("prioridad") or cola.prioridad_de_score(score),
        "estado": ESTADO_LLAMADO,
    }
