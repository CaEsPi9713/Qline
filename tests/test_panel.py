"""Panel de atención: turno actual por ventanilla y acciones Iniciar / Finalizar.

Requiere httpx y fakeredis; si faltan, las pruebas se omiten.
"""

import unittest

try:
    import fakeredis
    from fastapi.testclient import TestClient

    import app.main as main
    import app.redis_client as redis_client
    from app.constantes import clave_ventanilla_actual
    HAY_DEPENDENCIAS = True
except Exception:
    HAY_DEPENDENCIAS = False

from .fakes import ColeccionFalsa, turno, utc


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan httpx o fakeredis")
class PruebasPanel(unittest.TestCase):
    def setUp(self):
        self.col = ColeccionFalsa([
            turno("A-015", "llamado", "V-01"),
            turno("A-017", "en_atencion", "V-02", inicio=utc(14, 6)),
            turno("A-018", "atendido", "V-03"),
        ])
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self._cliente_orig, self._db_orig = redis_client._client, main.get_db
        redis_client._client = self.redis
        main.get_db = lambda: {"turnos": self.col}
        self.c = TestClient(main.app)

    def tearDown(self):
        redis_client._client = self._cliente_orig
        main.get_db = self._db_orig

    def test_muestra_turno_actual_y_acciones(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-015")
        html = self.c.get("/panel").text
        self.assertIn("A-015", html)
        self.assertIn("Iniciar atención", html)
        self.assertIn("A-017", html)                 # V-02: sin clave en Redis, se recupera de MongoDB
        self.assertIn("Finalizar atención", html)
        self.assertIn("Sin turno asignado", html)    # V-03

    def test_turno_atendido_en_redis_se_ignora_con_aviso(self):
        self.redis.set(clave_ventanilla_actual("V-03"), "A-018")
        html = self.c.get("/panel").text
        self.assertIn("Redis apunta a A-018", html)
        self.assertIn("Sin turno asignado", html)

    def test_iniciar_y_finalizar_desde_el_panel(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-015")
        r = self.c.post("/panel/iniciar", data={"codigo": "A-015", "ventanilla": "V-01"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("msg=", r.headers["location"])
        self.assertEqual(self.col.docs["A-015"]["estado"], "en_atencion")
        r = self.c.post("/panel/finalizar", data={"codigo": "A-015", "ventanilla": "V-01"}, follow_redirects=False)
        self.assertIn("msg=", r.headers["location"])
        self.assertEqual(self.col.docs["A-015"]["estado"], "atendido")
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))

    def test_errores_se_muestran_sin_500(self):
        r = self.c.post("/panel/finalizar", data={"codigo": "A-015", "ventanilla": "V-01"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)         # A-015 está 'llamado': rechazo controlado
        self.assertIn("error=", r.headers["location"])
        # Apache quita el prefijo BASE_PATH antes de llegar a la app; aquí se hace a mano.
        pagina = self.c.get(r.headers["location"].removeprefix(main.BASE))
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("solo se puede finalizar", pagina.text)

    def test_panel_funciona_con_redis_caido(self):
        def roto():
            raise ConnectionError("Redis caído (simulado)")

        import app.panel_atencion as pa
        orig, pa.get_redis = pa.get_redis, roto
        try:
            html = self.c.get("/panel").text
        finally:
            pa.get_redis = orig
        self.assertIn("Redis no disponible", html)
        self.assertIn("A-017", html)                 # se recupera de MongoDB


if __name__ == "__main__":
    unittest.main()
