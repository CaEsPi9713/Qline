"""
Pruebas automatizadas y aisladas para el backend de HU-001 (Emisión de turnos).

Todas las operaciones hacia MongoDB y Redis están completamente aisladas
mediante mocks y dobles de prueba (MagicMock, AsyncMock, patch).
No se realiza ninguna llamada a red ni modificación sobre bases de datos reales.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from pymongo.errors import PyMongoError
from redis.exceptions import ConnectionError, RedisError, ResponseError, TimeoutError

from app.constantes import (
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    SERVICIO_ID,
    SERVICIO_NOMBRE,
)
from app.emitir import EmisionError, emitir_turno
from app.main import accion_emitir, accion_quiosco, api_emitir_turno, app, vista_emitir, vista_quiosco


class TestHU001EmitirTurno(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Base de datos 100% aislada con MagicMock
        self.mock_db = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_db.__getitem__.return_value = self.mock_collection
        self.fake_id = ObjectId()
        self.mock_collection.insert_one.return_value = MagicMock(inserted_id=self.fake_id)
        self.mock_collection.delete_one.return_value = MagicMock(deleted_count=1)

    # 1. Successful issuance: normal priority
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-001")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_successful_issuance_normal_priority(self, mock_encolar, mock_siguiente_codigo):
        res = emitir_turno(self.mock_db, "normal")
        self.assertEqual(res["codigo"], "A-001")
        self.assertEqual(res["prioridad"], PRIORIDAD_NORMAL)
        self.assertEqual(res["estado"], ESTADO_PENDIENTE)
        self.assertEqual(res["servicio"], SERVICIO_ID)
        self.assertEqual(res["servicio_nombre"], SERVICIO_NOMBRE)
        self.assertEqual(res["id"], str(self.fake_id))
        self.assertIn("qr_token", res)
        self.assertIn("qr_url", res)
        self.assertTrue(res["qr_url"].endswith(f"/turno/qr/{res['qr_token']}"))

    # 2. Successful issuance: preferential priority
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-002")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_successful_issuance_preferential_priority(self, mock_encolar, mock_siguiente_codigo):
        res = emitir_turno(self.mock_db, "preferencial")
        self.assertEqual(res["codigo"], "A-002")
        self.assertEqual(res["prioridad"], PRIORIDAD_PREFERENCIAL)
        self.assertEqual(res["estado"], ESTADO_PENDIENTE)

    # 3. Unique sequential turn codes
    @patch("app.emitir.cola.encolar", return_value=True)
    @patch("app.emitir.cola.siguiente_codigo", side_effect=["A-001", "A-002", "A-003"])
    def test_unique_sequential_turn_codes(self, mock_siguiente_codigo, mock_encolar):
        t1 = emitir_turno(self.mock_db, "normal")
        t2 = emitir_turno(self.mock_db, "preferencial")
        t3 = emitir_turno(self.mock_db, "normal")
        self.assertEqual(t1["codigo"], "A-001")
        self.assertEqual(t2["codigo"], "A-002")
        self.assertEqual(t3["codigo"], "A-003")
        self.assertEqual(len({t1["codigo"], t2["codigo"], t3["codigo"]}), 3)

    # 4. Correct MongoDB document structure
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-015")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_correct_mongodb_document_structure(self, mock_encolar, mock_siguiente_codigo):
        emitir_turno(self.mock_db, "preferencial")
        self.mock_collection.insert_one.assert_called_once()
        doc = self.mock_collection.insert_one.call_args[0][0]

        # Validar campos canónicos de la Sección 4.5 del Plan Maestro y HU-003
        self.assertEqual(doc["codigo"], "A-015")
        self.assertEqual(doc["servicio"], SERVICIO_ID)
        self.assertEqual(doc["prioridad"], PRIORIDAD_PREFERENCIAL)
        self.assertEqual(doc["estado"], ESTADO_PENDIENTE)
        self.assertIsNone(doc["ventanilla"])
        self.assertIsNone(doc["operador"])
        self.assertIn("qr_token", doc)
        self.assertIsInstance(doc["qr_token"], str)

        # Timestamps
        self.assertIn("timestamps", doc)
        self.assertIsInstance(doc["timestamps"]["creado"], datetime)
        self.assertIsNone(doc["timestamps"]["llamado"])
        self.assertIsNone(doc["timestamps"]["inicio_atencion"])
        self.assertIsNone(doc["timestamps"]["finalizado"])
        self.assertIsNone(doc["timestamps"]["abandonado"])

        # Métricas
        self.assertIn("metricas", doc)
        self.assertIsNone(doc["metricas"]["espera_seg"])
        self.assertIsNone(doc["metricas"]["atencion_seg"])

    # 5. Native UTC datetime persistence
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-001")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_native_utc_datetime_persistence(self, mock_encolar, mock_siguiente_codigo):
        emitir_turno(self.mock_db, "normal")
        doc = self.mock_collection.insert_one.call_args[0][0]
        creado = doc["timestamps"]["creado"]
        self.assertIsInstance(creado, datetime)
        self.assertEqual(creado.tzinfo, timezone.utc)

    # 6. Correct Redis enqueue function arguments
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-010")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_correct_redis_enqueue_function_arguments(self, mock_encolar, mock_siguiente_codigo):
        emitir_turno(self.mock_db, "preferencial")
        mock_encolar.assert_called_once()
        args, _ = mock_encolar.call_args
        self.assertEqual(args[0], "A-010")
        self.assertEqual(args[1], PRIORIDAD_PREFERENCIAL)
        self.assertIsInstance(args[2], int)
        self.assertGreater(args[2], 0)

    # 7. Invalid, empty, or unsupported priorities
    def test_invalid_empty_or_unsupported_priorities(self):
        casos_invalidos = ["urgente", "vip", "", "   ", None, 123, [], {}]
        for invalida in casos_invalidos:
            with self.subTest(prioridad=invalida):
                with self.assertRaises(EmisionError) as ctx:
                    emitir_turno(self.mock_db, invalida)
                self.assertEqual(ctx.exception.status, 400)
                self.assertIn("prioridad", str(ctx.exception).lower())

    # 8. Redis failure during code generation
    @patch("app.emitir.cola.siguiente_codigo", side_effect=RedisError("Redis connection refused"))
    def test_redis_failure_during_code_generation(self, mock_siguiente_codigo):
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("Redis no disponible para generar código", str(ctx.exception))
        self.mock_collection.insert_one.assert_not_called()

    # 9. MongoDB insertion failure
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-001")
    @patch("app.emitir.cola.encolar")
    def test_mongodb_insertion_failure(self, mock_encolar, mock_siguiente_codigo):
        self.mock_collection.insert_one.side_effect = PyMongoError("Primary node unavailable")
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("MongoDB no disponible al persistir", str(ctx.exception))
        mock_encolar.assert_not_called()

    # 10. Confirmed enqueue failure and safe compensation
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-005")
    @patch("app.emitir.cola.encolar", return_value=False)
    def test_confirmed_enqueue_failure_and_safe_compensation(self, mock_encolar, mock_siguiente_codigo):
        # Cuando encolar retorna False (código duplicado en Redis): se debe eliminar exactamente el doc insertado
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("Inserción compensada", str(ctx.exception))
        self.mock_collection.delete_one.assert_called_once_with({"_id": self.fake_id})

    @patch("app.emitir.cola.siguiente_codigo", return_value="A-006")
    @patch("app.emitir.cola.encolar", side_effect=ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value"))
    def test_confirmed_enqueue_failure_response_error_compensation(self, mock_encolar, mock_siguiente_codigo):
        # Cuando Redis responde con error explícito de comando: se debe compensar
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 502)
        self.assertIn("Inserción compensada", str(ctx.exception))
        self.mock_collection.delete_one.assert_called_once_with({"_id": self.fake_id})

    # 11. Ambiguous Redis failure without destructive rollback
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-007")
    @patch("app.emitir.cola.encolar", side_effect=TimeoutError("Timeout reading from socket"))
    def test_ambiguous_redis_failure_without_destructive_rollback(self, mock_encolar, mock_siguiente_codigo):
        # En caso de timeout ambiguo: NO debe ejecutarse delete_one para no borrar un turno posiblemente encolado
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("Falla ambigua de conexión o timeout", str(ctx.exception))
        self.mock_collection.delete_one.assert_not_called()

    @patch("app.emitir.cola.siguiente_codigo", return_value="A-008")
    @patch("app.emitir.cola.encolar", side_effect=ConnectionError("Connection lost mid-operation"))
    def test_ambiguous_redis_connection_error_without_destructive_rollback(self, mock_encolar, mock_siguiente_codigo):
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("Falla ambigua de conexión o timeout", str(ctx.exception))
        self.mock_collection.delete_one.assert_not_called()

    # 12. Compensation failure handling
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-009")
    @patch("app.emitir.cola.encolar", return_value=False)
    def test_compensation_failure_handling(self, mock_encolar, mock_siguiente_codigo):
        # Falla al encolar y luego falla el intento de compensación en MongoDB
        self.mock_collection.delete_one.side_effect = PyMongoError("Write concern error during delete")
        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn("falló la compensación en MongoDB", str(ctx.exception))

    # 13. JSON and form input compatibility
    async def test_json_and_form_input_compatibility(self):
        # Petición JSON
        req_json = MagicMock()
        req_json.headers = {"content-type": "application/json"}
        req_json.json = AsyncMock(return_value={"prioridad": "normal"})

        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            mock_emitir.return_value = {
                "id": str(self.fake_id),
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-10-18T15:00:00+00:00",
            }
            res_json = await api_emitir_turno(req_json)
            self.assertTrue(res_json["ok"])
            self.assertEqual(res_json["turno"]["codigo"], "A-001")
            mock_emitir.assert_called_with(mock_emitir.call_args[0][0], "normal")

        # Petición Form Data
        req_form = MagicMock()
        req_form.headers = {"content-type": "application/x-www-form-urlencoded"}
        req_form.form = AsyncMock(return_value={"prioridad": "preferencial"})

        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            mock_emitir.return_value = {
                "id": str(self.fake_id),
                "codigo": "A-002",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_PREFERENCIAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-10-18T15:00:00+00:00",
            }
            res_form = await api_emitir_turno(req_form)
            self.assertTrue(res_form["ok"])
            self.assertEqual(res_form["turno"]["codigo"], "A-002")
            mock_emitir.assert_called_with(mock_emitir.call_args[0][0], "preferencial")

    # 14. FastAPI endpoint registration
    def test_fastapi_endpoint_registration(self):
        rutas = {r.path: r for r in app.routes}
        self.assertIn("/api/turnos/emitir", rutas)
        route_obj = rutas["/api/turnos/emitir"]
        self.assertIn("POST", route_obj.methods)

    # 15. Existing route regression checks
    def test_existing_route_regression_checks(self):
        rutas_esperadas = {
            "/",
            "/crear_coleccion",
            "/insertar",
            "/actualizar",
            "/eliminar",
            "/redis/estado",
            "/api/cola",
            "/cola",
            "/api/llamar",
            "/cola/llamar",
            "/api/turnos/emitir",
        }
        rutas_registradas = {r.path for r in app.routes}
        for ruta in rutas_esperadas:
            self.assertIn(ruta, rutas_registradas, f"Regresión: la ruta preexistente {ruta} fue removida")
        self.assertIn("/quiosco", rutas_registradas)

    # 16. Kiosk mode: View without internal/administrative navigation (HU-001 S3)
    def test_quiosco_view_renders_without_internal_navigation(self):
        req = MagicMock()
        resp = vista_quiosco(req)
        self.assertEqual(resp.status_code, 200)
        body = resp.body.decode("utf-8")
        self.assertIn("Quiosco", body)
        self.assertIn("Atención Regular (Normal)", body)
        self.assertIn("Atención Preferencial", body)

        # La vista de quiosco NO debe contener enlaces a módulos internos u operativos
        self.assertNotIn("/cola", body)
        self.assertNotIn("/panel", body)
        self.assertNotIn("/historial", body)
        self.assertNotIn("/dashboard", body)
        self.assertNotIn("CRUD MongoDB", body)

    # 17. Kiosk mode: Successful emission and ticket confirmation
    def test_quiosco_emission_success_and_confirmation(self):
        req = MagicMock()
        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            fake_token = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
            mock_emitir.return_value = {
                "id": str(self.fake_id),
                "codigo": "A-025",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-10-25T19:00:00+00:00",
                "qr_token": fake_token,
                "qr_url": f"https://grupo2.crnube.net/turno/qr/{fake_token}",
            }
            resp = accion_quiosco(req, "normal")
            self.assertEqual(resp.status_code, 200)
            body = resp.body.decode("utf-8")
            self.assertIn("A-025", body)
            self.assertIn("qr-svg", body)
            self.assertIn(fake_token, body)
            self.assertIn("/quiosco", body)

            # Confirmación de quiosco NO ofrece enlaces internos de operador o admin
            self.assertNotIn("/cola", body)
            self.assertNotIn("/panel", body)
            self.assertNotIn("/historial", body)
            self.assertNotIn("/dashboard", body)

    # 18. Kiosk mode: Invalid priority returns 400
    def test_quiosco_invalid_priority_returns_400(self):
        req = MagicMock()
        resp = accion_quiosco(req, "invalida")
        self.assertEqual(resp.status_code, 400)
        body = resp.body.decode("utf-8")
        self.assertIn("Prioridad inválida", body)


if __name__ == "__main__":
    unittest.main()
