"""Pruebas de HU-006 · Iniciar atención.

    python -m unittest discover -s tests -t . -v
"""

import threading
import unittest

from app.atencion import iniciar_atencion
from app.excepciones import (
    DatosInvalidos,
    ServicioNoDisponible,
    TransicionNoPermitida,
    TurnoNoEncontrado,
    VentanillaNoCoincide,
)

from .fakes import ColeccionFalsa, turno, utc


class PruebasIniciarAtencion(unittest.TestCase):
    def setUp(self):
        self.col = ColeccionFalsa([
            turno("A-015", "llamado", "V-01"),                   # caso feliz
            turno("A-016", "pendiente", None, "preferencial"),
            turno("A-017", "en_atencion", "V-02", inicio=utc(14, 6)),
            turno("A-018", "atendido", "V-01"),
            turno("A-019", "abandonado", "V-03"),
            turno("A-020", "llamado", "V-02", "preferencial"),
        ])

    def test_inicia_turno_llamado(self):
        r = iniciar_atencion(self.col, "A-015", "V-01", ahora=utc(14, 10))
        doc = self.col.docs["A-015"]
        self.assertEqual(r["estado"], "en_atencion")
        self.assertEqual(doc["estado"], "en_atencion")
        self.assertEqual(doc["timestamps"]["inicio_atencion"], utc(14, 10))
        self.assertEqual(doc["ventanilla"], "V-01")                  # conserva la ventanilla
        self.assertIsNotNone(doc["timestamps"]["llamado"])           # no pierde historial

    def test_rechaza_estados_distintos_de_llamado(self):
        for codigo, v in (("A-016", "V-01"), ("A-017", "V-02"), ("A-018", "V-01"), ("A-019", "V-03")):
            with self.subTest(codigo=codigo):
                estado = self.col.docs[codigo]["estado"]
                with self.assertRaises(TransicionNoPermitida):
                    iniciar_atencion(self.col, codigo, v)
                self.assertEqual(self.col.docs[codigo]["estado"], estado)

    def test_turno_inexistente(self):
        with self.assertRaises(TurnoNoEncontrado):
            iniciar_atencion(self.col, "A-999", "V-01")

    def test_ventanilla_no_coincide(self):
        with self.assertRaises(VentanillaNoCoincide):
            iniciar_atencion(self.col, "A-020", "V-01")
        self.assertEqual(self.col.docs["A-020"]["estado"], "llamado")
        self.assertIsNone(self.col.docs["A-020"]["timestamps"]["inicio_atencion"])

    def test_ventanilla_invalida(self):
        for v in ("V-09", "", None, "v-01"):
            with self.subTest(ventanilla=v):
                with self.assertRaises(DatosInvalidos):
                    iniciar_atencion(self.col, "A-015", v)

    def test_codigo_invalido(self):
        for c in ("", "XYZ", None, "A015", 15):
            with self.subTest(codigo=c):
                with self.assertRaises(DatosInvalidos):
                    iniciar_atencion(self.col, c, "V-01")

    def test_reintento_no_duplica_inicio(self):
        iniciar_atencion(self.col, "A-015", "V-01", ahora=utc(14, 10))
        with self.assertRaises(TransicionNoPermitida):
            iniciar_atencion(self.col, "A-015", "V-01", ahora=utc(15, 0))
        self.assertEqual(self.col.docs["A-015"]["timestamps"]["inicio_atencion"], utc(14, 10))

    def test_inicio_simultaneo_solo_uno_gana(self):
        resultados, barrera = [], threading.Barrier(10)

        def intentar():
            barrera.wait()
            try:
                iniciar_atencion(self.col, "A-015", "V-01")
                resultados.append("ok")
            except TransicionNoPermitida:
                resultados.append("rechazado")

        hilos = [threading.Thread(target=intentar) for _ in range(10)]
        for h in hilos: h.start()
        for h in hilos: h.join()
        self.assertEqual(resultados.count("ok"), 1)
        self.assertEqual(resultados.count("rechazado"), 9)

    def test_mongodb_no_disponible(self):
        self.col.falla = True
        with self.assertRaises(ServicioNoDisponible):
            iniciar_atencion(self.col, "A-015", "V-01")


try:
    import fakeredis
    from fastapi.testclient import TestClient
    import app.main as main
    import app.redis_client as redis_client
    HAY_CLIENTE = True
except Exception:  # starlette exige httpx para TestClient; fakeredis aísla Redis
    HAY_CLIENTE = False


@unittest.skipUnless(HAY_CLIENTE, "faltan httpx o fakeredis (pip install -r requirements-dev.txt)")
class PruebasRutaIniciar(unittest.TestCase):
    """La ruta traduce cada error controlado a su código HTTP, nunca a 500."""

    def setUp(self):
        self.col = ColeccionFalsa([
            turno("A-015", "llamado", "V-01"),
            turno("A-016", "pendiente", None),
            turno("A-020", "llamado", "V-02"),
        ])
        self._orig = main.get_db
        main.get_db = lambda: {"turnos": self.col}
        # Iniciar la atención toca Redis (confirmar presencia): se aísla con un Redis simulado.
        self._cliente_orig = redis_client._client
        redis_client._client = fakeredis.FakeRedis(decode_responses=True)
        self.c = TestClient(main.app)

    def tearDown(self):
        main.get_db = self._orig
        redis_client._client = self._cliente_orig

    def post(self, codigo, ventanilla):
        return self.c.post("/api/atencion/iniciar", data={"codigo": codigo, "ventanilla": ventanilla})

    def test_respuestas_http(self):
        r = self.post("A-015", "V-01")
        self.assertEqual((r.status_code, r.json()["estado"]), (200, "en_atencion"))
        self.assertEqual(self.post("A-015", "V-01").status_code, 409)    # reintento
        self.assertEqual(self.post("A-016", "V-01").status_code, 409)    # pendiente
        self.assertEqual(self.post("A-020", "V-01").status_code, 409)    # otra ventanilla
        self.assertEqual(self.post("A-999", "V-01").status_code, 404)
        self.assertEqual(self.post("A-015", "V-09").status_code, 422)
        self.assertEqual(self.post("basura", "V-01").status_code, 422)

    def test_mongodb_caido_503(self):
        self.col.falla = True
        r = self.post("A-015", "V-01")
        self.assertEqual(r.status_code, 503)
        self.assertFalse(r.json()["ok"])


if __name__ == "__main__":
    unittest.main()
