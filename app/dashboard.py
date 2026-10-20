"""
Módulo de Dashboard y Métricas SLA (HU-011 / HU-015).

Responsable: Carlos Espinoza (cespinoza)
Calcula mediante Aggregation Pipelines e indicadores analíticos en MongoDB:
  - Turnos en espera
  - Turnos atendidos
  - Tiempo promedio de espera
  - Tiempo promedio de atención
  - Ventanillas activas / con turno asignado
  - Cumplimiento de objetivo SLA (tiempo de espera)
"""
from typing import Optional
from pymongo.database import Database

from app.constantes import (
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    SERVICIO_ID,
    VENTANILLAS,
)

COLECCION_TURNOS = "turnos"

# Objetivo SLA por defecto: espera máxima de 300 segundos (5 minutos)
SLA_OBJETIVO_ESPERA_SEG_DEFECTO = 300
SLA_TASA_MINIMA_CUMPLIMIENTO = 80.0  # 80% de cumplimiento para calificar verde/cumple


def calcular_metricas_dashboard(
    db: Database,
    sla_espera_max_seg: int = SLA_OBJETIVO_ESPERA_SEG_DEFECTO,
) -> dict:
    """
    Ejecuta aggregation pipelines sobre la colección `turnos` de MongoDB
    para obtener los indicadores del dashboard y el cumplimiento de SLA.
    """
    col = db[COLECCION_TURNOS]

    # 1. Conteo global por estados
    pipeline_estados = [
        {"$match": {"servicio": SERVICIO_ID}},
        {"$group": {"_id": "$estado", "total": {"$sum": 1}}},
    ]
    conteo_estados = {est: 0 for est in (
        ESTADO_PENDIENTE, ESTADO_LLAMADO, ESTADO_EN_ATENCION, ESTADO_ATENDIDO, ESTADO_ABANDONADO
    )}
    for item in col.aggregate(pipeline_estados):
        if item["_id"] in conteo_estados:
            conteo_estados[item["_id"]] = item["total"]

    turnos_esperando = conteo_estados[ESTADO_PENDIENTE]
    turnos_llamados = conteo_estados[ESTADO_LLAMADO]
    turnos_en_atencion = conteo_estados[ESTADO_EN_ATENCION]
    turnos_atendidos = conteo_estados[ESTADO_ATENDIDO]
    turnos_abandonados = conteo_estados[ESTADO_ABANDONADO]
    total_turnos = sum(conteo_estados.values())

    # 2. Promedios de tiempos (espera y atención) y métricas SLA
    pipeline_tiempos = [
        {
            "$match": {
                "servicio": SERVICIO_ID,
                "$or": [
                    {"metricas.espera_seg": {"$ne": None}},
                    {"metricas.atencion_seg": {"$ne": None}},
                ],
            }
        },
        {
            "$group": {
                "_id": None,
                "promedio_espera": {"$avg": "$metricas.espera_seg"},
                "promedio_atencion": {"$avg": "$metricas.atencion_seg"},
                "max_espera": {"$max": "$metricas.espera_seg"},
                "min_espera": {"$min": "$metricas.espera_seg"},
                "total_con_espera": {
                    "$sum": {"$cond": [{"$ne": ["$metricas.espera_seg", None]}, 1, 0]}
                },
                "cumplen_sla": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$ne": ["$metricas.espera_seg", None]},
                                    {"$lte": ["$metricas.espera_seg", sla_espera_max_seg]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]

    res_tiempos = list(col.aggregate(pipeline_tiempos))
    if res_tiempos:
        data_t = res_tiempos[0]
        prom_espera = round(data_t.get("promedio_espera") or 0.0, 1)
        prom_atencion = round(data_t.get("promedio_atencion") or 0.0, 1)
        total_evaluados_sla = data_t.get("total_con_espera", 0)
        cumplen_sla = data_t.get("cumplen_sla", 0)
    else:
        prom_espera = 0.0
        prom_atencion = 0.0
        total_evaluados_sla = 0
        cumplen_sla = 0

    incumplen_sla = max(0, total_evaluados_sla - cumplen_sla)
    if total_evaluados_sla > 0:
        porcentaje_cumplimiento = round((cumplen_sla / total_evaluados_sla) * 100, 1)
    else:
        porcentaje_cumplimiento = 100.0

    sla_cumplido = porcentaje_cumplimiento >= SLA_TASA_MINIMA_CUMPLIMIENTO

    # 3. Ventanillas activas (ventanillas con turnos actualmente en 'llamado' o 'en_atencion')
    pipeline_ventanillas = [
        {
            "$match": {
                "servicio": SERVICIO_ID,
                "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
                "ventanilla": {"$ne": None},
            }
        },
        {"$group": {"_id": "$ventanilla", "turnos_activos": {"$sum": 1}}},
    ]
    ventanillas_ocupadas = {item["_id"]: item["turnos_activos"] for item in col.aggregate(pipeline_ventanillas)}
    ventanillas_activas_conteo = len(ventanillas_ocupadas)

    detalle_ventanillas = []
    for v in VENTANILLAS:
        detalle_ventanillas.append({
            "ventanilla": v,
            "ocupada": v in ventanillas_ocupadas,
            "turnos_en_proceso": ventanillas_ocupadas.get(v, 0),
        })

    return {
        "ok": True,
        "servicio": SERVICIO_ID,
        "totales": {
            "total_turnos": total_turnos,
            "esperando": turnos_esperando,
            "llamados": turnos_llamados,
            "en_atencion": turnos_en_atencion,
            "atendidos": turnos_atendidos,
            "abandonados": turnos_abandonados,
        },
        "promedios": {
            "espera_seg": prom_espera,
            "atencion_seg": prom_atencion,
        },
        "ventanillas": {
            "total_configuradas": len(VENTANILLAS),
            "activas": ventanillas_activas_conteo,
            "detalle": detalle_ventanillas,
        },
        "sla": {
            "objetivo_max_espera_seg": sla_espera_max_seg,
            "total_evaluados": total_evaluados_sla,
            "cumplen": cumplen_sla,
            "incumplen": incumplen_sla,
            "porcentaje_cumplimiento": porcentaje_cumplimiento,
            "tasa_minima_requerida": SLA_TASA_MINIMA_CUMPLIMIENTO,
            "estado": "CUMPLIDO" if sla_cumplido else "INCUMPLIDO",
        },
    }
