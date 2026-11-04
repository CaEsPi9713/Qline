"""HU-002: pruebas aisladas; no requiere servidores MongoDB/Redis."""

import unittest
from unittest.mock import MagicMock, patch

from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app import main
from app.consultar import ConsultaError, consultar_turno
from app.constantes import SERVICIO_ID


def documento(estado="pendiente", ventanilla=None):
    return {
        "codigo": "A-001", "servicio": SERVICIO_ID, "prioridad": "normal",
        "estado": estado, "ventanilla": ventanilla,
    }


class TestHU002Consulta(unittest.TestCase):
    def setUp(self):
        self.db = MagicMock()
        self.db["turnos"].find_one.return_value = documento()

    @patch("app.consultar.cola.posicion_en_cola", return_value=0)
    def test_pending_first_position(self, posicion):
        turno = consultar_turno(self.db, "A-001")
        self.assertEqual(turno["turnos_antes"], 0)
        self.assertEqual(turno["posicion"], 1)
        posicion.assert_called_once_with("A-001")
        self.db["turnos"].find_one.assert_called_once()
        self.assertEqual(self.db["turnos"].find_one.call_args.args[0],
                         {"codigo": "A-001", "servicio": SERVICIO_ID})
        self.db["turnos"].insert_one.assert_not_called()
        self.db["turnos"].update_one.assert_not_called()
        self.db["turnos"].delete_one.assert_not_called()

    @patch("app.consultar.cola.posicion_en_cola", return_value=3)
    def test_pending_fourth_position(self, _):
        turno = consultar_turno(self.db, "A-001")
        self.assertEqual((turno["turnos_antes"], turno["posicion"]), (3, 4))

    @patch("app.consultar.cola.posicion_en_cola", return_value=None)
    def test_pending_missing_in_redis(self, _):
        turno = consultar_turno(self.db, "A-001")
        self.assertIsNone(turno["turnos_antes"])
        self.assertIsNone(turno["posicion"])
        self.assertTrue(turno["aviso"])

    @patch("app.consultar.cola.posicion_en_cola", side_effect=RedisError("secret Redis endpoint"))
    def test_pending_redis_unavailable_returns_status_only(self, _):
        turno = consultar_turno(self.db, "A-001")
        self.assertEqual(turno["estado"], "pendiente")
        self.assertIsNone(turno["posicion"])
        self.assertNotIn("secret", turno["aviso"])

    @patch("app.consultar.cola.posicion_en_cola")
    def test_called_not_in_redis(self, posicion):
        self.db["turnos"].find_one.return_value = documento("llamado", "V-01")
        turno = consultar_turno(self.db, "A-001")
        self.assertEqual(turno["ventanilla"], "V-01")
        self.assertIsNone(turno["turnos_antes"])
        posicion.assert_not_called()

    @patch("app.consultar.cola.posicion_en_cola")
    def test_in_attention_not_in_redis(self, posicion):
        self.db["turnos"].find_one.return_value = documento("en_atencion", "V-02")
        turno = consultar_turno(self.db, "A-001")
        self.assertEqual(turno["estado"], "en_atencion")
        self.assertEqual(turno["ventanilla"], "V-02")
        posicion.assert_not_called()

    @patch("app.consultar.cola.posicion_en_cola")
    def test_attended_not_in_redis(self, posicion):
        self.db["turnos"].find_one.return_value = documento("atendido", "V-02")
        self.assertEqual(consultar_turno(self.db, "A-001")["estado"], "atendido")
        posicion.assert_not_called()

    @patch("app.consultar.cola.posicion_en_cola")
    def test_abandoned_not_in_redis(self, posicion):
        self.db["turnos"].find_one.return_value = documento("abandonado", "V-01")
        self.assertEqual(consultar_turno(self.db, "A-001")["estado"], "abandonado")
        posicion.assert_not_called()

    def test_invalid_codes_rejected_before_read(self):
        for codigo in ("", "A-1", "B-001", "urgente", None, 21, "A-001 OR 1=1"):
            with self.subTest(codigo=codigo), self.assertRaises(ConsultaError) as cm:
                consultar_turno(self.db, codigo)
            self.assertEqual(cm.exception.status, 400)
        self.db["turnos"].find_one.assert_not_called()

    @patch("app.consultar.cola.posicion_en_cola", return_value=0)
    def test_code_normalization(self, posicion):
        turno = consultar_turno(self.db, "  a-001  ")
        self.assertEqual(turno["codigo"], "A-001")
        posicion.assert_called_once_with("A-001")

    def test_unknown_turn_404(self):
        self.db["turnos"].find_one.return_value = None
        with self.assertRaises(ConsultaError) as cm:
            consultar_turno(self.db, "A-999")
        self.assertEqual(cm.exception.status, 404)

    def test_mongo_failure_503_sanitized(self):
        self.db["turnos"].find_one.side_effect = PyMongoError("secret URI")
        with self.assertRaises(ConsultaError) as cm:
            consultar_turno(self.db, "A-001")
        self.assertEqual(cm.exception.status, 503)
        self.assertNotIn("secret", str(cm.exception))

    def test_unknown_state_409(self):
        self.db["turnos"].find_one.return_value = documento("unrecognized")
        with self.assertRaises(ConsultaError) as cm:
            consultar_turno(self.db, "A-001")
        self.assertEqual(cm.exception.status, 409)

    def test_required_routes_registered(self):
        routes = {(r.path, method) for r in main.app.routes
                  for method in (getattr(r, "methods", None) or ())}
        for path in ("/consultar", "/turno/{codigo}", "/api/turnos/{codigo}"):
            self.assertIn((path, "GET"), routes)

    def test_original_issuance_route_preserved(self):
        routes = {(r.path, method) for r in main.app.routes
                  for method in (getattr(r, "methods", None) or ())}
        self.assertIn(("/api/turnos/emitir", "POST"), routes)
        self.assertIn(("/emitir", "GET"), routes)
        self.assertIn(("/emitir", "POST"), routes)

    @patch("app.main.consultar_turno")
    @patch("app.main.get_db")
    def test_api_success(self, get_db, servicio):
        servicio.return_value = {"codigo": "A-001", "estado": "pendiente"}
        result = main.api_consultar_turno("A-001")
        self.assertTrue(result["ok"])
        self.assertEqual(result["turno"]["codigo"], "A-001")
        servicio.assert_called_once_with(get_db.return_value, "A-001")

    @patch("app.main.get_db")
    def test_api_404(self, get_db):
        with patch("app.main.consultar_turno", side_effect=ConsultaError("No encontrado", 404)):
            response = main.api_consultar_turno("A-999")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
