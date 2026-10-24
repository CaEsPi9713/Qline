"""
TT-019 · Casos normal, conexión fallida y datos inválidos (módulos de Alessandro).

Comprueba, con peticiones HTTP reales, que la aplicación responde de forma CONTROLADA
(nunca con un error 500 sin explicar):

  1. Caso normal             con la app en funcionamiento.
  2. Datos inválidos         ventanilla, prioridad, UUID y códigos incorrectos o inexistentes.
  3. Conexión fallida        una SEGUNDA instancia de la app, apuntada a un puerto de Redis
                             donde no hay nada, para ver qué responde cada ruta cuando
                             Redis no contesta. No se detiene ni se toca el Redis real.

En el caso 3 se crea un turno de prueba con `qr_token` directamente en MongoDB (sin pasar
por Redis) para comprobar que una falla de Redis NO oculta el estado del turno; se elimina
al terminar. No se crea ningún otro dato.

Requiere la app en ejecución (la instancia normal). En el servidor, con el entorno virtual activo:

    python scripts/probar_fallos_redis.py
    python scripts/probar_fallos_redis.py --informe docs/evidencia/fallos.md
    python scripts/probar_fallos_redis.py --omitir-redis-caido        # solo casos 1 y 2

El informe describe lo ejecutado de verdad: no se escribe nada si la prueba no corre.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

PUERTO_REDIS_INEXISTENTE = "6390"
CODIGO_TURNO_PRUEBA = "A-9998"


# ----------------------------------------------------------------------------
# Clientes (mismo contrato: pedir -> (estado, texto, milisegundos))
# ----------------------------------------------------------------------------
class ClienteHTTP:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def pedir(self, metodo: str, ruta: str, datos: dict = None):
        cuerpo = None
        if datos is not None:
            from urllib.parse import urlencode
            cuerpo = urlencode(datos).encode()
        pedido = urllib.request.Request(self.base + ruta, data=cuerpo, method=metodo)
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(pedido, timeout=20) as r:
                estado, texto = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            estado, texto = e.code, e.read().decode("utf-8", "replace")
        return estado, texto, (time.perf_counter() - t0) * 1000


class ClientePrueba:
    """Mismo contrato sobre el TestClient de FastAPI (pruebas automáticas)."""

    def __init__(self, test_client):
        self.c = test_client

    def pedir(self, metodo: str, ruta: str, datos: dict = None):
        t0 = time.perf_counter()
        r = self.c.request(metodo, ruta, data=datos)
        return r.status_code, r.text, (time.perf_counter() - t0) * 1000


# ----------------------------------------------------------------------------
# Casos
# ----------------------------------------------------------------------------
def _json(texto):
    try:
        return json.loads(texto)
    except ValueError:
        return {}


def casos_normales():
    return [
        ("Estado de Redis", "GET", "/redis/estado", None, {200}, lambda t: _json(t).get("ok") is True,
         "200 con ok=true"),
        ("Cola activa (API)", "GET", "/api/cola", None, {200}, lambda t: _json(t).get("ok") is True,
         "200 con la lista de turnos"),
        ("Vista de la cola", "GET", "/cola", None, {200}, None, "200 con la página"),
        ("Panel de atención", "GET", "/panel", None, {200}, None, "200 con la página"),
        ("Estado del receptor de eventos", "GET", "/api/eventos/estado", None, {200},
         lambda t: _json(t).get("ok") is True, "200 con ok=true"),
        ("Evento de prueba por Pub/Sub", "POST", "/api/eventos/prueba", {}, {200},
         lambda t: _json(t).get("ok") is True, "200: el evento se publicó"),
    ]


def casos_datos_invalidos():
    token_inexistente = str(uuid.uuid4())
    return [
        ("Llamar con una ventanilla inexistente", "POST", "/api/llamar", {"ventanilla": "V-99"}, {400}, None,
         "400 con el motivo"),
        ("Llamar sin indicar ventanilla", "POST", "/api/llamar", {}, {422}, None, "422 (dato obligatorio)"),
        ("Emitir con una prioridad inválida", "POST", "/api/turnos/emitir", {"prioridad": "urgente"}, {400},
         lambda t: "inválida" in t.lower(), "400 con las opciones válidas"),
        ("Consultar por QR con un texto que no es UUID", "GET", "/api/turnos/qr/basura", None, {400}, None,
         "400 «no es válido»"),
        ("Consultar por QR con un UUID v1 (versión incorrecta)", "GET", f"/api/turnos/qr/{uuid.uuid1()}", None, {400}, None,
         "400: solo se aceptan UUID v4"),
        ("Consultar por QR con un intento de inyección", "GET", "/api/turnos/qr/%27%20OR%201%3D1%20--", None, {400}, None,
         "400 sin consultar la base de datos"),
        ("Consultar por QR con un UUID inexistente", "GET", f"/api/turnos/qr/{token_inexistente}", None, {404}, None,
         "404 «no corresponde a ningún turno»"),
        ("Página del QR con un UUID inválido", "GET", "/turno/qr/basura", None, {400},
         lambda t: "Traceback" not in t, "400 con página controlada, sin traza"),
        ("Página del QR con un UUID inexistente", "GET", f"/turno/qr/{token_inexistente}", None, {404},
         lambda t: "Traceback" not in t, "404 con página controlada, sin traza"),
        ("Consultar un turno inexistente por código", "GET", "/api/turnos/A-7777", None, {404}, None, "404"),
        ("Iniciar la atención de un turno inexistente", "POST", "/api/atencion/iniciar",
         {"codigo": "A-7777", "ventanilla": "V-01"}, {404}, None, "404"),
        ("Iniciar la atención con un código inválido", "POST", "/api/atencion/iniciar",
         {"codigo": "basura", "ventanilla": "V-01"}, {422}, None, "422"),
        ("Finalizar con una ventanilla inválida", "POST", "/api/atencion/finalizar",
         {"codigo": "A-7777", "ventanilla": "V-99"}, {422}, None, "422"),
    ]


def casos_redis_caido(token: str):
    sin_500 = lambda t: "Traceback" not in t  # noqa: E731
    return [
        ("Estado de Redis", "GET", "/redis/estado", None, {200}, lambda t: _json(t).get("ok") is False,
         "200 informando ok=false (no se rompe)"),
        ("Cola activa (API)", "GET", "/api/cola", None, {503}, lambda t: _json(t).get("ok") is False,
         "503 «Redis no disponible»"),
        ("Vista de la cola", "GET", "/cola", None, {200}, lambda t: "Redis no disponible" in t,
         "200: la página muestra el aviso en lugar de romperse"),
        ("Llamar al siguiente", "POST", "/api/llamar", {"ventanilla": "V-01"}, {503}, lambda t: _json(t).get("ok") is False,
         "503 controlado"),
        ("Emitir un turno", "POST", "/api/turnos/emitir", {"prioridad": "normal"}, {503}, lambda t: _json(t).get("ok") is False,
         "503 controlado: no deja un turno a medias"),
        ("Publicar un evento", "POST", "/api/eventos/prueba", {}, {503}, lambda t: _json(t).get("ok") is False,
         "503 controlado"),
        ("Panel de atención", "GET", "/panel", None, {200}, sin_500,
         "200: el panel sigue mostrando el estado de MongoDB"),
        ("Consulta por QR de un turno existente (API)", "GET", f"/api/turnos/qr/{token}", None, {200},
         lambda t: _json(t).get("turno", {}).get("estado") == "pendiente" and bool(_json(t)["turno"].get("aviso")),
         "200: se muestra el estado de MongoDB con un aviso de Redis"),
        ("Consulta por QR de un turno existente (página)", "GET", f"/turno/qr/{token}", None, {200}, sin_500,
         "200: la página se muestra"),
    ]


def ejecutar(cliente, casos: list) -> list:
    resultados = []
    for nombre, metodo, ruta, datos, esperados, valida, esperado_txt in casos:
        estado, texto, ms = cliente.pedir(metodo, ruta, datos)
        ok = estado in esperados and estado != 500 and (valida is None or bool(valida(texto)))
        resultados.append({"caso": nombre, "peticion": f"{metodo} {ruta.split('?')[0] if len(ruta) < 60 else ruta[:57] + '...'}",
                           "esperado": esperado_txt, "estado": estado, "ms": round(ms), "ok": ok})
    return resultados


# ----------------------------------------------------------------------------
# Segunda instancia de la app, con Redis inalcanzable
# ----------------------------------------------------------------------------
def levantar_app_sin_redis(puerto: int, espera_seg: int = 25):
    entorno = {**os.environ, "REDIS_PORT": PUERTO_REDIS_INEXISTENTE}
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "warning"],
        cwd=RAIZ, env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{puerto}"
    limite = time.time() + espera_seg
    while time.time() < limite:
        if proceso.poll() is not None:
            raise RuntimeError("La instancia sin Redis terminó al arrancar (¿puerto ocupado?).")
        try:
            urllib.request.urlopen(base + "/static/style.css", timeout=1)
            return proceso, base
        except Exception:
            time.sleep(0.4)
    proceso.terminate()
    raise RuntimeError("La instancia sin Redis no arrancó a tiempo.")


# ----------------------------------------------------------------------------
# Informe
# ----------------------------------------------------------------------------
def generar_informe(entorno: dict, secciones: list) -> str:
    total = sum(len(r) for _, _, r in secciones)
    fallos = sum(1 for _, _, r in secciones for x in r if not x["ok"])
    con_500 = sum(1 for _, _, r in secciones for x in r if x["estado"] == 500)
    f = ["# Casos normal, conexión fallida y datos inválidos (TT-019, módulos de Alessandro)", "",
         "> Informe generado por `scripts/probar_fallos_redis.py` con los resultados de **esa ejecución**; no se escribe a mano.", "",
         "## Entorno", "",
         f"- Fecha (UTC): {entorno['fecha']}",
         f"- Python: {entorno['python']} · {entorno['sistema']}",
         f"- Aplicación probada: {entorno['url']}",
         f"- Instancia con Redis inalcanzable: {entorno['url_sin_redis']}", "",
         "## Resultado global", "",
         f"**{'OK' if fallos == 0 else 'FALLA'}** · {total} casos ejecutados · {fallos} fuera de lo esperado · **{con_500} respuestas 500**.", ""]
    for titulo, explicacion, resultados in secciones:
        f += [f"## {titulo}", "", explicacion, "",
              "| Caso | Petición | Esperado | Estado obtenido | Tiempo (ms) | Resultado |", "|---|---|---|---|---|---|"]
        for x in resultados:
            f.append(f"| {x['caso']} | `{x['peticion']}` | {x['esperado']} | {x['estado']} | {x['ms']} | {'OK' if x['ok'] else 'FALLA'} |")
        f.append("")
    f += ["## Alcance y límites", "",
          "- La «conexión fallida» se simula con una segunda instancia de la app apuntada a un puerto de Redis donde no hay nada; no se detiene el Redis compartido.",
          "- Los tiempos incluyen el intento de conexión que falla: la app está configurada para fallar rápido (sin reintentos) en lugar de dejar esperando al usuario.",
          "- No se prueba la caída de MongoDB (no se puede detener el servidor del curso); su manejo controlado se cubre con las pruebas automáticas del repositorio.",
          "- El rechazo de documentos por el JSON Schema de MongoDB corresponde a Carlos (TT-019 de su módulo)."]
    return "\n".join(f) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:18002", help="URL de la app en funcionamiento")
    ap.add_argument("--puerto-sin-redis", type=int, default=18099, help="puerto de la instancia sin Redis (default: %(default)s)")
    ap.add_argument("--omitir-redis-caido", action="store_true", help="solo los casos 1 y 2")
    ap.add_argument("--informe", type=Path, help="escribe el informe en Markdown en esta ruta")
    args = ap.parse_args(argv)

    principal = ClienteHTTP(args.url)
    try:
        estado, _, _ = principal.pedir("GET", "/redis/estado")
    except Exception as e:
        print(f"La app no responde en {args.url}: {type(e).__name__}. Inícielo y reintente.", file=sys.stderr)
        return 1

    entorno = {"fecha": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "python": platform.python_version(),
               "sistema": platform.system(), "url": args.url,
               "url_sin_redis": "no ejecutada" if args.omitir_redis_caido else f"http://127.0.0.1:{args.puerto_sin_redis}"}
    secciones = []

    print("1. Caso normal")
    r1 = ejecutar(principal, casos_normales())
    secciones.append(("1. Caso normal", "La aplicación con Redis y MongoDB disponibles responde lo esperado.", r1))
    print("2. Datos inválidos")
    r2 = ejecutar(principal, casos_datos_invalidos())
    secciones.append(("2. Datos inválidos", "Cada dato incorrecto produce una respuesta controlada con su código HTTP; nada llega a la base de datos.", r2))

    if not args.omitir_redis_caido:
        print("3. Conexión fallida (instancia con Redis inalcanzable)")
        from app.main import get_db
        db = get_db()
        if db["turnos"].find_one({"codigo": CODIGO_TURNO_PRUEBA}):
            print(f"Ya existe un turno {CODIGO_TURNO_PRUEBA}; elimínelo y reintente.", file=sys.stderr)
            return 1
        token = str(uuid.uuid4())
        ahora = datetime.now(timezone.utc)
        db["turnos"].insert_one({
            "codigo": CODIGO_TURNO_PRUEBA, "qr_token": token, "servicio": "atencion_general", "prioridad": "normal",
            "estado": "pendiente", "ventanilla": None, "operador": None,
            "timestamps": {"creado": ahora, "llamado": None, "inicio_atencion": None, "finalizado": None, "abandonado": None},
            "metricas": {"espera_seg": None, "atencion_seg": None}})
        proceso = None
        try:
            proceso, base = levantar_app_sin_redis(args.puerto_sin_redis)
            r3 = ejecutar(ClienteHTTP(base), casos_redis_caido(token))
        finally:
            if proceso is not None:
                proceso.terminate()
                try:
                    proceso.wait(10)
                except Exception:
                    proceso.kill()
            db["turnos"].delete_many({"codigo": CODIGO_TURNO_PRUEBA})
        secciones.append(("3. Conexión fallida: Redis no responde",
                          "Con Redis inalcanzable, cada ruta responde de forma controlada y la consulta por QR sigue mostrando el estado que conserva MongoDB.", r3))

    for titulo, _, resultados in secciones:
        for x in resultados:
            print(f"  {'OK   ' if x['ok'] else 'FALLA'} {x['caso']}: {x['estado']} ({x['ms']} ms)")
    total_fallos = sum(1 for _, _, r in secciones for x in r if not x["ok"])
    print("Todo OK" if total_fallos == 0 else f"HAY FALLOS: {total_fallos}")

    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(generar_informe(entorno, secciones), encoding="utf-8")
        print(f"Informe escrito: {args.informe}")
    return 0 if total_fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
