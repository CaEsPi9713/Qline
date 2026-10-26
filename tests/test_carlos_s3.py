"""
Pruebas automatizadas para Seguimiento 3 (Carlos Espinoza · cespinoza).

Cubre:
  - HU-010: Exportación y descarga en archivo JSON de todo el historial filtrado.
  - HU-011: Exportación y descarga en archivo JSON del Dashboard de métricas y SLA.
  - TT-001 / TT-002: Soporte e índice parcial único para qr_token (compatibilidad hacia atrás).
  - TT-014 / TT-015: Script de medición y análisis de explain() y aggregation pipelines.
"""
import io
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.constantes import (
    ESTADO_ATENDIDO,
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    SERVICIO_ID,
    VENTANILLAS,
)
from app.dashboard import exportar_metricas_dashboard
from app.historial import exportar_historial_turnos
from app.main import (
    api_descargar_dashboard,
    api_descargar_historial,
    app,
)
from app.turnos_schema import (
    INDICES_TURNOS,
    PATRON_UUID_V4,
    SCHEMA_TURNOS,
    TurnoValidationError,
    validar_documento_turno,
)
import scripts.medir_indices_mongo as mim


class TestCarlosS3Exportaciones(unittest.TestCase):
    def setUp(self):
        self.ahora = datetime.now(timezone.utc)
        self.mock_db = MagicMock()
        self.mock_col = self.mock_db["turnos"]

        self.fake_docs = [
            {
                "_id": "60c72b2f9b1d8b2bad000001",
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_ATENDIDO,
                "ventanilla": "V-01",
                "operador": "op_1",
                "qr_token": "12345678-1234-4234-8234-123456789abc",
                "timestamps": {
                    "creado": self.ahora,
                    "llamado": self.ahora,
                    "inicio_atencion": self.ahora,
                    "finalizado": self.ahora,
                    "abandonado": None,
                },
                "metricas": {
                    "espera_seg": 120,
                    "atencion_seg": 240,
                },
            }
        ]

    def test_exportar_historial_turnos_completo(self):
        """Exporta todos los registros sin límite de paginación con metadatos de auditoría."""
        self.mock_col.count_documents.return_value = 1
        cursor_mock = self.mock_col.find.return_value
        sort_mock = cursor_mock.sort.return_value
        skip_mock = sort_mock.skip.return_value
        skip_mock.__iter__.return_value = iter(self.fake_docs)

        res = exportar_historial_turnos(self.mock_db, estado=ESTADO_ATENDIDO)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_exportados"], 1)
        self.assertEqual(res["total_registros_coincidentes"], 1)
        self.assertEqual(res["filtros_aplicados"]["estado"], ESTADO_ATENDIDO)
        self.assertIn("fecha_exportacion", res)
        self.assertEqual(len(res["turnos"]), 1)
        self.assertEqual(res["turnos"][0]["codigo"], "A-001")

    def test_exportar_metricas_dashboard(self):
        """Genera el paquete de métricas y SLA con fecha y tipo de reporte para descarga."""
        with patch("app.dashboard.calcular_metricas_dashboard") as mock_calc:
            mock_calc.return_value = {
                "ok": True,
                "servicio": SERVICIO_ID,
                "totales": {"total_turnos": 50},
                "sla": {"estado": "CUMPLIDO", "porcentaje_cumplimiento": 95.0},
            }
            res = exportar_metricas_dashboard(self.mock_db, sla_espera_max_seg=180)
            self.assertTrue(res["ok"])
            self.assertEqual(res["tipo_reporte"], "metricas_dashboard_sla")
            self.assertIn("fecha_exportacion", res)
            self.assertEqual(res["datos"]["sla"]["porcentaje_cumplimiento"], 95.0)

    def test_api_descargar_historial_endpoint(self):
        """El endpoint /api/historial/descargar entrega un archivo JSON adjunto (attachment)."""
        fake_export = {
            "ok": True,
            "servicio": SERVICIO_ID,
            "fecha_exportacion": self.ahora.isoformat(),
            "total_exportados": 1,
            "turnos": [{"codigo": "A-001"}],
        }
        with patch("app.main.get_db", return_value=self.mock_db), \
             patch("app.main.exportar_historial_turnos", return_value=fake_export):
            response = api_descargar_historial(estado="atendido")
            self.assertEqual(response.media_type, "application/json; charset=utf-8")
            disp = response.headers.get("content-disposition", "")
            self.assertIn("attachment", disp)
            self.assertIn("historial_turnos_", disp)
            self.assertIn(".json", disp)

            body = json.loads(response.body.decode("utf-8"))
            self.assertTrue(body["ok"])
            self.assertEqual(body["total_exportados"], 1)

    def test_api_descargar_dashboard_endpoint(self):
        """El endpoint /api/dashboard/descargar entrega el reporte JSON adjunto respetando el SLA."""
        fake_export = {
            "ok": True,
            "servicio": SERVICIO_ID,
            "tipo_reporte": "metricas_dashboard_sla",
            "datos": {"sla": {"objetivo_max_espera_seg": 180}},
        }
        with patch("app.main.get_db", return_value=self.mock_db), \
             patch("app.main.exportar_metricas_dashboard", return_value=fake_export):
            response = api_descargar_dashboard(sla_espera=180)
            self.assertEqual(response.media_type, "application/json; charset=utf-8")
            disp = response.headers.get("content-disposition", "")
            self.assertIn("attachment", disp)
            self.assertIn("dashboard_sla_180s_", disp)
            self.assertIn(".json", disp)

            body = json.loads(response.body.decode("utf-8"))
            self.assertEqual(body["tipo_reporte"], "metricas_dashboard_sla")



class TestCarlosS3QRTokenEIndice(unittest.TestCase):
    def setUp(self):
        self.ahora = datetime.now(timezone.utc)
        self.doc_base = {
            "codigo": "A-001",
            "servicio": SERVICIO_ID,
            "prioridad": PRIORIDAD_NORMAL,
            "estado": ESTADO_PENDIENTE,
            "ventanilla": None,
            "operador": None,
            "timestamps": {
                "creado": self.ahora,
                "llamado": None,
                "inicio_atencion": None,
                "finalizado": None,
                "abandonado": None,
            },
            "metricas": {
                "espera_seg": None,
                "atencion_seg": None,
            },
        }

    def test_documento_antiguo_sin_qr_token_sigue_siendo_valido(self):
        """Compatibilidad hacia atrás: documentos previos a S3 sin qr_token son admitidos."""
        self.assertNotIn("qr_token", self.doc_base)
        self.assertTrue(validar_documento_turno(self.doc_base))

    def test_documento_con_qr_token_valido_pasa(self):
        """Un documento con un UUID v4 válido en qr_token pasa la validación."""
        self.doc_base["qr_token"] = "e87cf7a8-3906-4444-934d-176f5f3e792c"
        self.assertTrue(validar_documento_turno(self.doc_base))

    def test_documento_con_qr_token_invalido_es_rechazado(self):
        """Formatos inválidos de UUID en qr_token disparan TurnoValidationError."""
        for invalido in ("no-es-uuid", "1234", "e87cf7a8-3906-4444-934d", ""):
            self.doc_base["qr_token"] = invalido
            with self.assertRaises(TurnoValidationError):
                validar_documento_turno(self.doc_base)

    def test_definicion_indice_parcial_unico_qr_token(self):
        """Verifica que el índice para qr_token sea único y con filtro parcial."""
        idx_qr = next((idx for idx in INDICES_TURNOS if idx["options"].get("name") == "idx_turnos_qr_token_unico"), None)
        self.assertIsNotNone(idx_qr, "No se encontró el índice idx_turnos_qr_token_unico")
        self.assertTrue(idx_qr["options"].get("unique"))
        partial = idx_qr["options"].get("partialFilterExpression", {})
        self.assertEqual(partial.get("qr_token"), {"$exists": True, "$type": "string"})


class TestCarlosS3MedicionesScript(unittest.TestCase):
    def test_minimo_tres_ejecuciones_requerido(self):
        """El script de medición rechaza peticiones con menos de 3 ejecuciones."""
        self.assertEqual(mim.MIN_EJECUCIONES, 3)
        with patch("sys.stderr"):
            salida = mim.main(["--ejecuciones", "2", "--simulado"])
        self.assertEqual(salida, 2)

    def test_resumen_estadistico_calcula_minimo_maximo_y_mediana(self):
        """La función resumen calcula correctamente min, max y mediana."""
        datos = [1.2, 0.5, 3.4, 2.1, 0.9]
        res = mim.resumen(datos)
        self.assertEqual(res["minimo"], 0.5)
        self.assertEqual(res["maximo"], 3.4)
        self.assertEqual(res["mediana"], 1.2)
        self.assertEqual(res["ejecuciones"], 5)

    def test_generar_markdown_informe_contiene_todas_las_secciones(self):
        """El informe generado contiene las secciones TT-014, TT-015 y tablas de resultados."""
        datos_sim = {
            "mongo_version": "7.0.45",
            "ejecuciones": 5,
            "op1": {
                "stats_indice": {"stage": "IXSCAN", "totalDocsExamined": 1, "totalKeysExamined": 1},
                "stats_sin_indice": {"stage": "COLLSCAN", "totalDocsExamined": 500, "totalKeysExamined": 0},
                "latencia_indice": mim.resumen([0.1, 0.11, 0.12, 0.1, 0.11]),
                "latencia_sin_indice": mim.resumen([0.5, 0.52, 0.51, 0.49, 0.5]),
            },
            "op2": {
                "stats_indice": {"stage": "FETCH -> IXSCAN", "totalDocsExamined": 20},
                "stats_sin_indice": {"stage": "SORT -> COLLSCAN", "totalDocsExamined": 500},
                "latencia_indice": mim.resumen([0.2, 0.21, 0.22, 0.2, 0.21]),
                "latencia_sin_indice": mim.resumen([0.8, 0.82, 0.81, 0.79, 0.8]),
            },
            "op3": {
                "stats_indice": {"stage": "IXSCAN", "totalDocsExamined": 1},
                "stats_sin_indice": {"stage": "COLLSCAN", "totalDocsExamined": 500},
                "latencia_indice": mim.resumen([0.12, 0.13, 0.12, 0.11, 0.12]),
                "latencia_sin_indice": mim.resumen([0.55, 0.56, 0.54, 0.55, 0.56]),
            },
            "agg": {
                "pipeline_estados": {"latencia": mim.resumen([0.3, 0.31, 0.32, 0.29, 0.3])},
                "pipeline_sla": {"latencia": mim.resumen([0.4, 0.41, 0.42, 0.39, 0.4])},
            },
        }
        md = mim.generar_markdown_informe(datos_sim, 500)
        self.assertIn("TT-014", md)
        self.assertIn("TT-015", md)
        self.assertIn("idx_turnos_codigo_unico", md)
        self.assertIn("idx_turnos_estado_creado", md)
        self.assertIn("idx_turnos_qr_token_unico", md)
        self.assertIn("Aggregation Pipelines", md)


if __name__ == "__main__":
    unittest.main()
