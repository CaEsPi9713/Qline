"""HU-007 · ruta HTTP y limpieza de Redis al finalizar.

Requiere httpx (TestClient) y fakeredis; si faltan, las pruebas se omiten.
"""

import unittest

try:
    import fakeredis
    from fastapi.testclient import TestClient

    import app.main as main
    import app.redis_client as redis_client
    from app import cola
    from app.constantes import CLAVE_COLA, clave_ventanilla_actual
    HAY_DEPENDENCIAS = True
except Exception:
    HAY_DEPENDENCIAS = False

from .fakes import ColeccionFalsa, turno, utc


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan httpx o fakeredis")
class PruebasRutaFinalizar(unittest.TestCase):
    def setUp(self):
        self.col = ColeccionFalsa([
            turno("A-030", "en_atencion", "V-01", inicio=utc(14, 10)),
            turno("A-031", "llamado", "V-01"),
        ])
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self._cliente_orig, self._db_orig = redis_client._client, main.get_db
        redis_client._client = self.redis
        main.get_db = lambda: {"turnos": self.col}
        self.c = TestClient(main.app)

    def tearDown(self):
        redis_client._client = self._cliente_orig
        main.get_db = self._db_orig

    def post(self, codigo, ventanilla):
        return self.c.post("/api/atencion/finalizar", data={"codigo": codigo, "ventanilla": ventanilla})

    def test_finaliza_y_libera_redis(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-030")
        self.redis.zadd(CLAVE_COLA, {"A-030": 1})          # estado incoherente a corregir
        r = self.post("A-030", "V-01")
        self.assertEqual(r.status_code, 200)
        cuerpo = r.json()
        self.assertEqual(cuerpo["estado"], "atendido")
        self.assertTrue(cuerpo["redis_liberado"])
        self.assertTrue(cuerpo["finalizado"].endswith("Z"))
        self.assertGreaterEqual(cuerpo["atencion_seg"], 0)
        self.assertEqual(self.col.docs["A-030"]["estado"], "atendido")
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))
        self.assertIsNone(self.redis.zscore(CLAVE_COLA, "A-030"))

    def test_no_libera_ventanilla_que_ya_atiende_otro_turno(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-099")
        self.assertEqual(self.post("A-030", "V-01").status_code, 200)
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-01")), "A-099")

    def test_errores_no_tocan_redis(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-031")
        self.assertEqual(self.post("A-031", "V-01").status_code, 409)   # nunca inició
        self.assertEqual(self.post("A-999", "V-01").status_code, 404)
        self.assertEqual(self.post("A-030", "V-09").status_code, 422)
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-01")), "A-031")

    def test_reintento_rechazado(self):
        self.assertEqual(self.post("A-030", "V-01").status_code, 200)
        self.assertEqual(self.post("A-030", "V-01").status_code, 409)

    def test_redis_caido_no_deshace_mongodb(self):
        redis_client._client = None
        orig = redis_client.get_redis

        def roto():
            raise ConnectionError("Redis caído (simulado)")

        import app.redis_atencion as ra
        import app.eventos as ev
        ra.get_redis = roto
        ev_orig, ev.get_redis = ev.get_redis, roto      # el aviso en vivo también falla, sin romper nada
        try:
            r = self.post("A-030", "V-01")
        finally:
            ra.get_redis = orig
            ev.get_redis = ev_orig
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["redis_liberado"])
        self.assertEqual(self.col.docs["A-030"]["estado"], "atendido")

    def test_flujo_completo_cola_llamar_iniciar_finalizar(self):
        """Redis decide (cola), MongoDB registra: el turno termina fuera de Redis."""
        cola.encolar("A-030", "normal", 1_000)
        self.col.docs["A-030"].update(estado="llamado")
        self.col.docs["A-030"]["timestamps"]["inicio_atencion"] = None
        self.assertEqual(cola.llamar_siguiente("V-01"), "A-030")
        self.assertEqual(self.c.post("/api/atencion/iniciar", data={"codigo": "A-030", "ventanilla": "V-01"}).status_code, 200)
        self.assertEqual(self.post("A-030", "V-01").status_code, 200)
        self.assertEqual(self.col.docs["A-030"]["estado"], "atendido")
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))
        self.assertEqual(cola.tamano_cola(), 0)


if __name__ == "__main__":
    unittest.main()
