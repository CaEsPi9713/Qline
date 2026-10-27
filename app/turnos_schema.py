"""
JSON Schema oficial de MongoDB para la colección `turnos` (TT-001 y TT-002).

Alineado con la Sección 4.5 del Plan Maestro de Desarrollo de QLine.
Define el validador a nivel de motor de base de datos ($jsonSchema) para impedir
estados desconocidos, prioridades inválidas, tipos incompatibles o estructuras
corruptas en los timestamps.
"""
from app.constantes import (
    ESTADOS,
    PRIORIDADES,
    SERVICIO_ID,
    VENTANILLAS,
)

COLECCION_TURNOS = "turnos"

# Formato del código: una letra mayúscula, guion y consecutivo (A-001, A-015).
# La serie real de la operación es "A-"; la serie "S-" es de los datos sintéticos
# (TT-005), que deben poder convivir con la validación del motor.
PATRON_CODIGO = r"^[A-Z]-\d{3,}$"
PATRON_UUID_V4 = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

# Definición formal de $jsonSchema de MongoDB
SCHEMA_TURNOS = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["codigo", "servicio", "prioridad", "estado", "timestamps", "metricas"],
        "additionalProperties": True,
        "properties": {
            "_id": {
                "bsonType": "objectId",
                "description": "Identificador único asignado por MongoDB",
            },
            "codigo": {
                "bsonType": "string",
                "pattern": PATRON_CODIGO,
                "description": "Código único y consecutivo del turno (ej. A-001, A-015; S-001 en datos sintéticos)",
            },
            "servicio": {
                "bsonType": "string",
                "enum": [SERVICIO_ID],
                "description": f"Servicio del turno; MVP únicamente '{SERVICIO_ID}'",
            },
            "prioridad": {
                "bsonType": "string",
                "enum": list(PRIORIDADES),
                "description": "Nivel de prioridad ('normal' o 'preferencial')",
            },
            "estado": {
                "bsonType": "string",
                "enum": list(ESTADOS),
                "description": "Estado del ciclo de vida del turno",
            },
            "ventanilla": {
                "bsonType": ["string", "null"],
                "enum": list(VENTANILLAS) + [None],
                "description": "Identificador de la ventanilla asignada o null",
            },
            "operador": {
                "bsonType": ["string", "null"],
                "description": "Identificador del operador asignado o null",
            },
            "qr_token": {
                "bsonType": ["string", "null"],
                "pattern": PATRON_UUID_V4,
                "description": "Token UUID v4 único para acceso y consulta móvil por QR (HU-003, HU-013)",
            },
            "timestamps": {
                "bsonType": "object",
                "required": ["creado"],
                "additionalProperties": False,
                "properties": {
                    "creado": {
                        "bsonType": "date",
                        "description": "Fecha y hora de creación del turno (UTC)",
                    },
                    "llamado": {
                        "bsonType": ["date", "null"],
                        "description": "Fecha y hora en que fue llamado a ventanilla o null",
                    },
                    "inicio_atencion": {
                        "bsonType": ["date", "null"],
                        "description": "Fecha y hora en que inició la atención o null",
                    },
                    "finalizado": {
                        "bsonType": ["date", "null"],
                        "description": "Fecha y hora en que finalizó la atención o null",
                    },
                    "abandonado": {
                        "bsonType": ["date", "null"],
                        "description": "Fecha y hora en que se marcó abandonado por TTL o null",
                    },
                },
            },
            "metricas": {
                "bsonType": "object",
                "additionalProperties": False,
                "properties": {
                    "espera_seg": {
                        "bsonType": ["int", "long", "double", "null"],
                        "description": "Tiempo total de espera en segundos o null",
                    },
                    "atencion_seg": {
                        "bsonType": ["int", "long", "double", "null"],
                        "description": "Tiempo total de atención en segundos o null",
                    },
                },
            },
        },
    }
}

# Índices requeridos para la colección `turnos`
INDICES_TURNOS = [
    {
        "keys": [("codigo", 1)],
        "options": {"unique": True, "name": "idx_turnos_codigo_unico"},
    },
    {
        "keys": [("estado", 1), ("timestamps.creado", 1)],
        "options": {"name": "idx_turnos_estado_creado"},
    },
    {
        "keys": [("ventanilla", 1)],
        "options": {"name": "idx_turnos_ventanilla", "sparse": True},
    },
    {
        "keys": [("timestamps.creado", -1)],
        "options": {"name": "idx_turnos_creado_desc"},
    },
    {
        # HU-008: el barrido de abandono busca {estado: llamado, timestamps.llamado <= ahora - 180 s}
        "keys": [("estado", 1), ("timestamps.llamado", 1)],
        "options": {"name": "idx_turnos_estado_llamado"},
    },
    {
        "keys": [("qr_token", 1)],
        "options": {
            "name": "idx_turnos_qr_token_unico",
            "unique": True,
            "partialFilterExpression": {"qr_token": {"$exists": True, "$type": "string"}},
        },
    },
]


def obtener_validador_turnos() -> dict:
    """Devuelve la estructura de validación completa para MongoDB."""
    return SCHEMA_TURNOS


class TurnoValidationError(ValueError):
    """Fallo en la validación del esquema de un turno."""


def validar_documento_turno(doc: dict) -> bool:
    """
    Validador en memoria equivalente a las reglas de $jsonSchema de MongoDB.
    Permite validar documentos antes de insertarlos o durante pruebas sin conexión activa.
    """
    if not isinstance(doc, dict):
        raise TurnoValidationError("El documento debe ser un diccionario.")

    for campo in ("codigo", "servicio", "prioridad", "estado", "timestamps", "metricas"):
        if campo not in doc:
            raise TurnoValidationError(f"Campo obligatorio faltante: '{campo}'")

    import re
    if not isinstance(doc["codigo"], str) or not re.fullmatch(PATRON_CODIGO, doc["codigo"]):
        raise TurnoValidationError(f"Código inválido: {doc.get('codigo')!r}. Debe coincidir con '{PATRON_CODIGO}'.")

    if doc["servicio"] != SERVICIO_ID:
        raise TurnoValidationError(f"Servicio inválido: {doc.get('servicio')!r}. Debe ser '{SERVICIO_ID}'.")

    if doc["prioridad"] not in PRIORIDADES:
        raise TurnoValidationError(f"Prioridad inválida: {doc.get('prioridad')!r}. Opciones: {PRIORIDADES}")

    if doc["estado"] not in ESTADOS:
        raise TurnoValidationError(f"Estado inválido: {doc.get('estado')!r}. Opciones: {ESTADOS}")

    ventanilla = doc.get("ventanilla")
    if ventanilla is not None and ventanilla not in VENTANILLAS:
        raise TurnoValidationError(f"Ventanilla inválida: {ventanilla!r}. Opciones: {VENTANILLAS} o null.")

    qr_token = doc.get("qr_token")
    if qr_token is not None:
        if not isinstance(qr_token, str) or not re.fullmatch(PATRON_UUID_V4, qr_token):
            raise TurnoValidationError(f"qr_token inválido: {qr_token!r}. Debe ser UUID v4 o null.")

    ts = doc.get("timestamps")
    if not isinstance(ts, dict) or "creado" not in ts or ts["creado"] is None:
        raise TurnoValidationError("El campo 'timestamps' debe ser un objeto con 'creado' obligatorio.")

    from datetime import datetime
    if not isinstance(ts["creado"], datetime):
        raise TurnoValidationError(f"'timestamps.creado' debe ser datetime/Date, no {type(ts['creado'])}.")

    for k in ("llamado", "inicio_atencion", "finalizado", "abandonado"):
        val = ts.get(k)
        if val is not None and not isinstance(val, datetime):
            raise TurnoValidationError(f"'timestamps.{k}' debe ser datetime/Date o null, no {type(val)}.")

    met = doc.get("metricas")
    if not isinstance(met, dict):
        raise TurnoValidationError("El campo 'metricas' debe ser un objeto.")

    for k in ("espera_seg", "atencion_seg"):
        val = met.get(k)
        if val is not None and not isinstance(val, (int, float)):
            raise TurnoValidationError(f"'metricas.{k}' debe ser numérico o null, no {type(val)}.")

    return True

