"""Fechas y horas legibles en las pantallas (app/formato.py); las APIs y descargas siguen en ISO 8601 UTC."""
import os
import re
import unittest
from datetime import datetime, timezone
from unittest import mock

from app import formato
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.datos_prueba import construir_turno

CR = {"ZONA_HORARIA": "America/Costa_Rica"}


class PruebasFormato(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, CR)
        p.start()
        self.addCleanup(p.stop)

    def test_convierte_de_utc_a_hora_local_con_formato_de_lectura(self):
        v = "2026-10-27T01:12:49.757000"                       # el formato que mostraban las pantallas
        self.assertEqual(formato.fecha_hora(v), "26/10/2026 19:12:49")
        self.assertEqual((formato.fecha(v), formato.hora(v), formato.hora(v, segundos=False)), ("26/10/2026", "19:12:49", "19:12"))

    def test_acepta_texto_con_z_con_desplazamiento_datetime_y_sin_zona(self):
        esperado = "26/10/2026 19:12:49"
        self.assertEqual(formato.fecha_hora("2026-10-27T01:12:49Z"), esperado)
        self.assertEqual(formato.fecha_hora("2026-10-27T01:12:49+00:00"), esperado)
        self.assertEqual(formato.fecha_hora("2026-10-27T03:12:49+02:00"), esperado)
        self.assertEqual(formato.fecha_hora(datetime(2026, 10, 27, 1, 12, 49)), esperado)
        self.assertEqual(formato.fecha_hora(datetime(2026, 10, 27, 1, 12, 49, tzinfo=timezone.utc)), esperado)

    def test_cambia_el_dia_cuando_la_hora_local_es_anterior_a_medianoche_utc(self):
        self.assertEqual(formato.fecha("2026-10-27T03:00:00Z"), "26/10/2026")
        self.assertEqual(formato.fecha("2026-10-27T06:00:00Z"), "27/10/2026")

    def test_sin_valor_o_con_texto_raro_no_rompe_la_pantalla(self):
        self.assertEqual((formato.fecha_hora(None), formato.fecha(""), formato.hora(None)), ("-", "-", "-"))
        self.assertEqual(formato.fecha_hora("ayer por la tarde"), "ayer por la tarde")
        self.assertEqual(formato.iso_utc("ayer"), "")

    def test_iso_utc_conserva_el_valor_exacto(self):
        self.assertEqual(formato.iso_utc("2026-10-27T01:12:49.757000"), "2026-10-27T01:12:49.757Z")
        self.assertEqual(formato.iso_utc("2026-10-27T03:12:49+02:00"), "2026-10-27T01:12:49.000Z")

    def test_la_zona_se_elige_con_zona_horaria(self):
        with mock.patch.dict(os.environ, {"ZONA_HORARIA": "UTC"}):
            self.assertEqual(formato.fecha_hora("2026-10-27T01:12:49Z"), "27/10/2026 01:12:49")
        with mock.patch.dict(os.environ, {"ZONA_HORARIA": "Europe/Madrid"}):
            self.assertEqual(formato.hora("2026-10-27T01:12:49Z"), "02:12:49")

    def test_una_zona_invalida_cae_a_utc_y_lo_dice(self):
        with mock.patch.dict(os.environ, {"ZONA_HORARIA": "Mundo/Inventado"}):
            self.assertEqual(formato.fecha_hora("2026-10-27T01:12:49Z"), "27/10/2026 01:12:49")
            self.assertEqual(formato.etiqueta_zona(), "UTC")

    def test_etiqueta_de_la_zona(self):
        self.assertEqual(formato.etiqueta_zona(), "hora de Costa Rica (UTC−6)")


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasPantallas(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {**CR, "PUBLIC_BASE_URL": "https://grupo2.crnube.net", "BASE_PATH": ""})
        p.start()
        self.addCleanup(p.stop)
        self.c = TestClient(main.app)
        self.col = self.db["turnos"]
        self.creado = datetime(2026, 10, 27, 1, 12, 49, 757000)          # sin zona, como lo entrega PyMongo
        self.col.insert_one(construir_turno("A-001", "atendido", "normal", self.creado, "V-01",
                                            datetime(2026, 10, 27, 1, 15, 0), inicio=datetime(2026, 10, 27, 1, 15, 30),
                                            finalizado=datetime(2026, 10, 27, 1, 19, 0)))
        self.col.insert_one(construir_turno("A-002", "abandonado", "normal", self.creado, "V-02",
                                            datetime(2026, 10, 27, 1, 16, 0)))

    def test_el_historial_muestra_fecha_y_hora_locales_y_conserva_el_utc_en_el_detalle(self):
        html = self.c.get("/historial").text
        self.assertIn("26/10/2026", html)
        self.assertIn("19:12:49", html)
        self.assertIn('title="2026-10-27T01:12:49.757Z (UTC)"', html)
        self.assertIn('datetime="2026-10-27T01:12:49.757Z"', html)
        self.assertNotIn("2026-10-27T01:12:49.757000", html)
        self.assertIn("hora de Costa Rica (UTC−6)", html)

    def test_el_historial_llama_cierre_a_la_ultima_columna_y_marca_el_abandono(self):
        html = self.c.get("/historial").text
        self.assertIn("<th>Cierre</th>", html)
        self.assertEqual(html.count('class="fecha-nota"'), 1)                          # solo A-002 lleva la etiqueta
        fila_abandono = html.split("A-002")[1].split("</tr>")[0]
        self.assertIn("abandono", fila_abandono)
        fila_atendido = html.split("A-001")[1].split("A-002")[0]
        self.assertNotIn(">abandono<", fila_atendido)

    def test_la_api_y_las_descargas_siguen_en_iso_utc(self):
        turno = self.c.get("/api/historial?codigo=A-001").json()["turnos"][0]
        self.assertEqual(turno["timestamps"]["creado"], "2026-10-27T01:12:49.757Z")
        descarga = self.c.get("/api/historial/descargar?codigo=A-001").json()
        self.assertEqual(descarga["turnos"][0]["timestamps"]["creado"], "2026-10-27T01:12:49.757Z")
        self.assertRegex(descarga["fecha_exportacion"], r"\+00:00$")

    def test_el_ticket_y_el_quiosco_muestran_la_hora_local(self):
        hora_local = r"\d{2}:\d{2}"
        for ruta in ("/quiosco", "/emitir"):
            r = self.c.post(ruta, data={"prioridad": "normal"})
            self.assertEqual(r.status_code, 200)
            self.assertRegex(r.text, r"<dt>Fecha</dt><dd>\d{2}/\d{2}/\d{4}</dd>")
            self.assertRegex(r.text, rf"<dt>Hora</dt><dd>{hora_local}</dd>")
            self.assertNotIn("UTC</dd>", r.text)
            self.assertNotRegex(r.text, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


if __name__ == "__main__":
    unittest.main()
