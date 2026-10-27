"""
Turnos de prueba coherentes con el contrato de `turnos` (sección 4.5 del plan).

Los usan las pruebas automáticas y las pruebas de recuperación y mediciones. Son
datos sintéticos: no contienen personas, solo códigos, prioridad, ventanilla y tiempos.
Cada turno respeta el orden de los tiempos de su estado y las métricas derivables.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.s3_comun import (
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
    a_utc,
)

ATENCION_POR_DEFECTO_SEG = 120      # duración de la atención si no se indica
PRESENTACION_POR_DEFECTO_SEG = 30   # tiempo entre la llamada y el inicio de la atención


def construir_turno(
    codigo: str,
    estado: str,
    prioridad: str,
    creado: datetime,
    ventanilla: str | None = None,
    llamado: datetime | None = None,
    *,
    inicio: datetime | None = None,
    finalizado: datetime | None = None,
    abandonado: datetime | None = None,
    qr_token: str | None = None,
) -> dict:
    """
    Turno de prueba en el estado indicado, con los tiempos que ese estado exige:

      pendiente    creado
      llamado      creado, llamado
      en_atencion  creado, llamado, inicio_atencion
      atendido     creado, llamado, inicio_atencion, finalizado
      abandonado   creado, llamado, abandonado (= llamado + 180 s por defecto)

    Lo que no se indique se calcula. Lanza ValueError si los datos no son coherentes.
    """
    if estado not in ESTADOS:
        raise ValueError(f"Estado desconocido: {estado!r}")
    if prioridad not in PRIORIDADES:
        raise ValueError(f"Prioridad desconocida: {prioridad!r}")
    if not codigo:
        raise ValueError("El código del turno no puede estar vacío")

    creado = a_utc(creado)
    if estado == ESTADO_PENDIENTE:
        if ventanilla is not None or llamado is not None:
            raise ValueError("Un turno pendiente no tiene ventanilla ni llamado")
    else:
        if ventanilla not in VENTANILLAS:
            raise ValueError(f"Ventanilla inválida: {ventanilla!r}")
        if llamado is None:
            raise ValueError("Un turno que ya fue llamado necesita la fecha de llamado")
        llamado = a_utc(llamado)
        if llamado < creado:
            raise ValueError("El llamado no puede ser anterior a la creación")

    if estado in (ESTADO_EN_ATENCION, ESTADO_ATENDIDO) and inicio is None:
        inicio = llamado + timedelta(seconds=PRESENTACION_POR_DEFECTO_SEG)
    if estado == ESTADO_ATENDIDO and finalizado is None:
        finalizado = inicio + timedelta(seconds=ATENCION_POR_DEFECTO_SEG)
    if estado == ESTADO_ABANDONADO and abandonado is None:
        abandonado = llamado + timedelta(seconds=TTL_ABANDONO_SEG)

    inicio = a_utc(inicio) if inicio else None
    finalizado = a_utc(finalizado) if finalizado else None
    abandonado = a_utc(abandonado) if abandonado else None
    if inicio and inicio < llamado:
        raise ValueError("El inicio de atención no puede ser anterior al llamado")
    if finalizado and finalizado < inicio:
        raise ValueError("La finalización no puede ser anterior al inicio")

    documento = {
        "codigo": codigo,
        "servicio": SERVICIO_ID,
        "prioridad": prioridad,
        "estado": estado,
        "ventanilla": ventanilla,
        "operador": None,
        "timestamps": {
            "creado": creado,
            "llamado": llamado if estado != ESTADO_PENDIENTE else None,
            "inicio_atencion": inicio,
            "finalizado": finalizado,
            "abandonado": abandonado,
        },
        "metricas": {
            "espera_seg": int((llamado - creado).total_seconds()) if estado != ESTADO_PENDIENTE else None,
            "atencion_seg": int((finalizado - inicio).total_seconds()) if finalizado else None,
        },
    }
    if qr_token is not None:
        documento["qr_token"] = qr_token
    return documento


def construir_mezcla_estados(ahora: datetime, serie: str = "A", pendientes: int = 8) -> list[dict]:
    """
    Una jornada simulada con turnos en los cinco estados. Los códigos son consecutivos
    (`{serie}-001`, `{serie}-002`…) y siguen el orden de creación, como en la operación real.

    Hay `pendientes` turnos en espera (cada tercero preferencial), un llamado cuyo plazo
    de 180 s ya venció (candidato a abandono), otro llamado aún vigente, uno en atención,
    tres atendidos y dos abandonados.
    """
    ahora = a_utc(ahora)
    plan: list[tuple[str, str, str | None, int | None]] = []   # (estado, prioridad, ventanilla, segundos desde el llamado)
    plan += [(ESTADO_ATENDIDO, PRIORIDAD_NORMAL, "V-01", 3000), (ESTADO_ATENDIDO, PRIORIDAD_PREFERENCIAL, "V-02", 2700),
             (ESTADO_ATENDIDO, PRIORIDAD_NORMAL, "V-03", 2400)]
    plan += [(ESTADO_ABANDONADO, PRIORIDAD_NORMAL, "V-01", 2000), (ESTADO_ABANDONADO, PRIORIDAD_NORMAL, "V-02", 1800)]
    plan += [(ESTADO_EN_ATENCION, PRIORIDAD_NORMAL, "V-01", 90)]
    plan += [(ESTADO_LLAMADO, PRIORIDAD_NORMAL, "V-02", TTL_ABANDONO_SEG + 20)]    # vencido
    plan += [(ESTADO_LLAMADO, PRIORIDAD_PREFERENCIAL, "V-03", 60)]                 # vigente
    plan += [(ESTADO_PENDIENTE, PRIORIDAD_PREFERENCIAL if i % 3 == 2 else PRIORIDAD_NORMAL, None, None)
             for i in range(pendientes)]

    docs = []
    for i, (estado, prioridad, ventanilla, seg_llamado) in enumerate(plan, start=1):
        creado = ahora - timedelta(minutes=len(plan) - i + 30)        # cada turno se crea 1 minuto después del anterior
        llamado = ahora - timedelta(seconds=seg_llamado) if seg_llamado is not None else None
        if llamado is not None and llamado < creado:
            creado = llamado - timedelta(seconds=30)
        docs.append(construir_turno(f"{serie}-{i:03d}", estado, prioridad, creado, ventanilla, llamado))
    docs.sort(key=lambda d: d["timestamps"]["creado"])
    for numero, d in enumerate(docs, start=1):                       # el código sigue el orden de creación
        d["codigo"] = f"{serie}-{numero:03d}"
    return docs
