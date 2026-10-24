"""
Llamar al siguiente turno (HU-005).

Redis decide quién es el siguiente (ZPOPMIN atómico) y MongoDB registra el
cambio de estado. Si MongoDB falla después de extraer el turno, se devuelve a
la cola para no perderlo ni dejar estados parciales.

Regla: una ventanilla atiende un turno a la vez. Si ya tiene uno `llamado` o
`en_atencion` no se le asigna otro (409). Hay dos defensas: una comprobación
previa contra MongoDB (que además repara una clave de Redis obsoleta) y la
reserva atómica de Redis (que cubre dos solicitudes simultáneas).
"""
from datetime import datetime, timezone

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app import cola, eventos
from app.constantes import ESTADO_EN_ATENCION, ESTADO_LLAMADO, ESTADO_PENDIENTE, VENTANILLAS

COLECCION = "turnos"
ESTADOS_ACTIVOS = [ESTADO_LLAMADO, ESTADO_EN_ATENCION]
TEXTO_ESTADO = {ESTADO_LLAMADO: "llamado", ESTADO_EN_ATENCION: "en atención"}


class LlamadoError(Exception):
    """Fallo controlado; `status` es el código HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 500):
        super().__init__(mensaje)
        self.status = status


def _turno_activo_de(db, ventanilla: str):
    """
    Turno `llamado` o `en_atencion` de la ventanilla según MongoDB, o None.
    Si la clave de Redis apunta a un turno que ya terminó (o que no existe), la
    libera: es un estado obsoleto y no debe bloquear la ventanilla.
    """
    col = db[COLECCION]
    codigo = cola.turno_actual(ventanilla)
    if codigo:
        doc = col.find_one({"codigo": codigo})
        if doc and doc.get("estado") in ESTADOS_ACTIVOS and doc.get("ventanilla") == ventanilla:
            return doc
        cola.liberar_ventanilla_si(ventanilla, codigo)
    return col.find_one({"ventanilla": ventanilla, "estado": {"$in": ESTADOS_ACTIVOS}})


def _ocupada(ventanilla: str, codigo: str, estado: str = None) -> LlamadoError:
    detalle = f" ({TEXTO_ESTADO[estado]})" if estado in TEXTO_ESTADO else ""
    return LlamadoError(
        f"{ventanilla} ya tiene el turno {codigo}{detalle}. "
        "Inícielo o finalícelo en el panel de atención antes de llamar otro.", 409)


def llamar_siguiente_turno(db, ventanilla: str) -> dict:
    """
    Devuelve {"codigo": None, ...} si no hay turnos; si no, los datos del turno
    llamado. Lanza LlamadoError / ColaError / RedisError en los fallos.
    """
    if ventanilla not in VENTANILLAS:
        raise cola.ColaError(f"Ventanilla inválida: {ventanilla!r}")
    try:
        activo = _turno_activo_de(db, ventanilla)
    except PyMongoError as e:
        raise LlamadoError(f"MongoDB no disponible: {e}", 503)
    if activo:
        raise _ocupada(ventanilla, activo["codigo"], activo.get("estado"))

    try:
        res = cola.reservar_y_extraer(ventanilla)
    except cola.VentanillaOcupada as e:
        if e.codigo:
            raise _ocupada(ventanilla, e.codigo)
        raise LlamadoError(f"{ventanilla} está recibiendo un turno en este momento; intente de nuevo.", 409)
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

    prioridad = doc.get("prioridad") or cola.prioridad_de_score(score)
    resultado = {
        "codigo": codigo,
        "ventanilla": ventanilla,
        "prioridad": prioridad,
        "estado": ESTADO_LLAMADO,
    }
    try:
        cola.confirmar_asignacion(ventanilla, codigo, prioridad=prioridad)
    except RedisError:
        # MongoDB ya registró la llamada: no se deshace. La ventanilla sigue ocupada
        # por MongoDB y el panel muestra el turno; solo falta el estado temporal.
        resultado["aviso"] = "El turno se llamó, pero no se pudo registrar su estado temporal en Redis."
    # Aviso en vivo (pantalla pública, consulta por QR); de mejor esfuerzo: nunca deshace la llamada.
    eventos.publicar(eventos.TURNO_LLAMADO, codigo=codigo, estado=ESTADO_LLAMADO,
                     ventanilla=ventanilla, prioridad=prioridad)
    return resultado
