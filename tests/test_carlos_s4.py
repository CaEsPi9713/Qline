"""
Pruebas de Seguimiento 4 (S4) para el entregable de Carlos Espinoza (cespinoza).

Módulo: Historial de turnos con filtro por rango de fechas, paginación y exportación (S4-M04).
"""
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient

from app.constantes import (
    ESTADO_ATENDIDO,
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


if __name__ == "__main__":
    unittest.main()
