"""Fase 1 · adaptadores de abandono y recuperación sobre Redis y MongoDB (simulados)."""
import json
import threading
import unittest
from datetime import datetime, timedelta, timezone

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    import fakeredis
    import mongomock

    from app import cola, integracion_s3 as integ, redis_client
    from app.abandono import barrer_abandonos
    from app.constantes import CLAVE_COLA, CLAVE_CONTADOR, CLAVE_EVENTOS, clave_turno, clave_ventanilla_actual
    from app.datos_prueba import construir_mezcla_estados, construir_turno
    from app.recuperacion import reconciliar_cola
    from app.s3_comun import RedisNoDisponible

AHORA = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseAdaptadores(unittest.TestCase):
    def setUp(self):
        self.r = fakeredis.FakeRedis(decode_responses=True)
        self._orig = redis_client._client
        redis_client._client = self.r
        self.col = mongomock.MongoClient()["grupo2_db"]["turnos"]

    def tearDown(self):
        redis_client._client = self._orig


class PruebasAbandono(BaseAdaptadores):
    def test_hash_existe(self):
        d = integ.dependencias_abandono(self.r)
        self.assertFalse(d["hash_existe"]("A-001"))
        self.r.hset(clave_turno("A-001"), "estado", "llamado")
        self.assertTrue(d["hash_existe"]("A-001"))

    def test_liberar_solo_si_apunta_al_mismo_turno(self):
        d = integ.dependencias_abandono(self.r)
        clave = clave_ventanilla_actual("V-01")
        self.r.set(clave, "A-002")
        d["liberar_ventanilla"]("V-01", "A-001")
        self.assertEqual(self.r.get(clave), "A-002")
        d["liberar_ventanilla"]("V-01", "A-002")
        self.assertIsNone(self.r.get(clave))

    def test_publica_el_evento_oficial(self):
        ps = self.r.pubsub()
        ps.subscribe(CLAVE_EVENTOS)
        ps.get_message(timeout=1)
        integ.dependencias_abandono(self.r)["publicar_evento"]("turno_abandonado", {"codigo": "A-001", "ventanilla": "V-01"})
        msg = ps.get_message(timeout=1)
        evento = json.loads(msg["data"])
        self.assertEqual((evento["tipo"], evento["codigo"], evento["ventanilla"]),
                         ("turno_abandonado", "A-001", "V-01"))

    def test_fallo_de_redis_se_informa(self):
        class Rota:
            def exists(self, *a): raise integ.RedisError("x")
            def get(self, *a): raise integ.RedisError("x")
            def publish(self, *a): raise integ.RedisError("x")
        d = integ.dependencias_abandono(Rota())
        for f, args in ((d["hash_existe"], ("A-1",)), (d["liberar_ventanilla"], ("V-01", "A-1")),
                        (d["publicar_evento"], ("turno_abandonado", {"codigo": "A-1"}))):
            with self.assertRaises(RedisNoDisponible):
                f(*args)

    def test_barrido_completo_con_los_adaptadores(self):
        llamado = AHORA - timedelta(seconds=200)
        self.col.insert_one(construir_turno("A-001", "llamado", "normal", llamado - timedelta(minutes=2), "V-01", llamado))
        self.r.set(clave_ventanilla_actual("V-01"), "A-001")      # el Hash ya expiró: no existe
        res = barrer_abandonos(self.col, ahora=AHORA, **integ.dependencias_abandono(self.r))
        self.assertEqual(res.abandonados, ["A-001"])
        self.assertTrue(res.ok)
        self.assertEqual(self.col.find_one({"codigo": "A-001"})["estado"], "abandonado")
        self.assertIsNone(self.r.get(clave_ventanilla_actual("V-01")))

    def test_barrido_respeta_hash_vigente(self):
        llamado = AHORA - timedelta(seconds=200)
        self.col.insert_one(construir_turno("A-001", "llamado", "normal", llamado - timedelta(minutes=2), "V-01", llamado))
        self.r.hset(clave_turno("A-001"), "estado", "llamado")
        res = barrer_abandonos(self.col, ahora=AHORA, **integ.dependencias_abandono(self.r))
        self.assertEqual(res.omitidos_vigentes, ["A-001"])
        self.assertEqual(self.col.find_one({"codigo": "A-001"})["estado"], "llamado")


class PruebasCola(BaseAdaptadores):
    def test_encolar_equivale_a_cola_encolar(self):
        creado = AHORA - timedelta(minutes=3)
        turno = construir_turno("A-001", "pendiente", "preferencial", creado)
        deps = integ.dependencias_cola(self.r)
        deps.encolar(turno)
        score = self.r.zscore(CLAVE_COLA, "A-001")
        cola.encolar("A-002", "preferencial", integ.milisegundos(creado))
        self.assertEqual(score, self.r.zscore(CLAVE_COLA, "A-002"))

    def test_encolar_no_reordena_ni_duplica(self):
        deps = integ.dependencias_cola(self.r)
        turno = construir_turno("A-001", "pendiente", "normal", AHORA)
        deps.encolar(turno)
        antes = self.r.zscore(CLAVE_COLA, "A-001")
        turno["timestamps"]["creado"] = AHORA + timedelta(hours=1)
        deps.encolar(turno)
        self.assertEqual(self.r.zscore(CLAVE_COLA, "A-001"), antes)
        self.assertEqual(self.r.zcard(CLAVE_COLA), 1)

    def test_leer_y_quitar(self):
        deps = integ.dependencias_cola(self.r)
        for i, p in enumerate(("normal", "preferencial", "normal"), start=1):
            deps.encolar(construir_turno(f"A-{i:03d}", "pendiente", p, AHORA + timedelta(seconds=i)))
        self.assertEqual(deps.leer_cola(), ["A-002", "A-001", "A-003"])
        deps.quitar("A-001")
        self.assertEqual(deps.leer_cola(), ["A-002", "A-003"])

    def test_contador_solo_sube(self):
        deps = integ.dependencias_cola(self.r)
        self.assertEqual(deps.leer_contador(), 0)
        deps.fijar_contador(10)
        self.assertEqual(deps.leer_contador(), 10)
        deps.fijar_contador(4)
        self.assertEqual(deps.leer_contador(), 10)

    def test_contador_concurrente_queda_en_el_maximo(self):
        deps = integ.dependencias_cola(self.r)
        hilos = [threading.Thread(target=deps.fijar_contador, args=(v,)) for v in range(1, 41)]
        for h in hilos: h.start()
        for h in hilos: h.join()
        self.assertEqual(deps.leer_contador(), 40)

    def test_claves_aisladas(self):
        deps = integ.dependencias_cola(self.r, clave_cola="prueba:cola", clave_contador="prueba:contador")
        deps.encolar(construir_turno("A-001", "pendiente", "normal", AHORA))
        deps.fijar_contador(7)
        self.assertEqual(self.r.zcard("prueba:cola"), 1)
        self.assertEqual(self.r.zcard(CLAVE_COLA), 0)
        self.assertIsNone(self.r.get(CLAVE_CONTADOR))

    def test_milisegundos_son_enteros_exactos(self):
        f = datetime(2026, 10, 24, 15, 0, 0, 123000, tzinfo=timezone.utc)
        self.assertEqual(integ.milisegundos(f), int(f.timestamp() * 1000))
        self.assertIsInstance(integ.milisegundos(f), int)
        self.assertEqual(integ.milisegundos(f.replace(tzinfo=None)), integ.milisegundos(f))

    def test_reconciliacion_reconstruye_la_cola_perdida(self):
        for d in construir_mezcla_estados(AHORA):
            self.col.insert_one(d)
        esperados = [d["codigo"] for d in self.col.find({"estado": "pendiente"})]
        rep = reconciliar_cola(self.col, integ.dependencias_cola(self.r), aplicar=True,
                               quitar_sobrantes=False, restaurar_contador=True, serie="A")
        self.assertEqual(rep.errores, [])
        self.assertEqual(sorted(self.r.zrange(CLAVE_COLA, 0, -1)), sorted(esperados))
        self.assertGreaterEqual(int(self.r.get(CLAVE_CONTADOR)), int(max(esperados)[2:]))


class PruebasImportacion(unittest.TestCase):
    def test_modulos_de_abandono_y_recuperacion_se_importan(self):
        import app.abandono, app.barrido, app.recuperacion   # noqa: F401


if __name__ == "__main__":
    unittest.main()
