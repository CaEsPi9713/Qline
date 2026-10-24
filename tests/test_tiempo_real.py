"""TT-013 (lado backend): publicación de eventos y distribución por WebSocket.

Requiere fakeredis y httpx; si faltan, las pruebas se omiten.
"""

import asyncio
import json
import time
import unittest

try:
    import fakeredis
    from fastapi.testclient import TestClient
    from redis.exceptions import ConnectionError as RedisConexion

    import app.main as main
    import app.redis_client as redis_client
    from app import eventos
    from app.constantes import CLAVE_EVENTOS
    from app.tiempo_real import Hub, hub
    HAY_DEPENDENCIAS = True
except Exception:
    HAY_DEPENDENCIAS = False


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis o httpx (pip install -r requirements-dev.txt)")
class BaseEventos(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self._cliente_orig = redis_client._client
        redis_client._client = self.redis
        hub.detener()

    def tearDown(self):
        hub.detener()
        redis_client._client = self._cliente_orig


class PruebasPublicacion(BaseEventos):
    def test_el_canal_usa_el_namespace_oficial(self):
        self.assertEqual(CLAVE_EVENTOS, "grupo2:qline:eventos")

    def test_el_evento_tiene_el_formato_acordado_y_omite_los_campos_vacios(self):
        e = eventos.construir_evento(eventos.TURNO_LLAMADO, codigo="A-001", estado="llamado",
                                     ventanilla="V-01", prioridad="normal")
        self.assertEqual(set(e), {"tipo", "ts", "codigo", "estado", "ventanilla", "prioridad"})
        self.assertTrue(e["ts"].endswith("Z"))
        minimo = eventos.construir_evento(eventos.TURNO_EMITIDO, codigo="A-002")
        self.assertEqual(set(minimo), {"tipo", "ts", "codigo"})

    def test_tipo_desconocido_se_rechaza(self):
        with self.assertRaises(ValueError):
            eventos.publicar("inventado", codigo="A-001")

    def test_publicar_devuelve_los_receptores(self):
        self.assertEqual(eventos.publicar(eventos.PRUEBA, codigo="X-001"), 0)   # nadie suscrito

    def test_un_fallo_de_redis_no_rompe_la_operacion(self):
        def roto(*a, **k):
            raise RedisConexion("caída simulada")
        self.redis.publish = roto
        self.assertIsNone(eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-001"))

    def test_el_mensaje_no_lleva_datos_personales(self):
        e = eventos.construir_evento(eventos.ATENCION_INICIADA, codigo="A-001", estado="en_atencion",
                                     ventanilla="V-02", prioridad="preferencial")
        self.assertTrue(set(e) <= {"tipo", "ts", "codigo", "estado", "ventanilla", "prioridad"})


class PruebasHub(BaseEventos):
    def _esperar_suscripcion(self, h):
        for _ in range(60):
            if h.suscrito:
                return
            time.sleep(0.05)
        self.fail("el receptor no se suscribió a tiempo")

    def test_un_cliente_recibe_los_eventos_publicados(self):
        async def caso():
            h = Hub()
            cliente = h.registrar(asyncio.get_running_loop())
            await asyncio.get_running_loop().run_in_executor(None, self._esperar_suscripcion, h)
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-001", ventanilla="V-01")
            e = await asyncio.wait_for(cliente.cola.get(), 3)
            h.detener()
            return e
        e = asyncio.run(caso())
        self.assertEqual((e["tipo"], e["codigo"], e["ventanilla"]), ("turno_llamado", "A-001", "V-01"))

    def test_el_filtro_por_codigo_solo_entrega_ese_turno(self):
        async def caso():
            h = Hub()
            solo_a1 = h.registrar(asyncio.get_running_loop(), "A-001")
            todos = h.registrar(asyncio.get_running_loop())
            await asyncio.get_running_loop().run_in_executor(None, self._esperar_suscripcion, h)
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-002")
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-001")
            primero = await asyncio.wait_for(solo_a1.cola.get(), 3)
            a_todos = [await asyncio.wait_for(todos.cola.get(), 3) for _ in range(2)]
            vacia = solo_a1.cola.empty()
            h.detener()
            return primero, a_todos, vacia
        primero, a_todos, vacia = asyncio.run(caso())
        self.assertEqual(primero["codigo"], "A-001")
        self.assertEqual([e["codigo"] for e in a_todos], ["A-002", "A-001"])
        self.assertTrue(vacia)

    def test_los_mensajes_invalidos_se_ignoran(self):
        h = Hub()
        h._repartir("no es json")
        h._repartir("[1, 2]")
        h._repartir(None)
        self.assertEqual(h.recibidos, 0)

    def test_un_cliente_lento_no_bloquea_ni_acumula_sin_limite(self):
        async def caso():
            h = Hub()
            cliente = h.registrar(asyncio.get_running_loop())
            for i in range(150):
                cliente._encolar({"tipo": "prueba", "n": i})
            n = cliente.cola.qsize()
            h.detener()
            return n, cliente.cola.get_nowait()
        n, primero = asyncio.run(caso())
        self.assertEqual(n, 100)
        self.assertEqual(primero["n"], 50)                           # se descartaron los más antiguos

    def test_el_hub_se_recupera_si_redis_falla_al_suscribirse(self):
        h = Hub()
        h._parar.clear()
        llamadas = {"n": 0}
        original = self.redis.pubsub

        def inestable(*a, **k):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                raise RedisConexion("caída simulada")
            return original(*a, **k)

        self.redis.pubsub = inestable
        import app.tiempo_real as tr
        espera_original, tr.ESPERA_REINTENTO_SEG = tr.ESPERA_REINTENTO_SEG, 0.1
        try:
            h.asegurar_iniciado()
            self._esperar_suscripcion(h)
        finally:
            tr.ESPERA_REINTENTO_SEG = espera_original
            h.detener()
        self.assertGreaterEqual(llamadas["n"], 2)


class PruebasWebSocket(BaseEventos):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)

    def test_ws_ping_envia_bienvenida_latido_y_eco(self):
        with self.c.websocket_connect("/ws/ping") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "bienvenida")
            self.assertEqual(ws.receive_json()["tipo"], "latido")
            ws.send_text("hola")
            eco = ws.receive_json()
            self.assertEqual((eco["tipo"], eco["mensaje"]), ("eco", "hola"))

    def test_ws_eventos_entrega_un_evento_publicado(self):
        with self.c.websocket_connect("/ws/eventos") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "conectado")
            for _ in range(60):                                      # espera a que el receptor se suscriba
                if hub.suscrito:
                    break
                time.sleep(0.05)
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-001", ventanilla="V-01", prioridad="normal")
            e = ws.receive_json()
            self.assertEqual((e["tipo"], e["codigo"], e["ventanilla"]), ("turno_llamado", "A-001", "V-01"))

    def test_ws_eventos_con_filtro_ignora_otros_turnos(self):
        with self.c.websocket_connect("/ws/eventos?codigo=A-005") as ws:
            self.assertEqual(ws.receive_json()["codigo"], "A-005")
            for _ in range(60):
                if hub.suscrito:
                    break
                time.sleep(0.05)
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-006")
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-005")
            self.assertEqual(ws.receive_json()["codigo"], "A-005")

    def test_ws_eventos_acepta_el_codigo_del_evento_de_prueba(self):
        """La página /ws-prueba filtra por TEST-WS: el filtro no debe limitarse al formato A-NNN."""
        with self.c.websocket_connect("/ws/eventos?codigo=TEST-WS") as ws:
            self.assertEqual(ws.receive_json()["codigo"], "TEST-WS")
            for _ in range(60):
                if hub.suscrito:
                    break
                time.sleep(0.05)
            self.c.post("/api/eventos/prueba")
            self.assertEqual(ws.receive_json()["tipo"], "prueba")

    def test_ws_eventos_rechaza_un_codigo_invalido(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.c.websocket_connect("/ws/eventos?codigo=basura") as ws:
                ws.receive_json()

    def test_al_desconectarse_el_cliente_se_libera(self):
        with self.c.websocket_connect("/ws/eventos") as ws:
            ws.receive_json()
            self.assertEqual(hub.estado()["clientes"], 1)
        for _ in range(40):
            if hub.estado()["clientes"] == 0:
                break
            time.sleep(0.05)
        self.assertEqual(hub.estado()["clientes"], 0)

    def test_evento_de_prueba_por_la_api(self):
        r = self.c.post("/api/eventos/prueba")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["codigo"], "TEST-WS")

    def test_evento_de_prueba_con_redis_caido_responde_503(self):
        def roto(*a, **k):
            raise RedisConexion("caída simulada")
        self.redis.publish = roto
        r = self.c.post("/api/eventos/prueba")
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.json()["ok"])

    def test_estado_del_receptor(self):
        r = self.c.get("/api/eventos/estado").json()
        self.assertTrue(r["ok"])
        self.assertEqual(set(r) - {"ok"}, {"suscrito", "clientes", "eventos_recibidos", "hilo_activo"})

    def test_la_pagina_de_prueba_carga_sin_navegacion_de_paso(self):
        html = self.c.get("/ws-prueba").text
        self.assertIn("Prueba de tiempo real", html)
        self.assertIn("/ws/ping", html)
        self.assertIn("/ws/eventos", html)


if __name__ == "__main__":
    unittest.main()
