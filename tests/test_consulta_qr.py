"""HU-013: consulta del turno por QR (UUID v4), con actualización automática.

Requiere fakeredis, mongomock y httpx; si faltan, las pruebas se omiten.
"""

import time
import unittest
import uuid

from tests.test_ventanilla_unica import AHORA, HAY_DEPENDENCIAS, BaseRedisMongo, doc

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient
    from pymongo.errors import PyMongoError
    from redis.exceptions import ConnectionError as RedisConexion

    import app.main as main
    from app import cola, eventos
    from app.consulta_qr import QRError, consultar_por_token, validar_token
    from app.llamado import llamar_siguiente_turno
    from app.tiempo_real import hub

TOKEN_A = str(uuid.uuid4())
TOKEN_B = str(uuid.uuid4())


class BaseQR(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        hub.detener()
        self.c = TestClient(main.app)

    def tearDown(self):
        hub.detener()
        super().tearDown()

    def turno_con_token(self, codigo, token, estado="pendiente", ventanilla=None, prioridad="normal", llegada_ms=None):
        d = doc(codigo, estado, ventanilla, prioridad, llamado=AHORA if estado != "pendiente" else None)
        d["qr_token"] = token
        self.db["turnos"].insert_one(d)
        if estado == "pendiente":
            cola.encolar(codigo, prioridad, llegada_ms or int(codigo.split("-")[1]))


class PruebasValidacionDelToken(BaseQR):
    def test_acepta_uuid_v4_en_cualquier_capitalizacion(self):
        t = str(uuid.uuid4())
        self.assertEqual(validar_token(t), t)
        self.assertEqual(validar_token(t.upper()), t)
        self.assertEqual(validar_token(f"  {t}  "), t)

    def test_rechaza_lo_que_no_es_uuid_v4(self):
        malos = [
            "", "A-001", "no-es-un-uuid", None, 123,
            str(uuid.uuid1()), str(uuid.uuid3(uuid.NAMESPACE_DNS, "x")),       # otras versiones
            "123e4567-e89b-12d3-a456-426614174000",                            # versión 1
            TOKEN_A + "x", TOKEN_A[:-1], TOKEN_A.replace("-", ""),
            "' OR 1=1 --", "../../etc/passwd", "{$ne: null}",
        ]
        for malo in malos:
            with self.subTest(token=malo):
                with self.assertRaises(QRError) as ctx:
                    validar_token(malo)
                self.assertEqual(ctx.exception.status, 400)


class PruebasConsultaPorToken(BaseQR):
    def test_turno_pendiente_muestra_posicion_y_turnos_por_delante(self):
        self.turno_con_token("A-001", TOKEN_A, prioridad="normal")
        self.turno_con_token("A-002", TOKEN_B, prioridad="preferencial")       # va primero
        t = consultar_por_token(self.db, TOKEN_A)
        self.assertEqual((t["codigo"], t["estado"], t["prioridad"]), ("A-001", "pendiente", "normal"))
        self.assertEqual((t["turnos_antes"], t["posicion"]), (1, 2))
        self.assertEqual(t["servicio"], "atencion_general")

    def test_turno_llamado_muestra_ventanilla_y_segundos_restantes(self):
        self.turno_con_token("A-001", TOKEN_A)
        llamar_siguiente_turno(self.db, "V-02")
        t = consultar_por_token(self.db, TOKEN_A)
        self.assertEqual((t["estado"], t["ventanilla"]), ("llamado", "V-02"))
        self.assertTrue(0 < t["segundos_restantes"] <= 180)
        self.assertIsNone(t["posicion"])

    def test_estados_finales_no_se_muestran_como_pendientes(self):
        for i, estado in enumerate(("en_atencion", "atendido", "abandonado"), start=1):
            token = str(uuid.uuid4())
            self.turno_con_token(f"A-{i:03d}", token, estado=estado, ventanilla="V-01")
            t = consultar_por_token(self.db, token)
            self.assertEqual(t["estado"], estado)
            self.assertIsNone(t["posicion"])
            self.assertIsNone(t["turnos_antes"])
            self.assertIsNone(t["segundos_restantes"])

    def test_token_inexistente_da_404(self):
        with self.assertRaises(QRError) as ctx:
            consultar_por_token(self.db, str(uuid.uuid4()))
        self.assertEqual(ctx.exception.status, 404)

    def test_la_respuesta_no_expone_token_ni_id(self):
        self.turno_con_token("A-001", TOKEN_A)
        t = consultar_por_token(self.db, TOKEN_A)
        texto = repr(t)
        self.assertNotIn(TOKEN_A, texto)
        self.assertNotIn("qr_token", texto)
        self.assertNotIn("_id", texto)

    def test_es_de_solo_lectura(self):
        self.turno_con_token("A-001", TOKEN_A)
        antes_doc = self.db["turnos"].find_one({"codigo": "A-001"})
        antes_cola = self.redis.zrange("grupo2:qline:cola:atencion_general", 0, -1, withscores=True)
        antes_claves = sorted(self.redis.keys("*"))
        for _ in range(3):
            consultar_por_token(self.db, TOKEN_A)
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"}), antes_doc)
        self.assertEqual(self.redis.zrange("grupo2:qline:cola:atencion_general", 0, -1, withscores=True), antes_cola)
        self.assertEqual(sorted(self.redis.keys("*")), antes_claves)

    def test_turno_historico_sin_token_no_se_resuelve_por_qr_pero_si_por_codigo(self):
        self.db["turnos"].insert_one(doc("A-009", "atendido", "V-01", llamado=AHORA))     # sin qr_token
        with self.assertRaises(QRError):
            consultar_por_token(self.db, str(uuid.uuid4()))
        from app.consultar import consultar_turno
        self.assertEqual(consultar_turno(self.db, "A-009")["estado"], "atendido")

    def test_dos_turnos_no_se_confunden(self):
        self.turno_con_token("A-001", TOKEN_A)
        self.turno_con_token("A-002", TOKEN_B)
        self.assertEqual(consultar_por_token(self.db, TOKEN_A)["codigo"], "A-001")
        self.assertEqual(consultar_por_token(self.db, TOKEN_B)["codigo"], "A-002")


class PruebasFallosDeMotores(BaseQR):
    def test_redis_caido_no_oculta_el_estado_de_mongodb(self):
        self.turno_con_token("A-001", TOKEN_A)

        def roto(*a, **k):
            raise RedisConexion("caída simulada")

        self.redis.zrank = roto
        t = consultar_por_token(self.db, TOKEN_A)
        self.assertEqual(t["estado"], "pendiente")                  # el estado de MongoDB se muestra
        self.assertIn("posición", t["aviso"])
        self.assertIsNone(t["posicion"])

    def test_redis_caido_con_turno_llamado_muestra_el_estado_sin_segundos(self):
        self.turno_con_token("A-001", TOKEN_A)
        llamar_siguiente_turno(self.db, "V-01")

        def roto(*a, **k):
            raise RedisConexion("caída simulada")

        self.redis.ttl = roto
        t = consultar_por_token(self.db, TOKEN_A)
        self.assertEqual((t["estado"], t["ventanilla"]), ("llamado", "V-01"))
        self.assertIsNone(t["segundos_restantes"])

    def test_mongodb_caido_da_503_distinto_de_redis(self):
        class Roto:
            def __getitem__(s, nombre):
                class C:
                    def find_one(c, *a, **k):
                        raise PyMongoError("caída simulada")
                return C()

        with self.assertRaises(QRError) as ctx:
            consultar_por_token(Roto(), TOKEN_A)
        self.assertEqual(ctx.exception.status, 503)


class PruebasRutas(BaseQR):
    def test_la_pagina_muestra_el_turno_y_es_apta_para_celular(self):
        self.turno_con_token("A-001", TOKEN_A)
        self.turno_con_token("A-002", TOKEN_B)
        r = self.c.get(f"/turno/qr/{TOKEN_B}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("A-002", html)
        self.assertIn("Turnos por delante", html)                    # la posición se destaca con un número grande
        self.assertIn('name="viewport"', html)
        self.assertIn("width=device-width", html)
        self.assertIn("noindex", html)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_la_pagina_publica_no_ofrece_enlaces_internos(self):
        self.turno_con_token("A-001", TOKEN_A)
        html = self.c.get(f"/turno/qr/{TOKEN_A}").text
        for prohibido in ("/panel", "/cola", "/historial", "/dashboard", "coleccion=", "/emitir", "CRUD"):
            self.assertNotIn(prohibido, html.replace(f"/api/turnos/qr/", "").replace("/ws/turno/qr/", ""))

    def test_la_pagina_no_se_rompe_en_cada_estado(self):
        textos = {
            "pendiente": "Su turno está en espera",
            "llamado": "¡Es su turno!",
            "en_atencion": "Está siendo atendido",
            "atendido": "Su atención finalizó",
            "abandonado": "se canceló",
        }
        for i, (estado, texto) in enumerate(textos.items(), start=1):
            token = str(uuid.uuid4())
            self.turno_con_token(f"A-{i:03d}", token, estado=estado, ventanilla="V-01" if estado != "pendiente" else None)
            r = self.c.get(f"/turno/qr/{token}")
            self.assertEqual(r.status_code, 200, estado)
            self.assertIn(texto, r.text, estado)

    def test_uuid_invalido_da_400_con_pagina_controlada(self):
        r = self.c.get("/turno/qr/esto-no-es-un-uuid")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Código QR no válido", r.text)
        self.assertNotIn("Traceback", r.text)

    def test_uuid_inexistente_da_404_con_pagina_controlada(self):
        r = self.c.get(f"/turno/qr/{uuid.uuid4()}")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Turno no encontrado", r.text)

    def test_mongodb_caido_da_503_y_la_pagina_se_reintenta(self):
        original = main.get_db

        class Roto:
            def __getitem__(s, nombre):
                class C:
                    def find_one(c, *a, **k):
                        raise PyMongoError("caída simulada")
                return C()

        main.get_db = lambda: Roto()
        try:
            r = self.c.get(f"/turno/qr/{TOKEN_A}")
        finally:
            main.get_db = original
        self.assertEqual(r.status_code, 503)
        self.assertIn("No podemos consultar su turno ahora", r.text)
        self.assertIn("Se reintentará automáticamente", r.text)

    def test_la_api_json_responde_cada_caso(self):
        self.turno_con_token("A-001", TOKEN_A)
        ok = self.c.get(f"/api/turnos/qr/{TOKEN_A}")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["turno"]["codigo"], "A-001")
        self.assertEqual(self.c.get("/api/turnos/qr/basura").status_code, 400)
        self.assertEqual(self.c.get(f"/api/turnos/qr/{uuid.uuid4()}").status_code, 404)
        self.assertEqual(ok.headers["cache-control"], "no-store")

    def test_la_ruta_del_qr_no_choca_con_la_consulta_por_codigo(self):
        self.turno_con_token("A-001", TOKEN_A)
        self.assertEqual(self.c.get("/turno/A-001").status_code, 200)             # HU-002 sigue funcionando
        self.assertEqual(self.c.get(f"/turno/qr/{TOKEN_A}").status_code, 200)

    def test_la_consulta_no_modifica_nada(self):
        self.turno_con_token("A-001", TOKEN_A)
        antes = self.db["turnos"].find_one({"codigo": "A-001"})
        self.c.get(f"/turno/qr/{TOKEN_A}")
        self.c.get(f"/api/turnos/qr/{TOKEN_A}")
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"}), antes)
        self.assertEqual(cola.tamano_cola(), 1)


class PruebasActualizacionAutomatica(BaseQR):
    def _esperar_hub(self):
        for _ in range(80):
            if hub.suscrito:
                return
            time.sleep(0.05)
        self.fail("el receptor de eventos no se suscribió")

    def test_el_estado_cambia_para_el_cliente_sin_recargar(self):
        """El cliente consulta su JSON tras cada señal: pendiente -> llamado -> en_atencion -> atendido."""
        self.turno_con_token("A-001", TOKEN_A)
        self.assertEqual(self.c.get(f"/api/turnos/qr/{TOKEN_A}").json()["turno"]["estado"], "pendiente")
        llamar_siguiente_turno(self.db, "V-01")
        t = self.c.get(f"/api/turnos/qr/{TOKEN_A}").json()["turno"]
        self.assertEqual((t["estado"], t["ventanilla"]), ("llamado", "V-01"))
        self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertEqual(self.c.get(f"/api/turnos/qr/{TOKEN_A}").json()["turno"]["estado"], "en_atencion")
        self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertEqual(self.c.get(f"/api/turnos/qr/{TOKEN_A}").json()["turno"]["estado"], "atendido")

    def test_la_posicion_mejora_cuando_se_llama_a_otro_turno(self):
        self.turno_con_token("A-001", TOKEN_A)
        self.turno_con_token("A-002", TOKEN_B)
        self.assertEqual(self.c.get(f"/api/turnos/qr/{TOKEN_B}").json()["turno"]["posicion"], 2)
        llamar_siguiente_turno(self.db, "V-01")                       # sale A-001
        self.assertEqual(self.c.get(f"/api/turnos/qr/{TOKEN_B}").json()["turno"]["posicion"], 1)

    def test_el_websocket_envia_una_senal_ante_cualquier_evento_sin_datos_de_otros_turnos(self):
        self.turno_con_token("A-001", TOKEN_A)
        with self.c.websocket_connect(f"/ws/turno/qr/{TOKEN_A}") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "conectado")
            self._esperar_hub()
            eventos.publicar(eventos.TURNO_LLAMADO, codigo="A-777", estado="llamado", ventanilla="V-03")
            senal = ws.receive_json()
            self.assertEqual(senal["tipo"], "actualizar")
            self.assertNotIn("codigo", senal)                          # no se filtra el código de otros turnos
            self.assertNotIn("ventanilla", senal)

    def test_el_websocket_rechaza_un_uuid_invalido_o_inexistente(self):
        for token, status in (("basura", 400), (str(uuid.uuid4()), 404)):
            with self.subTest(token=token):
                with self.c.websocket_connect(f"/ws/turno/qr/{token}") as ws:
                    e = ws.receive_json()
                    self.assertEqual((e["tipo"], e["status"]), ("error", status))

    def test_cada_cliente_recibe_la_senal_y_se_libera_al_cerrar(self):
        self.turno_con_token("A-001", TOKEN_A)
        with self.c.websocket_connect(f"/ws/turno/qr/{TOKEN_A}") as ws1, \
                self.c.websocket_connect(f"/ws/turno/qr/{TOKEN_A}") as ws2:
            ws1.receive_json(), ws2.receive_json()
            self._esperar_hub()
            eventos.publicar(eventos.TURNO_EMITIDO, codigo="A-002")
            self.assertEqual(ws1.receive_json()["tipo"], "actualizar")
            self.assertEqual(ws2.receive_json()["tipo"], "actualizar")
        for _ in range(40):
            if hub.estado()["clientes"] == 0:
                break
            time.sleep(0.05)
        self.assertEqual(hub.estado()["clientes"], 0)


class PruebasMovil(BaseQR):
    """La página se adapta al celular: viewport, diseño de una columna y respaldo si no hay WebSocket."""

    def test_el_css_incluye_la_vista_publica_adaptable(self):
        css = self.c.get("/static/style.css").text
        self.assertIn(".publico-cuerpo", css)
        self.assertIn("max-width: 520px", css)
        self.assertIn("@media (max-width: 380px)", css)

    def test_la_pagina_incluye_el_respaldo_por_consulta_periodica(self):
        self.turno_con_token("A-001", TOKEN_A)
        html = self.c.get(f"/turno/qr/{TOKEN_A}").text
        self.assertIn("PERIODO_RESPALDO_MS", html)
        self.assertIn("/ws/turno/qr/", html)
        self.assertIn("/api/turnos/qr/", html)

    def test_el_enlace_del_qr_respeta_base_path(self):
        self.turno_con_token("A-001", TOKEN_A)
        original, main.BASE = main.BASE, "/proyecto/qline"
        try:
            html = self.c.get(f"/turno/qr/{TOKEN_A}").text
        finally:
            main.BASE = original
        self.assertIn('href="/proyecto/qline/static/style.css', html)
        self.assertIn('var BASE = "/proyecto/qline"', html)


if __name__ == "__main__":
    unittest.main()
