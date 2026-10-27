"""HU-012 / TT-017 · recuperación de la cola desde MongoDB."""
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    import fakeredis
    import mongomock

    from app import integracion_s3 as integ, main, redis_client
    from app.constantes import CLAVE_COLA, CLAVE_CONTADOR
    from app.datos_prueba import construir_mezcla_estados, construir_turno
    from app.prueba_recuperacion import a_markdown, ejecutar_prueba
    from app.recuperacion import reconciliar_cola

AHORA = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class Base(unittest.TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis(decode_responses=True)
        self._cliente, self._get_db = redis_client._client, main.get_db
        redis_client._client = self.r
        self.db = mongomock.MongoClient()["grupo2_db"]
        main.get_db = lambda: self.db
        self.col = self.db["turnos"]
        self.deps = integ.dependencias_cola(self.r)

    def tearDown(self):
        redis_client._client, main.get_db = self._cliente, self._get_db

    def perder_serie_r(self, deps=None):
        deps = deps or self.deps
        for c in [c for c in deps.leer_cola() if c.startswith("R-")]:
            deps.quitar(c)


class PruebasReconciliar(Base):
    def test_solo_serie_no_toca_otros_turnos(self):
        self.col.insert_many(construir_mezcla_estados(AHORA, serie="R"))
        self.col.insert_one(construir_turno("A-099", "pendiente", "normal", AHORA))
        self.deps.encolar(construir_turno("A-099", "pendiente", "normal", AHORA))      # de la operación real
        rep = reconciliar_cola(self.col, self.deps, aplicar=True, quitar_sobrantes=True,
                               restaurar_contador=False, serie="R", solo_serie=True)
        cola = self.r.zrange(CLAVE_COLA, 0, -1)
        self.assertTrue(rep.ok)
        self.assertIn("A-099", cola)                           # no se quitó como sobrante
        self.assertEqual(rep.sobrantes, [])
        self.assertTrue(all(c.startswith(("R-", "A-099")) for c in cola))

    def test_con_solo_serie_se_ignoran_los_pendientes_de_otras_series(self):
        self.col.insert_many(construir_mezcla_estados(AHORA, serie="A"))
        rep = reconciliar_cola(self.col, self.deps, aplicar=True, restaurar_contador=False,
                               serie="R", solo_serie=True)
        self.assertEqual(rep.esperados, [])
        self.assertEqual(self.r.zcard(CLAVE_COLA), 0)

    def test_perdida_total_con_contador(self):
        docs = construir_mezcla_estados(AHORA, serie="A")
        self.col.insert_many(docs)
        rep = reconciliar_cola(self.col, self.deps, aplicar=True, serie="A")
        self.assertTrue(rep.ok)
        self.assertEqual(int(self.r.get(CLAVE_CONTADOR)), len(docs))
        pend = {d["codigo"] for d in docs if d["estado"] == "pendiente"}
        self.assertEqual(set(self.r.zrange(CLAVE_COLA, 0, -1)), pend)

    def test_preferenciales_primero_y_luego_por_llegada(self):
        self.col.insert_many(construir_mezcla_estados(AHORA, serie="A", pendientes=9))
        reconciliar_cola(self.col, self.deps, aplicar=True, restaurar_contador=False)
        cola = self.r.zrange(CLAVE_COLA, 0, -1)
        prioridad = {d["codigo"]: d["prioridad"] for d in self.col.find({})}
        niveles = [prioridad[c] for c in cola]
        self.assertEqual(niveles, sorted(niveles, key=lambda p: 0 if p == "preferencial" else 1))
        for p in ("preferencial", "normal"):
            del_nivel = [c for c in cola if prioridad[c] == p]
            self.assertEqual(del_nivel, sorted(del_nivel))


class PruebasEjecutarPrueba(Base):
    def prueba(self, **kw):
        return ejecutar_prueba(self.col, self.deps, base=AHORA, perder=self.perder_serie_r, **kw)

    def test_prueba_completa_correcta_y_limpia(self):
        self.col.insert_one(construir_turno("A-050", "pendiente", "normal", AHORA))
        self.deps.encolar(construir_turno("A-050", "pendiente", "normal", AHORA))
        res = self.prueba(pendientes=12)
        self.assertTrue(res.ok, [v for v in res.verificaciones if not v.ok])
        self.assertGreaterEqual(len(res.verificaciones), 8)
        self.assertEqual(self.col.count_documents({"codigo": {"$regex": "^R-"}}), 0)
        self.assertEqual(self.r.zrange(CLAVE_COLA, 0, -1), ["A-050"])      # lo real quedó intacto
        self.assertEqual(self.col.count_documents({"codigo": "A-050"}), 1)

    def test_con_contador_aislado(self):
        clave = "prueba:contador:R"
        deps_c = integ.dependencias_cola(self.r, clave_contador=clave)
        res = self.prueba(pendientes=10, deps_contador=deps_c, perder_contador=lambda: self.r.delete(clave))
        self.assertTrue(res.ok, [v for v in res.verificaciones if not v.ok])
        self.assertEqual(res.contador["restaurado"], res.contador["maximo_mongo"])
        self.assertIsNone(self.r.get(CLAVE_CONTADOR))                        # el contador real no se tocó

    def test_conservar_deja_los_turnos(self):
        self.prueba(pendientes=5, limpiar=False)
        self.assertGreater(self.col.count_documents({"codigo": {"$regex": "^R-"}}), 0)

    def test_detecta_una_recuperacion_que_no_funciona(self):
        malo = integ.dependencias_cola(self.r)
        original = malo.encolar
        sembrando = {"si": True}

        def encolar_roto(turno):            # tras la caída, la recuperación no puede encolar
            if sembrando["si"]:
                original(turno)

        malo.encolar = encolar_roto

        def perder():
            sembrando["si"] = False
            self.perder_serie_r(malo)

        res = ejecutar_prueba(self.col, malo, base=AHORA, perder=perder, pendientes=6)
        self.assertFalse(res.ok)

    def test_informe_markdown(self):
        md = a_markdown(self.prueba(pendientes=6))
        self.assertIn("Verificaciones", md)
        self.assertIn("CORRECTO", md)
        self.assertNotIn("SIMULADO", md)


class PruebasScripts(Base):
    def test_rehidratar_plan_y_aplicar(self):
        from scripts import rehidratar_cola
        self.col.insert_many(construir_mezcla_estados(AHORA, serie="A"))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rehidratar_cola.main([]), 0)
        self.assertEqual(self.r.zcard(CLAVE_COLA), 0)                      # el plan no escribe
        salida = io.StringIO()
        with redirect_stdout(salida):
            self.assertEqual(rehidratar_cola.main(["--aplicar"]), 0)
        self.assertGreater(self.r.zcard(CLAVE_COLA), 0)
        self.assertTrue(json.loads(salida.getvalue())["ok"])

    def test_rehidratar_informe(self):
        from scripts import rehidratar_cola
        self.col.insert_many(construir_mezcla_estados(AHORA, serie="A"))
        ruta = pathlib.Path(tempfile.mkdtemp()) / "r.md"
        with redirect_stdout(io.StringIO()):
            rehidratar_cola.main(["--aplicar", "--informe", str(ruta)])
        self.assertIn("Comparación antes / después", ruta.read_text(encoding="utf-8"))

    def test_rehidratar_no_ofrece_simulado(self):
        from scripts import rehidratar_cola
        with self.assertRaises(SystemExit):
            rehidratar_cola.main(["--simulado"])

    def test_probar_recuperacion(self):
        from scripts import probar_recuperacion
        salida = io.StringIO()
        with redirect_stdout(salida):
            self.assertEqual(probar_recuperacion.main(["--pendientes", "8"]), 0)
        self.assertIn("CORRECTO", salida.getvalue())
        self.assertIsNone(self.r.get(probar_recuperacion.CLAVE_CONTADOR_PRUEBA))


if __name__ == "__main__":
    unittest.main()
