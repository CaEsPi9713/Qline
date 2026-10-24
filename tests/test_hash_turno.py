"""TT-011 / TT-012 (lado Redis): Hash temporal `turno:{codigo}` con TTL de 180 s.

Requiere fakeredis y mongomock; si faltan, las pruebas se omiten.
"""

import time
import unittest

from tests.test_ventanilla_unica import AHORA, HAY_DEPENDENCIAS, BaseRedisMongo, doc

if HAY_DEPENDENCIAS:
    from redis.exceptions import ConnectionError as RedisConexion
    from fastapi.testclient import TestClient

    import app.main as main
    from app import cola
    from app.constantes import (
        CLAVE_COLA,
        CLAVE_CONTADOR,
        TTL_ABANDONO_SEG,
        clave_turno,
        clave_ventanilla_actual,
    )
    from app.llamado import llamar_siguiente_turno


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasHashTurno(BaseRedisMongo):
    def test_ttl_oficial_es_180_segundos(self):
        self.assertEqual(TTL_ABANDONO_SEG, 180)

    def test_registrar_llamado_crea_un_hash_con_los_campos_y_el_ttl(self):
        cola.registrar_llamado("A-001", "V-01", "preferencial", ahora_ms=1_000_000)
        clave = clave_turno("A-001")
        self.assertEqual(self.redis.type(clave), "hash")
        datos = self.redis.hgetall(clave)
        self.assertEqual(datos["codigo"], "A-001")
        self.assertEqual(datos["ventanilla"], "V-01")
        self.assertEqual(datos["prioridad"], "preferencial")
        self.assertEqual(int(datos["llamado_ms"]), 1_000_000)
        self.assertEqual(int(datos["vence_ms"]), 1_000_000 + 180_000)
        self.assertTrue(170 < self.redis.ttl(clave) <= 180)

    def test_la_clave_usa_el_namespace_oficial(self):
        self.assertEqual(clave_turno("A-001"), "grupo2:qline:turno:A-001")

    def test_turno_llamado_devuelve_los_datos_y_los_segundos_restantes(self):
        cola.registrar_llamado("A-001", "V-02", "normal")
        t = cola.turno_llamado("A-001")
        self.assertEqual((t["codigo"], t["ventanilla"], t["prioridad"]), ("A-001", "V-02", "normal"))
        self.assertTrue(170 < t["segundos_restantes"] <= 180)
        self.assertEqual(t["vence_ms"] - t["llamado_ms"], 180_000)

    def test_turno_inexistente_no_tiene_hash(self):
        self.assertIsNone(cola.turno_llamado("A-777"))
        self.assertIsNone(cola.segundos_restantes("A-777"))

    def test_el_hash_expira_solo(self):
        cola.registrar_llamado("A-001", "V-01", "normal", ttl=1)
        self.assertIsNotNone(cola.turno_llamado("A-001"))
        time.sleep(1.3)
        self.assertIsNone(cola.turno_llamado("A-001"))
        self.assertIsNone(cola.segundos_restantes("A-001"))
        self.assertFalse(self.redis.exists(clave_turno("A-001")))

    def test_registrar_de_nuevo_reinicia_el_ttl(self):
        cola.registrar_llamado("A-001", "V-01", "normal", ttl=5)
        cola.registrar_llamado("A-001", "V-01", "normal", ttl=100)
        self.assertGreater(self.redis.ttl(clave_turno("A-001")), 90)

    def test_entradas_invalidas(self):
        with self.assertRaises(cola.ColaError):
            cola.registrar_llamado("", "V-01")
        with self.assertRaises(cola.ColaError):
            cola.registrar_llamado("A-001", "V-01", ttl=0)

    def test_confirmar_presencia_elimina_el_hash(self):
        cola.registrar_llamado("A-001", "V-01", "normal")
        self.assertTrue(cola.confirmar_presencia("A-001"))
        self.assertIsNone(cola.turno_llamado("A-001"))
        self.assertFalse(cola.confirmar_presencia("A-001"))        # idempotente

    def test_confirmar_asignacion_deja_ventanilla_y_hash_juntos(self):
        cola.confirmar_asignacion("V-01", "A-001", prioridad="normal")
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-01")), "A-001")
        self.assertEqual(cola.turno_llamado("A-001")["ventanilla"], "V-01")
        self.assertEqual(self.redis.ttl(clave_ventanilla_actual("V-01")), -1)   # la ventanilla no vence

    def test_con_clave_de_prueba_no_se_crea_el_hash(self):
        cola.encolar("A-001", "normal", 1)
        cola.llamar_siguiente("V-01", clave_actual="grupo2:qline:test:ventanilla:V-01:actual")
        self.assertIsNone(cola.turno_llamado("A-001"))


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasHashEnElFlujo(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)

    def test_llamar_crea_el_hash_con_ttl(self):
        self.pendiente("A-001", prioridad="preferencial", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        t = cola.turno_llamado("A-001")
        self.assertEqual((t["ventanilla"], t["prioridad"]), ("V-01", "preferencial"))
        self.assertTrue(0 < t["segundos_restantes"] <= 180)

    def test_el_turno_no_creado_en_la_cola_no_deja_hash(self):
        self.assertIsNone(llamar_siguiente_turno(self.db, "V-01")["codigo"])
        self.assertEqual(self.redis.keys("grupo2:qline:turno:*"), [])

    def test_iniciar_la_atencion_elimina_el_hash(self):
        self.pendiente("A-001", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        self.assertIsNotNone(cola.turno_llamado("A-001"))
        r = self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(cola.turno_llamado("A-001"))             # ya no puede vencer

    def test_iniciar_desde_el_panel_tambien_lo_elimina(self):
        self.pendiente("A-001", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        self.c.post("/panel/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"}, follow_redirects=False)
        self.assertIsNone(cola.turno_llamado("A-001"))

    def test_un_inicio_rechazado_no_toca_el_hash(self):
        self.pendiente("A-001", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        r = self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-02"})
        self.assertEqual(r.status_code, 409)                       # otra ventanilla
        self.assertIsNotNone(cola.turno_llamado("A-001"))

    def test_finalizar_deja_a_redis_sin_estado_del_turno(self):
        self.pendiente("A-001", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertEqual(self.redis.keys("grupo2:qline:turno:*"), [])
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))

    def test_si_redis_falla_al_confirmar_el_turno_queda_llamado_con_aviso(self):
        self.pendiente("A-001", llegada_ms=1)
        original = cola.confirmar_asignacion

        def roto(*a, **k):
            raise RedisConexion("caída simulada")

        cola.confirmar_asignacion = roto
        try:
            r = llamar_siguiente_turno(self.db, "V-01")
        finally:
            cola.confirmar_asignacion = original
        self.assertEqual(r["codigo"], "A-001")
        self.assertIn("estado temporal", r["aviso"])
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "llamado")
        # La ventanilla sigue ocupada por MongoDB aunque falte la clave de Redis.
        self.pendiente("A-002", llegada_ms=2)
        from app.llamado import LlamadoError
        with self.assertRaises(LlamadoError):
            llamar_siguiente_turno(self.db, "V-01")

    def test_el_panel_muestra_la_cuenta_regresiva_del_turno_llamado(self):
        self.pendiente("A-001", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        html = self.c.get("/panel").text
        self.assertIn("Si no se presenta, se marcará como abandonado en", html)

    def test_el_panel_no_muestra_cuenta_regresiva_sin_hash(self):
        self.db["turnos"].insert_one(doc("A-009", "llamado", "V-01", llamado=AHORA))
        self.assertNotIn("Si no se presenta", self.c.get("/panel").text)

    def test_el_panel_no_muestra_cuenta_regresiva_en_atencion(self):
        self.pendiente("A-001", llegada_ms=1)
        llamar_siguiente_turno(self.db, "V-01")
        self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertNotIn("Si no se presenta", self.c.get("/panel").text)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasTresEstructurasRedis(BaseRedisMongo):
    """TT-011: Sorted Set + String + Hash usados de verdad por el flujo."""

    def test_el_flujo_usa_sorted_set_string_y_hash(self):
        self.db["turnos"].insert_one(doc("A-001"))
        self.redis.incr(CLAVE_CONTADOR)                              # String (contador)
        cola.encolar("A-001", "normal", 1)                          # Sorted Set (cola)
        llamar_siguiente_turno(self.db, "V-01")                      # String (ventanilla) + Hash (turno)
        self.assertEqual(self.redis.type(CLAVE_CONTADOR), "string")
        self.assertEqual(self.redis.type(clave_ventanilla_actual("V-01")), "string")
        self.assertEqual(self.redis.type(clave_turno("A-001")), "hash")
        cola.encolar("A-002", "normal", 2)
        self.assertEqual(self.redis.type(CLAVE_COLA), "zset")

    def test_todas_las_claves_estan_en_el_namespace(self):
        self.pendiente("A-001", llegada_ms=1)
        self.redis.incr(CLAVE_CONTADOR)
        llamar_siguiente_turno(self.db, "V-01")
        self.assertTrue(all(k.startswith("grupo2:qline:") for k in self.redis.keys("*")))


if __name__ == "__main__":
    unittest.main()
