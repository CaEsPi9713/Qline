"""HU-009 · diseño de la pantalla de sala: tarjeta principal, otros turnos, estado vacío y privacidad."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.datos_prueba import construir_turno

AHORA = datetime.now(timezone.utc)


class BasePantalla(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)
        self.col = self.db["turnos"]

    def turno(self, codigo, estado, ventanilla=None, seg=30, **kw):
        llamado = AHORA - timedelta(seconds=seg) if estado != "pendiente" else None
        self.col.insert_one(construir_turno(codigo, estado, "normal", AHORA - timedelta(minutes=15), ventanilla, llamado, **kw))


class PruebasDisenoDeLaSala(BasePantalla):
    def test_el_llamado_mas_reciente_es_la_tarjeta_principal(self):
        self.turno("A-007", "llamado", "V-03", seg=10)
        self.turno("A-006", "llamado", "V-02", seg=60)
        self.turno("A-005", "en_atencion", "V-01", seg=200)
        html = self.c.get("/pantalla").text
        principal = html.split('id="sala-principal"')[1].split('id="sala-otros"')[0]
        self.assertIn("Llamando ahora", principal)
        self.assertIn("A-007", principal)
        self.assertIn("V-03", principal)
        self.assertNotIn("A-006", principal)
        otros = html.split('id="sala-otros"')[1].split('class="sala-pie"')[0]
        self.assertIn("A-006", otros)
        self.assertIn("A-005", otros)
        self.assertIn("En atención", otros)

    def test_si_solo_hay_turnos_en_atencion_no_hay_tarjeta_principal(self):
        self.turno("A-005", "en_atencion", "V-01")
        html = self.c.get("/pantalla").text
        self.assertNotIn("Llamando ahora</span>", html.split('id="sala-otros"')[0])
        self.assertIn("Nadie está siendo llamado", html)
        self.assertIn("A-005", html.split('id="sala-otros"')[1])

    def test_estado_vacio(self):
        html = self.c.get("/pantalla").text
        self.assertIn("Sin turnos llamados", html)
        self.assertIn("Sin llamados activos", html)
        self.assertNotIn("Llamando ahora</span>", html.split('id="sala-otros"')[0])

    def test_muestra_cuantos_esperan(self):
        for n in range(1, 6):
            self.turno(f"A-{n:03d}", "pendiente")
        self.turno("A-010", "llamado", "V-01")
        html = self.c.get("/pantalla").text
        self.assertRegex(html, r'id="n-espera">5<')
        self.assertRegex(html, r'id="n-activos">1<')

    def test_la_api_trae_la_cantidad_en_espera(self):
        for n in range(1, 4):
            self.turno(f"A-{n:03d}", "pendiente")
        datos = self.c.get("/api/llamados").json()
        self.assertTrue(datos["ok"])
        self.assertEqual((datos["llamados"], datos["en_espera"]), ([], 3))

    def test_si_mongodb_falla_la_pantalla_responde_sin_la_cantidad(self):
        with mock.patch("app.main.get_db", side_effect=ConnectionError("caído")):
            r = self.c.get("/pantalla")
            datos = self.c.get("/api/llamados").json()
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(datos["en_espera"])
        self.assertIn('id="n-espera">—<', r.text)


class PruebasPrivacidadYSeguridad(BasePantalla):
    def test_no_expone_el_token_del_qr_ni_otros_datos(self):
        token = str(uuid.uuid4())
        self.turno("A-007", "llamado", "V-03", qr_token=token)
        html = self.c.get("/pantalla").text
        api = self.c.get("/api/llamados").text
        for texto in (html, api):
            self.assertNotIn(token, texto)
            self.assertNotIn("qr_token", texto)
            self.assertNotIn("operador", texto.lower().replace("operación", ""))
        self.assertEqual(set(self.c.get("/api/llamados").json()["llamados"][0]), {"codigo", "ventanilla", "estado"})

    def test_el_codigo_se_escapa_en_el_html_del_servidor(self):
        self.col.insert_one({"codigo": "<img src=x onerror=alert(1)>", "servicio": "atencion_general", "estado": "llamado",
                             "ventanilla": "V-01", "timestamps": {"llamado": AHORA}})
        html = self.c.get("/pantalla").text
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img", html)

    def test_el_script_construye_las_tarjetas_con_textcontent(self):
        html = self.c.get("/pantalla").text
        script = html.split("<script>")[1]
        self.assertNotIn("innerHTML", script)
        self.assertIn("textContent", script)

    def test_ofrece_aviso_sonoro_opcional_y_actualizacion_en_vivo(self):
        html = self.c.get("/pantalla").text
        self.assertIn('id="btn-sonido"', html)
        self.assertIn("/ws/eventos", html)
        self.assertIn("/api/llamados", html)

    def test_es_de_solo_lectura(self):
        self.turno("A-007", "llamado", "V-03")
        antes = list(self.col.find({}, {"_id": 0}))
        self.c.get("/pantalla")
        self.c.get("/api/llamados")
        self.assertEqual(list(self.col.find({}, {"_id": 0})), antes)


if __name__ == "__main__":
    unittest.main()
