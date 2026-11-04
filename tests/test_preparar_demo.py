"""P07 · preparar_demo comprueba el entorno, es idempotente y no borra nada."""
import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from app import cola
    from app import preparar_demo as pd
    from app.turnos_schema import INDICES_TURNOS
    from scripts import preparar_demo as script


def _cargar_con_upsert(coleccion, docs):
    """Equivale a cargador.cargar: mongomock no soporta bulk_write con ReplaceOne de esta versión de PyMongo."""
    for d in docs:
        coleccion.replace_one({"codigo": d["codigo"]}, d, upsert=True)
    return len(docs)


def _estados(resultados):
    return {r["nombre"]: r["estado"] for r in resultados}


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasPrepararDemo(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        parche = mock.patch("scripts.sinteticos.cargador.cargar", _cargar_con_upsert)
        parche.start()
        self.addCleanup(parche.stop)

    def crear_indices(self):
        for i in INDICES_TURNOS:
            self.db["turnos"].create_index(i["keys"], **i["options"])

    def test_sin_indices_es_un_error_que_dice_cuales_faltan(self):
        r = pd.indices(self.db)
        self.assertEqual(r["estado"], "error")
        self.assertIn("idx_turnos_codigo_unico", r["detalle"])

    def test_con_los_indices_creados_pasa(self):
        self.crear_indices()
        self.assertEqual(pd.indices(self.db)["estado"], "ok")

    def test_una_conexion_caida_es_un_error_y_corta_las_demas_comprobaciones(self):
        redis_caido = mock.Mock()
        redis_caido.ping.side_effect = ConnectionError("Connection refused 127.0.0.1:6379")
        res = pd.preparar(self.db, redis_caido)
        self.assertEqual(_estados(res)["Redis responde"], "error")
        self.assertTrue(pd.hay_errores(res))
        self.assertNotIn("Índices de turnos", _estados(res))
        self.assertNotIn("127.0.0.1", str(res))                      # sin datos de infraestructura

    def test_pocos_sinteticos_es_un_aviso_y_con_cargar_se_completan_sin_duplicar(self):
        self.assertEqual(pd.sinteticos(self.db)["estado"], "aviso")
        self.assertEqual(pd.sinteticos(self.db, cargar=True)["estado"], "ok")
        total = self.db["turnos"].count_documents({})
        pd.sinteticos(self.db, cargar=True)
        self.assertEqual(self.db["turnos"].count_documents({}), total)

    def test_direccion_de_los_qr(self):
        self.assertEqual(pd.direccion_qr("https://grupo2.crnube.net")["estado"], "ok")
        self.assertEqual(pd.direccion_qr("http://localhost:8000")["estado"], "aviso")
        self.assertEqual(pd.direccion_qr("")["estado"], "aviso")

    def test_zona_horaria(self):
        self.assertEqual(pd.zona_horaria("America/Costa_Rica")["estado"], "ok")
        self.assertEqual(pd.zona_horaria("Marte/Olimpo")["estado"], "aviso")

    def test_estado_de_partida_limpio_o_con_actividad(self):
        self.assertEqual(pd.estado_de_partida(self.db)["estado"], "ok")
        self.pendiente("A-001")
        self.assertEqual(pd.estado_de_partida(self.db)["estado"], "aviso")

    def test_en_espera_es_idempotente_y_emite_solo_los_que_faltan(self):
        self.assertEqual(len(pd.asegurar_en_espera(self.db, 4)), 4)
        self.assertEqual(cola.tamano_cola(), 4)
        self.assertEqual(pd.asegurar_en_espera(self.db, 4), [])
        self.assertEqual(len(pd.asegurar_en_espera(self.db, 6)), 2)
        self.assertEqual(cola.tamano_cola(), 6)

    def test_los_turnos_emitidos_incluyen_preferenciales(self):
        emitidos = pd.asegurar_en_espera(self.db, 6)
        self.assertIn("preferencial", {t["prioridad"] for t in emitidos})

    def test_no_borra_turnos_ni_claves_de_redis(self):
        self.crear_indices()
        self.pendiente("A-001")
        self.db["turnos"].insert_one({"codigo": "S-900", "estado": "atendido"})
        self.redis.set("grupo2:qline:ventanilla:V-01:actual", "A-001")
        pd.preparar(self.db, self.redis, en_espera=3, cargar_sinteticos=True, url_base="https://grupo2.crnube.net")
        self.assertIsNotNone(self.db["turnos"].find_one({"codigo": "A-001"}))
        self.assertIsNotNone(self.db["turnos"].find_one({"codigo": "S-900"}))
        self.assertEqual(self.redis.get("grupo2:qline:ventanilla:V-01:actual"), "A-001")

    def test_preparar_dos_veces_deja_el_mismo_estado(self):
        self.crear_indices()
        pd.preparar(self.db, self.redis, en_espera=4)
        turnos = self.db["turnos"].count_documents({})
        cola_antes = cola.tamano_cola()
        pd.preparar(self.db, self.redis, en_espera=4)
        self.assertEqual((self.db["turnos"].count_documents({}), cola.tamano_cola()), (turnos, cola_antes))


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasScript(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        parche = mock.patch("scripts.sinteticos.cargador.cargar", _cargar_con_upsert)
        parche.start()
        self.addCleanup(parche.stop)

    def correr(self, *args):
        salida = io.StringIO()
        with redirect_stdout(salida):
            codigo = script.main(list(args))
        return codigo, salida.getvalue()

    def test_valida_el_rango_de_en_espera(self):
        self.assertEqual(self.correr("--en-espera", "99")[0], 2)

    def test_resume_y_devuelve_error_si_faltan_los_indices(self):
        codigo, texto = self.correr()
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR", texto)
        self.assertIn("La demo NO está lista", texto)

    def test_con_todo_en_orden_devuelve_cero(self):
        for i in INDICES_TURNOS:
            self.db["turnos"].create_index(i["keys"], **i["options"])
        codigo, texto = self.correr("--cargar-sinteticos")
        self.assertEqual(codigo, 0)
        self.assertIn("Lista para la demo", texto)


if __name__ == "__main__":
    unittest.main()
