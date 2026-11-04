"""HU-008 · barrido de abandono: arranque con la app, configuración, índice y script."""
import io
import json
import os
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    import fakeredis
    import mongomock
    from fastapi.testclient import TestClient

    from app import integracion_s3 as integ, main, redis_client
    from app.constantes import CLAVE_EVENTOS, clave_turno, clave_ventanilla_actual
    from app.datos_prueba import construir_turno

from app.turnos_schema import INDICES_TURNOS


class PruebasConfiguracion(unittest.TestCase):
    def test_apagado_por_defecto_en_pruebas(self):
        self.assertFalse(integ.barrido_habilitado())      # tests/__init__.py lo apaga
        self.assertIsNone(integ.crear_barrido_abandono())

    def test_valores_de_la_variable(self):
        for valor, esperado in (("1", True), ("true", True), ("0", False), ("false", False),
                                ("off", False), ("", False)):
            with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": valor}):
                self.assertEqual(integ.barrido_habilitado(), esperado, valor)
        with mock.patch.dict(os.environ):
            os.environ.pop("BARRIDO_ABANDONO")
            self.assertTrue(integ.barrido_habilitado())     # sin la variable, encendido

    def test_intervalo(self):
        with mock.patch.dict(os.environ, {"BARRIDO_INTERVALO_SEG": "2.5"}):
            self.assertEqual(integ.intervalo_barrido(), 2.5)
        for malo in ("abc", "0", "-3"):
            with mock.patch.dict(os.environ, {"BARRIDO_INTERVALO_SEG": malo}):
                self.assertEqual(integ.intervalo_barrido(), integ.INTERVALO_BARRIDO_POR_DEFECTO_SEG)

    def test_indice_para_el_barrido(self):
        idx = next(i for i in INDICES_TURNOS if i["options"]["name"] == "idx_turnos_estado_llamado")
        self.assertEqual(idx["keys"], [("estado", 1), ("timestamps.llamado", 1)])


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseBarrido(unittest.TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis(decode_responses=True)
        self._cliente, self._get_db = redis_client._client, main.get_db
        redis_client._client = self.r
        self.db = mongomock.MongoClient()["grupo2_db"]
        main.get_db = lambda: self.db
        self.col = self.db["turnos"]

    def tearDown(self):
        redis_client._client, main.get_db = self._cliente, self._get_db

    def turno_llamado(self, codigo, hace_seg, ventanilla="V-01"):
        llamado = datetime.now(timezone.utc) - timedelta(seconds=hace_seg)
        self.col.insert_one(construir_turno(codigo, "llamado", "normal", llamado - timedelta(seconds=60),
                                            ventanilla, llamado))
        self.r.set(clave_ventanilla_actual(ventanilla), codigo)

    def esperar(self, condicion, limite=5.0):
        fin = time.time() + limite
        while time.time() < fin:
            if condicion():
                return True
            time.sleep(0.02)
        return False


class PruebasBarridoReal(BaseBarrido):
    def test_una_pasada_abandona_libera_y_publica(self):
        self.turno_llamado("A-001", 200)
        ps = self.r.pubsub()
        ps.subscribe(CLAVE_EVENTOS)
        ps.get_message(timeout=1)
        with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": "1"}):
            barrido = integ.crear_barrido_abandono()
        res = barrido.ejecutar_una_vez()
        self.assertEqual(res.abandonados, ["A-001"])
        self.assertEqual(self.col.find_one({"codigo": "A-001"})["estado"], "abandonado")
        self.assertIsNone(self.r.get(clave_ventanilla_actual("V-01")))
        evento = json.loads(ps.get_message(timeout=1)["data"])
        self.assertEqual((evento["tipo"], evento["codigo"]), ("turno_abandonado", "A-001"))

    def test_no_toca_los_vigentes(self):
        self.turno_llamado("A-001", 100)
        self.turno_llamado("A-002", 200, "V-02")
        self.r.hset(clave_turno("A-002"), "estado", "llamado")      # su Hash todavía vive
        with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": "1"}):
            res = integ.crear_barrido_abandono().ejecutar_una_vez()
        self.assertEqual(res.abandonados, [])
        self.assertEqual(self.col.count_documents({"estado": "llamado"}), 2)

    def test_mongo_caido_no_detiene_el_barrido(self):
        with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": "1"}):
            barrido = integ.crear_barrido_abandono()
        with mock.patch.object(main, "get_db", side_effect=ConnectionError("caído")),                 self.assertLogs("qline.barrido", level="ERROR"):
            barrido.ejecutar_una_vez()
        self.assertEqual(barrido.errores, 1)
        barrido.ejecutar_una_vez()
        self.assertEqual(barrido.pasadas, 1)


class PruebasArranqueConLaApp(BaseBarrido):
    def test_la_app_inicia_y_detiene_el_barrido(self):
        self.turno_llamado("A-001", 200)
        with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": "1", "BARRIDO_INTERVALO_SEG": "0.05"}):
            with TestClient(main.app):
                barrido = main.app.state.barrido
                self.assertTrue(barrido.activo)
                self.assertTrue(self.esperar(lambda: self.col.find_one({"codigo": "A-001"})["estado"] == "abandonado"))
        self.assertFalse(barrido.activo)

    def test_con_el_interruptor_apagado_no_hay_barrido(self):
        with TestClient(main.app):
            self.assertIsNone(main.app.state.barrido)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasScript(BaseBarrido):
    def test_script_una_pasada(self):
        from scripts import barrer_abandonos
        self.turno_llamado("A-001", 200)
        salida = io.StringIO()
        with redirect_stdout(salida):
            codigo = barrer_abandonos.main([])
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(salida.getvalue())["abandonados"], ["A-001"])

    def test_script_ya_no_ofrece_modo_simulado(self):
        from scripts import barrer_abandonos
        with self.assertRaises(SystemExit):
            barrer_abandonos.main(["--simulado"])


if __name__ == "__main__":
    unittest.main()
