"""El script de evidencia de /salud valida lo que dice validar (la versión del servidor corre con scripts.probar_salud)."""
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from scripts import probar_salud as ps
    from scripts.probar_fallos_redis import ClientePrueba, ejecutar


class PruebasScriptSalud(BaseRedisMongo):
    def correr(self, casos):
        return ejecutar(ClientePrueba(TestClient(main.app)), casos)

    def test_caso_normal_cumple(self):
        self.assertTrue(all(r["ok"] for r in self.correr(ps.caso_normal())))

    def test_redis_caido_cumple(self):
        with mock.patch("app.main.get_redis", side_effect=ConnectionError("Connection refused 127.0.0.1:6390")):
            self.assertTrue(all(r["ok"] for r in self.correr(ps.caso_redis_caido())))

    def test_mongo_caido_cumple(self):
        main.get_db = mock.Mock(side_effect=RuntimeError("mongodb://u:p@127.0.0.1:27099"))
        self.assertTrue(all(r["ok"] for r in self.correr(ps.caso_mongo_caido())))

    def test_ambos_caidos_cumple(self):
        main.get_db = mock.Mock(side_effect=RuntimeError("x"))
        with mock.patch("app.main.get_redis", side_effect=ConnectionError("x")):
            self.assertTrue(all(r["ok"] for r in self.correr(ps.caso_ambos_caidos())))

    def test_el_caso_falla_si_el_estado_no_es_el_esperado(self):
        with mock.patch("app.main.get_redis", side_effect=ConnectionError("x")):
            self.assertFalse(any(r["ok"] for r in self.correr(ps.caso_normal())))

    def test_el_caso_falla_si_la_respuesta_filtra_infraestructura(self):
        filtrado = {"estado": "ok", "app": "ok", "redis": "ok", "mongo": "ok", "barrido": False,
                    "detalle": "Connection refused 127.0.0.1:6390"}
        with mock.patch("app.salud.comprobar", return_value=(filtrado, 200)):
            self.assertFalse(any(r["ok"] for r in self.correr(ps.caso_normal())))

    def test_el_caso_falla_si_sobran_campos(self):
        extra = {"estado": "ok", "app": "ok", "redis": "ok", "mongo": "ok", "barrido": False, "version": "7.0"}
        with mock.patch("app.salud.comprobar", return_value=(extra, 200)):
            self.assertFalse(any(r["ok"] for r in self.correr(ps.caso_normal())))


class PruebasUtilidades(unittest.TestCase):
    @unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
    def test_sin_fugas(self):
        self.assertTrue(ps.sin_fugas('{"estado":"ok","redis":"ok"}'))
        for texto in ("Traceback (most recent call last)", "Connection refused", "mongodb://u:p@h", "127.0.0.1",
                      "localhost", "6390", "27099"):
            self.assertFalse(ps.sin_fugas(texto), texto)

    @unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
    def test_sin_fugas_detecta_el_usuario_de_mongo(self):
        with mock.patch.dict("os.environ", {"MONGO_USER": "alguien_secreto"}):
            self.assertFalse(ps.sin_fugas('{"x":"alguien_secreto"}'))

    @unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
    def test_informe_describe_lo_ejecutado(self):
        resultados = [{"caso": "c", "peticion": "GET /salud", "esperado": "e", "estado": 200, "ms": 3, "ok": True}]
        md = ps.generar_informe({"url": "http://x", "puertos": "1, 2, 3", "publica": "no ejecutada"},
                                [("1. Caso normal", "texto", resultados)])
        for texto in ("S4-M06", "**OK**", "0 respuestas 500", "no ejecutada", "Alcance y límites"):
            self.assertIn(texto, md)
        self.assertNotIn("SIMULADO", md)

    @unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
    def test_si_la_app_no_responde_no_escribe_informe(self):
        ruta = Path(tempfile.mkdtemp()) / "sub" / "salud.md"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            codigo = ps.main(["--url", "http://127.0.0.1:9", "--informe", str(ruta)])
        self.assertEqual(codigo, 1)
        self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
