"""Lógica de negocio de HU-006 · Iniciar atención.

Transición implementada: llamado -> en_atencion (y ninguna otra).

La verificación del estado y el cambio ocurren en UNA sola operación de
MongoDB (update_one con filtro). Así, si dos ventanillas intentan iniciar el
mismo turno a la vez, solo una encuentra el documento en estado "llamado".
NO se debe cambiar a "leer, validar en Python y luego escribir".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .constantes import ESTADO_EN_ATENCION, ESTADO_LLAMADO, VENTANILLAS
from .excepciones import (
    DatosInvalidos,
    ServicioNoDisponible,
    TransicionNoPermitida,
    TurnoNoEncontrado,
    VentanillaNoCoincide,
)

# Formato de código del contrato de ejemplo: A-015
PATRON_CODIGO = re.compile(r"^[A-Z]-\d{3,}$")


def validar_codigo(codigo: Any) -> str:
    if not isinstance(codigo, str) or not PATRON_CODIGO.match(codigo.strip()):
        raise DatosInvalidos("Código de turno inválido (formato esperado: A-015)")
    return codigo.strip()


def validar_ventanilla(ventanilla: Any) -> str:
    if ventanilla not in VENTANILLAS:
        raise DatosInvalidos(
            f"Ventanilla inválida. Valores permitidos: {', '.join(VENTANILLAS)}"
        )
    return ventanilla


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def iniciar_atencion(coleccion, codigo: str, ventanilla: str, ahora: datetime | None = None) -> dict:
    """Inicia la atención de un turno ``llamado``.

    Args:
        coleccion: colección ``turnos`` de PyMongo (o equivalente).
        codigo: código del turno, p. ej. ``A-015``.
        ventanilla: ventanilla que inicia; debe ser la que llamó el turno (regla R3).
        ahora: solo para pruebas; por defecto la hora actual en UTC.

    Returns:
        Resumen del turno ya en atención.

    Raises:
        DatosInvalidos, TurnoNoEncontrado, TransicionNoPermitida,
        VentanillaNoCoincide, ServicioNoDisponible.
    """
    codigo = validar_codigo(codigo)
    ventanilla = validar_ventanilla(ventanilla)
    momento = ahora or _ahora()

    try:
        resultado = coleccion.update_one(
            {
                "codigo": codigo,
                "estado": ESTADO_LLAMADO,
                "ventanilla": ventanilla,
            },
            {
                "$set": {
                    "estado": ESTADO_EN_ATENCION,
                    "timestamps.inicio_atencion": momento,
                }
            },
        )

        if resultado.modified_count == 1:
            return _resumen(coleccion.find_one({"codigo": codigo}))

        # No se modificó nada: determinar la causa para dar una respuesta controlada.
        turno = coleccion.find_one({"codigo": codigo})
    except Exception as exc:  # fallo de conexión u otro error del motor
        raise ServicioNoDisponible() from exc

    if turno is None:
        raise TurnoNoEncontrado()
    if turno.get("estado") != ESTADO_LLAMADO:
        raise TransicionNoPermitida(
            f"El turno está en estado '{turno.get('estado')}'; "
            "solo se puede iniciar un turno 'llamado'"
        )
    if turno.get("ventanilla") != ventanilla:
        raise VentanillaNoCoincide()
    # Caso límite: otra solicitud lo cambió entre medias.
    raise TransicionNoPermitida()


def _resumen(turno: dict) -> dict:
    inicio = (turno.get("timestamps") or {}).get("inicio_atencion")
    return {
        "codigo": turno["codigo"],
        "estado": turno["estado"],
        "ventanilla": turno.get("ventanilla"),
        "inicio_atencion": inicio.isoformat() if hasattr(inicio, "isoformat") else inicio,
    }
