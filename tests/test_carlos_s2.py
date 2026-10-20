"""
Pruebas automatizadas para TT-001 y TT-002 (Modelo y JSON Schema de Turnos).

Responsable: Carlos Espinoza (cespinoza)
Valida que el modelo de turnos cumpla estrictamente con la Sección 4.5 del Plan Maestro
y que el validador JSON Schema prevenga inconsistencias técnicas.
"""
import unittest
from datetime import datetime, timezone

from app.constantes import (
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    SERVICIO_ID,
    VENTANILLAS,
)
from app.turnos_schema import (
    INDICES_TURNOS,
    SCHEMA_TURNOS,
    TurnoValidationError,
    obtener_validador_turnos,
    validar_documento_turno,
)


class TestTurnosSchema(unittest.TestCase):
    def setUp(self):
        self.ahora = datetime.now(timezone.utc)
        self.doc_valido = {
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

    def test_schema_structure(self):
        """Verifica que la estructura $jsonSchema contenga las propiedades requeridas por MongoDB."""
        schema = obtener_validador_turnos()
        self.assertIn("$jsonSchema", schema)
        js = schema["$jsonSchema"]
        self.assertEqual(js["bsonType"], "object")
        self.assertIn("codigo", js["required"])
        self.assertIn("servicio", js["required"])
        self.assertIn("prioridad", js["required"])
        self.assertIn("estado", js["required"])
        self.assertIn("timestamps", js["required"])
        self.assertIn("metricas", js["required"])

        # Validar enums aprobados en el schema
        props = js["properties"]
        self.assertEqual(props["prioridad"]["enum"], ["normal", "preferencial"])
        self.assertEqual(
            props["estado"]["enum"],
            ["pendiente", "llamado", "en_atencion", "atendido", "abandonado"],
        )
        self.assertEqual(props["servicio"]["enum"], [SERVICIO_ID])

    def test_indices_definitions(self):
        """Verifica que los índices requeridos estén correctamente definidos."""
        nombres = [idx["options"]["name"] for idx in INDICES_TURNOS]
        self.assertIn("idx_turnos_codigo_unico", nombres)
        self.assertIn("idx_turnos_estado_creado", nombres)
        self.assertIn("idx_turnos_ventanilla", nombres)

        # Verificar que el código sea único
        idx_codigo = next(idx for idx in INDICES_TURNOS if idx["options"]["name"] == "idx_turnos_codigo_unico")
        self.assertTrue(idx_codigo["options"]["unique"])

    def test_documento_valido_pasa_validacion(self):
        """Un documento que cumple el contrato oficial pasa la validación sin errores."""
        self.assertTrue(validar_documento_turno(self.doc_valido))

    def test_estados_ciclo_de_vida(self):
        """Todos los estados oficiales del contrato son admitidos."""
        for est in (ESTADO_PENDIENTE, ESTADO_LLAMADO, ESTADO_EN_ATENCION, ESTADO_ATENDIDO, ESTADO_ABANDONADO):
            self.doc_valido["estado"] = est
            self.assertTrue(validar_documento_turno(self.doc_valido))

    def test_prioridades_oficiales(self):
        """Se admiten exactamente 'normal' y 'preferencial'."""
        self.doc_valido["prioridad"] = PRIORIDAD_PREFERENCIAL
        self.assertTrue(validar_documento_turno(self.doc_valido))

        self.doc_valido["prioridad"] = PRIORIDAD_NORMAL
        self.assertTrue(validar_documento_turno(self.doc_valido))

    def test_rechazo_prioridad_invalida(self):
        """Una prioridad no autorizada es rechazada con TurnoValidationError."""
        self.doc_valido["prioridad"] = "vip"
        with self.assertRaises(TurnoValidationError) as ctx:
            validar_documento_turno(self.doc_valido)
        self.assertIn("Prioridad inválida", str(ctx.exception))

    def test_rechazo_estado_invalido(self):
        """Un estado desconocido es rechazado."""
        self.doc_valido["estado"] = "en_espera_indefinida"
        with self.assertRaises(TurnoValidationError) as ctx:
            validar_documento_turno(self.doc_valido)
        self.assertIn("Estado inválido", str(ctx.exception))

    def test_rechazo_codigo_invalido(self):
        """Códigos que no cumplan el formato X-### (una letra mayúscula) son rechazados."""
        for codigo_invalido in ("123", "A-1", "A-", "XYZ", "a-001", "AA-001", "A-001\n", ""):
            self.doc_valido["codigo"] = codigo_invalido
            with self.assertRaises(TurnoValidationError):
                validar_documento_turno(self.doc_valido)

    def test_acepta_series_de_codigo_real_y_sintetica(self):
        """Serie real (A-) y sintética (S-) son válidas: TT-005 debe poder cargarse con el validador activo."""
        for codigo in ("A-001", "A-9999", "S-001", "S-554"):
            self.doc_valido["codigo"] = codigo
            self.assertTrue(validar_documento_turno(self.doc_valido))

    def test_esquema_y_validador_comparten_el_patron(self):
        from app.turnos_schema import PATRON_CODIGO, SCHEMA_TURNOS
        patron = SCHEMA_TURNOS["$jsonSchema"]["properties"]["codigo"]["pattern"]
        self.assertEqual(patron, PATRON_CODIGO)

    def test_rechazo_ventanilla_invalida(self):
        """Ventanillas fuera del catálogo acordado son rechazadas."""
        self.doc_valido["ventanilla"] = "V-99"
        with self.assertRaises(TurnoValidationError):
            validar_documento_turno(self.doc_valido)

    def test_rechazo_timestamps_incompletos_o_invalidos(self):
        """El timestamp 'creado' es mandatorio y debe ser tipo datetime."""
        # Sin creado
        self.doc_valido["timestamps"] = {}
        with self.assertRaises(TurnoValidationError):
            validar_documento_turno(self.doc_valido)

        # Creado no es datetime
        self.doc_valido["timestamps"] = {"creado": "2026-10-19T10:00:00Z"}
        with self.assertRaises(TurnoValidationError):
            validar_documento_turno(self.doc_valido)

    def test_metricas_calculadas_validas(self):
        """Métricas con enteros o flotantes son aceptadas."""
        self.doc_valido["metricas"] = {"espera_seg": 125, "atencion_seg": 300.5}
        self.assertTrue(validar_documento_turno(self.doc_valido))

        # Rechazar métricas con texto
        self.doc_valido["metricas"] = {"espera_seg": "mucho tiempo"}
        with self.assertRaises(TurnoValidationError):
            validar_documento_turno(self.doc_valido)


class TestHistorial(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        self.mock_db = MagicMock()
        self.mock_col = MagicMock()
        self.mock_db.__getitem__.return_value = self.mock_col

        self.ahora = datetime(2026, 10, 19, 14, 0, 0, tzinfo=timezone.utc)
        self.llamado = datetime(2026, 10, 19, 14, 3, 30, tzinfo=timezone.utc)  # 210s
        self.inicio = datetime(2026, 10, 19, 14, 4, 0, tzinfo=timezone.utc)
        self.fin = datetime(2026, 10, 19, 14, 9, 0, tzinfo=timezone.utc)       # 300s

        self.fake_docs = [
            {
                "_id": "507f1f77bcf86cd799439011",
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_ATENDIDO,
                "ventanilla": "V-01",
                "operador": None,
                "timestamps": {
                    "creado": self.ahora,
                    "llamado": self.llamado,
                    "inicio_atencion": self.inicio,
                    "finalizado": self.fin,
                    "abandonado": None,
                },
                "metricas": {
                    "espera_seg": None,  # Forzar cálculo derivado
                    "atencion_seg": None,
                },
            }
        ]

    def test_obtener_historial_calcula_tiempos_derivados(self):
        """Calcula tiempo de espera y atención automáticamente a partir de timestamps."""
        from app.historial import obtener_historial_turnos
        self.mock_col.count_documents.return_value = 1
        cursor_mock = self.mock_col.find.return_value
        sort_mock = cursor_mock.sort.return_value
        skip_mock = sort_mock.skip.return_value
        skip_mock.limit.return_value = self.fake_docs

        res = obtener_historial_turnos(self.mock_db)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 1)
        self.assertEqual(len(res["turnos"]), 1)

        turno = res["turnos"][0]
        self.assertEqual(turno["codigo"], "A-001")
        self.assertEqual(turno["estado"], ESTADO_ATENDIDO)
        # 210 segundos entre las 14:00 y las 14:03:30
        self.assertEqual(turno["metricas"]["espera_seg"], 210)
        # 300 segundos entre las 14:04 y las 14:09:00
        self.assertEqual(turno["metricas"]["atencion_seg"], 300)

    def test_obtener_historial_filtros(self):
        """Aplica filtros por estado y ventanilla en la consulta a MongoDB."""
        from app.historial import obtener_historial_turnos
        self.mock_col.count_documents.return_value = 0
        cursor_mock = self.mock_col.find.return_value
        sort_mock = cursor_mock.sort.return_value
        skip_mock = sort_mock.skip.return_value
        skip_mock.limit.return_value = []

        obtener_historial_turnos(
            self.mock_db,
            estado=ESTADO_PENDIENTE,
            ventanilla="V-02",
            prioridad=PRIORIDAD_PREFERENCIAL,
            codigo="A-010",
        )
        self.mock_col.count_documents.assert_called_with({
            "servicio": SERVICIO_ID,
            "estado": ESTADO_PENDIENTE,
            "ventanilla": "V-02",
            "prioridad": PRIORIDAD_PREFERENCIAL,
            "codigo": "A-010",
        })


class TestDashboard(unittest.TestCase):
    def setUp(self):
        from unittest.mock import MagicMock
        self.mock_db = MagicMock()
        self.mock_col = MagicMock()
        self.mock_db.__getitem__.return_value = self.mock_col


    def test_calcular_metricas_dashboard(self):
        """Calcula correctamente totales, promedios, ventanillas y SLA con pipelines de agregación."""
        from app.dashboard import calcular_metricas_dashboard

        # Mock de 3 agregaciones: estados, tiempos, ventanillas
        conteo_estados_raw = [
            {"_id": "pendiente", "total": 5},
            {"_id": "llamado", "total": 2},
            {"_id": "en_atencion", "total": 1},
            {"_id": "atendido", "total": 20},
            {"_id": "abandonado", "total": 2},
        ]
        tiempos_raw = [
            {
                "_id": None,
                "promedio_espera": 180.5,
                "promedio_atencion": 240.2,
                "max_espera": 400,
                "min_espera": 50,
                "total_con_espera": 20,
                "cumplen_sla": 18,  # 18 de 20 cumplen (90%)
            }
        ]
        ventanillas_raw = [
            {"_id": "V-01", "turnos_activos": 1},
            {"_id": "V-02", "turnos_activos": 1},
        ]

        self.mock_col.aggregate.side_effect = [
            conteo_estados_raw,
            tiempos_raw,
            ventanillas_raw,
        ]

        res = calcular_metricas_dashboard(self.mock_db, sla_espera_max_seg=300)
        self.assertTrue(res["ok"])
        self.assertEqual(res["totales"]["esperando"], 5)
        self.assertEqual(res["totales"]["atendidos"], 20)
        self.assertEqual(res["totales"]["total_turnos"], 30)

        self.assertEqual(res["promedios"]["espera_seg"], 180.5)
        self.assertEqual(res["promedios"]["atencion_seg"], 240.2)

        # Ventanillas: V-01 y V-02 ocupadas (2 activas de 3)
        self.assertEqual(res["ventanillas"]["activas"], 2)
        self.assertEqual(res["ventanillas"]["total_configuradas"], 3)

        # SLA: 18 de 20 = 90.0% -> CUMPLIDO
        self.assertEqual(res["sla"]["porcentaje_cumplimiento"], 90.0)
        self.assertEqual(res["sla"]["estado"], "CUMPLIDO")
        self.assertEqual(res["sla"]["cumplen"], 18)
        self.assertEqual(res["sla"]["incumplen"], 2)


class TestAdminCRUD(unittest.TestCase):
    def test_normalizar_timestamps_turno(self):
        """Convierte fechas ISO en strings a objetos datetime UTC."""
        from app.main import normalizar_timestamps_turno
        doc = {
            "timestamps": {
                "creado": "2026-10-19T10:00:00Z",
                "llamado": "2026-10-19T10:05:00+00:00",
                "inicio_atencion": None,
            }
        }
        normalizar_timestamps_turno(doc)
        self.assertIsInstance(doc["timestamps"]["creado"], datetime)
        self.assertIsInstance(doc["timestamps"]["llamado"], datetime)
        self.assertIsNone(doc["timestamps"]["inicio_atencion"])


if __name__ == "__main__":
    unittest.main()

