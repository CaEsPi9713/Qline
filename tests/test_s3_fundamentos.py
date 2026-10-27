"""Fase 1 · cimientos de abandono y recuperación: s3_comun, datos_prueba e informe."""
import unittest
from datetime import datetime, timedelta, timezone

from app import cola, constantes, s3_comun
from app.datos_prueba import construir_mezcla_estados, construir_turno
from app.informe import encabezado
from app.turnos_schema import validar_documento_turno

AHORA = datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc)


class PruebasS3Comun(unittest.TestCase):
    def test_reexporta_los_mismos_objetos_de_constantes(self):
        for nombre in ("ESTADO_LLAMADO", "ESTADO_ABANDONADO", "ESTADO_PENDIENTE", "TTL_ABANDONO_SEG",
                       "ESTADOS", "PRIORIDADES", "VENTANILLAS", "SERVICIO_ID"):
            self.assertIs(getattr(s3_comun, nombre), getattr(constantes, nombre), nombre)

    def test_rango_de_prioridad_coincide_con_la_cola(self):
        for prioridad, nivel in s3_comun.RANGO_PRIORIDAD.items():
            self.assertEqual(cola.calcular_score(prioridad, 0), nivel * cola.ESCALA)

    def test_servicio_inicial(self):
        self.assertEqual(s3_comun.SERVICIO_INICIAL, constantes.SERVICIO_ID)

    def test_errores_tienen_mensaje(self):
        self.assertIn("MongoDB", s3_comun.MongoNoDisponible().mensaje)
        self.assertIn("Redis", s3_comun.RedisNoDisponible().mensaje)
        self.assertEqual(s3_comun.ErrorS3("hola").mensaje, "hola")
        self.assertTrue(issubclass(s3_comun.MongoNoDisponible, s3_comun.ErrorS3))
        self.assertTrue(issubclass(s3_comun.RedisNoDisponible, s3_comun.ErrorS3))

    def test_a_utc(self):
        ingenua = datetime(2026, 1, 1, 12, 0)
        self.assertEqual(s3_comun.a_utc(ingenua).tzinfo, timezone.utc)
        self.assertEqual(s3_comun.a_utc(ingenua).hour, 12)
        otra = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=-6)))
        self.assertEqual(s3_comun.a_utc(otra).hour, 18)
        self.assertEqual(s3_comun.ahora_utc().tzinfo, timezone.utc)


class PruebasDatosPrueba(unittest.TestCase):
    def test_cada_estado_produce_un_documento_valido(self):
        llamado = AHORA - timedelta(minutes=10)
        for estado in constantes.ESTADOS:
            if estado == constantes.ESTADO_PENDIENTE:
                d = construir_turno("A-001", estado, "normal", AHORA - timedelta(hours=1))
            else:
                d = construir_turno("A-001", estado, "normal", AHORA - timedelta(hours=1), "V-01", llamado)
            self.assertTrue(validar_documento_turno(d), estado)

    def test_abandonado_vence_a_los_180_segundos(self):
        llamado = AHORA - timedelta(minutes=10)
        d = construir_turno("A-001", "abandonado", "normal", AHORA - timedelta(hours=1), "V-01", llamado)
        self.assertEqual(d["timestamps"]["abandonado"], llamado + timedelta(seconds=constantes.TTL_ABANDONO_SEG))

    def test_metricas_coherentes(self):
        llamado = AHORA - timedelta(minutes=10)
        creado = llamado - timedelta(seconds=90)
        d = construir_turno("A-001", "atendido", "normal", creado, "V-01", llamado)
        self.assertEqual(d["metricas"]["espera_seg"], 90)
        self.assertEqual(d["metricas"]["atencion_seg"], 120)

    def test_incoherencias_se_rechazan(self):
        with self.assertRaises(ValueError):
            construir_turno("A-001", "inexistente", "normal", AHORA)
        with self.assertRaises(ValueError):
            construir_turno("A-001", "normal", "urgente", AHORA)
        with self.assertRaises(ValueError):
            construir_turno("A-001", "llamado", "normal", AHORA, "V-01")          # sin fecha de llamado
        with self.assertRaises(ValueError):
            construir_turno("A-001", "llamado", "normal", AHORA, "V-99", AHORA)   # ventanilla inválida
        with self.assertRaises(ValueError):
            construir_turno("A-001", "pendiente", "normal", AHORA, "V-01")
        with self.assertRaises(ValueError):
            construir_turno("A-001", "llamado", "normal", AHORA, "V-01", AHORA - timedelta(seconds=1))

    def test_qr_token_opcional(self):
        d = construir_turno("A-001", "pendiente", "normal", AHORA, qr_token="abc")
        self.assertEqual(d["qr_token"], "abc")
        self.assertNotIn("qr_token", construir_turno("A-002", "pendiente", "normal", AHORA))

    def test_mezcla_tiene_los_cinco_estados_y_codigos_ordenados(self):
        docs = construir_mezcla_estados(AHORA, serie="R")
        self.assertEqual({d["estado"] for d in docs}, set(constantes.ESTADOS))
        codigos = [d["codigo"] for d in docs]
        self.assertEqual(codigos, sorted(codigos))
        self.assertEqual(len(set(codigos)), len(codigos))
        self.assertTrue(all(c.startswith("R-") for c in codigos))
        creados = [d["timestamps"]["creado"] for d in docs]
        self.assertEqual(creados, sorted(creados))
        for d in docs:
            self.assertTrue(validar_documento_turno(d), d["codigo"])

    def test_mezcla_incluye_llamado_vencido_y_vigente(self):
        docs = construir_mezcla_estados(AHORA)
        limite = AHORA - timedelta(seconds=constantes.TTL_ABANDONO_SEG)
        llamados = [d["timestamps"]["llamado"] for d in docs if d["estado"] == "llamado"]
        self.assertEqual(len(llamados), 2)
        self.assertEqual(sum(1 for t in llamados if t <= limite), 1)
        self.assertEqual(sum(1 for t in llamados if t > limite), 1)

    def test_mezcla_respeta_cantidad_de_pendientes_y_prioridades(self):
        docs = construir_mezcla_estados(AHORA, pendientes=6)
        pend = [d for d in docs if d["estado"] == "pendiente"]
        self.assertEqual(len(pend), 6)
        self.assertEqual({d["prioridad"] for d in pend}, {"normal", "preferencial"})


class PruebasInforme(unittest.TestCase):
    def test_encabezado_normal(self):
        t = encabezado("Prueba de recuperación")
        self.assertTrue(t.startswith("# Prueba de recuperación"))
        self.assertIn("no se escribe a mano", t)
        self.assertNotIn("SIMULADO", t)

    def test_encabezado_simulado_lo_advierte(self):
        self.assertIn("SIMULADO", encabezado("X", simulado=True))


if __name__ == "__main__":
    unittest.main()
