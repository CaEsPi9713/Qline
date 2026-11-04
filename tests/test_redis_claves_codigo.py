"""TT-027 · El mapa de claves de Redis coincide con lo que el código hace de verdad."""
import re
import unittest
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from app import cola
    from app.constantes import (CLAVE_COLA, CLAVE_CONTADOR, CLAVE_EVENTOS, TTL_ABANDONO_SEG, clave_turno,
                                clave_ventanilla_actual)

DOC = (Path(__file__).resolve().parents[1] / "docs" / "arquitectura" / "redis_claves.md").read_text(encoding="utf-8")


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasMapaContraElCodigo(BaseRedisMongo):
    def test_ttl_de_180_segundos_documentado_y_aplicado(self):
        self.assertEqual(TTL_ABANDONO_SEG, 180)
        self.assertIn("180 s", DOC)
        cola.registrar_llamado("A-001", "V-01", "normal")
        self.assertTrue(0 < self.redis.ttl(clave_turno("A-001")) <= 180)

    def test_los_campos_del_hash_son_los_documentados(self):
        cola.registrar_llamado("A-001", "V-01", "normal")
        campos = set(self.redis.hgetall(clave_turno("A-001")))
        documentados = set(re.findall(r"(?m)^\| `(\w+)` \|", DOC.split("## Estado temporal del turno llamado")[1].split("TTL:")[0]))
        documentados.discard("Campo")
        self.assertEqual(campos, documentados)

    def test_la_reserva_de_la_ventanilla_es_la_documentada(self):
        self.assertEqual(cola.RESERVA, "__asignando__")
        self.assertEqual(cola.TTL_RESERVA_SEG, 10)
        self.assertIn("__asignando__", DOC)
        self.assertIn("10 s", DOC)
        cola.encolar("A-001", "normal", 1)
        cola.reservar_y_extraer("V-04")                       # una ventanilla nueva usa la misma clave
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-04")), "__asignando__")
        self.assertTrue(0 < self.redis.ttl(clave_ventanilla_actual("V-04")) <= 10)

    def test_al_confirmar_el_turno_la_clave_de_la_ventanilla_no_tiene_ttl(self):
        cola.encolar("A-001", "normal", 1)
        cola.llamar_siguiente("V-01")
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-01")), "A-001")
        self.assertEqual(self.redis.ttl(clave_ventanilla_actual("V-01")), -1)

    def test_los_tipos_de_redis_son_los_documentados(self):
        cola.siguiente_codigo()
        cola.encolar("A-001", "normal", 1)
        cola.registrar_llamado("A-001", "V-01", "normal")
        self.assertEqual(self.redis.type(CLAVE_CONTADOR), "string")
        self.assertEqual(self.redis.type(CLAVE_COLA), "zset")
        self.assertEqual(self.redis.type(clave_turno("A-001")), "hash")

    def test_la_prioridad_domina_a_la_llegada_con_la_escala_documentada(self):
        self.assertEqual(cola.ESCALA, 10 ** 13)
        self.assertIn("10¹³", DOC)
        self.assertLess(cola.calcular_score("preferencial", 9_999_999_999_999), cola.calcular_score("normal", 1))

    def test_las_funciones_que_cita_el_documento_existen(self):
        citadas = set(re.findall(r"`(?:cola|redis_atencion)\.(\w+)\(", DOC))
        self.assertGreaterEqual(len(citadas), 5)
        for nombre in citadas:
            self.assertTrue(hasattr(cola, nombre) or nombre == "liberar_turno", nombre)

    def test_el_canal_de_eventos_es_el_documentado(self):
        self.assertEqual(CLAVE_EVENTOS, "grupo2:qline:eventos")
        self.assertIn(CLAVE_EVENTOS, DOC)

    def test_el_documento_afirma_lo_que_no_usa(self):
        for prohibido in ("EVAL", "CONFIG SET", "FLUSHALL", "FLUSHDB"):
            self.assertIn(prohibido, DOC)
        codigo = "".join(p.read_text(encoding="utf-8") for p in (Path(__file__).resolve().parents[1] / "app").glob("*.py"))
        self.assertNotRegex(codigo, r"\.(eval|evalsha|flushall|flushdb)\(")
        self.assertNotRegex(codigo, r"config_set\(")


if __name__ == "__main__":
    unittest.main()
