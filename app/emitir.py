"""
Emisión de turnos para Atención General (HU-001).

Genera el consecutivo único en Redis (INCR), crea el documento inicial
en MongoDB (estado 'pendiente', timestamps en UTC) y encola el turno
en el Sorted Set de Redis respetando el orden por prioridad y llegada.
Implementa compensación segura, manejo diferenciado de fallos parciales y
mensajes de error sanitizados que no exponen detalles internos ni credenciales.
"""
from datetime import datetime, timezone
import uuid

from pymongo.errors import PyMongoError
from redis.exceptions import ConnectionError, RedisError, ResponseError, TimeoutError

from app import cola
from app.constantes import (
    ESTADO_PENDIENTE,
    PRIORIDADES,
    SERVICIO_ID,
    SERVICIO_NOMBRE,
)
from app.qr import construir_url_qr

COLECCION = "turnos"


class EmisionError(Exception):
    """Fallo controlado en la emisión del turno; `status` es el código HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 500):
        super().__init__(mensaje)
        self.status = status


def _compensar_eliminacion(db, doc_id, codigo: str) -> None:
    """
    Elimina únicamente el documento insertado por la operación actual cuando se
    establece fehacientemente que el turno no ingresó a la cola Redis.
    No expone credenciales ni detalles de conexión en caso de fallo.
    """
    try:
        db[COLECCION].delete_one({"_id": doc_id})
    except PyMongoError as err_mongo:
        raise EmisionError(
            f"No se pudo encolar el turno {codigo} y falló la compensación en MongoDB. "
            f"ID de documento afectado: {doc_id}",
            500,
        ) from err_mongo


def emitir_turno(db, prioridad: str) -> dict:
    """
    Emite un nuevo turno para Atención General según el contrato del Plan Maestro (Sección 4.5).

    1. Valida la prioridad ('normal' o 'preferencial').
    2. Genera código atómico con Redis INCR (siguiente_codigo).
    3. Persiste el documento en MongoDB (colección 'turnos').
    4. Encola en Redis Sorted Set (cola.encolar).
       - Si el no-encolado es fehaciente (duplicado/rechazo): compensa eliminando el documento exacto.
       - Si la falla es ambigua (timeout/desconexión): preserva el documento para reconciliación.
    5. Retorna los datos del turno emitido sin exponer datos internos.
    """
    if not prioridad or not isinstance(prioridad, str):
        raise EmisionError("Debe especificar una prioridad ('normal' o 'preferencial').", 400)

    prioridad = prioridad.strip().lower()
    if prioridad not in PRIORIDADES:
        opciones = ", ".join(repr(p) for p in PRIORIDADES)
        raise EmisionError(
            f"Prioridad inválida: {prioridad!r}. Las opciones válidas son: {opciones}.",
            400,
        )

    # 1. Generación del código atómico en Redis
    try:
        codigo = cola.siguiente_codigo()
    except RedisError:
        raise EmisionError("Redis no disponible para generar código de turno.", 503)

    # 2. Preparación del documento conforme a Sección 4.5 y contrato HU-003
    ahora = datetime.now(timezone.utc)
    llegada_ms = int(ahora.timestamp() * 1000)
    qr_token = str(uuid.uuid4()).lower()

    documento = {
        "codigo": codigo,
        "servicio": SERVICIO_ID,
        "prioridad": prioridad,
        "estado": ESTADO_PENDIENTE,
        "ventanilla": None,
        "operador": None,
        "qr_token": qr_token,
        "timestamps": {
            "creado": ahora,
            "llamado": None,
            "inicio_atencion": None,
            "finalizado": None,
            "abandonado": None,
        },
        "metricas": {
            "espera_seg": None,
            "atencion_seg": None,
        },
    }

    # 3. Persistencia en MongoDB
    try:
        resultado = db[COLECCION].insert_one(documento)
        doc_id = resultado.inserted_id
    except PyMongoError:
        raise EmisionError("MongoDB no disponible al persistir el turno.", 503)

    # 4. Encolado en Redis (Sorted Set) con manejo diferenciado de fallos
    try:
        encolado = cola.encolar(codigo, prioridad, llegada_ms)
        if not encolado:
            # Falla confirmada de no-encolado (el código ya estaba en cola): compensar eliminando
            _compensar_eliminacion(db, doc_id, codigo)
            raise EmisionError(
                f"El turno {codigo} ya se encontraba registrado en la cola de Redis. Inserción compensada.",
                409,
            )
    except ResponseError:
        # Falla confirmada por comando rechazado en el servidor Redis: compensar eliminando
        _compensar_eliminacion(db, doc_id, codigo)
        raise EmisionError(
            f"Redis rechazó el comando de encolado para el turno {codigo}. Inserción compensada.",
            502,
        )
    except (ConnectionError, TimeoutError):
        # Falla ambigua de red/timeout: NO eliminar para no causar inconsistencia
        # en caso de que la operación haya llegado a Redis y el turno sea atendido.
        raise EmisionError(
            f"Falla ambigua de conexión o timeout con Redis al encolar el turno {codigo}. "
            "El turno se conservó en MongoDB para reconciliación y rehidratación posterior.",
            503,
        )
    except RedisError:
        # Falla genérica no tipificada: tratamiento conservador sin eliminación
        raise EmisionError(
            f"Error general en Redis al encolar el turno {codigo}. "
            "El turno se conservó en MongoDB para reconciliación.",
            503,
        )

    qr_url = construir_url_qr(qr_token)

    return {
        "id": str(doc_id),
        "codigo": codigo,
        "servicio": SERVICIO_ID,
        "servicio_nombre": SERVICIO_NOMBRE,
        "prioridad": prioridad,
        "estado": ESTADO_PENDIENTE,
        "creado": ahora.isoformat(),
        "qr_token": qr_token,
        "qr_url": qr_url,
    }
