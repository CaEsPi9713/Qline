"""
Elementos comunes de los módulos de abandono (HU-008) y recuperación (HU-012).

Las constantes NO se definen aquí: se reexportan desde app/constantes.py, que es la
única fuente de los contratos (TT-009). Así un cambio de contrato se hace en un solo
lugar y estos módulos no pueden quedar desalineados del resto del sistema.

Aquí solo viven lo que es propio de estos módulos: los errores controlados y dos
utilidades de fechas.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.constantes import (  # noqa: F401  (reexportadas a propósito)
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    ESTADOS,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    PRIORIDADES,
    SERVICIO_ID,
    TTL_ABANDONO_SEG,
    VENTANILLAS,
)

# Nombre usado por los módulos de recuperación para el único servicio del MVP.
SERVICIO_INICIAL = SERVICIO_ID

# Orden de atención por prioridad: menor sale primero. Coincide con el nivel que app/cola.py
# usa en el puntaje de la cola (0 = preferencial, 1 = normal); lo verifica una prueba.
RANGO_PRIORIDAD = {PRIORIDAD_PREFERENCIAL: 0, PRIORIDAD_NORMAL: 1}


class ErrorS3(Exception):
    """Error controlado de estos módulos. Lleva un mensaje legible para el operador."""

    mensaje = "Error en el proceso"

    def __init__(self, mensaje: str | None = None):
        self.mensaje = mensaje or self.mensaje
        super().__init__(self.mensaje)


class MongoNoDisponible(ErrorS3):
    mensaje = "MongoDB no está disponible: no se modificó nada."


class RedisNoDisponible(ErrorS3):
    mensaje = "Redis no está disponible: no se modificó nada."


EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


def a_utc(valor: datetime) -> datetime:
    """Fecha con zona UTC. PyMongo devuelve fechas sin zona (en UTC): se les asigna UTC explícitamente."""
    if valor.tzinfo is None:
        return valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)
