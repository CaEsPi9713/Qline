"""TT-014 / TT-015 · Medición de índices con explain() y de los aggregation pipelines del dashboard.

Todo lo que dice el informe sale de la medición: las etapas del plan, los documentos examinados,
las latencias y las conclusiones se calculan con los resultados de esa ejecución. No hay valores
de referencia ni modo simulado: si no hay un MongoDB real, el script termina con un error.

Consultas medidas, cada una con índice y forzando un recorrido completo (`hint $natural`):
  1. Búsqueda por código                 · idx_turnos_codigo_unico
  2. Historial por estado, ordenado      · idx_turnos_estado_creado
  3. Consulta por token QR               · idx_turnos_qr_token_unico (parcial único)
  4. Candidatos del barrido de abandono  · idx_turnos_estado_llamado (HU-008)
Y los dos pipelines del dashboard (los mismos que usa la aplicación, de app/dashboard.py).
"""
from __future__ import annotations

import platform
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.constantes import ESTADO_ATENDIDO, ESTADO_LLAMADO, SERVICIO_ID, TTL_ABANDONO_SEG
from app.dashboard import pipeline_conteo_estados, pipeline_tiempos_sla
from app.informe import encabezado

MIN_EJECUCIONES = 3
DEFECTO_EJECUCIONES = 5
DEFECTO_OPERACIONES = 50
CALENTAMIENTO = 10
MIN_DOCUMENTOS = 50
SCAN = [("$natural", 1)]

INDICES_REQUERIDOS = {
    "codigo": "idx_turnos_codigo_unico",
    "historial": "idx_turnos_estado_creado",
    "qr": "idx_turnos_qr_token_unico",
    "barrido": "idx_turnos_estado_llamado",
}


class MedicionError(Exception):
    """Error controlado: el mensaje explica qué hacer."""


# --------------------------------------------------------------------------------------
# Lectura de explain()
# --------------------------------------------------------------------------------------
def _etapa_raiz(explain: dict) -> dict:
    return (explain.get("executionStats") or {}).get("executionStages") \
        or (explain.get("queryPlanner") or {}).get("winningPlan") or {}


def camino_etapas(etapa: dict) -> list[str]:
    """Nombres de las etapas del plan, de la raíz a la hoja (sigue inputStage y el primer inputStages)."""
    nombres = []
    while isinstance(etapa, dict) and etapa:
        nombres.append(str(etapa.get("stage", "?")))
        etapa = etapa.get("inputStage") or next(iter(etapa.get("inputStages") or []), None)
    return nombres


def analizar_explain(explain: dict) -> dict:
    """Resume un explain("executionStats"): etapas, documentos y claves examinados, devueltos."""
    stats = explain.get("executionStats") or {}
    camino = camino_etapas(_etapa_raiz(explain))
    return {
        "camino": camino,
        "plan": " -> ".join(camino) or "?",
        "usa_indice": "IXSCAN" in camino,
        "recorrido_completo": "COLLSCAN" in camino,
        "ordena_en_memoria": "SORT" in camino,
        "docs_examinados": stats.get("totalDocsExamined", 0),
        "claves_examinadas": stats.get("totalKeysExamined", 0),
        "devueltos": stats.get("nReturned", 0),
        "ms_motor": stats.get("executionTimeMillis", 0),
    }


def mediana_de_latencias(funcion, n: int) -> float:
    """Ejecuta funcion(i) n veces (tras el calentamiento) y devuelve la mediana de su latencia, en ms."""
    for i in range(CALENTAMIENTO):
        funcion(-1 - i)
    lat = []
    for i in range(n):
        t0 = time.perf_counter()
        funcion(i)
        lat.append((time.perf_counter() - t0) * 1000)
    return statistics.median(lat)


def resumen(medianas: list[float]) -> dict:
    return {
        "ejecuciones": len(medianas),
        "minimo": round(min(medianas), 4),
        "maximo": round(max(medianas), 4),
        "mediana": round(statistics.median(medianas), 4),
        "medianas": [round(m, 4) for m in medianas],
    }


@dataclass
class Consulta:
    clave: str
    titulo: str
    indice: str
    descripcion: str
    con_indice: dict = field(default_factory=dict)
    sin_indice: dict = field(default_factory=dict)
    lat_indice: dict = field(default_factory=dict)
    lat_scan: dict = field(default_factory=dict)
    nota: str = ""

    @property
    def aceleracion(self) -> float:
        return self.lat_scan["mediana"] / max(self.lat_indice["mediana"], 0.0001)


@dataclass
class Pipeline:
    nombre: str
    etapas: str
    lat: dict


# --------------------------------------------------------------------------------------
# Mediciones
# --------------------------------------------------------------------------------------
def verificar_indices(col) -> None:
    existentes = set(col.index_information())
    faltan = [n for n in INDICES_REQUERIDOS.values() if n not in existentes]
    if faltan:
        raise MedicionError(
            "Faltan índices en la colección turnos: " + ", ".join(faltan) + ". Créelos sin borrar datos con:\n"
            "  python -c \"from app.main import get_db; from app.turnos_schema import INDICES_TURNOS; "
            "c=get_db()['turnos']; [c.create_index(i['keys'], **i['options']) for i in INDICES_TURNOS]\"")


def _medir(col, q: Consulta, construir, ejecuciones: int, operaciones: int) -> Consulta:
    """`construir(cursor_hint)` devuelve el cursor de la consulta; con hint=None usa el índice que elija MongoDB."""
    q.con_indice = analizar_explain(construir(None).explain())
    q.sin_indice = analizar_explain(construir(SCAN).explain())
    q.lat_indice = resumen([mediana_de_latencias(lambda _: list(construir(None)), operaciones)
                            for _ in range(ejecuciones)])
    q.lat_scan = resumen([mediana_de_latencias(lambda _: list(construir(SCAN)), operaciones)
                          for _ in range(ejecuciones)])
    return q


def _con_hint(cursor, hint):
    return cursor.hint(hint) if hint else cursor


def _token_para_medir(col):
    """Un qr_token existente; si no hay ninguno, crea un turno temporal (y lo devuelve para borrarlo)."""
    doc = col.find_one({"qr_token": {"$type": "string"}}, {"qr_token": 1})
    if doc:
        return doc["qr_token"], None
    from app.datos_prueba import construir_turno
    token, codigo = str(uuid.uuid4()), "Q-9901"
    col.delete_one({"codigo": codigo})
    try:
        col.insert_one(construir_turno(codigo, "pendiente", "normal", datetime.now(timezone.utc), qr_token=token))
    except Exception as exc:
        raise MedicionError(f"No hay turnos con qr_token y no se pudo crear uno temporal: {exc}") from exc
    return token, codigo


def medir_consultas(col, ejecuciones: int, operaciones: int) -> list[Consulta]:
    from app.consulta_qr import filtro_por_token
    codigo = (col.find_one({"servicio": SERVICIO_ID}, {"codigo": 1}) or {}).get("codigo")
    if not codigo:
        raise MedicionError("La colección turnos no tiene turnos del servicio para medir.")
    orden = [("timestamps.creado", -1)]
    limite_barrido = datetime.now(timezone.utc) - timedelta(seconds=TTL_ABANDONO_SEG)

    por_codigo = _medir(col, Consulta("codigo", "Búsqueda por código", INDICES_REQUERIDOS["codigo"],
                                      f'find({{"codigo": "{codigo}"}})'),
                        lambda h: _con_hint(col.find({"codigo": codigo}), h), ejecuciones, operaciones)
    historial = _medir(col, Consulta("historial", "Historial por estado, ordenado por creación (los 20 más recientes)",
                                     INDICES_REQUERIDOS["historial"],
                                     f'find({{"servicio": "{SERVICIO_ID}", "estado": "{ESTADO_ATENDIDO}"}})'
                                     '.sort("timestamps.creado", -1).limit(20)'),
                       lambda h: _con_hint(col.find({"servicio": SERVICIO_ID, "estado": ESTADO_ATENDIDO})
                                           .sort(orden).limit(20), h), ejecuciones, operaciones)
    barrido = _medir(col, Consulta("barrido", "Candidatos del barrido de abandono (HU-008)",
                                   INDICES_REQUERIDOS["barrido"],
                                   f'find({{"estado": "{ESTADO_LLAMADO}", "timestamps.llamado": '
                                   f'{{"$lte": ahora - {TTL_ABANDONO_SEG} s}}}})'),
                     lambda h: _con_hint(col.find({"estado": ESTADO_LLAMADO,
                                                   "timestamps.llamado": {"$lte": limite_barrido}}), h),
                     ejecuciones, operaciones)

    # El turno temporal (si hace falta) vive solo durante esta consulta, para no alterar las otras.
    token, temporal = _token_para_medir(col)
    try:
        q = Consulta("qr", "Consulta por token QR (el mismo filtro que usa la aplicación)",
                     INDICES_REQUERIDOS["qr"], 'find(filtro_por_token("<uuid v4>"))  # {"qr_token": {"$eq": t, "$type": "string"}}')
        if temporal:
            q.nota = ("No había turnos con qr_token: se creó un turno temporal durante esta consulta "
                      "(un documento más que en las demás) y se eliminó al terminar.")
        qr = _medir(col, q, lambda h: _con_hint(col.find(filtro_por_token(token)), h), ejecuciones, operaciones)
    finally:
        if temporal:
            col.delete_one({"codigo": temporal})
    return [por_codigo, historial, qr, barrido]


def medir_pipelines(col, ejecuciones: int, operaciones: int) -> list[Pipeline]:
    definiciones = [
        ("Conteo por estados", "$match -> $group", pipeline_conteo_estados()),
        ("Tiempos promedio y cumplimiento de SLA", "$match -> $group (con $avg y $cond)", pipeline_tiempos_sla()),
    ]
    return [Pipeline(nombre, etapas,
                     resumen([mediana_de_latencias(lambda _: list(col.aggregate(p)), operaciones)
                              for _ in range(ejecuciones)]))
            for nombre, etapas, p in definiciones]


# --------------------------------------------------------------------------------------
# Informe (todo calculado de los resultados)
# --------------------------------------------------------------------------------------
def _conclusion(q: Consulta) -> str:
    i, s = q.con_indice, q.sin_indice
    partes = [f"con índice examina {i['docs_examinados']} documento(s) ({i['claves_examinadas']} clave(s)) "
              f"y sin índice {s['docs_examinados']}"]
    if q.clave == "historial":
        partes.append("el plan con índice " + ("**ordena en memoria**" if i["ordena_en_memoria"]
                                              else "no ordena en memoria (usa el orden del índice)"))
        partes.append("el recorrido completo " + ("ordena en memoria" if s["ordena_en_memoria"]
                                                  else "no mostró una etapa SORT"))
    if not i["usa_indice"]:
        partes.append("**advertencia: el plan elegido no usa el índice**")
    partes.append(f"mediana {q.lat_indice['mediana']} ms frente a {q.lat_scan['mediana']} ms "
                  f"({q.aceleracion:.1f} veces)")
    return "; ".join(partes) + "."


def generar_informe(info: dict, consultas: list[Consulta], pipelines: list[Pipeline]) -> str:
    md = encabezado("Índices con explain() y aggregation pipelines (TT-014, TT-015 · Carlos Espinoza)")
    md += (f"\n## Entorno y método\n\n"
           f"- Motor: MongoDB {info['version']} · Documentos en `turnos`: **{info['documentos']}**\n"
           f"- Sistema: {platform.system()} · Python {platform.python_version()}\n"
           f"- **{info['ejecuciones']} ejecuciones** independientes por consulta (mínimo exigido: {MIN_EJECUCIONES}), "
           f"de {info['operaciones']} operaciones cada una tras {CALENTAMIENTO} de calentamiento que se descartan. "
           "De cada ejecución se toma la **mediana**; las tablas muestran el mínimo, el máximo y la mediana de esas medianas.\n"
           "- «Con índice» deja que MongoDB elija su plan. «Recorrido completo» fuerza `hint $natural` (lectura de toda la colección).\n"
           "- Latencia vista desde la aplicación, en milisegundos. Las etapas y los documentos examinados salen de "
           "`explain(\"executionStats\")`.\n"
           f"- Medición hecha con **{info['documentos']} documentos**: con tan pocos datos las diferencias de tiempo son "
           "pequeñas; los documentos examinados muestran mejor el efecto del índice.\n")
    md += "\n## TT-014 · Índices con explain()\n"
    for n, q in enumerate(consultas, start=1):
        md += (f"\n### {n}. {q.titulo} (`{q.indice}`)\n\nConsulta: `{q.descripcion}`\n\n"
               "| Estrategia | Plan (explain) | Docs examinados | Claves examinadas | Devueltos | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |\n"
               "|---|---|---|---|---|---|---|---|\n")
        for nombre, e, lat in (("Con índice", q.con_indice, q.lat_indice), ("Recorrido completo", q.sin_indice, q.lat_scan)):
            md += (f"| {nombre} | `{e['plan']}` | {e['docs_examinados']} | {e['claves_examinadas']} | {e['devueltos']} | "
                   f"{lat['minimo']} | {lat['maximo']} | **{lat['mediana']}** |\n")
        md += (f"\nMedianas de cada ejecución — con índice: {q.lat_indice['medianas']} · recorrido completo: {q.lat_scan['medianas']}\n"
               f"\n**Resultado:** {_conclusion(q)}\n" + (f"\n> {q.nota}\n" if q.nota else ""))
    md += ("\n## TT-015 · Aggregation pipelines del dashboard\n\nSon los mismos pipelines que usa la aplicación "
           "(`pipeline_conteo_estados` y `pipeline_tiempos_sla` de `app/dashboard.py`).\n\n"
           "| Pipeline | Etapas | Ejecuciones | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |\n|---|---|---|---|---|---|\n")
    for p in pipelines:
        md += f"| {p.nombre} | `{p.etapas}` | {p.lat['ejecuciones']} | {p.lat['minimo']} | {p.lat['maximo']} | **{p.lat['mediana']}** |\n"
    md += "\nMedianas de cada ejecución:\n"
    for p in pipelines:
        md += f"- {p.nombre}: {p.lat['medianas']} ms\n"
    sin_indice = [q.titulo for q in consultas if not q.con_indice["usa_indice"]]
    md += "\n## Lectura de los resultados\n\n"
    md += ("- Todas las consultas medidas usaron su índice.\n" if not sin_indice else
           "- **Atención:** estas consultas no usaron un índice: " + "; ".join(sin_indice) + ".\n")
    md += ("- Los pipelines agregan en el motor y devuelven solo el resumen, no los documentos; no se comparó contra "
           "un cálculo en Python, así que esta medición no cuantifica esa ventaja.\n")
    return md


def ejecutar(db, ejecuciones: int = DEFECTO_EJECUCIONES, operaciones: int = DEFECTO_OPERACIONES) -> str:
    """Mide todo contra la base `db` y devuelve el informe en Markdown. Lanza MedicionError si no se puede."""
    from app.turnos_schema import COLECCION_TURNOS
    if ejecuciones < MIN_EJECUCIONES:
        raise MedicionError(f"Se requieren al menos {MIN_EJECUCIONES} ejecuciones (se pidieron {ejecuciones}).")
    try:
        db.command("ping")
        version = db.client.server_info().get("version", "?")
        col = db[COLECCION_TURNOS]
        documentos = col.count_documents({})
    except Exception as exc:
        raise MedicionError(f"No se pudo conectar a MongoDB: {exc}") from exc
    if documentos < MIN_DOCUMENTOS:
        raise MedicionError(f"La colección turnos tiene {documentos} documentos; se necesitan al menos {MIN_DOCUMENTOS}. "
                            "Cargue los datos sintéticos: python scripts/generar_datos_sinteticos.py --cargar")
    verificar_indices(col)
    consultas = medir_consultas(col, ejecuciones, operaciones)
    pipelines = medir_pipelines(col, ejecuciones, operaciones)
    return generar_informe({"version": version, "documentos": documentos, "ejecuciones": ejecuciones,
                            "operaciones": operaciones}, consultas, pipelines)
