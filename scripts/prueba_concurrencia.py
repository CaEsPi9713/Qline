"""
TT-016 · Prueba formal de concurrencia: 0 turnos duplicados (sección 18.1 del plan).

Meta funcional del plan:  10 solicitudes concurrentes simuladas  ->  0 turnos duplicados.
No hace falta tener 10 ventanillas: la prueba simula consumidores concurrentes.

Escenarios
  A. Rondas de N consumidores simultáneos (hilos con barrera de arranque) sobre una
     cola de prueba. Cada ronda comprueba que: no hay códigos repetidos, se asignó
     exactamente un turno por consumidor, el conjunto asignado es el de los N primeros
     de la cola (la prioridad se respeta bajo concurrencia) y la cola bajó en N.
  B. Vaciado competitivo: N consumidores se disputan toda la cola hasta vaciarla.
     Cada turno debe salir exactamente una vez.
  C. (opcional, --http) Flujo real de extremo a extremo contra la app en ejecución:
     emite turnos, 10 solicitudes simultáneas a POST /api/llamar sobre las 3
     ventanillas reales, y comprueba MongoDB y Redis; luego inicia y finaliza.

Los escenarios A y B usan claves de prueba `grupo2:qline:test:conc:*` (no tocan el
contador ni la cola reales) y las eliminan al terminar. El escenario C usa la cola,
el contador y la colección reales: exige la cola vacía y las ventanillas libres, y al
terminar elimina los turnos que creó (el contador de códigos queda avanzado: reinícielo
antes de la demostración).

Uso, desde la raíz del proyecto y con el entorno virtual activo:

    python scripts/prueba_concurrencia.py                          # escenarios A y B
    python scripts/prueba_concurrencia.py --http                   # + escenario C (app corriendo)
    python scripts/prueba_concurrencia.py --http --informe docs/evidencia/concurrencia.md

El informe describe lo ejecutado de verdad: no se escribe nada si la prueba no corre.
"""
import argparse
import inspect
import json
import platform
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cola  # noqa: E402
from app.constantes import VENTANILLAS, clave_turno, clave_ventanilla_actual  # noqa: E402
from app.redis_client import get_redis, verificar_conexion  # noqa: E402

PREFIJO = "grupo2:qline:test:conc:"
CLAVE_COLA_PRUEBA = PREFIJO + "cola"
META_CONSUMIDORES = 10


def clave_actual(consumidor: str) -> str:
    return f"{PREFIJO}actual:{consumidor}"


def limpiar_pruebas(r) -> int:
    """Elimina SOLO las claves de prueba de este script."""
    claves = list(r.scan_iter(match=PREFIJO + "*"))
    return r.delete(*claves) if claves else 0


def precargar(n: int, base_ms: int = 1_000) -> list:
    """Encola n turnos de prueba (cada cuarto es preferencial). Devuelve el orden de atención esperado."""
    for i in range(n):
        prioridad = "preferencial" if i % 4 == 3 else "normal"
        cola.encolar(f"T-{i + 1:04d}", prioridad, base_ms + i, CLAVE_COLA_PRUEBA)
    return [t["codigo"] for t in cola.ver_cola(limite=n, clave_cola=CLAVE_COLA_PRUEBA)]


def primer_error(resultados) -> str:
    """Descripción del primer error inesperado de los consumidores (o cadena vacía)."""
    for x in resultados:
        if isinstance(x, Exception):
            return f"{type(x).__name__}: {x}"[:200]
    return ""


def correr_en_paralelo(n: int, tarea) -> list:
    """Lanza n hilos que arrancan a la vez (barrera) y devuelve el resultado de cada uno."""
    barrera = threading.Barrier(n)
    resultados = [None] * n

    def envoltura(i):
        barrera.wait()
        try:
            resultados[i] = tarea(i)
        except Exception as e:          # un fallo inesperado debe verse en el informe, no ocultarse
            resultados[i] = e

    hilos = [threading.Thread(target=envoltura, args=(i,)) for i in range(n)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    return resultados


# ----------------------------------------------------------------------------
# Escenario A: rondas de N consumidores simultáneos
# ----------------------------------------------------------------------------
def ronda_redis(r, consumidores: int = META_CONSUMIDORES, turnos: int = 25) -> dict:
    limpiar_pruebas(r)
    esperado = precargar(turnos)[:consumidores]

    def tarea(i):
        cid = f"C-{i + 1:02d}"
        res = cola.extraer_siguiente(cid, CLAVE_COLA_PRUEBA, clave_actual(cid), validar_ventanilla=False)
        return res[0] if res else None

    t0 = time.perf_counter()
    resultados = correr_en_paralelo(consumidores, tarea)
    ms = (time.perf_counter() - t0) * 1000

    errores = [x for x in resultados if isinstance(x, Exception)]
    asignados = [x for x in resultados if isinstance(x, str)]
    duplicados = len(asignados) - len(set(asignados))
    restantes = cola.tamano_cola(CLAVE_COLA_PRUEBA)
    por_consumidor_ok = all(
        r.get(clave_actual(f"C-{i + 1:02d}")) == resultados[i] for i in range(consumidores)
        if isinstance(resultados[i], str)
    )
    resultado = {
        "consumidores": consumidores, "turnos_en_cola": turnos, "asignados": len(asignados),
        "duplicados": duplicados, "errores": len(errores), "error_ejemplo": primer_error(resultados),
        "conjunto_esperado": set(asignados) == set(esperado),
        "cola_restante": restantes, "cola_restante_esperada": turnos - consumidores,
        "claves_por_consumidor": por_consumidor_ok, "ms": round(ms, 1),
    }
    resultado["ok"] = (duplicados == 0 and not errores and len(asignados) == consumidores
                       and resultado["conjunto_esperado"] and restantes == turnos - consumidores
                       and por_consumidor_ok)
    limpiar_pruebas(r)
    return resultado


# ----------------------------------------------------------------------------
# Escenario B: vaciado competitivo
# ----------------------------------------------------------------------------
def vaciado_redis(r, consumidores: int = META_CONSUMIDORES, turnos: int = 200) -> dict:
    limpiar_pruebas(r)
    precargar(turnos)

    def tarea(i):
        cid = f"C-{i + 1:02d}"
        clave = clave_actual(cid)
        mios = []
        while True:
            res = cola.extraer_siguiente(cid, CLAVE_COLA_PRUEBA, clave, validar_ventanilla=False)
            if res is None:
                return mios
            mios.append(res[0])
            r.delete(clave)             # el consumidor "atiende" y queda libre para el siguiente

    t0 = time.perf_counter()
    resultados = correr_en_paralelo(consumidores, tarea)
    ms = (time.perf_counter() - t0) * 1000
    errores = [x for x in resultados if isinstance(x, Exception)]
    todos = [c for lista in resultados if isinstance(lista, list) for c in lista]
    duplicados = len(todos) - len(set(todos))
    resultado = {
        "consumidores": consumidores, "turnos_en_cola": turnos, "asignados": len(todos),
        "unicos": len(set(todos)), "duplicados": duplicados, "errores": len(errores),
        "error_ejemplo": primer_error(resultados),
        "cola_restante": cola.tamano_cola(CLAVE_COLA_PRUEBA),
        "reparto": sorted((len(x) for x in resultados if isinstance(x, list)), reverse=True),
        "ms": round(ms, 1),
    }
    resultado["ok"] = (duplicados == 0 and not errores and len(todos) == turnos
                       and resultado["cola_restante"] == 0)
    limpiar_pruebas(r)
    return resultado


# ----------------------------------------------------------------------------
# Escenario C: flujo real de extremo a extremo (HTTP)
# ----------------------------------------------------------------------------
class ClienteHTTP:
    """Cliente mínimo de la app en ejecución (formularios, como los usa la interfaz)."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def post(self, ruta: str, datos: dict):
        cuerpo = urllib.parse.urlencode(datos).encode()
        pedido = urllib.request.Request(self.base + ruta, data=cuerpo, method="POST")
        try:
            with urllib.request.urlopen(pedido, timeout=15) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}


class ClientePrueba:
    """Mismo contrato que ClienteHTTP, sobre el TestClient de FastAPI (pruebas automáticas)."""

    def __init__(self, test_client):
        self.c = test_client

    def post(self, ruta: str, datos: dict):
        r = self.c.post(ruta, data=datos)
        return r.status_code, r.json()


SOLICITUDES = ["V-01", "V-02", "V-03", "V-01", "V-02", "V-03", "V-01", "V-02", "V-03", "V-01"]   # 10 simultáneas


def flujo_http(cliente, db, r, rondas: int = 3) -> dict:
    activos = db["turnos"].count_documents({"estado": {"$in": ["llamado", "en_atencion"]}})
    if cola.tamano_cola() != 0 or activos != 0:
        raise SystemExit("El escenario C exige la cola vacía y ninguna ventanilla ocupada. "
                         "Termine los turnos en curso o vacíe la cola y reintente.")

    total = 3 * rondas + 3
    # Se emiten primero los normales y luego los preferenciales: la prioridad debe adelantarlos.
    prioridades = ["normal"] * (total - 4) + ["preferencial"] * 4
    emitidos = []
    for p in prioridades:
        estado, cuerpo = cliente.post("/api/turnos/emitir", {"prioridad": p})
        if estado != 200:
            raise SystemExit(f"No se pudo emitir un turno de prueba: {estado} {cuerpo}")
        emitidos.append(cuerpo["turno"]["codigo"])
    orden = [t["codigo"] for t in cola.ver_cola(limite=total)]

    detalle, ok_total = [], True
    try:
        for n in range(1, rondas + 1):
            esperados = orden[3 * (n - 1): 3 * n]
            resultados = correr_en_paralelo(
                len(SOLICITUDES), lambda i: cliente.post("/api/llamar", {"ventanilla": SOLICITUDES[i]}))
            errores = [x for x in resultados if isinstance(x, Exception)]
            buenos = [(SOLICITUDES[i], x[1]) for i, x in enumerate(resultados)
                      if not isinstance(x, Exception) and x[0] == 200 and x[1].get("codigo")]
            rechazos = [x for x in resultados if not isinstance(x, Exception) and x[0] == 409]
            codigos = [b["codigo"] for _, b in buenos]
            duplicados = len(codigos) - len(set(codigos))
            ventanillas_distintas = len({v for v, _ in buenos}) == len(buenos)
            mongo_ok = all(
                (d := db["turnos"].find_one({"codigo": b["codigo"]})) is not None
                and d["estado"] == "llamado" and d["ventanilla"] == v for v, b in buenos)
            redis_ok = all(r.get(clave_ventanilla_actual(v)) == b["codigo"] for v, b in buenos)
            ok = (duplicados == 0 and not errores and len(buenos) == 3 and len(rechazos) == 7
                  and ventanillas_distintas and set(codigos) == set(esperados) and mongo_ok and redis_ok)

            # Cierra el ciclo: iniciar y finalizar libera las ventanillas para la ronda siguiente.
            ciclo_ok = True
            for v, b in buenos:
                e1, _ = cliente.post("/api/atencion/iniciar", {"codigo": b["codigo"], "ventanilla": v})
                e2, _ = cliente.post("/api/atencion/finalizar", {"codigo": b["codigo"], "ventanilla": v})
                ciclo_ok = ciclo_ok and e1 == 200 and e2 == 200
            liberadas = all(r.get(clave_ventanilla_actual(v)) is None for v in VENTANILLAS)
            ok = ok and ciclo_ok and liberadas
            ok_total = ok_total and ok
            detalle.append({
                "ronda": n, "solicitudes": len(SOLICITUDES), "asignados": len(buenos), "rechazados_409": len(rechazos),
                "duplicados": duplicados, "errores": len(errores), "codigos": codigos,
                "prioridad_respetada": set(codigos) == set(esperados), "mongo_ok": mongo_ok, "redis_ok": redis_ok,
                "ciclo_completo": ciclo_ok and liberadas, "ok": ok,
            })
    finally:
        _limpiar_http(db, r, emitidos)

    return {"turnos_emitidos": total, "rondas": detalle, "ok": ok_total and len(detalle) == rondas,
            "orden_esperado": orden}


def _limpiar_http(db, r, codigos: list) -> None:
    """Elimina los turnos creados por la prueba (MongoDB y Redis). Solo toca esos códigos."""
    if codigos:
        r.zrem(cola.CLAVE_COLA, *codigos)
        r.delete(*[clave_turno(c) for c in codigos])
        for v in VENTANILLAS:
            if r.get(clave_ventanilla_actual(v)) in codigos:
                r.delete(clave_ventanilla_actual(v))
        db["turnos"].delete_many({"codigo": {"$in": codigos}})


# ----------------------------------------------------------------------------
# Informe
# ----------------------------------------------------------------------------
def generar_informe(entorno: dict, rondas_a: list, vaciado: dict, http: dict = None) -> str:
    def marca(ok):
        return "OK" if ok else "FALLA"

    total_asignaciones = sum(x["asignados"] for x in rondas_a) + vaciado["asignados"]
    total_duplicados = sum(x["duplicados"] for x in rondas_a) + vaciado["duplicados"]
    if http:
        total_asignaciones += sum(x["asignados"] for x in http["rondas"])
        total_duplicados += sum(x["duplicados"] for x in http["rondas"])
    todo_ok = all(x["ok"] for x in rondas_a) and vaciado["ok"] and (http is None or http["ok"])

    f = ["# Prueba formal de concurrencia (TT-016)", "",
         "> Informe generado por `scripts/prueba_concurrencia.py` con los resultados de **esa ejecución**; no se escribe a mano.", "",
         "## Entorno", "",
         f"- Fecha (UTC): {entorno['fecha']}",
         f"- Redis: {entorno['redis']}",
         f"- Python: {entorno['python']} · {entorno['sistema']}",
         f"- Consumidores simultáneos por ronda: {rondas_a[0]['consumidores']} (meta del plan: 10)", "",
         "## Resultado global", "",
         f"**{marca(todo_ok)}** · {total_asignaciones} asignaciones comprobadas · **{total_duplicados} turnos duplicados**.", "",
         "## Escenario A · rondas de consumidores simultáneos", "",
         "Cada ronda arranca todos los consumidores a la vez con una barrera; se comprueba que cada uno recibe un turno "
         "distinto, que el conjunto asignado es el de los primeros de la cola (prioridad respetada) y que la cola baja en la cantidad exacta.", "",
         "| Ronda | Consumidores | Turnos en cola | Asignados | Duplicados | Errores | Prioridad respetada | Cola restante | Tiempo (ms) | Resultado |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, x in enumerate(rondas_a, 1):
        f.append(f"| {i} | {x['consumidores']} | {x['turnos_en_cola']} | {x['asignados']} | {x['duplicados']} | {x['errores']} | "
                 f"{'sí' if x['conjunto_esperado'] else 'no'} | {x['cola_restante']} (esperada {x['cola_restante_esperada']}) | "
                 f"{x['ms']} | {marca(x['ok'])} |")
    ejemplos = [x["error_ejemplo"] for x in rondas_a + [vaciado] if x.get("error_ejemplo")]
    if ejemplos:
        f += ["", f"> Primer error de un consumidor: `{ejemplos[0]}`"]
    f += ["", "## Escenario B · vaciado competitivo", "",
          f"{vaciado['consumidores']} consumidores se disputan {vaciado['turnos_en_cola']} turnos hasta vaciar la cola.", "",
          "| Turnos en cola | Asignados | Únicos | Duplicados | Errores | Cola restante | Tiempo (ms) | Resultado |", "|---|---|---|---|---|---|---|---|",
          f"| {vaciado['turnos_en_cola']} | {vaciado['asignados']} | {vaciado['unicos']} | {vaciado['duplicados']} | {vaciado['errores']} | "
          f"{vaciado['cola_restante']} | {vaciado['ms']} | {marca(vaciado['ok'])} |", "",
          f"Reparto entre consumidores (turnos por consumidor): {vaciado['reparto']}", ""]
    if http:
        f += ["## Escenario C · flujo real de extremo a extremo", "",
              f"{http['turnos_emitidos']} turnos emitidos por la API (primero normales, luego 4 preferenciales). En cada ronda, "
              "10 solicitudes simultáneas a `POST /api/llamar` sobre las 3 ventanillas reales; se verifica MongoDB y Redis y se cierra "
              "el ciclo (iniciar y finalizar).", "",
              "| Ronda | Solicitudes | Asignados | Rechazados (409) | Duplicados | Prioridad | MongoDB | Redis | Ciclo completo | Resultado |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for x in http["rondas"]:
            f.append(f"| {x['ronda']} | {x['solicitudes']} | {x['asignados']} ({', '.join(x['codigos'])}) | {x['rechazados_409']} | "
                     f"{x['duplicados']} | {'respetada' if x['prioridad_respetada'] else 'NO'} | {'OK' if x['mongo_ok'] else 'FALLA'} | "
                     f"{'OK' if x['redis_ok'] else 'FALLA'} | {'sí' if x['ciclo_completo'] else 'no'} | {marca(x['ok'])} |")
        f.append("")
    f += ["## Qué demuestra", "",
          "- `ZPOPMIN` es atómico: dos consumidores nunca reciben el mismo turno, ni siquiera con todos arrancando a la vez.",
          "- La reserva `SET NX` de la ventanilla impide asignar dos turnos a la misma ventanilla.",
          "- La prioridad se respeta bajo concurrencia.",
          "", "## Alcance y límites", "",
          "- Los escenarios A y B ejercitan Redis directamente (la parte que decide la asignación). El escenario C ejercita además MongoDB y la API.",
          "- Los consumidores son hilos de un mismo proceso: demuestran la atomicidad de Redis, no el rendimiento (eso es TT-018).",
          "- No sustituye la medición de latencias ni la prueba de recuperación (TT-017)."]
    return "\n".join(f) + "\n"


def version_de_cola_compatible() -> bool:
    """La prueba usa `validar_ventanilla`, agregado a app/cola.py junto con este script."""
    return "validar_ventanilla" in inspect.signature(cola.extraer_siguiente).parameters


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rondas", type=int, default=5, help="rondas del escenario A (default: %(default)s, mínimo del plan: 3)")
    ap.add_argument("--consumidores", type=int, default=META_CONSUMIDORES, help="consumidores simultáneos (default: %(default)s)")
    ap.add_argument("--turnos-vaciado", type=int, default=200, help="turnos del escenario B (default: %(default)s)")
    ap.add_argument("--http", action="store_true", help="agrega el escenario C contra la app en ejecución")
    ap.add_argument("--url", default="http://127.0.0.1:18002", help="URL de la app para el escenario C")
    ap.add_argument("--informe", type=Path, help="escribe el informe en Markdown en esta ruta")
    args = ap.parse_args(argv)
    if args.rondas < 1 or args.consumidores < 2 or args.turnos_vaciado < args.consumidores:
        print("Parámetros inválidos.", file=sys.stderr)
        return 2

    if not version_de_cola_compatible():
        print("app/cola.py está desactualizado: le falta el parámetro 'validar_ventanilla'. "
              "Suba la versión nueva de app/cola.py junto con este script y reintente.", file=sys.stderr)
        return 2
    estado = verificar_conexion()
    if not estado["ok"]:
        print(f"Redis no disponible: {estado.get('error')}", file=sys.stderr)
        return 1
    r = get_redis()
    entorno = {"fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
               "redis": f"{estado['version']} ({estado['host']}:{estado['port']})",
               "python": platform.python_version(), "sistema": platform.system()}

    print(f"Escenario A: {args.rondas} rondas de {args.consumidores} consumidores simultáneos")
    rondas = []
    for i in range(1, args.rondas + 1):
        x = ronda_redis(r, args.consumidores, turnos=max(25, args.consumidores * 2 + 5))
        rondas.append(x)
        print(f"  ronda {i}: {x['asignados']} asignados, {x['duplicados']} duplicados, {x['errores']} errores, "
              f"prioridad {'respetada' if x['conjunto_esperado'] else 'NO respetada'} -> {'OK' if x['ok'] else 'FALLA'}")
        if x["errores"]:
            print(f"    primer error: {x['error_ejemplo']}")

    print(f"Escenario B: {args.consumidores} consumidores vacían {args.turnos_vaciado} turnos")
    vaciado = vaciado_redis(r, args.consumidores, args.turnos_vaciado)
    print(f"  {vaciado['asignados']} asignados, {vaciado['unicos']} únicos, {vaciado['duplicados']} duplicados, "
          f"{vaciado['errores']} errores -> {'OK' if vaciado['ok'] else 'FALLA'}")
    if vaciado["errores"]:
        print(f"    primer error: {vaciado['error_ejemplo']}")

    http = None
    if args.http:
        from app.main import get_db
        print(f"Escenario C: flujo real contra {args.url}")
        http = flujo_http(ClienteHTTP(args.url), get_db(), r)
        for x in http["rondas"]:
            print(f"  ronda {x['ronda']}: {x['asignados']} asignados {x['codigos']}, {x['rechazados_409']} rechazados, "
                  f"{x['duplicados']} duplicados -> {'OK' if x['ok'] else 'FALLA'}")
        print("  (los turnos de prueba se eliminaron; reinicie el contador de códigos antes de la demostración)")

    todo_ok = all(x["ok"] for x in rondas) and vaciado["ok"] and (http is None or http["ok"])
    duplicados = sum(x["duplicados"] for x in rondas) + vaciado["duplicados"] + (
        sum(x["duplicados"] for x in http["rondas"]) if http else 0)
    print(("Todo OK" if todo_ok else "HAY FALLOS") + f" · turnos duplicados: {duplicados}")

    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(generar_informe(entorno, rondas, vaciado, http), encoding="utf-8")
        print(f"Informe escrito: {args.informe}")
    return 0 if todo_ok else 1


if __name__ == "__main__":
    sys.exit(main())
