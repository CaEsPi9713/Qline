"""TT-018: el programa de mediciones cumple el método del plan y no inventa resultados.

Requiere fakeredis, mongomock y httpx; si faltan, las pruebas se omiten.
Las cifras que producen estos motores SIMULADOS no son resultados del proyecto: aquí solo se
comprueba el método, la estructura del informe y la limpieza.
"""

import tempfile
import unittest
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    import app.main as main
    import scripts.medir_rendimiento as mr


class BaseMedicion(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self._verif_orig = mr.verificar_conexion
        mr.verificar_conexion = lambda: {"ok": True, "version": "7.0.15 (simulado)", "host": "127.0.0.1", "port": 6379}
        self.ejecutar = lambda *argumentos: mr.main(["--ejecuciones", "3", "--operaciones", "30", *argumentos])

    def tearDown(self):
        mr.verificar_conexion = self._verif_orig
        super().tearDown()


class PruebasMetodo(BaseMedicion):
    def test_se_exigen_al_menos_tres_ejecuciones(self):
        self.assertEqual(mr.MIN_EJECUCIONES, 3)
        self.assertEqual(mr.main(["--ejecuciones", "2", "--operaciones", "30"]), 2)

    def test_se_exige_un_minimo_de_operaciones_por_ejecucion(self):
        self.assertEqual(mr.main(["--ejecuciones", "3", "--operaciones", "5"]), 2)

    def test_se_miden_tres_operaciones(self):
        self.assertEqual([o[0] for o in mr.OPERACIONES], ["codigo", "encolar", "siguiente"])

    def test_el_resumen_tiene_minimo_maximo_y_mediana_coherentes(self):
        r = mr.resumen([3.0, 1.0, 2.0])
        self.assertEqual((r["ejecuciones"], r["minimo"], r["maximo"], r["mediana"]), (3, 1.0, 3.0, 2.0))
        self.assertLessEqual(r["minimo"], r["mediana"])
        self.assertLessEqual(r["mediana"], r["maximo"])

    def test_cada_medicion_descarta_el_calentamiento(self):
        llamadas = []
        mr.mediana_de_latencias(lambda i: llamadas.append(i), 25)
        self.assertEqual(len(llamadas), mr.CALENTAMIENTO + 25)
        self.assertTrue(all(i < 0 for i in llamadas[:mr.CALENTAMIENTO]))     # el calentamiento no cuenta

    def test_cada_operacion_de_redis_devuelve_una_latencia_positiva(self):
        for clave, *_ in mr.OPERACIONES:
            mr.preparar_redis(self.redis, 30)
            self.assertGreater(mr.medir_redis(self.redis, clave, 30), 0)

    def test_cada_operacion_de_mongodb_devuelve_una_latencia_positiva(self):
        for clave, *_ in mr.OPERACIONES:
            mr.preparar_mongo(self.db)
            self.assertGreater(mr.medir_mongo(self.db, clave, 30), 0)

    def test_la_operacion_siguiente_respeta_la_prioridad_en_ambos_motores(self):
        """Los dos motores entregan primero a los preferenciales (cada cuarto turno) y luego por llegada."""
        mr.sembrar_mongo(self.db[mr.COLECCION_TURNOS], 12)
        desde_mongo = [mr.siguiente_mongo(self.db[mr.COLECCION_TURNOS])["codigo"] for _ in range(12)]
        clave = mr.PREFIJO + "orden"
        mr.sembrar_redis(self.redis, clave, 12)
        desde_redis = [self.redis.zpopmin(clave, 1)[0][0] for _ in range(12)]
        esperado = ["B-3", "B-7", "B-11", "B-0", "B-1", "B-2", "B-4", "B-5", "B-6", "B-8", "B-9", "B-10"]
        self.assertEqual(desde_mongo, esperado)
        self.assertEqual(desde_redis, esperado)                          # misma regla en los dos motores


class PruebasLimpieza(BaseMedicion):
    def test_no_deja_claves_ni_colecciones_de_prueba_y_no_toca_las_reales(self):
        self.redis.set("grupo2:qline:contador:atencion_general", 5)
        self.db["turnos"].insert_one({"codigo": "A-001"})
        self.assertEqual(self.ejecutar(), 0)
        self.assertEqual(self.redis.keys(mr.PREFIJO + "*"), [])
        self.assertNotIn(mr.COLECCION_CONTADOR, self.db.list_collection_names())
        self.assertNotIn(mr.COLECCION_TURNOS, self.db.list_collection_names())
        self.assertEqual(self.redis.get("grupo2:qline:contador:atencion_general"), "5")
        self.assertEqual(self.db["turnos"].count_documents({}), 1)

    def test_limpia_aunque_la_medicion_falle(self):
        original = mr.medir_mongo

        def roto(*a, **k):
            raise RuntimeError("fallo simulado")

        mr.medir_mongo = roto
        try:
            with self.assertRaises(RuntimeError):
                self.ejecutar()
        finally:
            mr.medir_mongo = original
        self.assertEqual(self.redis.keys(mr.PREFIJO + "*"), [])


class PruebasHipotesisEInforme(BaseMedicion):
    @staticmethod
    def _resultados(redis_ms, mongo_ms):
        def r(ms):
            return {"ejecuciones": 3, "minimo": ms * 0.9, "maximo": ms * 1.1, "mediana": ms, "medianas": [ms] * 3}
        return {c: {"redis": r(redis_ms), "mongo": r(mongo_ms) if mongo_ms else None} for c, *_ in mr.OPERACIONES}

    def test_mejora_porcentual(self):
        self.assertAlmostEqual(mr.mejora_pct(1.0, 10.0), 90.0)
        self.assertAlmostEqual(mr.mejora_pct(5.0, 5.0), 0.0)
        self.assertLess(mr.mejora_pct(2.0, 1.0), 0)                       # Redis más lento: negativa

    def test_las_hipotesis_se_contrastan_no_se_asumen(self):
        cumple = mr.evaluar_hipotesis(self._resultados(0.5, 10.0))["codigo"]
        self.assertTrue(cumple["redis_menor_2ms"] and cumple["mejora_mayor_85"])
        no_cumple = mr.evaluar_hipotesis(self._resultados(3.0, 4.0))["codigo"]
        self.assertFalse(no_cumple["redis_menor_2ms"])
        self.assertFalse(no_cumple["mejora_mayor_85"])

    def test_el_informe_dice_que_las_cifras_de_s1_son_hipotesis(self):
        texto = mr.generar_informe({"fecha": "x", "redis": "7", "mongo": "5", "python": "3.12", "sistema": "Linux"},
                                   self._resultados(3.0, 4.0), 5, 200)
        self.assertIn("hipótesis inicial", texto)
        self.assertIn("| no | 25.0 % | no |", texto)                      # 3 ms no es < 2 ms, y 25 % no es > 85 %

    def test_el_informe_reconoce_cuando_redis_no_fue_mas_rapido(self):
        texto = mr.generar_informe({"fecha": "x", "redis": "7", "mongo": "5", "python": "x", "sistema": "x"},
                                   self._resultados(2.0, 1.0), 3, 100)
        self.assertIn("**no** fue más rápido", texto)

    def test_el_informe_contiene_ejecuciones_minimo_maximo_y_mediana(self):
        texto = mr.generar_informe({"fecha": "x", "redis": "7", "mongo": "5", "python": "x", "sistema": "x"},
                                   self._resultados(1.0, 5.0), 5, 200)
        for encabezado in ("Ejecuciones", "Mínimo (ms)", "Máximo (ms)", "Mediana (ms)", "Interpretación"):
            self.assertIn(encabezado, texto)
        self.assertIn("5 ejecuciones", texto.replace("**5 ejecuciones**", "5 ejecuciones"))

    def test_sin_mongodb_el_informe_lo_dice_y_no_inventa_la_comparacion(self):
        texto = mr.generar_informe({"fecha": "x", "redis": "7", "mongo": "no medido", "python": "x", "sistema": "x"},
                                   self._resultados(1.0, None), 3, 100)
        self.assertIn("--solo-redis", texto)
        self.assertIn("no medida", texto)
        self.assertNotIn("MongoDB | find_one_and_update", texto)

    def test_el_programa_escribe_el_informe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "evidencia" / "rendimiento.md"
            self.assertEqual(self.ejecutar("--informe", str(ruta)), 0)
            texto = ruta.read_text(encoding="utf-8")
            self.assertIn("TT-018", texto)
            self.assertIn("INCR", texto)
            self.assertIn("ZPOPMIN", texto)

    def test_solo_redis_no_toca_mongodb(self):
        main.get_db = lambda: self.fail("no debe consultar MongoDB")
        self.assertEqual(self.ejecutar("--solo-redis"), 0)

    def test_si_redis_no_responde_no_inventa_resultados(self):
        mr.verificar_conexion = lambda: {"ok": False, "error": "caída simulada"}
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "x.md"
            self.assertEqual(mr.main(["--ejecuciones", "3", "--operaciones", "30", "--informe", str(ruta)]), 1)
            self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
