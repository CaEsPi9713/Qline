"""
Pruebas automatizadas y aisladas para HU-003: UUID v4 y QR del ticket.

Verifica:
1. Generación de UUID v4 (formato canónico, versión 4, minúsculas, unicidad).
2. Persistencia en MongoDB en el mismo y único `insert_one` de la emisión.
3. Construcción de URL pública según contrato ({PUBLIC_BASE_URL}{BASE_PATH}/turno/qr/{uuid}).
4. Seguridad: el QR contiene exclusivamente la URL pública (sin datos personales ni credenciales).
5. Generación vectorial SVG nativa del código QR.
6. Integración con HU-013 (el token emitido es consumible por consultar_por_token).
7. Compatibilidad con turnos históricos sin qr_token (consultar_turno sigue funcionando).
8. Manejo de fallos (MongoDB caído no confirma turnos incompletos).

Todas las pruebas se ejecutan de manera aislada con dobles de prueba (mocks) sin tocar
MongoDB ni Redis reales.
"""
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId
from pymongo.errors import PyMongoError

from app.constantes import (
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    SERVICIO_ID,
    SERVICIO_NOMBRE,
)
from app.consulta_qr import QRError, consultar_por_token, validar_token
from app.consultar import consultar_turno
from app.emitir import EmisionError, emitir_turno
from app.main import accion_emitir, api_emitir_turno
from app.qr import construir_url_qr, generar_qr_svg

PATRON_UUID4_STRICT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class TestHU003UUIDyQR(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_collection = MagicMock()
        self.mock_db.__getitem__.return_value = self.mock_collection
        self.mock_db["turnos"] = self.mock_collection
        self.fake_id = ObjectId()
        self.mock_collection.insert_one.return_value = MagicMock(inserted_id=self.fake_id)
        self.mock_collection.delete_one.return_value = MagicMock(deleted_count=1)

    # -------------------------------------------------------------------------
    # 1. Generación de UUID v4 en emisión
    # -------------------------------------------------------------------------
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-001")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_genera_uuid_v4_valido_en_minusculas(self, mock_encolar, mock_siguiente_codigo):
        res = emitir_turno(self.mock_db, "normal")

        self.assertIn("qr_token", res)
        token = res["qr_token"]
        self.assertIsInstance(token, str)
        self.assertEqual(token, token.lower())
        self.assertTrue(
            bool(PATRON_UUID4_STRICT.match(token)),
            f"El token generado '{token}' no cumple con el formato canónico de UUID v4",
        )
        # Compatible con la función de validación de Alessandro
        token_validado = validar_token(token)
        self.assertEqual(token_validado, token)

    @patch("app.emitir.cola.siguiente_codigo", side_effect=["A-001", "A-002"])
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_uuid_es_independiente_y_unico_por_turno(self, mock_encolar, mock_siguiente_codigo):
        t1 = emitir_turno(self.mock_db, "normal")
        t2 = emitir_turno(self.mock_db, "preferencial")

        self.assertNotEqual(t1["qr_token"], t2["qr_token"])
        self.assertNotIn("A-001", t1["qr_token"])
        self.assertNotIn("A-002", t2["qr_token"])

    # -------------------------------------------------------------------------
    # 2. Persistencia atómica en el mismo insert_one
    # -------------------------------------------------------------------------
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-010")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_persiste_qr_token_en_el_mismo_insert_one(self, mock_encolar, mock_siguiente_codigo):
        res = emitir_turno(self.mock_db, "normal")

        self.mock_collection.insert_one.assert_called_once()
        doc_insertado = self.mock_collection.insert_one.call_args[0][0]

        self.assertIn("qr_token", doc_insertado)
        self.assertEqual(doc_insertado["qr_token"], res["qr_token"])
        self.assertEqual(doc_insertado["codigo"], "A-010")
        self.assertEqual(doc_insertado["estado"], ESTADO_PENDIENTE)

        # No debe haber actualizaciones posteriores (no update_one)
        self.mock_collection.update_one.assert_not_called()

    @patch("app.emitir.cola.siguiente_codigo", return_value="A-011")
    @patch("app.emitir.cola.encolar")
    def test_fallo_mongo_no_confirma_turno_incompleto(self, mock_encolar, mock_siguiente_codigo):
        self.mock_collection.insert_one.side_effect = PyMongoError("Error de escritura en nodo primario")

        with self.assertRaises(EmisionError) as ctx:
            emitir_turno(self.mock_db, "normal")

        self.assertEqual(ctx.exception.status, 503)
        mock_encolar.assert_not_called()

    # -------------------------------------------------------------------------
    # 3. Construcción de URL pública del QR
    # -------------------------------------------------------------------------
    def test_construir_url_qr_respetando_base_url_y_base_path(self):
        token = "12345678-1234-4234-8234-123456789abc"

        url1 = construir_url_qr(
            token, base_url="https://grupo2.crnube.net", base_path="/proyecto/qline"
        )
        self.assertEqual(
            url1, f"https://grupo2.crnube.net/proyecto/qline/turno/qr/{token}"
        )

        # Manejo de barras finales y espacios
        url2 = construir_url_qr(
            token, base_url="https://grupo2.crnube.net/", base_path="proyecto/qline/"
        )
        self.assertEqual(
            url2, f"https://grupo2.crnube.net/proyecto/qline/turno/qr/{token}"
        )

        # Sin base_path (raíz)
        url3 = construir_url_qr(token, base_url="https://qline.example.com", base_path="")
        self.assertEqual(url3, f"https://qline.example.com/turno/qr/{token}")

    def test_construir_url_qr_rechaza_token_invalido(self):
        with self.assertRaises(QRError) as ctx:
            construir_url_qr("no-es-uuid")
        self.assertEqual(ctx.exception.status, 400)

    # -------------------------------------------------------------------------
    # 4. Seguridad: el contenido del QR contiene solo la URL pública
    # -------------------------------------------------------------------------
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-099")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_el_qr_no_expone_credenciales_ni_datos_sensibles(self, mock_encolar, mock_siguiente_codigo):
        res = emitir_turno(self.mock_db, "normal")
        qr_url = res["qr_url"]

        self.assertNotIn("A-099", qr_url)
        self.assertNotIn("password", qr_url)
        self.assertNotIn(str(self.fake_id), qr_url)
        self.assertNotIn("operador", qr_url)

    # -------------------------------------------------------------------------
    # 5. Generación de SVG vectorial nativo
    # -------------------------------------------------------------------------
    def test_generar_qr_svg_produce_svg_valido(self):
        token = "e1a1795c-9d62-4299-8cf0-aa822be7b5c8"
        url = construir_url_qr(token, base_url="https://grupo2.crnube.net", base_path="/proyecto/qline")

        svg = generar_qr_svg(url)
        self.assertIsInstance(svg, str)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.endswith("</svg>"))
        self.assertIn("viewBox=", svg)
        self.assertIn("<path", svg)
        self.assertIn("<rect", svg)
        self.assertIn("shape-rendering=\"crispEdges\"", svg)

    def test_decodificacion_independiente_con_zxing_recupera_url_exacta(self):
        """Verifica mediante decodificación externa e independiente que el QR es escaneable."""
        try:
            from PIL import Image
            import zxingcpp
            from app.qr import _construir_matriz_qr
        except ImportError:
            self.skipTest("zxing-cpp o pillow no disponibles para prueba de decodificación")

        token = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        url_esperada = construir_url_qr(token, base_url="https://grupo2.crnube.net", base_path="/proyecto/qline")

        matrix, size = _construir_matriz_qr(url_esperada)
        quiet_zone = 4
        full_size = size + 2 * quiet_zone
        scale = 8
        img = Image.new("RGB", (full_size * scale, full_size * scale), (255, 255, 255))
        pixels = img.load()

        for r in range(size):
            for c in range(size):
                if matrix[r][c] == 1:
                    for dr in range(scale):
                        for dc in range(scale):
                            pixels[(c + quiet_zone) * scale + dc, (r + quiet_zone) * scale + dr] = (0, 0, 0)

        resultado = zxingcpp.read_barcode(img)
        self.assertIsNotNone(resultado, "El motor ZXing no pudo detectar ni decodificar el código QR generado")
        self.assertEqual(resultado.format.name, "QRCode")
        self.assertEqual(resultado.text, url_esperada)

    # -------------------------------------------------------------------------
    # 6. Integración con HU-013 (Alessandro)
    # -------------------------------------------------------------------------
    @patch("app.emitir.cola.siguiente_codigo", return_value="A-001")
    @patch("app.emitir.cola.encolar", return_value=True)
    def test_integracion_con_consultar_por_token(self, mock_encolar, mock_siguiente_codigo):
        res = emitir_turno(self.mock_db, "normal")
        token = res["qr_token"]

        # Simulamos que MongoDB devuelve el documento que emitir_turno acaba de insertar
        self.mock_collection.find_one.side_effect = [
            {"codigo": "A-001"},  # Primer find_one de consultar_por_token
            {
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "prioridad": "normal",
                "estado": ESTADO_PENDIENTE,
                "ventanilla": None,
                "qr_token": token,
            },  # Segundo find_one en consultar_turno
        ]

        with patch("app.consultar.cola.posicion_en_cola", return_value=0):
            turno_consultado = consultar_por_token(self.mock_db, token)
            self.assertEqual(turno_consultado["codigo"], "A-001")
            self.assertEqual(turno_consultado["estado"], ESTADO_PENDIENTE)
            self.assertEqual(turno_consultado["posicion"], 1)

    # -------------------------------------------------------------------------
    # 7. Compatibilidad histórica con turnos sin qr_token
    # -------------------------------------------------------------------------
    def test_compatibilidad_turnos_historicos_sin_qr_token(self):
        # Turno histórico de S2 emitido antes de HU-003
        doc_historico = {
            "codigo": "A-005",
            "servicio": SERVICIO_ID,
            "prioridad": "normal",
            "estado": ESTADO_PENDIENTE,
            "ventanilla": None,
            # sin qr_token
        }
        self.mock_collection.find_one.return_value = doc_historico

        with patch("app.consultar.cola.posicion_en_cola", return_value=2):
            t = consultar_turno(self.mock_db, "A-005")
            self.assertEqual(t["codigo"], "A-005")
            self.assertEqual(t["estado"], ESTADO_PENDIENTE)
            self.assertEqual(t["posicion"], 3)

        # Si se intenta consultar por token un turno que no existe, QRError 404
        self.mock_collection.find_one.return_value = None
        with self.assertRaises(QRError) as ctx:
            consultar_por_token(self.mock_db, "12345678-1234-4234-8234-123456789abc")
        self.assertEqual(ctx.exception.status, 404)

    # -------------------------------------------------------------------------
    # 8. Endpoints API y HTML
    # -------------------------------------------------------------------------
    async def test_api_emitir_turno_incluye_qr_token_y_qr_url(self):
        req = MagicMock()
        req.headers = {"content-type": "application/json"}
        req.json = AsyncMock(return_value={"prioridad": "normal"})

        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            fake_token = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
            mock_emitir.return_value = {
                "id": str(self.fake_id),
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-10-25T17:00:00+00:00",
                "qr_token": fake_token,
                "qr_url": f"https://grupo2.crnube.net/turno/qr/{fake_token}",
            }
            res = await api_emitir_turno(req)
            self.assertTrue(res["ok"])
            self.assertEqual(res["turno"]["qr_token"], fake_token)
            self.assertIn("qr_url", res["turno"])
            self.assertIn(fake_token, res["turno"]["qr_url"])

    def test_accion_emitir_renderiza_qr_en_turno_confirmado(self):
        fake_token = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
        fake_url = f"https://grupo2.crnube.net/turno/qr/{fake_token}"
        req = MagicMock()

        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            mock_emitir.return_value = {
                "id": str(self.fake_id),
                "codigo": "A-001",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-10-25T17:00:00+00:00",
                "qr_token": fake_token,
                "qr_url": fake_url,
            }
            resp = accion_emitir(req, "normal")
            self.assertEqual(resp.status_code, 200)
            body = resp.body.decode("utf-8")
            self.assertIn("A-001", body)
            self.assertIn("qr-svg", body)
            self.assertIn(fake_url, body)


if __name__ == "__main__":
    unittest.main()
