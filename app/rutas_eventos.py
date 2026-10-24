"""
Rutas de tiempo real (TT-013): WebSocket de eventos y verificación del canal.

- GET  /ws/ping              WebSocket de prueba: bienvenida, latido y eco. Sirve para
                             comprobar si el WebSocket atraviesa el proxy (Apache).
- GET  /ws/eventos           WebSocket con los eventos de los turnos (opcional ?codigo=A-001).
- GET  /ws/turno/qr/{uuid}   WebSocket de la consulta por QR: solo señales `actualizar` (HU-013).
- POST /api/eventos/prueba   Publica un evento de prueba en el canal.
- GET  /api/eventos/estado   Estado del receptor de eventos (para diagnóstico).

Si el WebSocket no estuviera disponible, las páginas siguen funcionando con
consultas periódicas a su propia API JSON.
"""
import asyncio
import re
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app import consulta_qr, eventos
from app.tiempo_real import hub


LATIDO_SEG = 25          # mantiene viva la conexión a través de proxies
PATRON_CODIGO = re.compile(r"[A-Z0-9]{1,12}-[A-Z0-9]{1,12}\Z")   # A-001, S-001 y el TEST-WS de la prueba
CODIGO_PRUEBA = "TEST-WS"


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def ws_ping(ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_json({"tipo": "bienvenida", "hora": _ahora()})
        await asyncio.sleep(1)
        await ws.send_json({"tipo": "latido", "hora": _ahora()})
        while True:
            texto = await ws.receive_text()
            await ws.send_json({"tipo": "eco", "mensaje": texto[:200]})
    except (WebSocketDisconnect, RuntimeError):
        pass


async def _servir(ws: WebSocket, cliente, saludo: dict) -> None:
    """Envía al navegador los eventos del cliente hasta que se desconecte. Cierra el registro al terminar."""
    recibir = asyncio.create_task(ws.receive_text())      # detecta la desconexión del cliente
    obtener = None
    try:
        await ws.send_json(saludo)
        while True:
            if obtener is None:
                obtener = asyncio.create_task(cliente.cola.get())
            hechas, _ = await asyncio.wait({recibir, obtener}, timeout=LATIDO_SEG,
                                           return_when=asyncio.FIRST_COMPLETED)
            if recibir in hechas:
                recibir.result()                           # lanza WebSocketDisconnect si se fue
                recibir = asyncio.create_task(ws.receive_text())   # texto del cliente: se ignora
            if obtener in hechas:
                await ws.send_json(obtener.result())
                obtener = None
            elif not hechas:
                await ws.send_json({"tipo": "latido", "hora": _ahora()})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.quitar(cliente)
        for tarea in (recibir, obtener):
            if tarea is not None and not tarea.done():
                tarea.cancel()


async def ws_eventos(ws: WebSocket, codigo: str = None):
    if codigo is not None and not PATRON_CODIGO.fullmatch(codigo.strip().upper()):
        await ws.close(code=1008)          # política: filtro de código inválido
        return
    await ws.accept()
    cliente = hub.registrar(asyncio.get_running_loop(), codigo.strip().upper() if codigo else None)
    await _servir(ws, cliente, {"tipo": "conectado", "suscrito": hub.suscrito,
                                "codigo": cliente.codigo, "hora": _ahora()})


def crear_ws_turno_qr(get_db):
    """
    WebSocket de la consulta por QR (HU-013). Valida el UUID y que exista el turno
    antes de suscribir; si no, envía el motivo y cierra. Solo envía señales
    `actualizar` (sin códigos de otros turnos): la página vuelve a consultar su
    propio estado con /api/turnos/qr/{uuid}.
    """
    async def ws_turno_qr(ws: WebSocket, token: str):
        await ws.accept()
        try:
            await run_in_threadpool(consulta_qr.consultar_por_token, get_db(), token)
        except consulta_qr.QRError as e:
            await ws.send_json({"tipo": "error", "error": str(e), "status": e.status})
            await ws.close(code=1008)
            return
        cliente = hub.registrar(asyncio.get_running_loop(), anonimo=True)
        await _servir(ws, cliente, {"tipo": "conectado", "suscrito": hub.suscrito, "hora": _ahora()})
    return ws_turno_qr


def api_evento_de_prueba():
    """Publica un evento de prueba; devuelve cuántos receptores (procesos suscritos) lo recibieron."""
    receptores = eventos.publicar(eventos.PRUEBA, codigo=CODIGO_PRUEBA, estado="prueba")
    if receptores is None:
        return JSONResponse({"ok": False, "error": "Redis no disponible: no se pudo publicar."}, status_code=503)
    return {"ok": True, "receptores": receptores, "codigo": CODIGO_PRUEBA}


def api_eventos_estado():
    return {"ok": True, **hub.estado()}


def registrar(app: FastAPI, get_db=None) -> None:
    """
    Registra las rutas directamente sobre la app (sin APIRouter): así `app.routes`
    sigue siendo una lista plana de rutas con `path`, como espera el resto del proyecto.
    """
    app.add_api_websocket_route("/ws/ping", ws_ping)
    app.add_api_websocket_route("/ws/eventos", ws_eventos)
    if get_db is not None:
        app.add_api_websocket_route("/ws/turno/qr/{token}", crear_ws_turno_qr(get_db))
    app.add_api_route("/api/eventos/prueba", api_evento_de_prueba, methods=["POST"])
    app.add_api_route("/api/eventos/estado", api_eventos_estado, methods=["GET"])
