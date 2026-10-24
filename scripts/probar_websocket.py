"""
Verifica el tiempo real (TT-013) DIRECTAMENTE contra la app, sin pasar por Apache.

Sirve para separar dos causas cuando un WebSocket no funciona en el navegador:
  - si este script pasa y la página /ws-prueba falla, la app está bien y el
    bloqueo está en el proxy (Apache);
  - si este script falla, el problema está en la app, en Redis o en el puerto.

Requiere que la app esté corriendo. En el servidor, con el entorno virtual activo:

    python scripts/probar_websocket.py                 # http://127.0.0.1:18002
    python scripts/probar_websocket.py --puerto 8000

Usa la biblioteca `websockets`, que se instala con `uvicorn[standard]`.
"""
import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request

try:
    import websockets
except ImportError:          # pragma: no cover
    print("Falta la biblioteca 'websockets' (pip install -r requirements.txt).")
    sys.exit(2)


async def esperar(ws, tipo, segundos=5):
    async def leer():
        while True:
            datos = json.loads(await ws.recv())
            if datos.get("tipo") == tipo:
                return datos
    return await asyncio.wait_for(leer(), segundos)


def publicar_prueba(base_http):
    pedido = urllib.request.Request(base_http + "/api/eventos/prueba", method="POST")
    with urllib.request.urlopen(pedido, timeout=5) as r:
        return json.loads(r.read())


async def principal(host, puerto):
    base_ws = f"ws://{host}:{puerto}"
    base_http = f"http://{host}:{puerto}"
    resultados = []

    def anotar(nombre, ok, detalle=""):
        resultados.append(ok)
        print(("OK   " if ok else "FALLA"), nombre, ("- " + detalle) if detalle else "")

    try:
        async with websockets.connect(base_ws + "/ws/ping", open_timeout=5) as ws:
            b = await esperar(ws, "bienvenida")
            await esperar(ws, "latido")
            anotar("/ws/ping: bienvenida y latido del servidor", True, b.get("hora", ""))
            await ws.send("hola")
            eco = await esperar(ws, "eco")
            anotar("/ws/ping: eco del mensaje", eco.get("mensaje") == "hola")
    except Exception as e:
        anotar("/ws/ping", False, f"{type(e).__name__}: {e}")

    try:
        async with websockets.connect(base_ws + "/ws/eventos?codigo=TEST-WS", open_timeout=5) as ws:
            c = await esperar(ws, "conectado")
            anotar("/ws/eventos: conexión", True, f"suscrito a Redis: {c.get('suscrito')}")
            await asyncio.sleep(0.8)              # deja que el receptor se suscriba
            respuesta = await asyncio.get_running_loop().run_in_executor(None, publicar_prueba, base_http)
            anotar("POST /api/eventos/prueba", respuesta.get("ok") is True,
                   f"receptores en Redis: {respuesta.get('receptores')}")
            ev = await esperar(ws, "prueba")
            anotar("evento de Redis recibido por el WebSocket", ev.get("codigo") == "TEST-WS")
    except urllib.error.URLError as e:
        anotar("POST /api/eventos/prueba", False, str(e))
    except Exception as e:
        anotar("/ws/eventos", False, f"{type(e).__name__}: {e}")

    try:
        with urllib.request.urlopen(base_http + "/api/eventos/estado", timeout=5) as r:
            estado = json.loads(r.read())
        anotar("receptor de eventos activo", estado.get("hilo_activo") is True, str(estado))
    except Exception as e:
        anotar("GET /api/eventos/estado", False, str(e))

    return all(resultados)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=18002)
    args = ap.parse_args()
    ok = asyncio.run(principal(args.host, args.puerto))
    print("Todo OK" if ok else "HAY FALLOS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
