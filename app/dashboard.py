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
from datetime import datetime, timezone
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


def pipeline_conteo_estados() -> list:
    """Pipeline del dashboard: cantidad de turnos por estado ($match -> $group)."""
    return [
        {"$match": {"servicio": SERVICIO_ID}},
        {"$group": {"_id": "$estado", "total": {"$sum": 1}}},
    ]


def pipeline_tiempos_sla(sla_espera_max_seg: int = SLA_OBJETIVO_ESPERA_SEG_DEFECTO) -> list:
    """Pipeline del dashboard: promedios de espera y atención, cumplimiento del SLA y desglose por rangos ($match -> $group)."""
    return [
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
                "rango_rapido": {
                    "$sum": {
                        "$cond": [
                            {"$and": [{"$ne": ["$metricas.espera_seg", None]}, {"$lte": ["$metricas.espera_seg", 120]}]},
                            1,
                            0,
                        ]
                    }
                },
                "rango_moderado": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$gt": ["$metricas.espera_seg", 120]},
                                    {"$lte": ["$metricas.espera_seg", 300]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "rango_extendido": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$gt": ["$metricas.espera_seg", 300]},
                                    {"$lte": ["$metricas.espera_seg", 600]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "rango_critico": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$metricas.espera_seg", 600]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]


def formatear_duracion_legible(segundos: float) -> str:
    """Convierte segundos en una cadena amigable como '45s' o '2m 05s'."""
    if segundos is None or segundos < 0:
        return "0s"
    s_totales = int(round(segundos))
    if s_totales < 60:
        return f"{s_totales}s"
    minutos, s_resto = divmod(s_totales, 60)
    if minutos < 60:
        return f"{minutos}m {s_resto:02d}s" if s_resto > 0 else f"{minutos}m"
    horas, m_resto = divmod(minutos, 60)
    return f"{horas}h {m_resto:02d}m"


def calcular_metricas_dashboard(
    db: Database,
    sla_espera_max_seg: int = SLA_OBJETIVO_ESPERA_SEG_DEFECTO,
) -> dict:
    """
    Ejecuta aggregation pipelines sobre la colección `turnos` de MongoDB
    para obtener los indicadores del dashboard, cumplimiento de SLA y datos gráficos (HU-011 / P02).
    """
    col = db[COLECCION_TURNOS]

    # 1. Conteo global por estados
    pipeline_estados = pipeline_conteo_estados()
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
    pipeline_tiempos = pipeline_tiempos_sla(sla_espera_max_seg)

    res_tiempos = list(col.aggregate(pipeline_tiempos))
    if res_tiempos:
        data_t = res_tiempos[0]
        prom_espera = round(data_t.get("promedio_espera") or 0.0, 1)
        prom_atencion = round(data_t.get("promedio_atencion") or 0.0, 1)
        max_espera = round(data_t.get("max_espera") or 0.0, 1)
        min_espera = round(data_t.get("min_espera") or 0.0, 1)
        total_evaluados_sla = data_t.get("total_con_espera", 0)
        cumplen_sla = data_t.get("cumplen_sla", 0)
        distribucion_espera = {
            "hasta_2min": data_t.get("rango_rapido", 0),
            "de_2_a_5min": data_t.get("rango_moderado", 0),
            "de_5_a_10min": data_t.get("rango_extendido", 0),
            "mas_de_10min": data_t.get("rango_critico", 0),
        }
    else:
        prom_espera = 0.0
        prom_atencion = 0.0
        max_espera = 0.0
        min_espera = 0.0
        total_evaluados_sla = 0
        cumplen_sla = 0
        distribucion_espera = {
            "hasta_2min": 0,
            "de_2_a_5min": 0,
            "de_5_a_10min": 0,
            "mas_de_10min": 0,
        }

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

    # Identificar lista de ventanillas configuradas dinámicamente o base
    try:
        from app.ventanillas import obtener_codigos_ventanillas
        codigos_ventanillas = obtener_codigos_ventanillas(db, solo_activas=False)
        if not codigos_ventanillas:
            codigos_ventanillas = list(VENTANILLAS)
    except Exception:
        codigos_ventanillas = list(VENTANILLAS)

    detalle_ventanillas = []
    for v in codigos_ventanillas:
        detalle_ventanillas.append({
            "ventanilla": v,
            "ocupada": v in ventanillas_ocupadas,
            "turnos_en_proceso": ventanillas_ocupadas.get(v, 0),
        })

    # 4. Afluencia horaria (P02 - estadísticas analíticas y gráficas)
    distribucion_horaria = []
    try:
        pipeline_horario = [
            {"$match": {"servicio": SERVICIO_ID, "timestamps.creado": {"$ne": None}}},
            {"$group": {"_id": {"$hour": "$timestamps.creado"}, "total": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        items_horario = {item["_id"]: item["total"] for item in col.aggregate(pipeline_horario) if item.get("_id") is not None}
        for h_local in range(7, 19):
            # En Costa Rica (UTC-6), UTC = (local + 6) % 24
            h_utc = (h_local + 6) % 24
            total_h = items_horario.get(h_utc, 0)
            distribucion_horaria.append({
                "hora": f"{h_local:02d}:00",
                "hora_num": h_local,
                "total": total_h,
            })
    except (StopIteration, Exception):
        for h_local in range(7, 19):
            distribucion_horaria.append({
                "hora": f"{h_local:02d}:00",
                "hora_num": h_local,
                "total": 0,
            })

    max_afluencia = max([item["total"] for item in distribucion_horaria] or [1])
    hora_pico = None
    for item in distribucion_horaria:
        item["porcentaje_pico"] = round((item["total"] / max_afluencia) * 100, 1) if max_afluencia > 0 else 0
        item["es_pico"] = (item["total"] == max_afluencia and max_afluencia > 0)
        item["porcentaje_total"] = round((item["total"] / total_turnos * 100), 1) if total_turnos > 0 else 0.0
        if item["es_pico"] and not hora_pico:
            hora_pico = {"hora": item["hora"], "total": item["total"]}

    # 5. Rendimiento histórico por ventanilla (P02)
    rendimiento_ventanillas = []
    ventanilla_lider = None
    try:
        pipeline_rendimiento = [
            {
                "$match": {
                    "servicio": SERVICIO_ID,
                    "ventanilla": {"$in": codigos_ventanillas},
                    "estado": ESTADO_ATENDIDO,
                }
            },
            {
                "$group": {
                    "_id": "$ventanilla",
                    "total_atendidos": {"$sum": 1},
                    "promedio_atencion_seg": {"$avg": "$metricas.atencion_seg"},
                }
            },
        ]
        items_rend = {item["_id"]: item for item in col.aggregate(pipeline_rendimiento) if item.get("_id") is not None}
        max_atendidos_v = max([info.get("total_atendidos", 0) for info in items_rend.values()] or [1])
        total_atendidos_ventanillas = sum([info.get("total_atendidos", 0) for info in items_rend.values()])

        for v in codigos_ventanillas:
            info = items_rend.get(v, {})
            tot = info.get("total_atendidos", 0)
            prom_at_v = round(info.get("promedio_atencion_seg") or 0.0, 1)
            pct_total = round((tot / total_atendidos_ventanillas * 100), 1) if total_atendidos_ventanillas > 0 else 0.0
            es_lider = (tot == max_atendidos_v and max_atendidos_v > 0)
            if es_lider and not ventanilla_lider:
                ventanilla_lider = {"ventanilla": v, "total": tot, "promedio_seg": prom_at_v}

            rendimiento_ventanillas.append({
                "ventanilla": v,
                "total_atendidos": tot,
                "promedio_atencion_seg": prom_at_v,
                "promedio_atencion_formateado": formatear_duracion_legible(prom_at_v),
                "porcentaje_max": round((tot / max_atendidos_v) * 100, 1) if max_atendidos_v > 0 else 0,
                "porcentaje_total": pct_total,
                "activa_ahora": v in ventanillas_ocupadas,
                "es_lider": es_lider,
            })
    except (StopIteration, Exception):
        for v in codigos_ventanillas:
            rendimiento_ventanillas.append({
                "ventanilla": v,
                "total_atendidos": 0,
                "promedio_atencion_seg": 0.0,
                "promedio_atencion_formateado": "0s",
                "porcentaje_max": 0,
                "porcentaje_total": 0.0,
                "activa_ahora": False,
                "es_lider": False,
            })

    # 6. Métricas operacionales y diagnóstico de calidad
    tasa_abandono = round((turnos_abandonados / total_turnos * 100), 1) if total_turnos > 0 else 0.0
    tasa_atencion = round((turnos_atendidos / total_turnos * 100), 1) if total_turnos > 0 else 0.0
    turnos_en_proceso_total = turnos_llamados + turnos_en_atencion
    ocupacion_ventanillas_pct = round((ventanillas_activas_conteo / len(codigos_ventanillas) * 100), 1) if codigos_ventanillas else 0.0

    porcentajes_espera = {}
    if total_evaluados_sla > 0:
        for k, v in distribucion_espera.items():
            porcentajes_espera[k] = round((v / total_evaluados_sla) * 100, 1)
    else:
        porcentajes_espera = {k: 0.0 for k in distribucion_espera}

    cumplimiento_5min = (
        distribucion_espera.get("hasta_2min", 0) + distribucion_espera.get("de_2_a_5min", 0)
    )
    cumplimiento_5min_pct = round((cumplimiento_5min / total_evaluados_sla * 100), 1) if total_evaluados_sla > 0 else 100.0

    alertas = []
    recomendaciones = []
    if turnos_esperando > (ventanillas_activas_conteo * 3) and turnos_esperando >= 3:
        semaforo = "rojo"
        estado_operativo = "CONGESTIONADO"
        alertas.append(f"Alta demanda en sala ({turnos_esperando} turnos en espera frente a {ventanillas_activas_conteo} ventanillas activas).")
        recomendaciones.append("Habilitar ventanillas adicionales para descongestionar la fila.")
    elif not sla_cumplido:
        semaforo = "amarillo"
        estado_operativo = "EN ALERTA SLA"
        alertas.append(f"Cumplimiento SLA ({porcentaje_cumplimiento}%) inferior a la meta mínima institucional ({SLA_TASA_MINIMA_CUMPLIMIENTO}%).")
        recomendaciones.append(f"Priorizar atención de turnos que superen el umbral configurado de {sla_espera_max_seg}s.")
    elif tasa_abandono > 10.0 and total_turnos >= 5:
        semaforo = "amarillo"
        estado_operativo = "DESERCIÓN MODERADA"
        alertas.append(f"Tasa de abandono en {tasa_abandono}% ({turnos_abandonados} turnos cancelados).")
        recomendaciones.append("Monitorear tiempos de espera inicial para mitigar la deserción de clientes en sala.")
    else:
        semaforo = "verde"
        estado_operativo = "FLUIDO"
        alertas.append("Operación regular en rangos óptimos de atención y cumplimiento de servicio.")
        recomendaciones.append("Mantener la asignación actual de módulos de atención institucional.")

    if hora_pico and hora_pico.get("total", 0) > 0:
        recomendaciones.append(f"Franja pico registrada: {hora_pico['hora']} con {hora_pico['total']} turnos emitidos.")

    diagnostico = {
        "semaforo": semaforo,
        "estado_operativo": estado_operativo,
        "alertas": alertas,
        "recomendaciones": recomendaciones,
        "hora_pico": hora_pico,
        "ventanilla_lider": ventanilla_lider,
        "cumplimiento_5min_pct": cumplimiento_5min_pct,
    }

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
            "total_configuradas": len(codigos_ventanillas),
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
        "graficos": {
            "afluencia_horaria": distribucion_horaria,
            "rendimiento_ventanillas": rendimiento_ventanillas,
            "distribucion_espera": distribucion_espera,
            "porcentajes_espera": porcentajes_espera,
            "cumplimiento_5min_pct": cumplimiento_5min_pct,
        },
        "kpis_avanzados": {
            "tasa_abandono": tasa_abandono,
            "tasa_atencion": tasa_atencion,
            "turnos_en_proceso": turnos_en_proceso_total,
            "ocupacion_ventanillas_pct": ocupacion_ventanillas_pct,
            "max_espera_seg": max_espera,
            "min_espera_seg": min_espera,
            "max_espera_formateada": formatear_duracion_legible(max_espera),
            "min_espera_formateada": formatear_duracion_legible(min_espera),
            "promedio_espera_formateado": formatear_duracion_legible(prom_espera),
            "promedio_atencion_formateado": formatear_duracion_legible(prom_atencion),
        },
        "diagnostico": diagnostico,
    }


def exportar_metricas_dashboard(
    db: Database,
    sla_espera_max_seg: int = SLA_OBJETIVO_ESPERA_SEG_DEFECTO,
) -> dict:
    """
    Exporta las métricas operacionales del dashboard y el análisis de SLA (HU-011)
    con metadatos de auditoría para descarga en formato JSON.
    """
    metricas = calcular_metricas_dashboard(db, sla_espera_max_seg=sla_espera_max_seg)
    return {
        "ok": True,
        "servicio": SERVICIO_ID,
        "fecha_exportacion": datetime.now(timezone.utc).isoformat(),
        "tipo_reporte": "metricas_dashboard_sla",
        "datos": metricas,
    }

