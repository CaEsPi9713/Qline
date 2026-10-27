"""TT-019 · casos de fallo de abandono y recuperación."""
import io
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    import fakeredis
    import mongomock

    from app import fallos_s3 as f, main, redis_client


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasFallos(unittest.TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis(decode_responses=True)
        self._cliente, self._get_db = redis_client._client, main.get_db
        redis_client._client = self.r
        self.db = mongomock.MongoClient()["grupo2_db"]
        main.get_db = lambda: self.db
        self.col = self.db["turnos"]

    def tearDown(self):
        redis_client._client, main.get_db = self._cliente, self._get_db

    def test_todos_los_casos_dan_lo_esperado(self):
        casos = f.ejecutar_casos(self.col, self.r, f.RedisCaido())
        fallos = [(c.nombre, c.observado) for c in casos if not c.ok]
        self.assertEqual(fallos, [])
        self.assertGreaterEqual(len(casos), 18)
        self.assertEqual({c.seccion for c in casos}, {f.S1, f.S2, f.S3, f.S4, f.S5})

    def test_limpia_todo_al_terminar(self):
        self.col.insert_one({"codigo": "A-001", "estado": "pendiente"})
        self.r.set("grupo2:qline:ventanilla:V-01:actual", "A-001")
        f.ejecutar_casos(self.col, self.r, f.RedisCaido())
        self.assertEqual(self.col.count_documents({"codigo": {"$regex": "^F-"}}), 0)
        self.assertEqual(self.r.keys("grupo2:qline:prueba:*"), [])
        self.assertEqual(self.r.get("grupo2:qline:ventanilla:V-01:actual"), "A-001")   # lo real, intacto
        self.assertEqual(self.col.count_documents({"codigo": "A-001"}), 1)

    def test_no_publica_en_el_canal_real(self):
        ps = self.r.pubsub()
        ps.subscribe("grupo2:qline:eventos")
        ps.get_message(timeout=1)
        f.ejecutar_casos(self.col, self.r, f.RedisCaido())
        self.assertIsNone(ps.get_message(timeout=0.2))

    def test_un_caso_que_lanza_se_marca_como_falla(self):
        def roto(ctx):
            raise KeyError("x")
        f.CASOS.append(("9. Prueba", "roto", "-", "-", roto))
        try:
            casos = f.ejecutar_casos(self.col, self.r, f.RedisCaido())
        finally:
            f.CASOS.pop()
        ultimo = casos[-1]
        self.assertFalse(ultimo.ok)
        self.assertIn("EXCEPCIÓN NO CONTROLADA", ultimo.observado)
        self.assertIn("CON FALLAS", f.informe(casos))

    def test_informe(self):
        md = f.informe(f.ejecutar_casos(self.col, self.r, f.RedisCaido()))
        for texto in ("1. Caso normal", "2. Redis caído", "3. MongoDB caído", "4. Datos inválidos", "**OK**"):
            self.assertIn(texto, md)

    def test_script(self):
        from scripts import probar_fallos_recuperacion as script
        ruta = pathlib.Path(tempfile.mkdtemp()) / "f.md"
        original = script.cliente_redis_caido
        script.cliente_redis_caido = lambda puerto: f.RedisCaido()
        try:
            with redirect_stdout(io.StringIO()):
                codigo = script.main(["--informe", str(ruta)])
        finally:
            script.cliente_redis_caido = original
        self.assertEqual(codigo, 0)
        self.assertIn("Resultado global", ruta.read_text(encoding="utf-8"))


class PruebasClientes(unittest.TestCase):
    def test_redis_caido_lanza_error_de_conexion(self):
        from redis.exceptions import ConnectionError as E
        if not HAY_DEPENDENCIAS:
            self.skipTest("faltan dependencias")
        with self.assertRaises(E):
            f.RedisCaido().get("x")

    def test_coleccion_caida(self):
        if not HAY_DEPENDENCIAS:
            self.skipTest("faltan dependencias")
        with self.assertRaises(ConnectionError):
            f.ColeccionCaida().find({})


if __name__ == "__main__":
    unittest.main()
