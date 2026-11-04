"""
TT-018 · Mediciones de rendimiento de Redis frente a MongoDB (parte de Alessandro).

Mide 3 operaciones representativas de QLine, cada una en su versión Redis y en su
equivalente en MongoDB:

  1. Generar el código del turno   Redis INCR            vs  MongoDB find_one_and_update ($inc)
  2. Poner el turno en la cola     Redis ZADD            vs  MongoDB insert_one
  3. Sacar el siguiente turno      Redis ZPOPMIN         vs  MongoDB find_one_and_update
                                                              (el pendiente de mayor prioridad)

Método (sección 18.2 del plan: "debe medirse, no asumirse"):
  - Cada operación se repite en EJECUCIONES independientes (mínimo 3, por defecto 5).
  - Una ejecución son N operaciones seguidas; de ella se toma la MEDIANA de sus latencias.
  - Antes de medir se descartan unas operaciones de calentamiento (conexión y caché).
  - Se informa, por operación y motor: número de ejecuciones, mínimo, máximo y mediana
    (de las medianas de cada ejecución), y una interpretación.
  - Las cifras de S1 (Redis < 2 ms y más de 85 % de mejora) son HIPÓTESIS: el informe las
    contrasta con lo medido y dice si se cumplen o no.

Usa claves `grupo2:qline:test:bench:*` y las colecciones de prueba `bench_qline_*`, que
elimina al terminar; no toca `turnos`, el contador ni la cola reales.

    python scripts/medir_rendimiento.py
    python scripts/medir_rendimiento.py --ejecuciones 7 --operaciones 300 --informe docs/evidencia/rendimiento.md
    python scripts/medir_rendimiento.py --solo-redis        # si MongoDB no está disponible

Cómo interpretar: mide la latencia vista desde la aplicación (incluye el viaje por la red
local y la biblioteca cliente), que es la que percibe QLine; no mide el rendimiento
interno de cada motor. Los resultados dependen de la carga del servidor compartido.
"""
import argparse
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.redis_client import get_redis, verificar_conexion  # noqa: E402

PREFIJO = "grupo2:qline:test:bench:"
COLECCION_CONTADOR = "bench_qline_contador"
COLECCION_TURNOS = "bench_qline_turnos"
CALENTAMIENTO = 20
MIN_EJECUCIONES = 3
HIPOTESIS_REDIS_MS = 2.0          # S1: latencia de Redis < 2 ms
HIPOTESIS_MEJORA_PCT = 85.0       # S1: más de 85 % de mejora frente a MongoDB

OPERACIONES = [
    ("codigo", "Generar el código del turno", "INCR", "find_one_and_update ($inc)"),
    ("encolar", "Poner el turno en la cola", "ZADD", "insert_one"),
    ("siguiente", "Sacar el siguiente turno", "ZPOPMIN", "find_one_and_update (mayor prioridad)"),
]


def mediana_de_latencias(funcion, n: int) -> float:
    """Ejecuta `funcion(i)` n veces y devuelve la mediana de su latencia en milisegundos."""
    for i in range(CALENTAMIENTO):
        funcion(-1 - i)
    lat = []
    for i in range(n):
        t0 = time.perf_counter()
        funcion(i)
        lat.append((time.perf_counter() - t0) * 1000)
    return statistics.median(lat)


def resumen(medianas: list) -> dict:
    return {"ejecuciones": len(medianas), "minimo": min(medianas), "maximo": max(medianas),
            "mediana": statistics.median(medianas), "medianas": [round(m, 4) for m in medianas]}


# ----------------------------------------------------------------------------
# Redis
# ----------------------------------------------------------------------------
def preparar_redis(r, n: int) -> None:
    claves = list(r.scan_iter(match=PREFIJO + "*"))
    if claves:
        r.delete(*claves)


def sembrar_redis(r, clave: str, total: int) -> None:
    """Cola de prueba: cada cuarto turno es preferencial (sale primero)."""
    r.zadd(clave, {f"B-{i}": (0 if i % 4 == 3 else 10**13) + i for i in range(total)})


def medir_redis(r, operacion: str, n: int) -> float:
    if operacion == "codigo":
        clave = PREFIJO + "contador"
        return mediana_de_latencias(lambda i: r.incr(clave), n)
    if operacion == "encolar":
        clave = PREFIJO + "cola_enc"
        return mediana_de_latencias(
            lambda i: r.zadd(clave, {f"B-{i}": (1 if i % 4 == 3 else 10**13) + abs(i)}, nx=True), n)
    if operacion == "siguiente":
        clave = PREFIJO + "cola_sig"
        sembrar_redis(r, clave, n + CALENTAMIENTO)
        return mediana_de_latencias(lambda i: r.zpopmin(clave, 1), n)
    raise ValueError(operacion)


# ----------------------------------------------------------------------------
# MongoDB
# ----------------------------------------------------------------------------
def preparar_mongo(db) -> None:
    db.drop_collection(COLECCION_CONTADOR)
    db.drop_collection(COLECCION_TURNOS)
    db[COLECCION_CONTADOR].insert_one({"_id": "atencion_general", "n": 0})
    # Índice que sirve al "siguiente turno": justo el que se le daría en producción.
    db[COLECCION_TURNOS].create_index([("estado", 1), ("nivel", 1), ("creado", 1)])


def sembrar_mongo(col, total: int) -> None:
    """Turnos pendientes de prueba: cada cuarto es preferencial (nivel 0, sale primero)."""
    col.delete_many({})
    col.insert_many([{"codigo": f"B-{i}", "estado": "pendiente", "nivel": 0 if i % 4 == 3 else 1, "creado": i}
                     for i in range(total)])


def siguiente_mongo(col):
    """El turno que MongoDB entregaría: el pendiente de mayor prioridad y más antiguo."""
    return col.find_one_and_update({"estado": "pendiente"}, {"$set": {"estado": "llamado"}},
                                   sort=[("nivel", 1), ("creado", 1)])


def medir_mongo(db, operacion: str, n: int) -> float:
    if operacion == "codigo":
        col = db[COLECCION_CONTADOR]
        return mediana_de_latencias(
            lambda i: col.find_one_and_update({"_id": "atencion_general"}, {"$inc": {"n": 1}}, return_document=True), n)
    if operacion == "encolar":
        col = db[COLECCION_TURNOS]
        return mediana_de_latencias(
            lambda i: col.insert_one({"codigo": f"B-enc-{time.perf_counter_ns()}-{i}", "estado": "pendiente",
                                      "nivel": 0 if i % 4 == 3 else 1, "creado": i}), n)
    if operacion == "siguiente":
        col = db[COLECCION_TURNOS]
        sembrar_mongo(col, n + CALENTAMIENTO)
        return mediana_de_latencias(lambda i: siguiente_mongo(col), n)
    raise ValueError(operacion)


def limpiar(r, db) -> None:
    claves = list(r.scan_iter(match=PREFIJO + "*"))
    if claves:
        r.delete(*claves)
    if db is not None:
        db.drop_collection(COLECCION_CONTADOR)
        db.drop_collection(COLECCION_TURNOS)


# ----------------------------------------------------------------------------
# Análisis e informe
# ----------------------------------------------------------------------------
def mejora_pct(redis_ms: float, mongo_ms: float) -> float:
    """Cuánto menos tarda Redis que MongoDB, en porcentaje (positivo: Redis es más rápido)."""
    return (mongo_ms - redis_ms) / mongo_ms * 100 if mongo_ms > 0 else 0.0


def evaluar_hipotesis(resultados: dict) -> dict:
    """Contrasta las hipótesis de S1 con lo medido. No asume que se cumplan."""
    filas = {}
    for clave, datos in resultados.items():
        redis_ms = datos["redis"]["mediana"]
        fila = {"redis_menor_2ms": redis_ms < HIPOTESIS_REDIS_MS}
        if datos.get("mongo"):
            m = mejora_pct(redis_ms, datos["mongo"]["mediana"])
            fila.update(mejora=m, mejora_mayor_85=m > HIPOTESIS_MEJORA_PCT)
        filas[clave] = fila
    return filas


def interpretar(resultados: dict, hipotesis: dict) -> list:
    lineas = []
    for clave, titulo, op_redis, op_mongo in OPERACIONES:
        d = resultados[clave]
        h = hipotesis[clave]
        t = f"**{titulo}** ({op_redis}): Redis tardó {d['redis']['mediana']:.3f} ms de mediana"
        if d.get("mongo"):
            veces = d["mongo"]["mediana"] / d["redis"]["mediana"] if d["redis"]["mediana"] > 0 else float("inf")
            t += (f"; MongoDB ({op_mongo}) {d['mongo']['mediana']:.3f} ms. Redis fue {veces:.1f} veces más rápido "
                  f"({h['mejora']:.1f} % menos latencia)" if h["mejora"] > 0
                  else f"; MongoDB ({op_mongo}) {d['mongo']['mediana']:.3f} ms. Redis **no** fue más rápido en esta medición")
        lineas.append(t + ".")
    return lineas


def generar_informe(entorno: dict, resultados: dict, ejecuciones: int, operaciones: int) -> str:
    hip = evaluar_hipotesis(resultados)
    hay_mongo = all(resultados[c].get("mongo") for c, *_ in OPERACIONES)
    f = ["# Mediciones de rendimiento · Redis frente a MongoDB (TT-018, parte de Alessandro)", "",
         "> Informe generado por `scripts/medir_rendimiento.py` con los resultados de **esa ejecución**; no se escribe a mano.", "",
         "## Entorno y método", "",
         f"- Fecha (UTC): {entorno['fecha']}",
         f"- Redis: {entorno['redis']} · MongoDB: {entorno['mongo']}",
         f"- Python: {entorno['python']} · {entorno['sistema']}",
         f"- **{ejecuciones} ejecuciones** por operación y motor; cada ejecución son **{operaciones} operaciones** seguidas, "
         f"tras {CALENTAMIENTO} de calentamiento que se descartan.",
         "- De cada ejecución se toma la **mediana** de sus latencias; las tablas muestran el mínimo, el máximo y la mediana de esas medianas.",
         "- Latencia vista desde la aplicación (incluye la red local y la biblioteca cliente), en milisegundos.", ""]
    for clave, titulo, op_redis, op_mongo in OPERACIONES:
        d = resultados[clave]
        f += [f"## {titulo}", "",
              "| Motor | Operación | Ejecuciones | Mínimo (ms) | Máximo (ms) | **Mediana (ms)** |", "|---|---|---|---|---|---|",
              f"| Redis | {op_redis} | {d['redis']['ejecuciones']} | {d['redis']['minimo']:.3f} | {d['redis']['maximo']:.3f} | **{d['redis']['mediana']:.3f}** |"]
        if d.get("mongo"):
            f.append(f"| MongoDB | {op_mongo} | {d['mongo']['ejecuciones']} | {d['mongo']['minimo']:.3f} | {d['mongo']['maximo']:.3f} | **{d['mongo']['mediana']:.3f}** |")
        f += ["", f"Medianas de cada ejecución — Redis: {d['redis']['medianas']}"
              + (f" · MongoDB: {d['mongo']['medianas']}" if d.get("mongo") else ""), ""]
    f += ["## Interpretación", ""] + [f"- {x}" for x in interpretar(resultados, hip)]
    f += ["", "## Contraste con las hipótesis de S1", "",
          "S1 planteó como **hipótesis inicial** una latencia de Redis menor de 2 ms y una mejora de más del 85 % frente a MongoDB. "
          "Con lo medido:", "",
          "| Operación | Redis < 2 ms | Mejora frente a MongoDB | ¿Más del 85 %? |", "|---|---|---|---|"]
    for clave, titulo, *_ in OPERACIONES:
        h = hip[clave]
        mejora = f"{h['mejora']:.1f} %" if "mejora" in h else "no medida"
        mayor = ("sí" if h["mejora_mayor_85"] else "no") if "mejora" in h else "—"
        f.append(f"| {titulo} | {'sí' if h['redis_menor_2ms'] else 'no'} | {mejora} | {mayor} |")
    if not hay_mongo:
        f += ["", "> No se midió MongoDB (`--solo-redis`): la comparación y la mejora no están disponibles."]
    f += ["", "## Límites de esta medición", "",
          "- Es una medición desde la aplicación hacia un servidor **compartido**: la carga de otros grupos puede variar los números entre ejecuciones; por eso se reportan el mínimo, el máximo y la mediana.",
          "- Compara operaciones equivalentes para QLine, no el rendimiento interno de cada motor.",
          "- Las operaciones de MongoDB usan colecciones de prueba con el índice que tendría la consulta real; sin ese índice la diferencia sería mayor.",
          "- Las mediciones de las otras partes del equipo (índices con `explain()`, agregaciones y recuperación) las consolidan sus responsables."]
    return "\n".join(f) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ejecuciones", type=int, default=5, help=f"ejecuciones por operación (mínimo {MIN_EJECUCIONES}, default: %(default)s)")
    ap.add_argument("--operaciones", type=int, default=200, help="operaciones por ejecución (default: %(default)s)")
    ap.add_argument("--solo-redis", action="store_true", help="no mide MongoDB")
    ap.add_argument("--informe", type=Path, help="escribe el informe en Markdown en esta ruta")
    args = ap.parse_args(argv)
    if args.ejecuciones < MIN_EJECUCIONES or args.operaciones < 20:
        print(f"Se exigen al menos {MIN_EJECUCIONES} ejecuciones y 20 operaciones por ejecución.", file=sys.stderr)
        return 2

    estado = verificar_conexion()
    if not estado["ok"]:
        print(f"Redis no disponible: {estado.get('error')}", file=sys.stderr)
        return 1
    r = get_redis()
    db, version_mongo = None, "no medido"
    if not args.solo_redis:
        try:
            from app.main import get_db
            db = get_db()
            version_mongo = db.client.server_info().get("version", "?")
        except Exception as e:
            print(f"MongoDB no disponible ({type(e).__name__}: {str(e)[:100]}). Use --solo-redis para medir solo Redis.", file=sys.stderr)
            return 1

    entorno = {"fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "redis": estado["version"], "mongo": version_mongo,
               "python": platform.python_version(), "sistema": platform.system()}
    resultados = {}
    try:
        for clave, titulo, op_redis, op_mongo in OPERACIONES:
            medianas_redis, medianas_mongo = [], []
            for _ in range(args.ejecuciones):
                preparar_redis(r, args.operaciones)
                medianas_redis.append(medir_redis(r, clave, args.operaciones))
                if db is not None:
                    preparar_mongo(db)
                    medianas_mongo.append(medir_mongo(db, clave, args.operaciones))
            resultados[clave] = {"redis": resumen(medianas_redis),
                                 "mongo": resumen(medianas_mongo) if medianas_mongo else None}
            d = resultados[clave]
            linea = f"{titulo}: Redis {d['redis']['mediana']:.3f} ms"
            if d["mongo"]:
                linea += f" · MongoDB {d['mongo']['mediana']:.3f} ms · mejora {mejora_pct(d['redis']['mediana'], d['mongo']['mediana']):.1f} %"
            print(linea + f" (mediana de {args.ejecuciones} ejecuciones)")
    finally:
        limpiar(r, db)

    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(generar_informe(entorno, resultados, args.ejecuciones, args.operaciones), encoding="utf-8")
        print(f"Informe escrito: {args.informe}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
