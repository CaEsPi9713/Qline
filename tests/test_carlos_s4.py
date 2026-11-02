"""
Pruebas de Seguimiento 4 (S4) para el entregable de Carlos Espinoza (cespinoza).

Módulo: Historial de turnos con filtro por rango de fechas, paginación y exportación (S4-M04).
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from app.constantes import (
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    SERVICIO_ID,
)
from app.formato import zona
from app.historial import (
    COLECCION_TURNOS,
    exportar_historial_turnos,
    obtener_historial_turnos,
    parsear_fecha_filtro,
)
from app.main import app


class TestHistorialFiltroFechas(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_col = MagicMock()
        self.mock_db.__getitem__.return_value = self.mock_col

    def test_parsear_fecha_filtro_formatos(self):
        """Verifica parseo de formatos YYYY-MM-DD, ISO, datetime y casos inválidos."""
        tz_local = zona()

        # Inicio de día YYYY-MM-DD
        dt_inicio = parsear_fecha_filtro("2026-10-25", fin_de_dia=False)
        self.assertIsNotNone(dt_inicio)
        self.assertEqual(dt_inicio.tzinfo, timezone.utc)
        esperado_inicio = datetime(2026, 10, 25, 0, 0, 0, 0, tzinfo=tz_local).astimezone(timezone.utc)
        self.assertEqual(dt_inicio, esperado_inicio)

        # Fin de día YYYY-MM-DD
        dt_fin = parsear_fecha_filtro("2026-10-25", fin_de_dia=True)
        self.assertIsNotNone(dt_fin)
        esperado_fin = datetime(2026, 10, 25, 23, 59, 59, 999999, tzinfo=tz_local).astimezone(timezone.utc)
        self.assertEqual(dt_fin, esperado_fin)

        # ISO con Z
        dt_iso = parsear_fecha_filtro("2026-10-25T14:30:00Z")
        self.assertIsNotNone(dt_iso)
        self.assertEqual(dt_iso, datetime(2026, 10, 25, 14, 30, 0, tzinfo=timezone.utc))

        # Objeto datetime directo
        dt_obj = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(parsear_fecha_filtro(dt_obj), dt_obj)

        # Inválidos o vacíos
        self.assertIsNone(parsear_fecha_filtro(None))
        self.assertIsNone(parsear_fecha_filtro(""))
        self.assertIsNone(parsear_fecha_filtro("no-es-fecha"))

    def test_obtener_historial_aplica_rango_fechas(self):
        """Aplica condición $gte y $lte bajo timestamps.creado al consultar MongoDB."""
        self.mock_col.count_documents.return_value = 0
        cursor_mock = self.mock_col.find.return_value
        sort_mock = cursor_mock.sort.return_value
        skip_mock = sort_mock.skip.return_value
        skip_mock.limit.return_value = []

        obtener_historial_turnos(
            self.mock_db,
            fecha_desde="2026-10-20",
            fecha_hasta="2026-10-25",
        )

        args, _ = self.mock_col.count_documents.call_args
        filtro_aplicado = args[0]
        self.assertEqual(filtro_aplicado["servicio"], SERVICIO_ID)
        self.assertIn("timestamps.creado", filtro_aplicado)
        cond_fechas = filtro_aplicado["timestamps.creado"]
        self.assertIn("$gte", cond_fechas)
        self.assertIn("$lte", cond_fechas)
        self.assertLess(cond_fechas["$gte"], cond_fechas["$lte"])

    def test_obtener_historial_paginacion_metadata(self):
        """Calcula metadatos de paginación (pagina_actual, total_paginas, salto, limite)."""
        self.mock_col.count_documents.return_value = 45
        cursor_mock = self.mock_col.find.return_value
        sort_mock = cursor_mock.sort.return_value
        skip_mock = sort_mock.skip.return_value
        skip_mock.limit.return_value = []

        res = obtener_historial_turnos(
            self.mock_db,
            limite=10,
            salto=20,
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 45)
        self.assertEqual(res["limite"], 10)
        self.assertEqual(res["salto"], 20)
        self.assertEqual(res["pagina_actual"], 3)
        self.assertEqual(res["total_paginas"], 5)

    def test_exportar_historial_turnos_con_rango(self):
        """exportar_historial_turnos pasa los filtros de fecha y exporta sin límite."""
        fake_docs = [
            {
                "_id": "671000000000000000000001",
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_ATENDIDO,
                "ventanilla": "V-01",
                "operador": "op1",
                "timestamps": {
                    "creado": datetime(2026, 10, 25, 14, 0, 0, tzinfo=timezone.utc),
                    "llamado": datetime(2026, 10, 25, 14, 2, 0, tzinfo=timezone.utc),
                    "inicio_atencion": datetime(2026, 10, 25, 14, 2, 30, tzinfo=timezone.utc),
                    "finalizado": datetime(2026, 10, 25, 14, 8, 0, tzinfo=timezone.utc),
                    "abandonado": None,
                },
                "metricas": {},
            }
        ]
        self.mock_col.count_documents.return_value = 1
        cursor_mock = self.mock_col.find.return_value
        sort_mock = cursor_mock.sort.return_value
        skip_mock = sort_mock.skip.return_value
        skip_mock.__iter__.return_value = iter(fake_docs)
        skip_mock.limit.return_value = fake_docs

        res = exportar_historial_turnos(
            self.mock_db,
            fecha_desde="2026-10-25",
            fecha_hasta="2026-10-25",
        )

        self.assertTrue(res["ok"])
        self.assertEqual(res["total_exportados"], 1)
        self.assertEqual(res["filtros_aplicados"]["fecha_desde"], "2026-10-25")
        self.assertEqual(res["filtros_aplicados"]["fecha_hasta"], "2026-10-25")


class TestHistorialMongomockIntegracion(unittest.TestCase):
    def setUp(self):
        try:
            import mongomock
            self.db = mongomock.MongoClient().db
        except ImportError:
            self.skipTest("mongomock no disponible")

        # Cargar turnos en 3 días distintos (24, 25 y 26 de octubre)
        self.col = self.db[COLECCION_TURNOS]
        self.col.insert_many([
            {
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "estado": ESTADO_ATENDIDO,
                "prioridad": PRIORIDAD_NORMAL,
                "ventanilla": "V-01",
                "timestamps": {
                    "creado": datetime(2026, 10, 24, 15, 0, 0, tzinfo=timezone.utc),
                    "llamado": datetime(2026, 10, 24, 15, 5, 0, tzinfo=timezone.utc),
                },
                "metricas": {},
            },
            {
                "codigo": "A-002",
                "servicio": SERVICIO_ID,
                "estado": ESTADO_ATENDIDO,
                "prioridad": PRIORIDAD_PREFERENCIAL,
                "ventanilla": "V-02",
                "timestamps": {
                    "creado": datetime(2026, 10, 25, 16, 0, 0, tzinfo=timezone.utc),
                    "llamado": datetime(2026, 10, 25, 16, 3, 0, tzinfo=timezone.utc),
                },
                "metricas": {},
            },
            {
                "codigo": "A-003",
                "servicio": SERVICIO_ID,
                "estado": ESTADO_PENDIENTE,
                "prioridad": PRIORIDAD_NORMAL,
                "ventanilla": None,
                "timestamps": {
                    "creado": datetime(2026, 10, 26, 17, 0, 0, tzinfo=timezone.utc),
                    "llamado": None,
                },
                "metricas": {},
            },
        ])

    def test_filtro_rango_fechas_mongomock(self):
        """Filtra exactamente los turnos del 25 de octubre en la base de datos."""
        res = obtener_historial_turnos(
            self.db,
            fecha_desde="2026-10-25",
            fecha_hasta="2026-10-25",
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["turnos"][0]["codigo"], "A-002")


class TestHistorialEndpointsFastAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("app.main.obtener_historial_turnos")
    def test_api_historial_parametros_fechas(self, mock_obtener):
        """Verifica que el endpoint /api/historial traslada fecha_desde y fecha_hasta."""
        mock_obtener.return_value = {
            "ok": True,
            "total": 0,
            "turnos": [],
            "filtros": {},
        }
        resp = self.client.get("/api/historial?fecha_desde=2026-10-20&fecha_hasta=2026-10-25&limite=20&salto=10")
        self.assertEqual(resp.status_code, 200)
        mock_obtener.assert_called_once()
        _, kwargs = mock_obtener.call_args
        self.assertEqual(kwargs["fecha_desde"], "2026-10-20")
        self.assertEqual(kwargs["fecha_hasta"], "2026-10-25")
        self.assertEqual(kwargs["limite"], 20)
        self.assertEqual(kwargs["salto"], 10)

    @patch("app.main.exportar_historial_turnos")
    def test_api_descargar_historial_con_fechas(self, mock_exportar):
        """Verifica que /api/historial/descargar genera el nombre de archivo con fechas."""
        mock_exportar.return_value = {
            "ok": True,
            "servicio": SERVICIO_ID,
            "total_exportados": 0,
            "turnos": [],
            "filtros_aplicados": {},
        }
        resp = self.client.get("/api/historial/descargar?fecha_desde=2026-10-20&fecha_hasta=2026-10-25")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/json; charset=utf-8")
        disp = resp.headers.get("content-disposition", "")
        self.assertIn("attachment", disp)
        self.assertIn("historial_turnos_desde_20261020_hasta_20261025_", disp)
        self.assertIn(".json", disp)

    @patch("app.main.obtener_historial_turnos")
    def test_vista_historial_html(self, mock_obtener):
        """Verifica que la plantilla HTML renderiza campos de fecha y controles de paginación."""
        mock_obtener.return_value = {
            "ok": True,
            "total": 50,
            "limite": 10,
            "salto": 10,
            "pagina_actual": 2,
            "total_paginas": 5,
            "filtros": {
                "codigo": None,
                "estado": None,
                "ventanilla": None,
                "prioridad": None,
                "fecha_desde": "2026-10-20",
                "fecha_hasta": "2026-10-25",
            },
            "turnos": [
                {
                    "codigo": "A-010",
                    "prioridad": "normal",
                    "estado": "atendido",
                    "ventanilla": "V-01",
                    "timestamps": {
                        "creado": "2026-10-20T10:00:00.000Z",
                        "llamado": "2026-10-20T10:02:00.000Z",
                        "finalizado": "2026-10-20T10:05:00.000Z",
                        "abandonado": None,
                    },
                    "metricas": {
                        "espera_seg": 120,
                        "atencion_seg": 180,
                    },
                }
            ],
        }
        resp = self.client.get("/historial?fecha_desde=2026-10-20&fecha_hasta=2026-10-25&limite=10&salto=10")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn('name="fecha_desde"', html)
        self.assertIn('name="fecha_hasta"', html)
        self.assertIn('value="2026-10-20"', html)
        self.assertIn('value="2026-10-25"', html)
        self.assertIn('Página 2 de 5', html)
        self.assertIn('Anterior', html)
        self.assertIn('Siguiente', html)


class TestDashboardGraficos(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        try:
            import mongomock
            self.db = mongomock.MongoClient().db
        except ImportError:
            self.skipTest("mongomock no disponible")

        # Cargar datos de prueba con turnos en distintos estados, horas y ventanillas
        from app.dashboard import COLECCION_TURNOS, calcular_metricas_dashboard
        self.calcular_metricas_dashboard = calcular_metricas_dashboard
        col = self.db[COLECCION_TURNOS]
        col.insert_many([
            {
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "estado": ESTADO_ATENDIDO,
                "prioridad": PRIORIDAD_NORMAL,
                "ventanilla": "V-01",
                "timestamps": {
                    "creado": datetime(2026, 10, 25, 14, 0, 0, tzinfo=timezone.utc),  # 8:00 AM local
                    "llamado": datetime(2026, 10, 25, 14, 1, 30, tzinfo=timezone.utc),
                    "inicio_atencion": datetime(2026, 10, 25, 14, 2, 0, tzinfo=timezone.utc),
                    "finalizado": datetime(2026, 10, 25, 14, 5, 0, tzinfo=timezone.utc),
                    "abandonado": None,
                },
                "metricas": {
                    "espera_seg": 90,   # <= 120 (rango rápido)
                    "atencion_seg": 180,
                },
            },
            {
                "codigo": "A-002",
                "servicio": SERVICIO_ID,
                "estado": ESTADO_ATENDIDO,
                "prioridad": PRIORIDAD_PREFERENCIAL,
                "ventanilla": "V-02",
                "timestamps": {
                    "creado": datetime(2026, 10, 25, 15, 0, 0, tzinfo=timezone.utc),  # 9:00 AM local
                    "llamado": datetime(2026, 10, 25, 15, 4, 0, tzinfo=timezone.utc),
                    "inicio_atencion": datetime(2026, 10, 25, 15, 4, 30, tzinfo=timezone.utc),
                    "finalizado": datetime(2026, 10, 25, 15, 9, 0, tzinfo=timezone.utc),
                    "abandonado": None,
                },
                "metricas": {
                    "espera_seg": 240,  # 121-300 (rango moderado)
                    "atencion_seg": 270,
                },
            },
        ])

    def test_calcular_metricas_dashboard_graficos(self):
        """Verifica que calcular_metricas_dashboard genera métricas de afluencia, ventanillas y distribución."""
        res = self.calcular_metricas_dashboard(self.db, sla_espera_max_seg=300)
        self.assertTrue(res["ok"])
        self.assertIn("graficos", res)
        graficos = res["graficos"]

        # 1. Afluencia horaria
        self.assertIn("afluencia_horaria", graficos)
        horas = graficos["afluencia_horaria"]
        self.assertTrue(len(horas) >= 12)  # 7:00 a 18:00
        # 8:00 y 9:00 deben tener turnos
        totales_por_hora = {h["hora"]: h["total"] for h in horas}
        self.assertEqual(totales_por_hora.get("08:00"), 1)
        self.assertEqual(totales_por_hora.get("09:00"), 1)

        # 2. Desglose de espera
        self.assertIn("distribucion_espera", graficos)
        dist_esp = graficos["distribucion_espera"]
        self.assertEqual(dist_esp["hasta_2min"], 1)   # A-001 (90s)
        self.assertEqual(dist_esp["de_2_a_5min"], 1)  # A-002 (240s)

        # 3. Rendimiento ventanillas
        self.assertIn("rendimiento_ventanillas", graficos)
        rend = {v["ventanilla"]: v for v in graficos["rendimiento_ventanillas"]}
        self.assertEqual(rend["V-01"]["total_atendidos"], 1)
        self.assertEqual(rend["V-02"]["total_atendidos"], 1)

        # 4. KPIs avanzados y diagnóstico operacional (S4 mejora analítica)
        self.assertIn("kpis_avanzados", res)
        kpis = res["kpis_avanzados"]
        self.assertIn("tasa_abandono", kpis)
        self.assertIn("tasa_atencion", kpis)
        self.assertIn("max_espera_formateada", kpis)
        self.assertIn("promedio_espera_formateado", kpis)

        self.assertIn("diagnostico", res)
        diag = res["diagnostico"]
        self.assertIn(diag["semaforo"], ("verde", "amarillo", "rojo"))
        self.assertIn("alertas", diag)
        self.assertIn("recomendaciones", diag)

    @patch("app.main.get_db")
    def test_vista_dashboard_html_con_graficos(self, mock_get_db):
        """Verifica que /dashboard renderiza los bloques gráficos de afluencia, espera y ventanillas."""
        mock_get_db.return_value = self.db
        resp = self.client.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("Afluencia horaria de turnos", html)
        self.assertIn("Desglose de tiempos de espera", html)
        self.assertIn("Productividad y atenciones por ventanilla", html)
        self.assertIn("grafico-barras-v", html)
        self.assertIn("barra-segmentada", html)
        self.assertIn("grafico-barras-h", html)
        self.assertIn("dashboard-toolbar", html)
        self.assertIn("panel-diagnostico", html)
        self.assertIn("gauge-svg", html)
        self.assertIn("bandas-sla-grid", html)


class TestReporteDiarioScript(unittest.TestCase):
    def test_script_reporte_diario_cli_simulado(self):
        """Verifica ejecución del script reporte_diario.py en modo simulado con exportación a archivos temporales."""
        import tempfile
        from scripts.reporte_diario import main

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "reporte.json"
            md_path = Path(tmpdir) / "reporte.md"

            code = main([
                "--simulado",
                "--fecha", "2026-10-25",
                "--sla-espera", "300",
                "--salida-json", str(json_path),
                "--salida-md", str(md_path),
            ])
            self.assertEqual(code, 0)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())

            datos_json = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertTrue(datos_json["ok"])
            self.assertEqual(datos_json["fecha_reporte"], "2026-10-25")
            self.assertIn("resumen_operacional", datos_json)
            self.assertIn("tiempos_servicio", datos_json)
            self.assertIn("analisis_sla", datos_json)

            contenido_md = md_path.read_text(encoding="utf-8")
            self.assertIn("# Reporte Diario de Operaciones y Auditoría SLA", contenido_md)
            self.assertIn("Resumen Operacional de Turnos", contenido_md)
            self.assertIn("Productividad por Ventanilla", contenido_md)


class TestVentanillasDinamicas(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        try:
            import mongomock
            self.db = mongomock.MongoClient().db
        except ImportError:
            self.skipTest("mongomock no disponible")

    def test_validar_codigo_ventanilla(self):
        """Valida que los códigos cumplan el formato 'V-XX' y rechace formatos inválidos."""
        from app.ventanillas import VentanillaError, validar_codigo_ventanilla

        self.assertEqual(validar_codigo_ventanilla("v-01"), "V-01")
        self.assertEqual(validar_codigo_ventanilla("V-04"), "V-04")
        self.assertEqual(validar_codigo_ventanilla("V-10"), "V-10")

        with self.assertRaises(VentanillaError):
            validar_codigo_ventanilla("CAJA-1")
        with self.assertRaises(VentanillaError):
            validar_codigo_ventanilla("")
        with self.assertRaises(VentanillaError):
            validar_codigo_ventanilla(None)

    def test_onboarding_ventanilla_ciclo_completo(self):
        """Verifica registro, listado, desactivación y reactivación dinámica en MongoDB."""
        from app.ventanillas import (
            COLECCION_TURNOS,
            VentanillaError,
            desactivar_ventanilla,
            listar_ventanillas,
            reactivar_ventanilla,
            registrar_ventanilla,
        )

        # 1. Registrar nueva ventanilla V-04
        res = registrar_ventanilla(self.db, codigo="V-04", nombre="Ventanilla Rápida", tipo="preferencial")
        self.assertTrue(res["ok"])
        self.assertEqual(res["accion"], "creada")
        self.assertEqual(res["codigo"], "V-04")

        # 2. Listar
        lista = listar_ventanillas(self.db, solo_activas=True)
        codigos = [v["codigo"] for v in lista]
        self.assertIn("V-04", codigos)

        # 3. Desactivar sin turno activo -> Exitoso
        res_desact = desactivar_ventanilla(self.db, codigo="V-04")
        self.assertTrue(res_desact["ok"])
        self.assertEqual(res_desact["estado"], "inactiva")

        # Ahora en solo_activas no debe aparecer V-04
        activas = [v["codigo"] for v in listar_ventanillas(self.db, solo_activas=True)]
        self.assertNotIn("V-04", activas)

        # 4. Reactivar
        res_react = reactivar_ventanilla(self.db, codigo="V-04")
        self.assertTrue(res_react["ok"])
        self.assertEqual(res_react["estado"], "activa")

        # 5. Intentar desactivar cuando tiene un turno activo en atención -> Falla con VentanillaError
        self.db[COLECCION_TURNOS].insert_one({
            "codigo": "A-050",
            "servicio": SERVICIO_ID,
            "ventanilla": "V-04",
            "estado": ESTADO_EN_ATENCION,
        })
        with self.assertRaises(VentanillaError):
            desactivar_ventanilla(self.db, codigo="V-04")

    @patch("app.main.get_db")
    def test_endpoints_ventanillas_fastapi(self, mock_get_db):
        """Verifica los endpoints /api/ventanillas y los formularios de administración."""
        mock_get_db.return_value = self.db

        # GET API
        resp = self.client.get("/api/ventanillas")
        self.assertEqual(resp.status_code, 200)
        datos = resp.json()
        self.assertTrue(datos["ok"])

        # POST API registrar
        resp_post = self.client.post("/api/ventanillas", data={"codigo": "V-05", "nombre": "Módulo 5"})
        self.assertEqual(resp_post.status_code, 200)
        self.assertEqual(resp_post.json()["codigo"], "V-05")

        # Formulario web crear
        resp_web_crear = self.client.post("/ventanillas/crear", data={"codigo": "V-06", "nombre": "Módulo 6"}, follow_redirects=False)
        self.assertEqual(resp_web_crear.status_code, 303)
        self.assertIn("ok=ventanilla_creada", resp_web_crear.headers.get("location", ""))

        # Formulario web desactivar
        resp_web_desact = self.client.post("/ventanillas/desactivar", data={"codigo": "V-06"}, follow_redirects=False)
        self.assertEqual(resp_web_desact.status_code, 303)
        self.assertIn("ok=ventanilla_desactivada", resp_web_desact.headers.get("location", ""))


class TestCargarDatosRelease(unittest.TestCase):
    def test_dataset_release_valido_contra_json_schema(self):
        """Verifica que todos los documentos generados cumplan estrictamente con el JSON Schema oficial."""
        from app.turnos_schema import validar_documento_turno
        from scripts.cargar_datos_release import generar_dataset_release

        docs = generar_dataset_release(cantidad=30)
        self.assertEqual(len(docs), 30)
        for doc in docs:
            # Debe validar sin excepciones
            validar_documento_turno(doc)

    def test_cargar_datos_release_idempotencia(self):
        """Verifica que la carga sea reproducible y no genere duplicados al ejecutarse múltiples veces."""
        try:
            import mongomock
            db = mongomock.MongoClient().db
        except ImportError:
            self.skipTest("mongomock no disponible")

        from scripts.cargar_datos_release import cargar_datos_release

        res1 = cargar_datos_release(db, cantidad=25, limpiar=False)
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["insertados"], 25)
        self.assertEqual(res1["total_en_coleccion"], 25)

        # Segunda ejecución: debe actualizar y mantener total en 25
        res2 = cargar_datos_release(db, cantidad=25, limpiar=False)
        self.assertTrue(res2["ok"])
        self.assertEqual(res2["insertados"], 0)
        self.assertEqual(res2["actualizados"], 25)
        self.assertEqual(res2["total_en_coleccion"], 25)

    def test_cargar_datos_release_cli_simulado(self):
        """Verifica ejecución de la CLI con salida JSON."""
        from scripts.cargar_datos_release import main
        code = main(["--simulado", "--turnos", "15", "--json"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
