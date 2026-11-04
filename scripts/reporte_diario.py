"""
S4-M05 · Generación de Reporte Diario de Atención y Cumplimiento SLA.

Responsable: Carlos Espinoza (cespinoza)
Permite auditar y generar el informe diario de operaciones del servicio institucional
`QLine · Atención General`, consolidando métricas operacionales, tiempos de servicio,
afluencia horaria y cumplimiento de SLA a partir de MongoDB.

Uso:
    python scripts/reporte_diario.py [--fecha YYYY-MM-DD] [--sla-espera 300] [--salida-json PATH] [--salida-md PATH] [--simulado]
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Optional

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.constantes import (  # noqa: E402
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    SERVICIO_ID,
    VENTANILLAS,
)
from app.dashboard import COLECCION_TURNOS, SLA_OBJETIVO_ESPERA_SEG_DEFECTO, SLA_TASA_MINIMA_CUMPLIMIENTO  # noqa: E402
from app.formato import zona  # noqa: E402
from app.historial import parsear_fecha_filtro  # noqa: E402


def generar_reporte_diario(
    db: Any,
    fecha_str: Optional[str] = None,
    sla_espera_seg: int = SLA_OBJETIVO_ESPERA_SEG_DEFECTO,
) -> dict:
    """
    Ejecuta aggregation pipelines en MongoDB para consolidar el reporte operacional
    y analítico correspondiente a una fecha específica.
    """
    col = db[COLECCION_TURNOS]

    if not fecha_str or not fecha_str.strip():
        fecha_str = datetime.now(zona()).strftime("%Y-%m-%d")
    else:
        fecha_str = fecha_str.strip()

    dt_desde = parsear_fecha_filtro(fecha_str, fin_de_dia=False)
    dt_hasta = parsear_fecha_filtro(fecha_str, fin_de_dia=True)

    filtro_fecha = {}
    if dt_desde:
        filtro_fecha["$gte"] = dt_desde
    if dt_hasta:
        filtro_fecha["$lte"] = dt_hasta

    filtro_base = {"servicio": SERVICIO_ID}
    if filtro_fecha:
        filtro_base["timestamps.creado"] = filtro_fecha

    # 1. Conteo de estados
    pipeline_estados = [
        {"$match": filtro_base},
        {"$group": {"_id": "$estado", "total": {"$sum": 1}}},
    ]
    conteo_estados = {est: 0 for est in (
        ESTADO_PENDIENTE, ESTADO_LLAMADO, ESTADO_EN_ATENCION, ESTADO_ATENDIDO, ESTADO_ABANDONADO
    )}
    for item in col.aggregate(pipeline_estados):
        if item.get("_id") in conteo_estados:
            conteo_estados[item["_id"]] = item["total"]

    total_turnos = sum(conteo_estados.values())

    # 2. Métricas de tiempos y cumplimiento de SLA
    pipeline_tiempos = [
        {
            "$match": {
                **filtro_base,
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
                                    {"$lte": ["$metricas.espera_seg", sla_espera_seg]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "hasta_2min": {
                    "$sum": {
                        "$cond": [
                            {"$and": [{"$ne": ["$metricas.espera_seg", None]}, {"$lte": ["$metricas.espera_seg", 120]}]},
                            1,
                            0,
                        ]
                    }
                },
                "de_2_a_5min": {
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
                "de_5_a_10min": {
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
                "mas_de_10min": {
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

    res_tiempos = list(col.aggregate(pipeline_tiempos))
    if res_tiempos:
        dt_tiempos = res_tiempos[0]
        prom_espera = round(dt_tiempos.get("promedio_espera") or 0.0, 1)
        prom_atencion = round(dt_tiempos.get("promedio_atencion") or 0.0, 1)
        max_espera = dt_tiempos.get("max_espera") or 0
        min_espera = dt_tiempos.get("min_espera") or 0
        total_evaluados = dt_tiempos.get("total_con_espera", 0)
        cumplen_sla = dt_tiempos.get("cumplen_sla", 0)
        distribucion_espera = {
            "hasta_2min": dt_tiempos.get("hasta_2min", 0),
            "de_2_a_5min": dt_tiempos.get("de_2_a_5min", 0),
            "de_5_a_10min": dt_tiempos.get("de_5_a_10min", 0),
            "mas_de_10min": dt_tiempos.get("mas_de_10min", 0),
        }
    else:
        prom_espera = 0.0
        prom_atencion = 0.0
        max_espera = 0
        min_espera = 0
        total_evaluados = 0
        cumplen_sla = 0
        distribucion_espera = {
            "hasta_2min": 0,
            "de_2_a_5min": 0,
            "de_5_a_10min": 0,
            "mas_de_10min": 0,
        }

    incumplen_sla = max(0, total_evaluados - cumplen_sla)
    porcentaje_cumplimiento = (
        round((cumplen_sla / total_evaluados) * 100, 1) if total_evaluados > 0 else 100.0
    )
    sla_cumplido = porcentaje_cumplimiento >= SLA_TASA_MINIMA_CUMPLIMIENTO

    # 3. Productividad por ventanilla
    pipeline_ventanillas = [
        {
            "$match": {
                **filtro_base,
                "ventanilla": {"$in": VENTANILLAS},
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
    items_v = {item["_id"]: item for item in col.aggregate(pipeline_ventanillas) if item.get("_id")}
    desglose_ventanillas = []
    for v in VENTANILLAS:
        info = items_v.get(v, {})
        desglose_ventanillas.append({
            "ventanilla": v,
            "atendidos": info.get("total_atendidos", 0),
            "promedio_atencion_seg": round(info.get("promedio_atencion_seg") or 0.0, 1),
        })

    # 4. Afluencia horaria (07:00 a 18:00)
    pipeline_afluencia = [
        {"$match": filtro_base},
        {"$group": {"_id": {"$hour": "$timestamps.creado"}, "total": {"$sum": 1}}},
    ]
    items_h = {item["_id"]: item["total"] for item in col.aggregate(pipeline_afluencia) if item.get("_id") is not None}
    distribucion_horaria = []
    for h_local in range(7, 19):
        h_utc = (h_local + 6) % 24
        distribucion_horaria.append({
            "hora": f"{h_local:02d}:00",
            "total": items_h.get(h_utc, 0),
        })

    return {
        "ok": True,
        "servicio": SERVICIO_ID,
        "fecha_reporte": fecha_str,
        "generado_en": datetime.now(timezone.utc).isoformat(),
        "resumen_operacional": {
            "total_turnos": total_turnos,
            "atendidos": conteo_estados[ESTADO_ATENDIDO],
            "en_espera": conteo_estados[ESTADO_PENDIENTE],
            "en_atencion": conteo_estados[ESTADO_EN_ATENCION],
            "llamados": conteo_estados[ESTADO_LLAMADO],
            "abandonados": conteo_estados[ESTADO_ABANDONADO],
            "tasa_abandono": round((conteo_estados[ESTADO_ABANDONADO] / total_turnos * 100), 1) if total_turnos > 0 else 0.0,
        },
        "tiempos_servicio": {
            "promedio_espera_seg": prom_espera,
            "promedio_atencion_seg": prom_atencion,
            "maximo_espera_seg": max_espera,
            "minimo_espera_seg": min_espera,
            "distribucion_rangos": distribucion_espera,
        },
        "analisis_sla": {
            "objetivo_max_espera_seg": sla_espera_seg,
            "tasa_minima_requerida": SLA_TASA_MINIMA_CUMPLIMIENTO,
            "porcentaje_cumplimiento": porcentaje_cumplimiento,
            "estado": "CUMPLIDO" if sla_cumplido else "INCUMPLIDO",
            "evaluados": total_evaluados,
            "cumplen": cumplen_sla,
            "incumplen": incumplen_sla,
        },
        "productividad_ventanillas": desglose_ventanillas,
        "afluencia_horaria": distribucion_horaria,
    }


def renderizar_markdown(reporte: dict) -> str:
    """Convierte los datos estructurados del reporte en un documento Markdown estructurado."""
    resumen = reporte["resumen_operacional"]
    tiempos = reporte["tiempos_servicio"]
    sla = reporte["analisis_sla"]
    dist_r = tiempos["distribucion_rangos"]

    estado_sla_badge = "**CUMPLIDO**" if sla["estado"] == "CUMPLIDO" else "**INCUMPLIDO**"

    lineas = [
        f"# Reporte Diario de Operaciones y Auditoría SLA",
        f"",
        f"- **Servicio:** `{reporte['servicio']}` (Atención General)",
        f"- **Fecha auditada:** `{reporte['fecha_reporte']}`",
        f"- **Generado el:** `{reporte['generado_en']}` (UTC)",
        f"- **Evaluador / DBA:** Carlos Espinoza (`cespinoza`)",
        f"",
        f"## 1. Resumen Operacional de Turnos",
        f"",
        f"| Métrica | Cantidad | % del Total |",
        f"| :--- | :---: | :---: |",
        f"| **Total turnos gestionados** | **{resumen['total_turnos']}** | 100.0% |",
        f"| Atendidos satisfactoriamente | {resumen['atendidos']} | {(resumen['atendidos'] / max(1, resumen['total_turnos']) * 100):.1f}% |",
        f"| Abandonados (sin presentarse) | {resumen['abandonados']} | {resumen['tasa_abandono']:.1f}% |",
        f"| En atención activa | {resumen['en_atencion']} | {(resumen['en_atencion'] / max(1, resumen['total_turnos']) * 100):.1f}% |",
        f"| Pendientes en cola | {resumen['en_espera']} | {(resumen['en_espera'] / max(1, resumen['total_turnos']) * 100):.1f}% |",
        f"",
        f"## 2. Indicadores de Tiempos y Nivel de Servicio (SLA)",
        f"",
        f"- **Objetivo SLA:** Espera máxima de `{sla['objetivo_max_espera_seg']} s` ({sla['objetivo_max_espera_seg'] // 60} minutos).",
        f"- **Cumplimiento obtenido:** **{sla['porcentaje_cumplimiento']}%** (Exigido: >= {sla['tasa_minima_requerida']}%) -> {estado_sla_badge}",
        f"- **Turnos evaluados:** `{sla['evaluados']}` (Conformes: `{sla['cumplen']}` | Excedidos: `{sla['incumplen']}`)",
        f"- **Promedio de espera:** `{tiempos['promedio_espera_seg']} s` (Mín: `{tiempos['minimo_espera_seg']} s`, Máx: `{tiempos['maximo_espera_seg']} s`)",
        f"- **Promedio de atención:** `{tiempos['promedio_atencion_seg']} s`",
        f"",
        f"### Distribución de Tiempos de Espera",
        f"| Rango de Espera | Turnos | % Evaluados |",
        f"| :--- | :---: | :---: |",
        f"| Excelente (<= 2 min) | {dist_r['hasta_2min']} | {(dist_r['hasta_2min'] / max(1, sla['evaluados']) * 100):.1f}% |",
        f"| Aceptable (2 a 5 min) | {dist_r['de_2_a_5min']} | {(dist_r['de_2_a_5min'] / max(1, sla['evaluados']) * 100):.1f}% |",
        f"| En límite (5 a 10 min) | {dist_r['de_5_a_10min']} | {(dist_r['de_5_a_10min'] / max(1, sla['evaluados']) * 100):.1f}% |",
        f"| Crítico (> 10 min) | {dist_r['mas_de_10min']} | {(dist_r['mas_de_10min'] / max(1, sla['evaluados']) * 100):.1f}% |",
        f"",
        f"## 3. Productividad por Ventanilla",
        f"",
        f"| Ventanilla | Turnos Atendidos | Tiempo Promedio de Atención |",
        f"| :---: | :---: | :---: |",
    ]

    for v in reporte["productividad_ventanillas"]:
        lineas.append(f"| `{v['ventanilla']}` | {v['atendidos']} | {v['promedio_atencion_seg']} s |")

    lineas.extend([
        f"",
        f"## 4. Afluencia Horaria Registrada",
        f"",
        f"| Franja Horaria | Turnos Registrados |",
        f"| :---: | :---: |",
    ])

    for h in reporte["afluencia_horaria"]:
        lineas.append(f"| {h['hora']} | {h['total']} |")

    lineas.append("")
    return "\n".join(lineas)


def _crear_datos_simulados(fecha_str: Optional[str] = None) -> Any:
    """Crea una base de datos en memoria (mongomock) con turnos representativos para pruebas."""
    import mongomock
    db = mongomock.MongoClient().db
    col = db[COLECCION_TURNOS]

    if not fecha_str:
        fecha_str = datetime.now(zona()).strftime("%Y-%m-%d")

    dt_dia = parsear_fecha_filtro(fecha_str, fin_de_dia=False) or datetime.now(timezone.utc)
    base_ts = datetime(dt_dia.year, dt_dia.month, dt_dia.day, 14, 0, 0, tzinfo=timezone.utc)

    col.insert_many([
        {
            "codigo": f"A-{i:03d}",
            "servicio": SERVICIO_ID,
            "estado": ESTADO_ATENDIDO,
            "prioridad": "normal" if i % 3 != 0 else "preferencial",
            "ventanilla": f"V-0{(i % 3) + 1}",
            "timestamps": {
                "creado": base_ts,
                "llamado": base_ts,
                "finalizado": base_ts,
            },
            "metricas": {
                "espera_seg": 60 + (i * 15),
                "atencion_seg": 120 + (i * 10),
            },
        }
        for i in range(1, 13)
    ])
    return db


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generador reproducible de reportes diarios de atención institucional y cumplimiento SLA (S4-M05).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fecha", type=str, default="", help="Fecha del reporte en formato YYYY-MM-DD (por defecto hoy).")
    parser.add_argument("--sla-espera", type=int, default=SLA_OBJETIVO_ESPERA_SEG_DEFECTO, help="Objetivo máximo de espera en segundos.")
    parser.add_argument("--salida-json", type=Path, help="Ruta de archivo para guardar el reporte en JSON.")
    parser.add_argument("--salida-md", type=Path, help="Ruta de archivo para guardar el reporte en Markdown.")
    parser.add_argument("--simulado", action="store_true", help="Usa base de datos simulada en memoria (mongomock) para validación.")

    args = parser.parse_args(argumentos)

    fecha_elegida = args.fecha.strip() or datetime.now(zona()).strftime("%Y-%m-%d")

    if args.simulado:
        db = _crear_datos_simulados(fecha_elegida)
    else:
        try:
            from app.main import get_db
            db = get_db()
        except Exception as e:
            print(f"Error al conectar con MongoDB: {e}", file=sys.stderr)
            return 1

    try:
        reporte = generar_reporte_diario(
            db,
            fecha_str=args.fecha or None,
            sla_espera_seg=args.sla_espera,
        )
    except Exception as e:
        print(f"Error generando reporte diario: {e}", file=sys.stderr)
        return 1

    contenido_md = renderizar_markdown(reporte)

    if args.salida_json:
        args.salida_json.parent.mkdir(parents=True, exist_ok=True)
        args.salida_json.write_text(json.dumps(reporte, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Reporte JSON guardado en: {args.salida_json}", file=sys.stderr)

    if args.salida_md:
        args.salida_md.parent.mkdir(parents=True, exist_ok=True)
        args.salida_md.write_text(contenido_md, encoding="utf-8")
        print(f"Reporte Markdown guardado en: {args.salida_md}", file=sys.stderr)

    # Imprimir en consola si no se especificaron archivos o para visualización inmediata
    if not args.salida_json and not args.salida_md:
        print(contenido_md)

    return 0


if __name__ == "__main__":
    sys.exit(main())
