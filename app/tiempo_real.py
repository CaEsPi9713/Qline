"""
Distribución de eventos en vivo por WebSocket (TT-013, lado recepción).

Un hilo por proceso se suscribe al canal Redis `grupo2:qline:eventos` y reparte
cada mensaje a los clientes WebSocket conectados a ese proceso. Si la app corre
con varios procesos (gunicorn), cada uno tiene su hilo y su Pub/Sub entrega el
mensaje a todos.

El hilo arranca la primera vez que se conecta un cliente (no al importar el
módulo) y se reconecta solo si Redis se cae. Los clientes que no responden se
descartan sin afectar a los demás.
"""
import asyncio
import json
import logging
import threading

from redis.exceptions import RedisError

from app.constantes import CLAVE_EVENTOS
from app.redis_client import get_redis

log = logging.getLogger("qline.tiempo_real")

ESPERA_REINTENTO_SEG = 2.0
LIMITE_COLA_CLIENTE = 100
ESPERA_LECTURA_SEG = 0.5      # cada cuánto el hilo comprueba si debe detenerse


class Cliente:
    """
    Una conexión WebSocket: su cola de eventos y su filtro opcional por código.

    Con `anonimo=True` el cliente recibe una señal `{"tipo": "actualizar"}` por
    CUALQUIER evento, sin código ni datos de otros turnos. Lo usa la consulta por
    QR: la posición en la fila cambia cuando se llama a otros turnos, pero el
    cliente no debe enterarse de cuáles son.
    """

    def __init__(self, loop, codigo: str = None, anonimo: bool = False):
        self.loop = loop
        self.codigo = codigo
        self.anonimo = anonimo
        self.cola = asyncio.Queue(maxsize=LIMITE_COLA_CLIENTE)

    def acepta(self, evento: dict) -> bool:
        return self.anonimo or self.codigo is None or evento.get("codigo") == self.codigo

    def _encolar(self, evento: dict) -> None:
        if self.cola.full():          # cliente lento: se descarta lo más antiguo
            try:
                self.cola.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.cola.put_nowait(evento)

    def entregar(self, evento: dict) -> None:
        """Llamado desde el hilo de Redis: entrega el evento en el bucle del cliente."""
        if self.anonimo:
            evento = {"tipo": "actualizar", "ts": evento.get("ts")}
        try:
            self.loop.call_soon_threadsafe(self._encolar, evento)
        except RuntimeError:          # el bucle ya se cerró
            pass


class Hub:
    def __init__(self):
        self._clientes = set()
        self._candado = threading.Lock()
        self._hilo = None
        self._parar = threading.Event()
        self.suscrito = False         # True mientras el Pub/Sub de Redis está activo
        self.recibidos = 0

    # --- ciclo de vida -------------------------------------------------------
    def asegurar_iniciado(self) -> None:
        with self._candado:
            if self._hilo is not None and self._hilo.is_alive():
                return
            self._parar.clear()
            self._hilo = threading.Thread(target=self._escuchar, name="qline-eventos", daemon=True)
            self._hilo.start()

    def detener(self, espera: float = 3.0) -> None:
        self._parar.set()
        hilo = self._hilo
        if hilo is not None and hilo.is_alive():
            hilo.join(espera)
        self._hilo = None
        self.suscrito = False
        with self._candado:
            self._clientes.clear()

    # --- clientes ------------------------------------------------------------
    def registrar(self, loop, codigo: str = None, anonimo: bool = False) -> Cliente:
        cliente = Cliente(loop, codigo, anonimo)
        with self._candado:
            self._clientes.add(cliente)
        self.asegurar_iniciado()
        return cliente

    def quitar(self, cliente: Cliente) -> None:
        with self._candado:
            self._clientes.discard(cliente)

    def estado(self) -> dict:
        with self._candado:
            clientes = len(self._clientes)
        return {"suscrito": self.suscrito, "clientes": clientes, "eventos_recibidos": self.recibidos,
                "hilo_activo": bool(self._hilo and self._hilo.is_alive())}

    # --- hilo de Redis -------------------------------------------------------
    def _repartir(self, mensaje: str) -> None:
        try:
            evento = json.loads(mensaje)
        except (TypeError, ValueError):
            return
        if not isinstance(evento, dict):
            return
        self.recibidos += 1
        with self._candado:
            clientes = list(self._clientes)
        for cliente in clientes:
            if cliente.acepta(evento):
                cliente.entregar(evento)

    def _escuchar(self) -> None:
        while not self._parar.is_set():
            pubsub = None
            try:
                pubsub = get_redis().pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(CLAVE_EVENTOS)
                self.suscrito = True
                while not self._parar.is_set():
                    msg = pubsub.get_message(timeout=ESPERA_LECTURA_SEG)
                    if msg and msg.get("type") == "message":
                        self._repartir(msg.get("data"))
            except RedisError as e:
                log.warning("Pub/Sub de Redis no disponible, se reintenta: %s", e)
            finally:
                self.suscrito = False
                if pubsub is not None:
                    try:
                        pubsub.close()
                    except Exception:
                        pass
            self._parar.wait(ESPERA_REINTENTO_SEG)


hub = Hub()
