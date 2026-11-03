"""P02 · Desglose por fecha del dashboard: días en hora local, indicadores por día, rango de fechas y avisos."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.dashboard import calcular_metricas_dashboard, desglose_por_fecha


def turno(codigo, creado, estado="atendido", espera=100, atencion=60, servicio="atencion_general"):
    return {"codigo": codigo, "servicio": servicio, "prioridad": "normal", "estado": estado, "ventanilla": "V-01",
            "timestamps": {"creado": creado, "llamado": None, "inicio_atencion": None, "finalizado": None, "abandonado": None},
            "metricas": {"espera_seg": espera if estado != "pendiente" else None,
                         "atencion_seg": atencion if estado == "atendido" else None}}


def utc(dia, hora, minuto=0, mes=10):
    return datetime(2026, mes, dia, hora, minuto, tzinfo=timezone.utc)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDelDesglose(BaseRedisMongo):
    def insertar(self, *turnos):
        self.db["turnos"].insert_many(list(turnos))

    def test_agrupa_por_dia_en_hora_local_y_no_en_utc(self):
        # 28/10 03:00 UTC = 27/10 21:00 en Costa Rica (UTC-6); 28/10 06:00 UTC = 28/10 00:00 local
        self.insertar(turno("A-001", utc(28, 3)), turno("A-002", utc(28, 6)), turno("A-003", utc(28, 18)))
        dias = {d["fecha"]: d["total"] for d in desglose_por_fecha(self.db, zona="America/Costa_Rica")["dias"]}
        self.assertEqual(dias, {"2026-10-27": 1, "2026-10-28": 2})

    def test_con_utc_el_mismo_turno_cae_en_otro_dia(self):
        self.insertar(turno("A-001", utc(28, 3)))
        self.assertEqual([d["fecha"] for d in desglose_por_fecha(self.db, zona="UTC")["dias"]], ["2026-10-28"])

    def test_indicadores_de_un_dia(self):
        self.insertar(
            turno("A-001", utc(28, 15), "atendido", espera=100, atencion=60),
            turno("A-002", utc(28, 16), "atendido", espera=500, atencion=120),
            turno("A-003", utc(28, 17), "abandonado", espera=200, atencion=None),
            turno("A-004", utc(28, 18), "pendiente"),
        )
        dia = desglose_por_fecha(self.db, sla_espera_max_seg=300, zona="America/Costa_Rica")["dias"][0]
        self.assertEqual((dia["total"], dia["atendidos"], dia["abandonados"], dia["en_proceso"]), (4, 2, 1, 1))
        self.assertEqual(dia["tasa_abandono"], 25.0)
        self.assertEqual(dia["espera_seg"], round((100 + 500 + 200) / 3, 1))
        self.assertEqual(dia["atencion_seg"], 90.0)
        self.assertEqual(dia["sla_pct"], round(2 / 3 * 100, 1))                  # 100 y 200 cumplen 300 s; 500 no
        self.assertEqual(dia["sla_estado"], "INCUMPLIDO")
        self.assertEqual(dia["fecha_legible"], "28/10/2026")

    def test_el_umbral_de_sla_cambia_el_cumplimiento_del_dia(self):
        self.insertar(turno("A-001", utc(28, 15), espera=400), turno("A-002", utc(28, 16), espera=500))
        self.assertEqual(desglose_por_fecha(self.db, 300)["dias"][0]["sla_estado"], "INCUMPLIDO")
        self.assertEqual(desglose_por_fecha(self.db, 600)["dias"][0]["sla_estado"], "CUMPLIDO")

    def test_sin_rango_muestra_los_ultimos_dias_con_datos(self):
        for n in range(1, 21):
            self.insertar(turno(f"A-{n:03d}", utc(n, 15)))
        res = desglose_por_fecha(self.db, max_dias=14)
        self.assertEqual(len(res["dias"]), 14)
        self.assertEqual((res["dias"][0]["fecha"], res["dias"][-1]["fecha"]), ("2026-10-07", "2026-10-20"))

    def test_rango_incluye_ambos_extremos_en_hora_local(self):
        for n in (10, 11, 12, 13):
            self.insertar(turno(f"A-{n}", utc(n, 15)))
        res = desglose_por_fecha(self.db, fecha_desde="2026-10-11", fecha_hasta="2026-10-12")
        self.assertEqual([d["fecha"] for d in res["dias"]], ["2026-10-11", "2026-10-12"])
        self.assertEqual(res["rango"], {"desde": "2026-10-11", "hasta": "2026-10-12"})

    def test_solo_desde_o_solo_hasta(self):
        for n in (10, 11, 12):
            self.insertar(turno(f"A-{n}", utc(n, 15)))
        self.assertEqual(len(desglose_por_fecha(self.db, fecha_desde="2026-10-11")["dias"]), 2)
        self.assertEqual(len(desglose_por_fecha(self.db, fecha_hasta="2026-10-10")["dias"]), 1)

    def test_fechas_invalidas_se_ignoran_con_aviso(self):
        self.insertar(turno("A-001", utc(10, 15)))
        res = desglose_por_fecha(self.db, fecha_desde="no-es-fecha", fecha_hasta="2026-13-45")
        self.assertEqual(len(res["dias"]), 1)
        self.assertIn("desde", res["aviso"])
        self.assertIn("hasta", res["aviso"])

    def test_fechas_invertidas_se_intercambian(self):
        for n in (10, 11, 12):
            self.insertar(turno(f"A-{n}", utc(n, 15)))
        res = desglose_por_fecha(self.db, fecha_desde="2026-10-12", fecha_hasta="2026-10-10")
        self.assertEqual(len(res["dias"]), 3)
        self.assertIn("intercambiaron", res["aviso"])

    def test_ignora_otros_servicios_y_turnos_sin_fecha(self):
        self.insertar(turno("A-001", utc(10, 15)), turno("X-001", utc(10, 15), servicio="otro"))
        self.db["turnos"].insert_one({"codigo": "A-002", "servicio": "atencion_general", "estado": "pendiente",
                                      "timestamps": {"creado": None}, "metricas": {}})
        self.assertEqual(desglose_por_fecha(self.db)["total_turnos"], 1)

    def test_sin_turnos_devuelve_lista_vacia(self):
        res = desglose_por_fecha(self.db)
        self.assertEqual((res["dias"], res["total_turnos"]), ([], 0))

    def test_la_zona_viene_de_la_variable_de_entorno_y_una_invalida_cae_en_utc(self):
        with mock.patch.dict("os.environ", {"ZONA_HORARIA": "Marte/Olimpo"}):
            self.assertEqual(desglose_por_fecha(self.db)["zona"], "UTC")
        with mock.patch.dict("os.environ", {"ZONA_HORARIA": "America/Costa_Rica"}):
            self.assertEqual(desglose_por_fecha(self.db)["zona"], "America/Costa_Rica")

    def test_la_barra_mas_alta_es_el_dia_con_mas_turnos(self):
        self.insertar(turno("A-1", utc(10, 15)), turno("A-2", utc(10, 16)), turno("A-3", utc(11, 15)))
        barras = {d["fecha"]: d["porcentaje_barra"] for d in desglose_por_fecha(self.db)["dias"]}
        self.assertEqual(barras, {"2026-10-10": 100.0, "2026-10-11": 50.0})


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasEnElDashboard(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)
        self.db["turnos"].insert_many([turno("A-001", utc(10, 15)), turno("A-002", utc(11, 15), "abandonado"),
                                       turno("A-003", utc(12, 15))])

    def test_las_metricas_incluyen_el_desglose(self):
        m = calcular_metricas_dashboard(self.db)
        self.assertEqual([d["fecha"] for d in m["por_fecha"]["dias"]], ["2026-10-10", "2026-10-11", "2026-10-12"])

    def test_la_pantalla_muestra_el_desglose_y_el_formulario(self):
        html = self.c.get("/dashboard").text
        for texto in ("Desglose por fecha", 'name="fecha_desde"', 'name="fecha_hasta"', "10/10/2026", "12/10/2026"):
            self.assertIn(texto, html)

    def test_la_pantalla_aplica_el_rango(self):
        html = self.c.get("/dashboard?fecha_desde=2026-10-11&fecha_hasta=2026-10-11").text
        self.assertIn("11/10/2026", html)
        self.assertNotIn("<strong>10/10/2026</strong>", html)
        self.assertIn('value="2026-10-11"', html)

    def test_un_rango_sin_datos_lo_dice(self):
        html = self.c.get("/dashboard?fecha_desde=2030-01-01&fecha_hasta=2030-01-02").text
        self.assertIn("No hay turnos en ese rango de fechas", html)

    def test_una_fecha_invalida_no_rompe_la_pantalla_y_avisa(self):
        r = self.c.get("/dashboard?fecha_desde=ayer")
        self.assertEqual(r.status_code, 200)
        self.assertIn("no es válida", r.text)

    def test_la_api_y_la_descarga_json_traen_el_desglose(self):
        api = self.c.get("/api/dashboard?fecha_desde=2026-10-10&fecha_hasta=2026-10-10").json()
        self.assertEqual([d["fecha"] for d in api["por_fecha"]["dias"]], ["2026-10-10"])
        descarga = json.loads(self.c.get("/api/dashboard/descargar?fecha_desde=2026-10-12").content)
        self.assertEqual([d["fecha"] for d in descarga["datos"]["por_fecha"]["dias"]], ["2026-10-12"])

    def test_si_falla_el_desglose_el_resto_del_dashboard_sigue(self):
        with mock.patch("app.dashboard.desglose_por_fecha", side_effect=RuntimeError("boom")):
            r = self.c.get("/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertIn("No se pudo calcular el desglose por fecha", r.text)
        self.assertNotIn("boom", r.text)


if __name__ == "__main__":
    unittest.main()
