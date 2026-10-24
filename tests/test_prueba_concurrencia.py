"""TT-016: la prueba formal de concurrencia funciona, detecta fallos y limpia lo que crea.

Requiere fakeredis, mongomock y httpx; si faltan, las pruebas se omiten.
"""

import tempfile
import time
import unittest
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app import cola
    from app.constantes import CLAVE_COLA, CLAVE_CONTADOR
    import scripts.prueba_concurrencia as pc


class BaseConcurrencia(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self._verif_orig = pc.verificar_conexion
        pc.verificar_conexion = lambda: {"ok": True, "version": "7.0.15 (simulado)", "host": "127.0.0.1", "port": 6379}

    def tearDown(self):
        pc.verificar_conexion = self._verif_orig
        super().tearDown()


class PruebasEscenariosRedis(BaseConcurrencia):
    def test_la_meta_del_plan_son_diez_solicitudes_concurrentes(self):
        self.assertEqual(pc.META_CONSUMIDORES, 10)

    def test_ronda_de_diez_consumidores_sin_duplicados_y_con_prioridad(self):
        x = pc.ronda_redis(self.redis, consumidores=10, turnos=25)
        self.assertTrue(x["ok"], x)
        self.assertEqual((x["asignados"], x["duplicados"], x["errores"]), (10, 0, 0))
        self.assertTrue(x["conjunto_esperado"])
        self.assertEqual(x["cola_restante"], 15)

    def test_varias_rondas_seguidas_siguen_siendo_correctas(self):
        for _ in range(5):
            self.assertTrue(pc.ronda_redis(self.redis)["ok"])

    def test_el_vaciado_competitivo_entrega_cada_turno_una_sola_vez(self):
        x = pc.vaciado_redis(self.redis, consumidores=10, turnos=120)
        self.assertTrue(x["ok"], x)
        self.assertEqual((x["asignados"], x["unicos"], x["duplicados"], x["cola_restante"]), (120, 120, 0, 0))
        self.assertEqual(sum(x["reparto"]), 120)

    def test_la_prueba_limpia_sus_claves_y_no_toca_las_reales(self):
        self.redis.set(CLAVE_CONTADOR, 7)
        cola.encolar("A-001", "normal", 1)
        pc.ronda_redis(self.redis)
        pc.vaciado_redis(self.redis, turnos=30)
        self.assertEqual(self.redis.keys(pc.PREFIJO + "*"), [])
        self.assertEqual(self.redis.get(CLAVE_CONTADOR), "7")
        self.assertEqual(cola.tamano_cola(), 1)                      # la cola real quedó intacta

    def test_limpiar_pruebas_solo_borra_el_prefijo_de_prueba(self):
        self.redis.set(pc.PREFIJO + "x", 1)
        self.redis.set("grupo2:qline:contador:atencion_general", 3)
        self.assertEqual(pc.limpiar_pruebas(self.redis), 1)
        self.assertEqual(self.redis.get("grupo2:qline:contador:atencion_general"), "3")


class PruebasQuePruebaDetectaFallos(BaseConcurrencia):
    """Una prueba que nunca falla no demuestra nada: se comprueba que detecta una asignación no atómica."""

    def test_detecta_duplicados_si_la_extraccion_no_es_atomica(self):
        original = cola.reservar_y_extraer

        def no_atomica(ventanilla, clave_cola=CLAVE_COLA, clave_actual=None, validar_ventanilla=True):
            # Lee el primero, "piensa" un instante y recién entonces lo quita: la carrera clásica.
            primero = self.redis.zrange(clave_cola, 0, 0, withscores=True)
            if not primero:
                return None
            time.sleep(0.02)
            self.redis.zrem(clave_cola, primero[0][0])
            return primero[0]

        cola.reservar_y_extraer = no_atomica
        try:
            x = pc.ronda_redis(self.redis, consumidores=10, turnos=25)
        finally:
            cola.reservar_y_extraer = original
        self.assertFalse(x["ok"])
        self.assertGreater(x["duplicados"], 0)

    def test_no_aprueba_si_hay_menos_turnos_que_consumidores(self):
        x = pc.ronda_redis(self.redis, consumidores=10, turnos=5)
        self.assertFalse(x["ok"])                                    # a 5 consumidores no les tocó nada

    def test_un_error_inesperado_de_un_consumidor_se_cuenta_y_no_se_oculta(self):
        original = cola.reservar_y_extraer

        def con_error(*a, **k):
            raise RuntimeError("fallo simulado")

        cola.reservar_y_extraer = con_error
        try:
            x = pc.ronda_redis(self.redis, consumidores=4, turnos=20)
        finally:
            cola.reservar_y_extraer = original
        self.assertFalse(x["ok"])
        self.assertEqual(x["errores"], 4)


class PruebasFlujoHTTP(BaseConcurrencia):
    def setUp(self):
        super().setUp()
        self.cliente = pc.ClientePrueba(TestClient(main.app))

    def test_flujo_real_de_extremo_a_extremo(self):
        x = pc.flujo_http(self.cliente, self.db, self.redis, rondas=3)
        self.assertTrue(x["ok"], x)
        self.assertEqual(len(x["rondas"]), 3)
        for ronda in x["rondas"]:
            self.assertEqual((ronda["solicitudes"], ronda["asignados"], ronda["rechazados_409"], ronda["duplicados"]),
                             (10, 3, 7, 0))
            self.assertTrue(ronda["prioridad_respetada"] and ronda["mongo_ok"] and ronda["redis_ok"] and ronda["ciclo_completo"])

    def test_la_primera_ronda_asigna_los_preferenciales_aunque_se_emitieron_al_final(self):
        x = pc.flujo_http(self.cliente, self.db, self.redis, rondas=1)
        # Había 4 preferenciales emitidos al final: los 3 primeros asignados son preferenciales.
        self.assertEqual(len(x["rondas"][0]["codigos"]), 3)
        self.assertTrue(set(x["rondas"][0]["codigos"]) <= set(x["orden_esperado"][:3]))

    def test_limpia_los_turnos_y_las_claves_que_creo(self):
        pc.flujo_http(self.cliente, self.db, self.redis, rondas=2)
        self.assertEqual(self.db["turnos"].count_documents({}), 0)
        self.assertEqual(cola.tamano_cola(), 0)
        self.assertEqual(self.redis.keys("grupo2:qline:turno:*"), [])
        self.assertEqual(self.redis.keys("grupo2:qline:ventanilla:*"), [])

    def test_se_niega_a_correr_con_la_cola_ocupada(self):
        cola.encolar("A-001", "normal", 1)
        with self.assertRaises(SystemExit):
            pc.flujo_http(self.cliente, self.db, self.redis, rondas=1)
        self.assertEqual(cola.tamano_cola(), 1)                      # no tocó nada

    def test_se_niega_a_correr_con_una_ventanilla_ocupada(self):
        self.db["turnos"].insert_one({"codigo": "A-001", "estado": "llamado", "ventanilla": "V-01"})
        with self.assertRaises(SystemExit):
            pc.flujo_http(self.cliente, self.db, self.redis, rondas=1)


class PruebasInformeYPrograma(BaseConcurrencia):
    def _resultados(self):
        rondas = [pc.ronda_redis(self.redis) for _ in range(3)]
        return rondas, pc.vaciado_redis(self.redis, turnos=60)

    def test_el_informe_resume_lo_ejecutado(self):
        rondas, vaciado = self._resultados()
        texto = pc.generar_informe({"fecha": "2026-10-25 12:00:00", "redis": "7.0.15", "python": "3.12", "sistema": "Linux"},
                                   rondas, vaciado)
        self.assertIn("0 turnos duplicados", texto)
        self.assertIn("Escenario A", texto)
        self.assertIn("Escenario B", texto)
        self.assertNotIn("Escenario C", texto)                      # no se ejecutó: no se menciona como hecho
        self.assertEqual(texto.count("| OK |"), 4)

    def test_el_informe_marca_la_falla_si_la_hay(self):
        rondas, vaciado = self._resultados()
        rondas[1]["duplicados"], rondas[1]["ok"] = 2, False
        texto = pc.generar_informe({"fecha": "x", "redis": "x", "python": "x", "sistema": "x"}, rondas, vaciado)
        self.assertIn("**FALLA**", texto)
        self.assertIn("2 turnos duplicados", texto)

    def test_el_informe_incluye_el_escenario_http_cuando_se_ejecuta(self):
        rondas, vaciado = self._resultados()
        http = pc.flujo_http(pc.ClientePrueba(TestClient(main.app)), self.db, self.redis, rondas=2)
        texto = pc.generar_informe({"fecha": "x", "redis": "x", "python": "x", "sistema": "x"}, rondas, vaciado, http)
        self.assertIn("Escenario C", texto)
        self.assertIn("POST /api/llamar", texto)

    def test_el_programa_termina_bien_y_escribe_el_informe(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "evidencia" / "concurrencia.md"
            codigo = pc.main(["--rondas", "3", "--turnos-vaciado", "50", "--informe", str(ruta)])
            self.assertEqual(codigo, 0)
            self.assertIn("0 turnos duplicados", ruta.read_text(encoding="utf-8"))

    def test_el_programa_rechaza_parametros_invalidos(self):
        self.assertEqual(pc.main(["--rondas", "0"]), 2)
        self.assertEqual(pc.main(["--consumidores", "1"]), 2)
        self.assertEqual(pc.main(["--consumidores", "10", "--turnos-vaciado", "5"]), 2)

    def test_detecta_un_cola_py_desactualizado_y_lo_dice_sin_ejecutar_nada(self):
        original = cola.extraer_siguiente

        def version_vieja(ventanilla, clave_cola=CLAVE_COLA, clave_actual=None):   # sin validar_ventanilla
            return original(ventanilla, clave_cola, clave_actual)

        cola.extraer_siguiente = version_vieja
        try:
            with tempfile.TemporaryDirectory() as carpeta:
                ruta = Path(carpeta) / "x.md"
                self.assertEqual(pc.main(["--informe", str(ruta)]), 2)
                self.assertFalse(ruta.exists())
        finally:
            cola.extraer_siguiente = original

    def test_los_errores_de_los_consumidores_se_explican_en_el_informe(self):
        original = cola.reservar_y_extraer

        def con_error(*a, **k):
            raise TypeError("got an unexpected keyword argument")

        cola.reservar_y_extraer = con_error
        try:
            rondas = [pc.ronda_redis(self.redis, consumidores=3, turnos=10)]
            vaciado = pc.vaciado_redis(self.redis, consumidores=3, turnos=10)
        finally:
            cola.reservar_y_extraer = original
        self.assertIn("TypeError", rondas[0]["error_ejemplo"])
        texto = pc.generar_informe({"fecha": "x", "redis": "x", "python": "x", "sistema": "x"}, rondas, vaciado)
        self.assertIn("Primer error de un consumidor", texto)
        self.assertIn("TypeError", texto)
        self.assertIn("**FALLA**", texto)

    def test_si_redis_no_responde_no_inventa_resultados(self):
        pc.verificar_conexion = lambda: {"ok": False, "error": "caída simulada"}
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "x.md"
            self.assertEqual(pc.main(["--informe", str(ruta)]), 1)
            self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
