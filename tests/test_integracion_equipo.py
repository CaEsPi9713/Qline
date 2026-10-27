"""Integración entre las áreas del equipo en el Seguimiento 3.

  Aaron    quiosco, QR en el ticket y pantalla pública
  Alessandro  cola, llamado, consulta por QR, eventos
  Abigail  abandono y recuperación de la cola
  Carlos   qr_token en el esquema, historial y dashboard, descargas JSON

Recorre el flujo por HTTP con MongoDB y Redis simulados (el servidor real se verifica con el guion de
GUION_VERIFICACION_S3.md). Cada prueba protege un contrato entre dos áreas.
"""
import io
import json
import os
import re
import threading
import unittest
from contextlib import redirect_stdout
from unittest import mock

from redis.exceptions import TimeoutError as RedisTimeout

from tests.test_e2e_abandono import BaseE2E
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    from app import consultar, emitir
    from app.constantes import CLAVE_COLA
    from app.consulta_qr import consultar_por_token, filtro_por_token
    from app.turnos_schema import INDICES_TURNOS, PATRON_UUID_V4, validar_documento_turno


class BaseEquipo(BaseE2E):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://grupo2.crnube.net", "BASE_PATH": ""})
        patcher.start()
        self.addCleanup(patcher.stop)


class PruebasFlujoDelEquipo(BaseEquipo):
    """Quiosco (Aaron) → QR → llamar → pantalla → abandono (Abigail) → historial y descargas (Carlos)."""

    def test_del_quiosco_hasta_las_descargas_json(self):
        # Aaron · el cliente emite desde el quiosco y recibe el ticket con QR
        r = self.c.post("/quiosco", data={"prioridad": "normal"})
        self.assertEqual(r.status_code, 200)
        doc = self.turnos().find_one({})
        codigo, token = doc["codigo"], doc["qr_token"]
        self.assertIn(codigo, r.text)
        self.assertIn("<svg", r.text)                                           # el QR va inline
        self.assertIn(f"/turno/qr/{token}", r.text)                             # y apunta a la ruta de HU-013
        self.assertNotIn("localhost", r.text)

        # Alessandro · el cliente abre su página por QR; se llama el turno
        self.assertEqual(self.c.get(f"/turno/qr/{token}").status_code, 200)
        self.assertEqual(self.c.get(f"/api/turnos/qr/{token}").json()["turno"]["estado"], "pendiente")
        self.assertEqual(self.llamar().status_code, 200)

        # Aaron · la pantalla de sala lo muestra, sin datos personales ni el token
        llamados = self.c.get("/api/llamados").json()["llamados"]
        self.assertEqual([x["codigo"] for x in llamados], [codigo])
        self.assertEqual(set(llamados[0]), {"codigo", "ventanilla", "estado"})
        pantalla = self.c.get("/pantalla").text
        self.assertIn(codigo, pantalla)
        self.assertNotIn(token, pantalla)

        # Abigail · no se presenta: el barrido lo abandona y la pantalla lo retira
        self.vencer(codigo)
        self.assertEqual(self.barrer().abandonados, [codigo])
        self.assertEqual(self.c.get("/api/llamados").json()["llamados"], [])
        self.assertIn("no se presentó a tiempo", self.c.get(f"/turno/qr/{token}").text)

        # Carlos · el historial y las descargas JSON reflejan el abandono con sus tiempos
        historial = self.c.get("/api/historial/descargar?estado=abandonado")
        self.assertEqual(historial.status_code, 200)
        self.assertIn("application/json", historial.headers["content-type"])
        self.assertIn("attachment", historial.headers["content-disposition"])
        datos = json.loads(historial.text)
        self.assertEqual((datos["total_exportados"], datos["total_registros_coincidentes"]), (1, 1))
        turno = datos["turnos"][0]
        self.assertEqual((turno["codigo"], turno["estado"], turno["ventanilla"]), (codigo, "abandonado", "V-01"))
        self.assertIsNotNone(turno["timestamps"]["abandonado"])
        self.assertNotIn("qr_token", turno)                                      # el historial exportado no filtra el token

        todos = json.loads(self.c.get("/api/historial/descargar").text)
        self.assertEqual(todos["total_exportados"], 1)
        self.assertEqual(json.loads(self.c.get("/api/historial/descargar?estado=atendido").text)["total_exportados"], 0)

        dash = self.c.get("/api/dashboard/descargar?sla_espera=120")
        self.assertEqual(dash.status_code, 200)
        self.assertIn("dashboard_sla_120s_", dash.headers["content-disposition"])
        cuerpo = json.loads(dash.text)
        self.assertEqual(cuerpo["tipo_reporte"], "metricas_dashboard_sla")
        self.assertEqual(cuerpo["datos"]["totales"]["abandonados"], 1)
        self.assertEqual(cuerpo["datos"]["sla"]["objetivo_max_espera_seg"], 120)


class PruebasContratosEntreAreas(BaseEquipo):
    def setUp(self):
        super().setUp()
        for i in INDICES_TURNOS:                    # los índices reales de Carlos, incluido el único del qr_token
            self.turnos().create_index(i["keys"], **i["options"])

    def test_el_token_de_aaron_cumple_el_esquema_de_carlos(self):
        for _ in range(5):
            emitir.emitir_turno(self.db, "normal")
        for d in self.turnos().find({}, {"_id": 0}):
            self.assertRegex(d["qr_token"], PATRON_UUID_V4)
            self.assertEqual(d["qr_token"], d["qr_token"].lower())
            self.assertTrue(validar_documento_turno(d), d["codigo"])

    def test_la_consulta_de_alessandro_encuentra_el_turno_con_el_filtro_del_indice(self):
        t = emitir.emitir_turno(self.db, "preferencial")
        self.assertEqual(self.turnos().find_one(filtro_por_token(t["qr_token"]))["codigo"], t["codigo"])
        self.assertEqual(consultar_por_token(self.db, t["qr_token"])["codigo"], t["codigo"])

    def test_la_url_del_qr_es_la_ruta_que_sirve_la_aplicacion(self):
        t = emitir.emitir_turno(self.db, "normal")
        ruta = re.search(r"(/turno/qr/[0-9a-f-]{36})$", t["qr_url"]).group(1)
        self.assertEqual(self.c.get(ruta).status_code, 200)
        self.assertNotIn("localhost", t["qr_url"])

    def test_emision_concurrente_no_repite_codigos_ni_tokens(self):
        resultados, errores = [], []

        def emitir_uno():
            try:
                resultados.append(emitir.emitir_turno(self.db, "normal"))
            except Exception as e:                    # noqa: BLE001
                errores.append(repr(e))

        hilos = [threading.Thread(target=emitir_uno) for _ in range(20)]
        for h in hilos: h.start()
        for h in hilos: h.join()
        self.assertEqual(errores, [])
        self.assertEqual(len({r["codigo"] for r in resultados}), 20)
        self.assertEqual(len({r["qr_token"] for r in resultados}), 20)
        self.assertEqual(self.turnos().count_documents({}), 20)
        self.assertEqual(self.redis.zcard(CLAVE_COLA), 20)

    def test_un_token_repetido_lo_rechaza_el_indice_unico(self):
        from pymongo.errors import DuplicateKeyError
        t = emitir.emitir_turno(self.db, "normal")
        copia = self.turnos().find_one({"codigo": t["codigo"]}, {"_id": 0})
        copia["codigo"] = "A-999"
        with self.assertRaises(DuplicateKeyError):
            self.turnos().insert_one(copia)

    def test_los_turnos_antiguos_sin_token_siguen_funcionando(self):
        self.turnos().insert_one({"codigo": "A-900", "servicio": "atencion_general", "prioridad": "normal",
                                  "estado": "atendido", "ventanilla": "V-01", "operador": None,
                                  "timestamps": {"creado": __import__("datetime").datetime(2026, 10, 1)},
                                  "metricas": {"espera_seg": 10, "atencion_seg": 20}})
        nuevo = emitir.emitir_turno(self.db, "normal")                         # no choca con el índice parcial
        self.assertEqual(consultar.consultar_turno(self.db, "A-900")["codigo"], "A-900")
        self.assertEqual(json.loads(self.c.get("/api/historial/descargar").text)["total_exportados"], 2)
        self.assertTrue(nuevo["qr_token"])


class PruebasAaronConAbigail(BaseEquipo):
    """Emisión de Aaron + recuperación de Abigail: si Redis falla al encolar, el turno no se pierde."""

    def test_un_turno_emitido_cuando_redis_falla_se_recupera_con_la_rehidratacion(self):
        with mock.patch("app.emitir.cola.encolar", side_effect=RedisTimeout("timeout")):
            r = self.c.post("/api/turnos/emitir", data={"prioridad": "normal"})
        self.assertEqual(r.status_code, 503)
        doc = self.turnos().find_one({})
        self.assertEqual(doc["estado"], "pendiente")                             # MongoDB conservó el turno
        self.assertEqual(self.redis.zcard(CLAVE_COLA), 0)                        # pero no está en la cola
        self.assertEqual(self.llamar().json()["codigo"], None)                   # nadie lo puede llamar todavía

        from scripts import rehidratar_cola
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rehidratar_cola.main(["--aplicar"]), 0)

        self.assertEqual(self.redis.zrange(CLAVE_COLA, 0, -1), [doc["codigo"]])
        r = self.llamar()
        self.assertEqual((r.status_code, r.json()["codigo"]), (200, doc["codigo"]))
        self.assertEqual(self.c.get(f"/api/turnos/qr/{doc['qr_token']}").json()["turno"]["estado"], "llamado")

    def test_la_rehidratacion_respeta_la_prioridad_de_los_turnos_del_quiosco(self):
        normal = self.c.post("/quiosco", data={"prioridad": "normal"})
        pref = self.c.post("/quiosco", data={"prioridad": "preferencial"})
        self.assertEqual((normal.status_code, pref.status_code), (200, 200))
        codigos = [d["codigo"] for d in self.turnos().find({}).sort("timestamps.creado", 1)]
        self.redis.delete(CLAVE_COLA)
        from scripts import rehidratar_cola
        with redirect_stdout(io.StringIO()):
            rehidratar_cola.main(["--aplicar"])
        self.assertEqual(self.redis.zrange(CLAVE_COLA, 0, -1), [codigos[1], codigos[0]])    # preferencial primero


if __name__ == "__main__":
    unittest.main()
