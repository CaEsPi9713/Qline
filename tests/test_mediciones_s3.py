"""TT-018 · mediciones de recuperación y abandono: aislamiento, mínimo de ejecuciones e informe."""
import io
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    import fakeredis
    import mongomock

    from app import integracion_s3 as integ, main, mediciones_s3 as med, redis_client
    from app.constantes import CLAVE_COLA, CLAVE_EVENTOS
    from app.datos_prueba import construir_turno

AHORA = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)
COLA_M, EVENTOS_M = "prueba:cola:M", "prueba:eventos"


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class Base(unittest.TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis(decode_responses=True)
        self._cliente, self._get_db = redis_client._client, main.get_db
        redis_client._client = self.r
        self.db = mongomock.MongoClient()["grupo2_db"]
        main.get_db = lambda: self.db
        self.col = self.db["turnos"]
        self.deps = integ.dependencias_cola(self.r, clave_cola=COLA_M, clave_contador="prueba:contador:M")
        self.dep_aband = integ.dependencias_abandono(self.r, clave_eventos=EVENTOS_M)

    def tearDown(self):
        redis_client._client, main.get_db = self._cliente, self._get_db

    def turno_real_vencido(self):
        llamado = AHORA - timedelta(seconds=500)
        self.col.insert_one(construir_turno("A-001", "llamado", "normal", llamado - timedelta(seconds=60),
                                            "V-01", llamado))


class PruebasMediciones(Base):
    def test_rehidratacion(self):
        m = med.medir_rehidratacion(self.col, self.deps, AHORA, 30, 3)
        self.assertEqual((m.ejecuciones, m.n), (3, 30))
        self.assertTrue(m.correcta)
        self.assertGreater(m.mediana, 0)
        self.assertEqual(self.col.count_documents({}), 0)                   # limpió
        self.assertEqual(self.r.zcard(COLA_M), 0)

    def test_reconciliacion_sin_cambios(self):
        m = med.medir_reconciliacion_sin_cambios(self.col, self.deps, AHORA, 30, 3)
        self.assertTrue(m.correcta)
        self.assertEqual(self.col.count_documents({}), 0)

    def test_barrido_solo_ve_la_serie_m(self):
        self.turno_real_vencido()                                            # vencido, pero no es de la medición
        m = med.medir_barrido(self.col, self.deps, self.dep_aband, AHORA, 25, 3)
        self.assertTrue(m.correcta)
        real = self.col.find_one({"codigo": "A-001"})
        self.assertEqual(real["estado"], "llamado")                          # intacto
        self.assertEqual(self.col.count_documents({"codigo": {"$regex": "^M-"}}), 0)

    def test_no_toca_la_cola_ni_los_eventos_reales(self):
        ps = self.r.pubsub()
        ps.subscribe(CLAVE_EVENTOS)
        ps.get_message(timeout=1)
        med.medir_rehidratacion(self.col, self.deps, AHORA, 10, 3)
        med.medir_barrido(self.col, self.deps, self.dep_aband, AHORA, 10, 3)
        self.assertEqual(self.r.zcard(CLAVE_COLA), 0)
        self.assertIsNone(ps.get_message(timeout=0.2))                       # el público no recibió nada

    def test_exige_al_menos_tres_ejecuciones(self):
        with self.assertRaises(ValueError):
            med.medir_rehidratacion(self.col, self.deps, AHORA, 5, 2)
        with self.assertRaises(ValueError):
            med.medir_barrido(self.col, self.deps, self.dep_aband, AHORA, 5, 1)

    def test_medicion_incorrecta_se_marca(self):
        m = med.Medicion("x", 5, [0.1, 0.2, 0.3], correctas=2)
        self.assertFalse(m.correcta)
        self.assertEqual(m.mediana, 0.2)

    def test_informe(self):
        resultados = [med.medir_rehidratacion(self.col, self.deps, AHORA, 10, 3),
                      med.medir_barrido(self.col, self.deps, self.dep_aband, AHORA, 10, 3)]
        md = med.informe(resultados, [10], 3)
        for texto in ("Mediana (ms)", "Rehidratar la cola (10 pendientes)", "Barrido de abandono", "3 ejecuciones"):
            self.assertIn(texto, md)
        self.assertNotIn("SIMULADO", md)
        self.assertNotIn("Atención:", md)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasRelojAdelantado(unittest.TestCase):
    """El barrido automático de la app no debe poder abandonar los turnos de la medición."""

    def test_los_llamados_vencen_para_el_reloj_de_prueba_y_no_para_el_real(self):
        from app.constantes import TTL_ABANDONO_SEG
        real = datetime.now(timezone.utc)
        reloj = real + timedelta(seconds=med.ADELANTO_RELOJ_SEG)
        for d in med._docs_llamados_vencidos(reloj, 500):
            llamado = d["timestamps"]["llamado"]
            self.assertLessEqual(llamado, reloj - timedelta(seconds=TTL_ABANDONO_SEG))       # vencido para la prueba
            self.assertGreater(llamado, real - timedelta(seconds=TTL_ABANDONO_SEG))          # no para el reloj real

    def test_los_casos_de_fallo_tambien_usan_el_reloj_adelantado(self):
        from app import fallos_s3 as f
        from app.constantes import TTL_ABANDONO_SEG
        r = fakeredis.FakeRedis(decode_responses=True)
        col = mongomock.MongoClient()["g"]["turnos"]
        real = datetime.now(timezone.utc)
        ctx = f.Contexto(col, r, None, real + timedelta(seconds=med.ADELANTO_RELOJ_SEG))
        ctx.llamado("F-001", seg=500)                                        # el llamado más viejo de los casos
        llamado = col.find_one({"codigo": "F-001"})["timestamps"]["llamado"].replace(tzinfo=timezone.utc)
        self.assertGreater(llamado, real - timedelta(seconds=TTL_ABANDONO_SEG))


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasScript(Base):
    def test_script_genera_informe_y_limpia_claves(self):
        from scripts import medir_recuperacion as script
        ruta = pathlib.Path(tempfile.mkdtemp()) / "r.md"
        with redirect_stdout(io.StringIO()):
            codigo = script.main(["--tamanos", "10", "--ejecuciones", "3", "--informe", str(ruta)])
        self.assertEqual(codigo, 0)
        self.assertIn("Mediana (ms)", ruta.read_text(encoding="utf-8"))
        self.assertEqual(self.r.keys("grupo2:qline:prueba:*"), [])

    def test_script_rechaza_menos_de_tres_ejecuciones(self):
        from scripts import medir_recuperacion as script
        self.assertEqual(script.main(["--ejecuciones", "2"]), 2)


if __name__ == "__main__":
    unittest.main()
