"""Regla: una ventanilla atiende un turno a la vez (S2-A, Fase 0 de S3).

Requiere fakeredis (Redis simulado) y mongomock; si faltan, las pruebas se omiten.
"""

import threading
import unittest
from datetime import datetime, timedelta, timezone

try:
    import fakeredis
    import mongomock
    from fastapi.testclient import TestClient

    import app.main as main
    import app.redis_client as redis_client
    from app import cola
    from app.constantes import CLAVE_COLA, clave_ventanilla_actual
    from app.llamado import LlamadoError, llamar_siguiente_turno
    HAY_DEPENDENCIAS = True
except Exception:
    HAY_DEPENDENCIAS = False

AHORA = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)


def doc(codigo, estado="pendiente", ventanilla=None, prioridad="normal", llamado=None):
    return {
        "codigo": codigo, "servicio": "atencion_general", "prioridad": prioridad, "estado": estado,
        "ventanilla": ventanilla, "operador": None,
        "timestamps": {"creado": AHORA - timedelta(minutes=10), "llamado": llamado,
                       "inicio_atencion": None, "finalizado": None, "abandonado": None},
        "metricas": {"espera_seg": None, "atencion_seg": None},
    }


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseRedisMongo(unittest.TestCase):
    def setUp(self):
        self.redis = fakeredis.FakeRedis(decode_responses=True)
        self._cliente_orig, self._db_orig = redis_client._client, main.get_db
        redis_client._client = self.redis
        self.db = mongomock.MongoClient()["grupo2_db"]
        main.get_db = lambda: self.db

    def tearDown(self):
        redis_client._client = self._cliente_orig
        main.get_db = self._db_orig

    def pendiente(self, codigo, prioridad="normal", llegada_ms=1000):
        self.db["turnos"].insert_one(doc(codigo, prioridad=prioridad))
        cola.encolar(codigo, prioridad, llegada_ms)


class PruebasReservaEnRedis(BaseRedisMongo):
    def test_segunda_asignacion_a_la_misma_ventanilla_se_rechaza(self):
        cola.encolar("A-001", "normal", 1)
        cola.encolar("A-002", "normal", 2)
        self.assertEqual(cola.llamar_siguiente("V-01"), "A-001")
        with self.assertRaises(cola.VentanillaOcupada) as ctx:
            cola.llamar_siguiente("V-01")
        self.assertEqual(ctx.exception.codigo, "A-001")
        self.assertEqual(cola.tamano_cola(), 1)               # A-002 no se tocó

    def test_otra_ventanilla_si_puede_llamar(self):
        cola.encolar("A-001", "normal", 1)
        cola.encolar("A-002", "normal", 2)
        self.assertEqual(cola.llamar_siguiente("V-01"), "A-001")
        self.assertEqual(cola.llamar_siguiente("V-02"), "A-002")

    def test_liberada_la_ventanilla_vuelve_a_poder_llamar(self):
        cola.encolar("A-001", "normal", 1)
        cola.encolar("A-002", "normal", 2)
        cola.llamar_siguiente("V-01")
        cola.liberar_ventanilla("V-01")
        self.assertEqual(cola.llamar_siguiente("V-01"), "A-002")

    def test_cola_vacia_no_deja_la_ventanilla_reservada(self):
        self.assertIsNone(cola.llamar_siguiente("V-01"))
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))
        cola.encolar("A-001", "normal", 1)
        self.assertEqual(cola.llamar_siguiente("V-01"), "A-001")

    def test_la_reserva_en_curso_bloquea_y_expira(self):
        self.redis.set(clave_ventanilla_actual("V-01"), cola.RESERVA, ex=cola.TTL_RESERVA_SEG)
        cola.encolar("A-001", "normal", 1)
        with self.assertRaises(cola.VentanillaOcupada) as ctx:
            cola.llamar_siguiente("V-01")
        self.assertIsNone(ctx.exception.codigo)               # otra solicitud está asignando
        self.assertGreater(self.redis.ttl(clave_ventanilla_actual("V-01")), 0)   # no queda bloqueada para siempre

    def test_turno_actual_ignora_la_reserva(self):
        self.redis.set(clave_ventanilla_actual("V-01"), cola.RESERVA)
        self.assertIsNone(cola.turno_actual("V-01"))
        self.redis.set(clave_ventanilla_actual("V-01"), "A-007")
        self.assertEqual(cola.turno_actual("V-01"), "A-007")

    def test_liberar_solo_si_apunta_al_mismo_turno(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-007")
        self.assertFalse(cola.liberar_ventanilla_si("V-01", "A-001"))
        self.assertEqual(cola.turno_actual("V-01"), "A-007")
        self.assertTrue(cola.liberar_ventanilla_si("V-01", "A-007"))

    def test_clic_doble_simultaneo_en_la_misma_ventanilla_asigna_uno_solo(self):
        for i in range(10):
            cola.encolar(f"A-{i + 1:03d}", "normal", i + 1)
        resultados, barrera = [], threading.Barrier(10)

        def intentar():
            barrera.wait()
            try:
                resultados.append(cola.llamar_siguiente("V-01"))
            except cola.VentanillaOcupada:
                resultados.append("ocupada")

        hilos = [threading.Thread(target=intentar) for _ in range(10)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        asignados = [r for r in resultados if r != "ocupada"]
        self.assertEqual(len(asignados), 1)
        self.assertEqual(resultados.count("ocupada"), 9)
        self.assertEqual(cola.tamano_cola(), 9)               # se extrajo exactamente un turno

    def test_tres_ventanillas_simultaneas_reciben_turnos_distintos(self):
        for i in range(6):
            cola.encolar(f"A-{i + 1:03d}", "normal", i + 1)
        resultados, barrera = [], threading.Barrier(6)

        def intentar(v):
            barrera.wait()
            try:
                resultados.append(cola.llamar_siguiente(v))
            except cola.VentanillaOcupada:
                resultados.append("ocupada")

        hilos = [threading.Thread(target=intentar, args=(v,)) for v in ("V-01", "V-02", "V-03") * 2]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        asignados = [r for r in resultados if r != "ocupada"]
        self.assertEqual(len(asignados), 3)
        self.assertEqual(len(set(asignados)), 3)              # 0 duplicados
        self.assertEqual(cola.tamano_cola(), 3)

    def test_fallo_de_redis_al_extraer_libera_la_reserva(self):
        cola.encolar("A-001", "normal", 1)
        original = self.redis.zpopmin

        def roto(*a, **k):
            raise redis_client.redis.exceptions.ConnectionError("caída simulada")

        self.redis.zpopmin = roto
        try:
            with self.assertRaises(redis_client.redis.exceptions.RedisError):
                cola.llamar_siguiente("V-01")
        finally:
            self.redis.zpopmin = original
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))
        self.assertEqual(cola.llamar_siguiente("V-01"), "A-001")


class PruebasLlamarConMongo(BaseRedisMongo):
    def test_segunda_llamada_de_la_misma_ventanilla_da_409_y_no_extrae(self):
        self.pendiente("A-001", llegada_ms=1)
        self.pendiente("A-002", llegada_ms=2)
        r = llamar_siguiente_turno(self.db, "V-01")
        self.assertEqual(r["codigo"], "A-001")
        with self.assertRaises(LlamadoError) as ctx:
            llamar_siguiente_turno(self.db, "V-01")
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("A-001", str(ctx.exception))
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-002"})["estado"], "pendiente")
        self.assertEqual(cola.tamano_cola(), 1)

    def test_otra_ventanilla_sigue_funcionando(self):
        self.pendiente("A-001", llegada_ms=1)
        self.pendiente("A-002", llegada_ms=2)
        llamar_siguiente_turno(self.db, "V-01")
        self.assertEqual(llamar_siguiente_turno(self.db, "V-02")["codigo"], "A-002")

    def test_mongodb_bloquea_aunque_redis_perdio_la_clave(self):
        """Tras una pérdida de Redis, un turno llamado en MongoDB sigue ocupando la ventanilla."""
        self.db["turnos"].insert_one(doc("A-003", "llamado", "V-01", llamado=AHORA))
        self.pendiente("A-004", llegada_ms=1)
        with self.assertRaises(LlamadoError) as ctx:
            llamar_siguiente_turno(self.db, "V-01")
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("A-003", str(ctx.exception))
        self.assertEqual(cola.tamano_cola(), 1)

    def test_en_atencion_tambien_ocupa_la_ventanilla(self):
        self.db["turnos"].insert_one(doc("A-003", "en_atencion", "V-01", llamado=AHORA))
        self.pendiente("A-004", llegada_ms=1)
        with self.assertRaises(LlamadoError) as ctx:
            llamar_siguiente_turno(self.db, "V-01")
        self.assertIn("en atención", str(ctx.exception))

    def test_clave_obsoleta_de_un_turno_ya_atendido_se_repara(self):
        self.db["turnos"].insert_one(doc("A-003", "atendido", "V-01", llamado=AHORA))
        self.redis.set(clave_ventanilla_actual("V-01"), "A-003")     # quedó de una caída
        self.pendiente("A-004", llegada_ms=1)
        self.assertEqual(llamar_siguiente_turno(self.db, "V-01")["codigo"], "A-004")

    def test_clave_de_un_turno_inexistente_se_repara(self):
        self.redis.set(clave_ventanilla_actual("V-01"), "A-999")
        self.pendiente("A-004", llegada_ms=1)
        self.assertEqual(llamar_siguiente_turno(self.db, "V-01")["codigo"], "A-004")

    def test_tras_finalizar_la_ventanilla_puede_llamar_otro(self):
        from app.atencion import finalizar_atencion, iniciar_atencion
        from app.redis_atencion import liberar_turno
        self.pendiente("A-001", llegada_ms=1)
        self.pendiente("A-002", llegada_ms=2)
        llamar_siguiente_turno(self.db, "V-01")
        iniciar_atencion(self.db["turnos"], "A-001", "V-01")
        finalizar_atencion(self.db["turnos"], "A-001", "V-01", al_finalizar=lambda c: liberar_turno(c, "V-01"))
        self.assertEqual(llamar_siguiente_turno(self.db, "V-01")["codigo"], "A-002")

    def test_mongodb_caido_devuelve_el_turno_y_libera_la_ventanilla(self):
        self.pendiente("A-001", llegada_ms=1)
        from pymongo.errors import PyMongoError
        original = self.db["turnos"].find_one_and_update

        class Roto:
            def __getitem__(s, nombre):
                col = self_db[nombre]

                class C:
                    def find_one(c, *a, **k):
                        return col.find_one(*a, **k)

                    def find_one_and_update(c, *a, **k):
                        raise PyMongoError("caída simulada")

                return C()

        self_db = self.db
        with self.assertRaises(LlamadoError) as ctx:
            llamar_siguiente_turno(Roto(), "V-01")
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(cola.tamano_cola(), 1)                      # el turno volvió
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))
        self.assertEqual(llamar_siguiente_turno(self.db, "V-01")["codigo"], "A-001")


class PruebasRutasYVistas(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)

    def test_api_llamar_responde_409_cuando_la_ventanilla_esta_ocupada(self):
        self.pendiente("A-001", llegada_ms=1)
        self.pendiente("A-002", llegada_ms=2)
        self.assertEqual(self.c.post("/api/llamar", data={"ventanilla": "V-01"}).status_code, 200)
        r = self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.assertEqual(r.status_code, 409)
        self.assertFalse(r.json()["ok"])
        self.assertIn("A-001", r.json()["error"])

    def test_formulario_de_cola_muestra_el_error_sin_romperse(self):
        self.pendiente("A-001", llegada_ms=1)
        self.pendiente("A-002", llegada_ms=2)
        self.c.post("/cola/llamar", data={"ventanilla": "V-01"}, follow_redirects=False)
        r = self.c.post("/cola/llamar", data={"ventanilla": "V-01"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("error=", r.headers["location"])

    def test_cola_marca_las_ventanillas_ocupadas_y_solo_ofrece_las_libres(self):
        self.pendiente("A-001", llegada_ms=1)
        self.c.post("/api/llamar", data={"ventanilla": "V-01"})
        html = self.c.get("/cola").text
        self.assertIn("V-01 · ocupada (A-001)", html)
        self.assertIn('<option value="V-02">V-02</option>', html)

    def test_cola_deshabilita_el_boton_si_todas_estan_ocupadas(self):
        for i, v in enumerate(("V-01", "V-02", "V-03"), start=1):
            self.pendiente(f"A-{i:03d}", llegada_ms=i)
            self.c.post("/api/llamar", data={"ventanilla": v})
        html = self.c.get("/cola").text
        self.assertIn("Todas las ventanillas tienen un turno en curso", html)
        self.assertIn("disabled>Llamar siguiente", html)

    def test_panel_muestra_los_turnos_extra_de_una_ventanilla(self):
        """Dos turnos activos en una misma ventanilla (dato heredado): ninguno queda invisible."""
        self.db["turnos"].insert_one(doc("A-010", "en_atencion", "V-01", llamado=AHORA - timedelta(minutes=5)))
        self.db["turnos"].insert_one(doc("A-011", "llamado", "V-01", llamado=AHORA))
        html = self.c.get("/panel").text
        self.assertIn("A-010", html)
        self.assertIn("A-011", html)
        self.assertIn("Otros turnos asignados a V-01", html)
        self.assertIn("V-01 tiene 2 turnos activos", html)
        self.assertIn("Finalizar atención", html)
        self.assertIn("Iniciar atención", html)

    def test_panel_sin_extras_no_muestra_la_seccion(self):
        self.db["turnos"].insert_one(doc("A-010", "llamado", "V-01", llamado=AHORA))
        self.redis.set(clave_ventanilla_actual("V-01"), "A-010")
        self.assertNotIn("Otros turnos asignados", self.c.get("/panel").text)


if __name__ == "__main__":
    unittest.main()
