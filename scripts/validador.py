"""Validación de los datos sintéticos contra el contrato de turnos (sección 4.5).

No sustituye al JSON Schema de MongoDB (TT-002, de Carlos): es una comprobación
local, previa a cargar, para detectar datos incoherentes antes de que el
validator del servidor los rechace.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime

from .constantes import (
    CAMPOS_METRICAS,
    CAMPOS_TIMESTAMPS,
    CAMPOS_TURNO,
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    ESTADOS,
    PRIORIDAD_PREFERENCIAL,
    PRIORIDADES,
    SERVICIO_INICIAL,
    TTL_ABANDONO_SEG,
    VENTANILLAS,
)

PATRON_CODIGO = re.compile(r"^[A-Z]-\d{3,}$")

# Qué marcas de tiempo deben existir en cada estado.
TIMESTAMPS_POR_ESTADO = {
    ESTADO_PENDIENTE: {"creado"},
    ESTADO_LLAMADO: {"creado", "llamado"},
    ESTADO_EN_ATENCION: {"creado", "llamado", "inicio_atencion"},
    ESTADO_ATENDIDO: {"creado", "llamado", "inicio_atencion", "finalizado"},
    ESTADO_ABANDONADO: {"creado", "llamado", "abandonado"},
}


def validar_turno(doc: dict) -> list[str]:
    """Devuelve la lista de errores del documento (vacía si es válido)."""
    errores: list[str] = []
    cod = doc.get("codigo", "?")

    if set(doc) != set(CAMPOS_TURNO):
        errores.append(f"{cod}: campos distintos al contrato: {sorted(set(doc) ^ set(CAMPOS_TURNO))}")
        return errores

    if not isinstance(doc["codigo"], str) or not PATRON_CODIGO.match(doc["codigo"]):
        errores.append(f"{cod}: código con formato inválido")
    if doc["servicio"] != SERVICIO_INICIAL:
        errores.append(f"{cod}: servicio debe ser {SERVICIO_INICIAL}")
    if doc["prioridad"] not in PRIORIDADES:
        errores.append(f"{cod}: prioridad desconocida {doc['prioridad']!r}")
    if doc["estado"] not in ESTADOS:
        errores.append(f"{cod}: estado desconocido {doc['estado']!r}")
        return errores
    if doc["operador"] is not None:
        errores.append(f"{cod}: operador debe ser null en S2 (sin autenticación)")

    if doc["estado"] == ESTADO_PENDIENTE:
        if doc["ventanilla"] is not None:
            errores.append(f"{cod}: ventanilla debe ser null mientras esté pendiente")
    elif doc["ventanilla"] not in VENTANILLAS:
        errores.append(f"{cod}: ventanilla inválida {doc['ventanilla']!r}")

    ts, met = doc["timestamps"], doc["metricas"]
    if not isinstance(ts, dict) or set(ts) != set(CAMPOS_TIMESTAMPS):
        errores.append(f"{cod}: estructura de timestamps inválida")
        return errores
    if not isinstance(met, dict) or set(met) != set(CAMPOS_METRICAS):
        errores.append(f"{cod}: estructura de metricas inválida")
        return errores

    esperados = TIMESTAMPS_POR_ESTADO[doc["estado"]]
    for campo in CAMPOS_TIMESTAMPS:
        valor = ts[campo]
        if campo in esperados:
            if not isinstance(valor, datetime) or valor.tzinfo is None:
                errores.append(f"{cod}: timestamps.{campo} debe ser fecha con zona horaria")
        elif valor is not None:
            errores.append(f"{cod}: timestamps.{campo} debe ser null en estado {doc['estado']}")
    if errores:
        return errores

    # Orden cronológico
    orden = ["creado", "llamado", "inicio_atencion", "finalizado"]
    previos = [ts[c] for c in orden if ts[c] is not None]
    if previos != sorted(previos):
        errores.append(f"{cod}: marcas de tiempo fuera de orden cronológico")
    if ts["abandonado"] is not None:
        if int((ts["abandonado"] - ts["llamado"]).total_seconds()) != TTL_ABANDONO_SEG:
            errores.append(f"{cod}: abandono debe ocurrir {TTL_ABANDONO_SEG} s después del llamado")

    # Métricas derivables
    espera = int((ts["llamado"] - ts["creado"]).total_seconds()) if ts["llamado"] else None
    atencion = int((ts["finalizado"] - ts["inicio_atencion"]).total_seconds()) if ts["finalizado"] else None
    if met["espera_seg"] != espera:
        errores.append(f"{cod}: metricas.espera_seg inconsistente ({met['espera_seg']} vs {espera})")
    if met["atencion_seg"] != atencion:
        errores.append(f"{cod}: metricas.atencion_seg inconsistente ({met['atencion_seg']} vs {atencion})")
    return errores


def validar_conjunto(docs: list[dict]) -> list[str]:
    """Valida cada turno y las reglas entre turnos."""
    errores: list[str] = []
    for d in docs:
        errores.extend(validar_turno(d))
    if errores:
        return errores

    codigos = [d["codigo"] for d in docs]
    duplicados = [c for c, n in Counter(codigos).items() if n > 1]
    if duplicados:
        errores.append(f"Códigos duplicados: {duplicados[:5]}")

    # Una ventanilla no atiende dos turnos a la vez.
    for v in VENTANILLAS:
        intervalos = []
        for d in docs:
            if d["ventanilla"] != v:
                continue
            ts = d["timestamps"]
            fin = ts["finalizado"] or ts["abandonado"]  # None = aún abierto
            intervalos.append((ts["llamado"], fin, d["codigo"]))
        intervalos.sort(key=lambda x: x[0])
        for (ini_a, fin_a, cod_a), (ini_b, _fin_b, cod_b) in zip(intervalos, intervalos[1:]):
            if fin_a is None or fin_a > ini_b:
                errores.append(f"{v}: {cod_a} se solapa con {cod_b}")

    # Prioridad antes que llegada; FIFO dentro de la misma prioridad.
    llamados = [d for d in docs if d["timestamps"]["llamado"] is not None]
    for x in llamados:
        t = x["timestamps"]["llamado"]
        rango_x = (0 if x["prioridad"] == PRIORIDAD_PREFERENCIAL else 1, x["timestamps"]["creado"])
        for y in docs:
            if y is x:
                continue
            ty = y["timestamps"]
            esperaba = ty["creado"] <= t and (ty["llamado"] is None or ty["llamado"] > t)
            if not esperaba:
                continue
            rango_y = (0 if y["prioridad"] == PRIORIDAD_PREFERENCIAL else 1, ty["creado"])
            if rango_y < rango_x:
                errores.append(f"{x['codigo']} fue llamado antes que {y['codigo']}, que tenía mayor derecho")
    return errores


def resumen(docs: list[dict]) -> dict:
    """Estadísticas descriptivas del conjunto (para mostrar o documentar)."""
    esperas = [d["metricas"]["espera_seg"] for d in docs if d["metricas"]["espera_seg"] is not None]
    atenciones = [d["metricas"]["atencion_seg"] for d in docs if d["metricas"]["atencion_seg"] is not None]
    return {
        "total": len(docs),
        "por_estado": dict(sorted(Counter(d["estado"] for d in docs).items())),
        "por_prioridad": dict(sorted(Counter(d["prioridad"] for d in docs).items())),
        "por_ventanilla": dict(sorted(Counter(d["ventanilla"] or "(sin ventanilla)" for d in docs).items())),
        "mediana_espera_seg": statistics.median(esperas) if esperas else None,
        "mediana_atencion_seg": statistics.median(atenciones) if atenciones else None,
        "primer_codigo": docs[0]["codigo"] if docs else None,
        "ultimo_codigo": docs[-1]["codigo"] if docs else None,
    }
