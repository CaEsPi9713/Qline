"""TT-028 · La carga de release escribe y borra SOLO su propia serie L-NNN: nunca los turnos reales (A-NNN) ni los sintéticos."""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone

try:
    import mongomock
    HAY_MONGOMOCK = True
except ImportError:  # pragma: no cover
    HAY_MONGOMOCK = False

from app.turnos_schema import validar_documento_turno
from scripts import cargar_datos_release as cr

AHORA = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class PruebasDelDataset(unittest.TestCase):
    def test_solo_serie_l_y_solo_estados_terminales(self):
        docs = cr.generar_dataset_release(cantidad=80)
        self.assertEqual(len(docs), 80)
        self.assertTrue(all(cr.es_codigo_release(d["codigo"]) for d in docs))
        self.assertTrue(all(d["codigo"].startswith("L-") for d in docs))
        self.assertEqual({d["estado"] for d in docs} - {"atendido", "abandonado"}, set())
        self.assertEqual({d["estado"] for d in docs}, {"atendido", "abandonado"})

    def test_cada_documento_cumple_el_contrato(self):
        for d in cr.generar_dataset_release(cantidad=60):
            validar_documento_turno(d)
            self.assertNotIn("qr_token", d)

    def test_los_datos_son_reproducibles(self):
        self.assertEqual(cr.generar_dataset_release(cantidad=20), cr.generar_dataset_release(cantidad=20))

    def test_las_fechas_no_dependen_de_cuando_se_ejecuta(self):
        docs = cr.generar_dataset_release(cantidad=5)
        self.assertEqual(docs[0]["timestamps"]["creado"].date(), cr.FECHA_BASE_RELEASE.date())

    def test_rechaza_cantidades_fuera_de_rango(self):
        for n in (0, -1, cr.CANTIDAD_MAXIMA + 1, "10"):
            with self.assertRaises(ValueError):
                cr.generar_dataset_release(cantidad=n)

    def test_el_reconocimiento_de_la_serie_es_estricto(self):
        for bueno in ("L-001", "L-1234"):
            self.assertTrue(cr.es_codigo_release(bueno))
        for malo in ("A-001", "S-001", "R-001", "L-", "LL-001", "L-001x", None, 5):
            self.assertFalse(cr.es_codigo_release(malo), malo)


@unittest.skipUnless(HAY_MONGOMOCK, "falta mongomock")
class PruebasConBaseDeDatos(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient().db
        self.col = self.db["turnos"]
        # Operación real y datos de otras pruebas ya presentes en el servidor
        self.real = {"codigo": "A-001", "servicio": "atencion_general", "prioridad": "normal", "estado": "en_atencion",
                     "ventanilla": "V-01", "qr_token": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                     "timestamps": {"creado": AHORA, "llamado": AHORA, "inicio_atencion": AHORA,
                                    "finalizado": None, "abandonado": None},
                     "metricas": {"espera_seg": 10, "atencion_seg": None}}
        self.col.insert_one(dict(self.real))
        for codigo in ("S-001", "S-554", "R-001", "Z-901"):
            self.col.insert_one({**self.real, "codigo": codigo, "qr_token": None, "estado": "atendido"})

    def conservados(self):
        a = self.col.find_one({"codigo": "A-001"})
        self.assertEqual((a["estado"], a["ventanilla"], a["qr_token"]), ("en_atencion", "V-01", self.real["qr_token"]))
        for codigo in ("S-001", "S-554", "R-001", "Z-901"):
            self.assertIsNotNone(self.col.find_one({"codigo": codigo}), codigo)

    def test_cargar_no_toca_los_turnos_reales_ni_los_sinteticos(self):
        cr.cargar_datos_release(self.db, cantidad=50)
        self.conservados()
        self.assertEqual(self.col.count_documents({"codigo": {"$regex": "^L-"}}), 50)

    def test_limpiar_borra_solo_la_serie_l(self):
        cr.cargar_datos_release(self.db, cantidad=30)
        res = cr.cargar_datos_release(self.db, cantidad=10, limpiar=True)
        self.assertEqual(res["eliminados"], 30)
        self.assertEqual(res["turnos_release"], 10)
        self.conservados()

    def test_limpiar_sin_turnos_previos_no_borra_nada_ajeno(self):
        res = cr.cargar_datos_release(self.db, cantidad=5, limpiar=True)
        self.assertEqual(res["eliminados"], 0)
        self.conservados()

    def test_la_carga_es_idempotente(self):
        r1 = cr.cargar_datos_release(self.db, cantidad=40)
        r2 = cr.cargar_datos_release(self.db, cantidad=40)
        self.assertEqual((r1["insertados"], r2["insertados"], r2["actualizados"]), (40, 0, 0))
        self.assertEqual(r2["turnos_release"], 40)

    def test_una_cantidad_invalida_no_escribe_ni_borra(self):
        antes = self.col.count_documents({})
        with self.assertRaises(ValueError):
            cr.cargar_datos_release(self.db, cantidad=0, limpiar=True)
        self.assertEqual(self.col.count_documents({}), antes)

    def test_no_deja_turnos_activos_que_confundan_la_operacion(self):
        cr.cargar_datos_release(self.db, cantidad=100)
        activos = self.col.count_documents({"codigo": {"$regex": "^L-"}, "estado": {"$in": ["pendiente", "llamado", "en_atencion"]}})
        self.assertEqual(activos, 0)


@unittest.skipUnless(HAY_MONGOMOCK, "falta mongomock")
class PruebasDeLaLinea(unittest.TestCase):
    def correr(self, *args):
        salida, error = io.StringIO(), io.StringIO()
        with redirect_stdout(salida), redirect_stderr(error):
            codigo = cr.main(list(args))
        return codigo, salida.getvalue(), error.getvalue()

    def test_limpiar_exige_confirmar(self):
        codigo, _, error = self.correr("--simulado", "--limpiar")
        self.assertEqual(codigo, 2)
        self.assertIn("--confirmar", error)

    def test_una_cantidad_invalida_termina_con_error_controlado(self):
        codigo, _, error = self.correr("--simulado", "--turnos", "0")
        self.assertEqual(codigo, 2)
        self.assertIn("cantidad", error)

    def test_la_salida_indica_la_serie_cargada(self):
        codigo, salida, _ = self.correr("--simulado", "--turnos", "12")
        self.assertEqual(codigo, 0)
        self.assertIn("L-NNN", salida)


if __name__ == "__main__":
    unittest.main()
