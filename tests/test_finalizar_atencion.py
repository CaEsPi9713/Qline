"""Pruebas de HU-007 · Finalizar atención (casos PF-01 ... PF-14 del plan).

    python -m unittest discover -s tests -t . -v
"""

import threading
import unittest
from datetime import datetime, timezone

from app.atencion import calcular_atencion_seg, finalizar_atencion, iniciar_atencion
from app.excepciones import (
    DatosInvalidos,
    ServicioNoDisponible,
    TransicionNoPermitida,
    TurnoInconsistente,
    TurnoNoEncontrado,
    VentanillaNoCoincide,
)

from .fakes import ColeccionFalsa, turno, utc


class PruebasFinalizarAtencion(unittest.TestCase):
    def setUp(self):
        self.col = ColeccionFalsa([
            turno("A-030", "en_atencion", "V-01", inicio=utc(14, 10)),   # caso feliz
            turno("A-031", "llamado", "V-01"),                           # nunca inició
            turno("A-032", "pendiente", None),
            turno("A-033", "atendido", "V-01", inicio=utc(14, 10)),
            turno("A-034", "abandonado", "V-03"),
            turno("A-035", "en_atencion", "V-02", inicio=utc(14, 12)),   # otra ventanilla
            turno("A-036", "en_atencion", "V-01", inicio=None),          # inconsistente
        ])
        self.col.docs["A-033"]["timestamps"]["finalizado"] = utc(14, 14)
        self.col.docs["A-033"]["metricas"]["atencion_seg"] = 240

    # PF-01
    def test_pf01_finaliza_turno_en_atencion(self):
        fin = utc(14, 14)
        r = finalizar_atencion(self.col, "A-030", "V-01", ahora=fin)
        doc = self.col.docs["A-030"]
        self.assertEqual(r["estado"], "atendido")
        self.assertEqual(doc["estado"], "atendido")
        self.assertEqual(doc["timestamps"]["finalizado"], fin)
        self.assertEqual(doc["metricas"]["atencion_seg"], 240)   # 14:10 -> 14:14
        self.assertEqual(doc["ventanilla"], "V-01")
        self.assertEqual(doc["timestamps"]["inicio_atencion"], utc(14, 10))  # no se pierde historial

    # PF-02
    def test_pf02_no_finaliza_turno_que_nunca_inicio(self):
        with self.assertRaises(TransicionNoPermitida):
            finalizar_atencion(self.col, "A-031", "V-01")
        self.assertEqual(self.col.docs["A-031"]["estado"], "llamado")

    # PF-03, PF-05
    def test_pf03_05_rechaza_pendiente_y_abandonado(self):
        for codigo, v in (("A-032", "V-01"), ("A-034", "V-03")):
            with self.subTest(codigo=codigo):
                estado = self.col.docs[codigo]["estado"]
                with self.assertRaises(TransicionNoPermitida):
                    finalizar_atencion(self.col, codigo, v)
                self.assertEqual(self.col.docs[codigo]["estado"], estado)

    # PF-04
    def test_pf04_no_sobrescribe_turno_ya_atendido(self):
        with self.assertRaises(TransicionNoPermitida):
            finalizar_atencion(self.col, "A-033", "V-01", ahora=utc(15, 0))
        doc = self.col.docs["A-033"]
        self.assertEqual(doc["timestamps"]["finalizado"], utc(14, 14))
        self.assertEqual(doc["metricas"]["atencion_seg"], 240)

    # PF-06
    def test_pf06_turno_inexistente(self):
        with self.assertRaises(TurnoNoEncontrado):
            finalizar_atencion(self.col, "A-999", "V-01")

    # PF-07
    def test_pf07_ventanilla_no_coincide(self):
        with self.assertRaises(VentanillaNoCoincide):
            finalizar_atencion(self.col, "A-035", "V-01")
        self.assertEqual(self.col.docs["A-035"]["estado"], "en_atencion")

    # PF-08
    def test_pf08_ventanilla_invalida(self):
        for v in ("V-09", "", None, "v-01"):
            with self.subTest(ventanilla=v):
                with self.assertRaises(DatosInvalidos):
                    finalizar_atencion(self.col, "A-030", v)

    # PF-09
    def test_pf09_codigo_invalido(self):
        for c in ("", "XYZ", None, "A030", 30):
            with self.subTest(codigo=c):
                with self.assertRaises(DatosInvalidos):
                    finalizar_atencion(self.col, c, "V-01")

    # PF-10
    def test_pf10_reintento_no_duplica_finalizacion(self):
        finalizar_atencion(self.col, "A-030", "V-01", ahora=utc(14, 14))
        with self.assertRaises(TransicionNoPermitida):
            finalizar_atencion(self.col, "A-030", "V-01", ahora=utc(15, 0))
        self.assertEqual(self.col.docs["A-030"]["timestamps"]["finalizado"], utc(14, 14))

    # PF-11
    def test_pf11_finalizacion_simultanea_solo_una_gana(self):
        resultados, barrera = [], threading.Barrier(10)

        def intentar():
            barrera.wait()
            try:
                finalizar_atencion(self.col, "A-030", "V-01")
                resultados.append("ok")
            except TransicionNoPermitida:
                resultados.append("rechazado")

        hilos = [threading.Thread(target=intentar) for _ in range(10)]
        for h in hilos: h.start()
        for h in hilos: h.join()
        self.assertEqual(resultados.count("ok"), 1)
        self.assertEqual(resultados.count("rechazado"), 9)

    # PF-12
    def test_pf12_mongodb_no_disponible(self):
        self.col.falla = True
        with self.assertRaises(ServicioNoDisponible):
            finalizar_atencion(self.col, "A-030", "V-01")

    # PF-13
    def test_pf13_turno_sin_inicio_registrado(self):
        with self.assertRaises(TurnoInconsistente):
            finalizar_atencion(self.col, "A-036", "V-01")
        self.assertEqual(self.col.docs["A-036"]["estado"], "en_atencion")

    # PF-14
    def test_pf14_gancho_redis_se_invoca_solo_si_finaliza(self):
        llamados = []
        finalizar_atencion(self.col, "A-030", "V-01", ahora=utc(14, 14), al_finalizar=llamados.append)
        self.assertEqual(llamados, ["A-030"])
        with self.assertRaises(TransicionNoPermitida):
            finalizar_atencion(self.col, "A-031", "V-01", al_finalizar=llamados.append)
        self.assertEqual(llamados, ["A-030"])

    def test_calculo_atencion_seg_con_fecha_sin_zona(self):
        # PyMongo devuelve datetimes sin zona (UTC) por defecto
        self.assertEqual(calcular_atencion_seg(datetime(2026, 10, 18, 14, 10), utc(14, 14)), 240)

    def test_flujo_iniciar_y_finalizar(self):
        """HU-006 + HU-007: llamado -> en_atencion -> atendido."""
        self.col.docs["A-040"] = turno("A-040", "llamado", "V-02")
        iniciar_atencion(self.col, "A-040", "V-02", ahora=utc(15, 0))
        r = finalizar_atencion(self.col, "A-040", "V-02", ahora=utc(15, 5, 30))
        self.assertEqual(r["estado"], "atendido")
        self.assertEqual(r["atencion_seg"], 330)


if __name__ == "__main__":
    unittest.main()
