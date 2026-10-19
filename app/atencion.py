"""Lógica de negocio del ciclo de atención.

HU-006 Iniciar atención:    llamado -> en_atencion
HU-007 Finalizar atención:  en_atencion -> atendido
(y ninguna otra transición).

La verificación del estado y el cambio ocurren en UNA sola operación de
MongoDB (update_one con filtro). Así, si dos ventanillas intentan iniciar el
mismo turno a la vez, solo una encuentra el documento en estado "llamado".
Lo mismo aplica a finalizar_atencion con el estado "en_atencion".
NO se debe cambiar a "leer, validar en Python y luego escribir".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

from app.constantes import (
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    VENTANILLAS,
)
from app.excepciones import (
    DatosInvalidos,
    ServicioNoDisponible,
    TransicionNoPermitida,
    TurnoInconsistente,
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




def _como_utc(valor: datetime) -> datetime:
    """PyMongo devuelve fechas sin zona (UTC); se les asigna UTC explícitamente."""
    return valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor


def _iso(valor) -> str | None:
    if not isinstance(valor, datetime):
        return valor
    return _como_utc(valor).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _resumen(turno: dict) -> dict:
    ts = turno.get("timestamps") or {}
    return {
        "codigo": turno["codigo"],
        "estado": turno["estado"],
        "ventanilla": turno.get("ventanilla"),
        "inicio_atencion": _iso(ts.get("inicio_atencion")),
    }


def calcular_atencion_seg(inicio: datetime, fin: datetime) -> int:
    """Segundos entre inicio_atencion y finalizado (metricas.atencion_seg)."""
    segundos = (_como_utc(fin) - _como_utc(inicio)).total_seconds()
    if segundos < 0:
        raise TurnoInconsistente("La finalización es anterior al inicio de la atención")
    return int(round(segundos))


def finalizar_atencion(
    coleccion,
    codigo: str,
    ventanilla: str,
    ahora: datetime | None = None,
    al_finalizar: Callable[[str], Any] | None = None,
) -> dict:
    """Finaliza la atención de un turno ``en_atencion`` (HU-007).

    El cambio se hace con un update_one cuyo filtro exige el estado, la
    ventanilla y el inicio leído: si dos solicitudes finalizan a la vez, solo
    una modifica el documento y la otra recibe TransicionNoPermitida. Un
    reintento tampoco sobrescribe ``finalizado``.

    Args:
        al_finalizar: gancho que se invoca con el código SOLO si este llamado
            finalizó el turno (sirve para liberar el estado en Redis). Si falla,
            el turno queda igualmente ``atendido`` en MongoDB y el resultado
            indica ``redis_liberado: False``.

    Raises:
        DatosInvalidos, TurnoNoEncontrado, TransicionNoPermitida,
        VentanillaNoCoincide, TurnoInconsistente, ServicioNoDisponible.
    """
    codigo = validar_codigo(codigo)
    ventanilla = validar_ventanilla(ventanilla)
    momento = ahora or _ahora()

    try:
        turno = coleccion.find_one({"codigo": codigo})
    except Exception as exc:
        raise ServicioNoDisponible() from exc

    if turno is None:
        raise TurnoNoEncontrado()
    if turno.get("estado") != ESTADO_EN_ATENCION:
        raise TransicionNoPermitida(
            f"El turno está en estado '{turno.get('estado')}'; "
            "solo se puede finalizar un turno 'en_atencion'"
        )
    if turno.get("ventanilla") != ventanilla:
        raise VentanillaNoCoincide("El turno está siendo atendido en otra ventanilla")
    inicio = (turno.get("timestamps") or {}).get("inicio_atencion")
    if not isinstance(inicio, datetime):
        raise TurnoInconsistente("El turno está en atención pero no tiene inicio registrado")

    atencion_seg = calcular_atencion_seg(inicio, momento)

    try:
        resultado = coleccion.update_one(
            {
                "codigo": codigo,
                "estado": ESTADO_EN_ATENCION,
                "ventanilla": ventanilla,
                "timestamps.inicio_atencion": inicio,
            },
            {
                "$set": {
                    "estado": ESTADO_ATENDIDO,
                    "timestamps.finalizado": momento,
                    "metricas.atencion_seg": atencion_seg,
                }
            },
        )
    except Exception as exc:
        raise ServicioNoDisponible() from exc

    if resultado.modified_count != 1:
        # Otra solicitud lo finalizó (o cambió) entre la lectura y la escritura.
        raise TransicionNoPermitida("El turno ya no está en atención (finalizado por otra solicitud)")

    respuesta = {
        "codigo": codigo,
        "estado": ESTADO_ATENDIDO,
        "ventanilla": ventanilla,
        "inicio_atencion": _iso(inicio),
        "finalizado": _iso(momento),
        "atencion_seg": atencion_seg,
        "redis_liberado": None,
    }
    if al_finalizar is not None:
        try:
            al_finalizar(codigo)
            respuesta["redis_liberado"] = True
        except Exception:
            respuesta["redis_liberado"] = False
    return respuesta
