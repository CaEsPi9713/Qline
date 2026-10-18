"""HU-002: consulta de un turno sin modificar MongoDB ni Redis.

MongoDB determina el estado persistido; Redis solamente aporta la posicion de
los turnos pendientes. Una falla de Redis no oculta el estado del turno.
"""

import re

from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app import cola
from app.constantes import ESTADO_PENDIENTE, ESTADOS, SERVICIO_ID

COLECCION = "turnos"
PATRON_CODIGO = re.compile(r"A-\d{3,}\Z")


class ConsultaError(Exception):
    """Error controlado en una consulta; status es el HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 500):
        super().__init__(mensaje)
        self.status = status


def consultar_turno(db, codigo: str) -> dict:
    """Obtiene estado y posicion del turno sin alterar ninguno de los motores."""
    if not isinstance(codigo, str):
        raise ConsultaError("Ingrese un código de turno válido (por ejemplo, A-001).", 400)

    codigo = codigo.strip().upper()
    if not PATRON_CODIGO.fullmatch(codigo):
        raise ConsultaError("Ingrese un código de turno válido (por ejemplo, A-001).", 400)

    try:
        documento = db[COLECCION].find_one(
            {"codigo": codigo, "servicio": SERVICIO_ID},
            {"_id": 0, "codigo": 1, "servicio": 1, "prioridad": 1,
             "estado": 1, "ventanilla": 1},
        )
    except PyMongoError as exc:
        raise ConsultaError("No es posible consultar MongoDB en este momento.", 503) from exc

    if documento is None:
        raise ConsultaError(f"No se encontró el turno {codigo}.", 404)

    estado = documento.get("estado")
    if estado not in ESTADOS:
        raise ConsultaError("El turno tiene un estado no reconocido.", 409)

    turnos_antes = None
    posicion = None
    aviso = None

    if estado == ESTADO_PENDIENTE:
        try:
            turnos_antes = cola.posicion_en_cola(codigo)
        except RedisError:
            aviso = "La posición en la cola no está disponible temporalmente."
        else:
            if turnos_antes is None:
                aviso = "El turno está pendiente, pero no se pudo determinar su posición en la cola."
            else:
                posicion = turnos_antes + 1

    return {
        "codigo": documento["codigo"],
        "servicio": documento["servicio"],
        "prioridad": documento.get("prioridad"),
        "estado": estado,
        "ventanilla": documento.get("ventanilla"),
        "turnos_antes": turnos_antes,
        "posicion": posicion,
        "aviso": aviso,
    }
