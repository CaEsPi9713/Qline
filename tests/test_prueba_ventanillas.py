"""La evidencia de P09 (que se ejecuta en el servidor) funciona con una base simulada, limpia lo que crea y distingue el límite del motor."""
import unittest

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from app import prueba_ventanillas as pv
    from app import ventanillas


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasEvidenciaVentanillas(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        ventanillas._ULTIMAS_CONOCIDAS = ventanillas.VENTANILLAS

    def test_los_casos_de_la_aplicacion_cumplen(self):
        resultados, _ = pv.ejecutar(self.db)
        self.assertEqual([r["caso"] for r in resultados if not r["ok"]], [])
        self.assertFalse(pv.hay_fallos_de_aplicacion(resultados))

    def test_no_deja_nada_y_no_toca_turnos_reales(self):
        self.db["turnos"].insert_one({"codigo": "A-001", "marca": "real"})
        pv.ejecutar(self.db)
        self.assertEqual(self.db["turnos"].count_documents({"codigo": pv.CODIGO_PRUEBA}), 0)
        self.assertIsNone(self.db["ventanillas"].find_one({"codigo": pv.VENTANILLA_PRUEBA}))
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["marca"], "real")

    def test_si_la_ventanilla_ya_existia_no_se_borra(self):
        self.db["ventanillas"].insert_one({"codigo": pv.VENTANILLA_PRUEBA, "estado": "activa", "nombre": "previa"})
        pv.ejecutar(self.db)
        self.assertIsNotNone(self.db["ventanillas"].find_one({"codigo": pv.VENTANILLA_PRUEBA}))

    def test_un_motor_que_rechaza_se_informa_como_limite_y_no_como_fallo(self):
        class Rechaza:
            def __init__(self, col):
                self.col = col

            def __getattr__(self, nombre):
                return getattr(self.col, nombre)

            def insert_one(self, doc):
                from pymongo.errors import WriteError
                raise WriteError("Document failed validation", code=121)

        class Db:
            def __init__(self, db):
                self.db = db

            def __getitem__(self, nombre):
                col = self.db[nombre]
                return Rechaza(col) if nombre == "turnos" else col

        resultados, veredicto = pv.ejecutar(Db(self.db))
        self.assertIn("RECHAZA", veredicto)
        self.assertFalse(pv.hay_fallos_de_aplicacion(resultados))
        md = pv.a_markdown(resultados, veredicto)
        self.assertIn("OK CON LÍMITE", md)
        self.assertIn("collMod", md)

    def test_con_un_motor_que_acepta_el_informe_es_ok(self):
        resultados, veredicto = pv.ejecutar(self.db)           # mongomock no aplica validadores
        self.assertIn("ACEPTA", veredicto)
        self.assertIn("**OK**", pv.a_markdown(resultados, veredicto))


if __name__ == "__main__":
    unittest.main()
