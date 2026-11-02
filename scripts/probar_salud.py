"""
S4-M06 · Evidencia de `/salud` en el servidor.

Comprueba con peticiones HTTP reales que `GET /salud`:
  1. Caso normal         con Redis y MongoDB reales: 200 y estado «ok».
  2. Redis inalcanzable  una instancia de la app apuntada a un puerto de Redis sin servicio: 503.
  3. MongoDB inalcanzable idem con un puerto de MongoDB sin servicio: 503 (tarda hasta 5 s: es el
                          tiempo de selección de servidor de `get_db()`).
  4. Ambos inalcanzables  503.
  5. Protección           opcional, con --url-publica: sin credenciales, Apache debe responder 401.

En todos los casos el cuerpo solo trae estados: no puede contener puertos, servidores, usuarios,
«mongodb://», texto de excepciones ni trazas. No se detiene ni se toca ningún servicio real: las
instancias «caídas» son procesos propios con el barrido de abandono apagado (no escriben en MongoDB).

Requiere la app en ejecución. En el servidor, con el entorno virtual activo:

    python -m scripts.probar_salud
    python -m scripts.probar_salud --informe docs/evidencia/salud.md
    python -m scripts.probar_salud --url-publica https://grupo2.crnube.net/proyecto/qline

El informe describe lo ejecutado de verdad: si la app no responde, no se escribe nada.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.informe import encabezado  # noqa: E402
from scripts.probar_fallos_redis import ClienteHTTP, ejecutar  # noqa: E402

PUERTO_REDIS_INEXISTENTE = "6390"
PUERTO_MONGO_INEXISTENTE = "27099"
CAMPOS = {"estado", "app", "redis", "mongo", "barrido"}
# Nada de esto puede aparecer en el cuerpo de /salud.
PROHIBIDO_BASE = ("Traceback", "refused", "Connection", "mongodb://", "127.0.0.1", "localhost",
                  PUERTO_REDIS_INEXISTENTE, PUERTO_MONGO_INEXISTENTE)


def _json(texto: str) -> dict:
    try:
        datos = json.loads(texto)
        return datos if isinstance(datos, dict) else {}
    except ValueError:
        return {}


def sin_fugas(texto: str) -> bool:
    prohibidos = list(PROHIBIDO_BASE)
    usuario = os.getenv("MONGO_USER", "")
    if usuario:
        prohibidos.append(usuario)
    return not any(p in texto for p in prohibidos)


def _estado(texto: str, **esperado) -> bool:
    cuerpo = _json(texto)
    return (set(cuerpo) == CAMPOS and all(cuerpo.get(k) == v for k, v in esperado.items())
            and sin_fugas(texto))


def caso_normal() -> list:
    return [("Estado con Redis y MongoDB reales", "GET", "/salud", None, {200},
             lambda t: _estado(t, estado="ok", app="ok", redis="ok", mongo="ok"),
             "200 con estado ok y solo los 5 campos, sin datos de infraestructura")]


def caso_redis_caido() -> list:
    return [("Redis sin servicio", "GET", "/salud", None, {503},
             lambda t: _estado(t, estado="degradado", redis="error", mongo="ok"),
             "503: redis=error, mongo=ok, sin fugas")]


def caso_mongo_caido() -> list:
    return [("MongoDB sin servicio", "GET", "/salud", None, {503},
             lambda t: _estado(t, estado="degradado", redis="ok", mongo="error"),
             "503: mongo=error, redis=ok, sin fugas")]


def caso_ambos_caidos() -> list:
    return [("Redis y MongoDB sin servicio", "GET", "/salud", None, {503},
             lambda t: _estado(t, estado="degradado", redis="error", mongo="error"),
             "503: ambos en error, sin fugas")]


def caso_proteccion() -> list:
    return [("Sin credenciales a través de Apache", "GET", "/salud", None, {401},
             lambda t: "estado" not in _json(t), "401: /salud no es público")]


def levantar_app(puerto: int, entorno_extra: dict, espera_seg: int = 25):
    """Instancia propia de la app con el barrido apagado; devuelve (proceso, url base)."""
    entorno = {**os.environ, "BARRIDO_ABANDONO": "0", **entorno_extra}
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto),
         "--log-level", "warning"],
        cwd=RAIZ, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{puerto}"
    limite = time.time() + espera_seg
    while time.time() < limite:
        if proceso.poll() is not None:
            raise RuntimeError(f"La instancia del puerto {puerto} terminó al arrancar (¿puerto ocupado?).")
        try:
            urllib.request.urlopen(base + "/static/style.css", timeout=1)
            return proceso, base
        except Exception:  # noqa: BLE001 · aún no arranca
            time.sleep(0.4)
    proceso.terminate()
    raise RuntimeError(f"La instancia del puerto {puerto} no arrancó a tiempo.")


def probar_instancia(puerto: int, entorno_extra: dict, casos: list) -> list:
    proceso = None
    try:
        proceso, base = levantar_app(puerto, entorno_extra)
        return ejecutar(ClienteHTTP(base), casos)
    finally:
        if proceso is not None:
            proceso.terminate()
            try:
                proceso.wait(10)
            except Exception:  # noqa: BLE001
                proceso.kill()


def generar_informe(entorno: dict, secciones: list) -> str:
    total = sum(len(r) for _, _, r in secciones)
    fallos = sum(1 for _, _, r in secciones for x in r if not x["ok"])
    con_500 = sum(1 for _, _, r in secciones for x in r if x["estado"] == 500)
    f = [encabezado("`/salud`: estado de la aplicación, Redis y MongoDB (S4-M06)"),
         f"- Aplicación probada: {entorno['url']}",
         f"- Instancias con servicios inalcanzables: puertos {entorno['puertos']}",
         f"- Verificación a través de Apache: {entorno['publica']}", "",
         "## Resultado global", "",
         f"**{'OK' if fallos == 0 else 'FALLA'}** · {total} casos ejecutados · {fallos} fuera de lo esperado · "
         f"**{con_500} respuestas 500**.", ""]
    for titulo, explicacion, resultados in secciones:
        f += [f"## {titulo}", "", explicacion, "",
              "| Caso | Petición | Esperado | Estado obtenido | Tiempo (ms) | Resultado |", "|---|---|---|---|---|---|"]
        for x in resultados:
            f.append(f"| {x['caso']} | `{x['peticion']}` | {x['esperado']} | {x['estado']} | {x['ms']} | "
                     f"{'OK' if x['ok'] else 'FALLA'} |")
        f.append("")
    f += ["## Alcance y límites", "",
          "- Los servicios «caídos» se simulan con instancias propias de la app apuntadas a puertos sin servicio; "
          "no se detiene ni se modifica el Redis ni el MongoDB compartidos.",
          "- Esas instancias arrancan con `BARRIDO_ABANDONO=0`, por lo que no escriben en MongoDB; su campo "
          "`barrido` es `false` y no cuenta como fallo.",
          "- Con un servicio inalcanzable la respuesta tarda: hasta 3 s con Redis (tiempo de espera del cliente) y "
          "hasta 5 s con MongoDB (selección de servidor de `get_db()`); con ambos caídos se suman (unos 7 s en una prueba local).",
          "- «Sin fugas» significa que el cuerpo no contiene puertos, `127.0.0.1`, `localhost`, `mongodb://`, "
          "el usuario de MongoDB, texto de conexión rechazada ni trazas.",
          "- La protección de Apache solo se comprueba si se indicó `--url-publica`; la prueba automática de "
          "`tests/test_htaccess.py` verifica que `/salud` no está entre las rutas públicas."]
    return "\n".join(f) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:18002", help="URL de la app en funcionamiento")
    ap.add_argument("--puerto-base", type=int, default=18100,
                    help="primer puerto de las 3 instancias «caídas» (default: %(default)s)")
    ap.add_argument("--url-publica", help="URL pública (con Apache) para comprobar que /salud exige credenciales")
    ap.add_argument("--omitir-caidas", action="store_true", help="solo el caso normal")
    ap.add_argument("--informe", type=Path, help="escribe el informe en Markdown en esta ruta")
    args = ap.parse_args(argv)

    principal = ClienteHTTP(args.url)
    try:
        principal.pedir("GET", "/salud")
    except Exception as e:  # noqa: BLE001
        print(f"La app no responde en {args.url}: {type(e).__name__}. Inícielo y reintente.", file=sys.stderr)
        return 1

    secciones = []
    print("1. Caso normal")
    secciones.append(("1. Caso normal", "Con Redis y MongoDB reales, `/salud` responde 200.",
                      ejecutar(principal, caso_normal())))
    puertos = "no ejecutadas"
    if not args.omitir_caidas:
        p = args.puerto_base
        puertos = f"{p}, {p + 1}, {p + 2}"
        try:
            print("2. Redis inalcanzable")
            secciones.append(("2. Redis inalcanzable", "Con Redis sin servicio, `/salud` responde 503 y MongoDB sigue en «ok».",
                              probar_instancia(p, {"REDIS_PORT": PUERTO_REDIS_INEXISTENTE}, caso_redis_caido())))
            print("3. MongoDB inalcanzable (tarda unos segundos)")
            secciones.append(("3. MongoDB inalcanzable", "Con MongoDB sin servicio, `/salud` responde 503 y Redis sigue en «ok».",
                              probar_instancia(p + 1, {"MONGO_PORT": PUERTO_MONGO_INEXISTENTE}, caso_mongo_caido())))
            print("4. Ambos inalcanzables")
            secciones.append(("4. Redis y MongoDB inalcanzables", "Con ambos sin servicio, `/salud` sigue respondiendo (503), nunca 500.",
                              probar_instancia(p + 2, {"REDIS_PORT": PUERTO_REDIS_INEXISTENTE,
                                                       "MONGO_PORT": PUERTO_MONGO_INEXISTENTE}, caso_ambos_caidos())))
        except RuntimeError as e:
            print(f"No se pudo levantar una instancia de prueba: {e}", file=sys.stderr)
            return 1
    publica = "no ejecutada"
    if args.url_publica:
        print("5. Protección de Apache")
        publica = args.url_publica
        secciones.append(("5. Protección de Apache", "Sin usuario ni contraseña, la ruta no debe responder con datos.",
                          ejecutar(ClienteHTTP(args.url_publica), caso_proteccion())))

    for _, _, resultados in secciones:
        for x in resultados:
            print(f"  {'OK   ' if x['ok'] else 'FALLA'} {x['caso']}: {x['estado']} ({x['ms']} ms)")
    fallos = sum(1 for _, _, r in secciones for x in r if not x["ok"])
    print("Todo OK" if fallos == 0 else f"HAY FALLOS: {fallos}")

    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(generar_informe({"url": args.url, "puertos": puertos, "publica": publica}, secciones),
                                encoding="utf-8")
        print(f"Informe escrito: {args.informe}")
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
