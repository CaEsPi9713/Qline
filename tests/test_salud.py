"""S4-M06 · /salud responde solo con estados, con 200 o 503, y nunca filtra el texto de un fallo."""
import unittest
from tests.apoyo_sesion import ClienteConSesion
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app import salud

SECRETO = "mongodb://usuario:clave-secreta@10.0.0.7:27017/base"


class _Barrido:
    def __init__(self, activo):
        self.activo = activo


class PruebasSalud(BaseRedisMongo):
    def pedir(self):
        return ClienteConSesion(main.app).get("/salud")

    def test_todo_sano_responde_200(self):
        r = self.pedir()
        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertEqual((cuerpo["estado"], cuerpo["app"], cuerpo["redis"], cuerpo["mongo"]),
                         ("ok", "ok", "ok", "ok"))
        self.assertIn("barrido", cuerpo)

    def test_redis_caido_responde_503_y_mongo_sigue_ok(self):
        with mock.patch("app.main.get_redis", side_effect=ConnectionError(SECRETO)):
            r = self.pedir()
        self.assertEqual(r.status_code, 503)
        self.assertEqual((r.json()["estado"], r.json()["redis"], r.json()["mongo"]), ("degradado", "error", "ok"))

    def test_mongo_caido_responde_503_y_redis_sigue_ok(self):
        main.get_db = mock.Mock(side_effect=RuntimeError(SECRETO))
        r = self.pedir()
        self.assertEqual(r.status_code, 503)
        self.assertEqual((r.json()["estado"], r.json()["redis"], r.json()["mongo"]), ("degradado", "ok", "error"))

    def test_ambos_caidos_responde_503_sin_500(self):
        main.get_db = mock.Mock(side_effect=RuntimeError(SECRETO))
        with mock.patch("app.main.get_redis", side_effect=ConnectionError(SECRETO)):
            r = self.pedir()
        self.assertEqual(r.status_code, 503)
        self.assertEqual((r.json()["redis"], r.json()["mongo"]), ("error", "error"))

    def test_el_cuerpo_no_filtra_el_texto_del_fallo_ni_infraestructura(self):
        main.get_db = mock.Mock(side_effect=RuntimeError(SECRETO))
        with mock.patch("app.main.get_redis", side_effect=ConnectionError(SECRETO)):
            texto = self.pedir().text
        for prohibido in ("clave-secreta", "usuario", "10.0.0.7", "27017", "mongodb://", "Traceback", "Error"):
            self.assertNotIn(prohibido, texto)

    def test_solo_expone_los_campos_esperados(self):
        self.assertEqual(set(self.pedir().json()), {"estado", "app", "redis", "mongo", "barrido"})

    def test_el_fallo_se_registra_en_el_servidor_sin_el_mensaje(self):
        with self.assertLogs("qline.salud", level="WARNING") as registro:
            salud.comprobar(lambda: self.db, mock.Mock(side_effect=ConnectionError(SECRETO)))
        self.assertIn("redis", registro.output[0])
        self.assertNotIn("clave-secreta", registro.output[0])

    def test_barrido_activo_o_apagado_no_cambia_el_estado(self):
        for activo in (True, False):
            cuerpo, codigo = salud.comprobar(lambda: self.db, lambda: self.redis, _Barrido(activo))
            self.assertEqual((cuerpo["barrido"], cuerpo["estado"], codigo), (activo, "ok", 200))
        cuerpo, _ = salud.comprobar(lambda: self.db, lambda: self.redis, None)
        self.assertFalse(cuerpo["barrido"])


class PruebasRedisEstado(BaseRedisMongo):
    """`/redis/estado` solo dice si Redis responde: sin host, puerto, versión ni texto del error."""

    def test_con_redis_sano_solo_devuelve_ok(self):
        main.verificar_redis = lambda: {"ok": True, "host": "10.0.0.7", "port": 6379, "version": "7.0.15"}
        r = ClienteConSesion(main.app).get("/redis/estado")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True}))

    def test_con_redis_caido_no_filtra_el_error(self):
        main.verificar_redis = lambda: {"ok": False, "host": "10.0.0.7", "port": 6379, "error": SECRETO}
        r = ClienteConSesion(main.app).get("/redis/estado")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": False}))
        for prohibido in ("clave-secreta", "10.0.0.7", "6379", "mongodb://"):
            self.assertNotIn(prohibido, r.text)


if __name__ == "__main__":
    unittest.main()
