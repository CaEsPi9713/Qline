"""Fase 4 de TT-013: cada transición de negocio publica su evento en vivo, y solo si tuvo éxito.

Requiere fakeredis, mongomock y httpx; si faltan, las pruebas se omiten.
"""

import json
import time
import unittest
import uuid

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient
    from redis.exceptions import ConnectionError as RedisConexion

    import app.main as main
    from app import cola, eventos
    from app.constantes import CLAVE_EVENTOS
    from app.llamado import llamar_siguiente_turno
    from app.tiempo_real import hub

PERMITIDOS = {"tipo", "ts", "codigo", "estado", "ventanilla", "prioridad"}


class BaseNegocio(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        hub.detener()
        self.c = TestClient(main.app)
        self.suscriptor = self.redis.pubsub(ignore_subscribe_messages=True)
        self.suscriptor.subscribe(CLAVE_EVENTOS)
        self.suscriptor.get_message(timeout=0.05)

    def tearDown(self):
        self.suscriptor.close()
        hub.detener()
        super().tearDown()

    def recibidos(self):
        """Eventos publicados desde la última lectura."""
        salida = []
        while True:
            m = self.suscriptor.get_message(timeout=0.05)
            if m is None:
                return salida
            if m.get("type") == "message":
                salida.append(json.loads(m["data"]))

    def emitir(self, prioridad="normal"):
        r = self.c.post("/api/turnos/emitir", data={"prioridad": prioridad})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["turno"]["codigo"]


class PruebasEventosPorTransicion(BaseNegocio):
    def test_emitir_por_la_api_publica_turno_emitido(self):
        codigo = self.emitir("preferencial")
        (e,) = self.recibidos()
        self.assertEqual((e["tipo"], e["codigo"], e["estado"], e["prioridad"]),
                         ("turno_emitido", codigo, "pendiente", "preferencial"))

    def test_emitir_por_el_formulario_web_tambien_lo_publica(self):
        r = self.c.post("/emitir", data={"prioridad": "normal"})
        self.assertEqual(r.status_code, 200)
        (e,) = self.recibidos()
        self.assertEqual((e["tipo"], e["estado"]), ("turno_emitido", "pendiente"))

    def test_una_emision_rechazada_no_publica_nada(self):
        r = self.c.post("/api/turnos/emitir", data={"prioridad": "urgente"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.recibidos(), [])

    def test_llamar_publica_turno_llamado_con_ventanilla_y_prioridad(self):
        self.emitir("preferencial")
        self.recibidos()
        r = self.c.post("/api/llamar", data={"ventanilla": "V-02"})
        self.assertEqual(r.status_code, 200)
        (e,) = self.recibidos()
        self.assertEqual((e["tipo"], e["estado"], e["ventanilla"], e["prioridad"]),
                         ("turno_llamado", "llamado", "V-02", "preferencial"))

    def test_llamar_desde_el_formulario_de_cola_publica_un_solo_evento(self):
        self.emitir()
        self.recibidos()
        self.c.post("/cola/llamar", data={"ventanilla": "V-01"}, follow_redirects=False)
        self.assertEqual([e["tipo"] for e in self.recibidos()], ["turno_llamado"])

    def test_llamar_con_la_cola_vacia_no_publica(self):
        self.assertIsNone(llamar_siguiente_turno(self.db, "V-01")["codigo"])
        self.assertEqual(self.recibidos(), [])

    def test_una_llamada_rechazada_por_ventanilla_ocupada_no_publica(self):
        self.emitir()
        self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.recibidos()
        r = self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.recibidos(), [])

    def test_iniciar_publica_atencion_iniciada(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.recibidos()
        r = self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 200)
        (e,) = self.recibidos()
        self.assertEqual((e["tipo"], e["codigo"], e["estado"], e["ventanilla"]),
                         ("atencion_iniciada", codigo, "en_atencion", "V-01"))

    def test_iniciar_desde_el_panel_tambien_publica(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.recibidos()
        self.c.post("/panel/iniciar", data={"codigo": codigo, "ventanilla": "V-01"}, follow_redirects=False)
        self.assertEqual([e["tipo"] for e in self.recibidos()], ["atencion_iniciada"])

    def test_un_inicio_rechazado_no_publica(self):
        codigo = self.emitir()                                       # sigue pendiente: no se puede iniciar
        self.recibidos()
        r = self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.recibidos(), [])

    def test_finalizar_publica_atencion_finalizada(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.recibidos()
        r = self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 200)
        (e,) = self.recibidos()
        self.assertEqual((e["tipo"], e["codigo"], e["estado"], e["ventanilla"]),
                         ("atencion_finalizada", codigo, "atendido", "V-01"))

    def test_finalizar_desde_el_panel_tambien_publica(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.recibidos()
        self.c.post("/panel/finalizar", data={"codigo": codigo, "ventanilla": "V-01"}, follow_redirects=False)
        self.assertEqual([e["tipo"] for e in self.recibidos()], ["atencion_finalizada"])

    def test_un_fin_rechazado_no_publica(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})            # llamado, nunca inició
        self.recibidos()
        r = self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.recibidos(), [])

    def test_el_flujo_completo_publica_los_eventos_en_orden(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-03"})
        self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-03"})
        self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": "V-03"})
        recibidos = self.recibidos()
        self.assertEqual([e["tipo"] for e in recibidos],
                         ["turno_emitido", "turno_llamado", "atencion_iniciada", "atencion_finalizada"])
        self.assertEqual({e["codigo"] for e in recibidos}, {codigo})
        self.assertEqual([e["estado"] for e in recibidos], ["pendiente", "llamado", "en_atencion", "atendido"])

    def test_ningun_evento_lleva_datos_personales(self):
        codigo = self.emitir()
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": "V-01"})
        for e in self.recibidos():
            self.assertTrue(set(e) <= PERMITIDOS, e)


class PruebasRedisCaidoAlPublicar(BaseNegocio):
    """Si el aviso en vivo falla, la operación de negocio no se deshace ni se rompe."""

    def romper_publicacion(self):
        def roto(*a, **k):
            raise RedisConexion("caída simulada")
        self.redis.publish = roto

    def test_el_flujo_completo_funciona_aunque_no_se_pueda_publicar(self):
        self.romper_publicacion()
        codigo = self.emitir()
        self.assertEqual(self.c.post("/api/llamar", data={"ventanilla": "V-01"}).status_code, 200)
        self.assertEqual(self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"}).status_code, 200)
        r = self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.db["turnos"].find_one({"codigo": codigo})["estado"], "atendido")

    def test_los_formularios_web_tambien_funcionan(self):
        self.romper_publicacion()
        self.assertEqual(self.c.post("/emitir", data={"prioridad": "normal"}).status_code, 200)
        r = self.c.post("/cola/llamar", data={"ventanilla": "V-01"}, follow_redirects=False)
        self.assertIn("msg=", r.headers["location"])


class PruebasActualizacionAlInstante(BaseNegocio):
    """La consulta por QR recibe la señal en cuanto cambia el turno, sin esperar la consulta de seguridad."""

    def _esperar_hub(self):
        for _ in range(80):
            if hub.suscrito:
                return
            time.sleep(0.05)
        self.fail("el receptor de eventos no se suscribió")

    def _turno_con_token(self):
        codigo = self.emitir()
        token = str(uuid.uuid4())
        self.db["turnos"].update_one({"codigo": codigo}, {"$set": {"qr_token": token}})
        return codigo, token

    def test_la_pagina_del_qr_recibe_una_senal_en_cada_transicion(self):
        codigo, token = self._turno_con_token()
        with self.c.websocket_connect(f"/ws/turno/qr/{token}") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "conectado")
            self._esperar_hub()
            self.c.post("/api/llamar", data={"ventanilla": "V-01"})
            self.assertEqual(ws.receive_json()["tipo"], "actualizar")
            self.assertEqual(self.c.get(f"/api/turnos/qr/{token}").json()["turno"]["estado"], "llamado")
            self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": "V-01"})
            self.assertEqual(ws.receive_json()["tipo"], "actualizar")
            self.assertEqual(self.c.get(f"/api/turnos/qr/{token}").json()["turno"]["estado"], "en_atencion")
            self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": "V-01"})
            self.assertEqual(ws.receive_json()["tipo"], "actualizar")
            self.assertEqual(self.c.get(f"/api/turnos/qr/{token}").json()["turno"]["estado"], "atendido")

    def test_la_posicion_se_actualiza_cuando_otro_turno_es_llamado(self):
        self.emitir()                                               # A-001, delante
        _, token = self._turno_con_token()                          # A-002
        self.assertEqual(self.c.get(f"/api/turnos/qr/{token}").json()["turno"]["posicion"], 2)
        with self.c.websocket_connect(f"/ws/turno/qr/{token}") as ws:
            ws.receive_json()
            self._esperar_hub()
            self.c.post("/api/llamar", data={"ventanilla": "V-01"})   # sale A-001
            senal = ws.receive_json()
            self.assertEqual(senal["tipo"], "actualizar")
            self.assertNotIn("codigo", senal)                       # no se filtra el turno ajeno
            self.assertEqual(self.c.get(f"/api/turnos/qr/{token}").json()["turno"]["posicion"], 1)

    def test_el_filtro_por_codigo_solo_entrega_los_eventos_de_ese_turno(self):
        a = self.emitir()
        b = self.emitir()
        with self.c.websocket_connect(f"/ws/eventos?codigo={b}") as ws:
            ws.receive_json()
            self._esperar_hub()
            self.c.post("/api/llamar", data={"ventanilla": "V-01"})   # llama a A (el primero)
            self.c.post("/api/llamar", data={"ventanilla": "V-02"})   # llama a B
            e = ws.receive_json()
            self.assertEqual((e["tipo"], e["codigo"]), ("turno_llamado", b))
            self.assertNotEqual(e["codigo"], a)


if __name__ == "__main__":
    unittest.main()
