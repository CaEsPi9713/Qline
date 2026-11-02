"""
Pruebas de regresión y aceptación para las tareas de Aaron Benavides en S4:
- P01: Aviso explícito de finalización de atención en QR (SSR y JS)
- P04: Identidad institucional verificada y consistente (QLine · Atención General)
- P05: Indicaciones claras y accesibles en la página de consulta QR
- S4-M02: Ticket imprimible (window.print, @media print, pausa de temporizador)
"""

import unittest
import uuid
from unittest.mock import MagicMock, patch

from tests.test_consulta_qr import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    from app import main
    from app.constantes import (
        ESTADO_ATENDIDO,
        ESTADO_PENDIENTE,
        PRIORIDAD_NORMAL,
        PRIORIDAD_PREFERENCIAL,
        SERVICIO_ID,
        SERVICIO_NOMBRE,
    )
    from tests.test_consulta_qr import BaseQR
else:
    BaseQR = unittest.TestCase


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan dependencias de prueba (fakeredis, mongomock o httpx)")
class PruebasS4Aaron(BaseQR):

    # =========================================================================
    # P01: Aviso de finalización de atención en QR
    # =========================================================================
    def test_p01_aviso_finalizacion_atendido_en_ssr(self):
        """Verifica que al renderizar un turno 'atendido', la página indique que finalizó y puede cerrar la pestaña."""
        token = str(uuid.uuid4())
        self.turno_con_token("A-099", token, estado=ESTADO_ATENDIDO, ventanilla="V-01")
        r = self.c.get(f"/turno/qr/{token}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("Su atención finalizó. Puede cerrar esta pestaña.", html)
        self.assertIn("Puede cerrar esta pestaña", html)
        self.assertIn("badge-atendido", html)

    def test_p01_script_cliente_incluye_aviso_en_actualizacion_en_vivo(self):
        """Verifica que la lógica JS para actualización dinámica contenga el mensaje explícito de cierre."""
        token = str(uuid.uuid4())
        self.turno_con_token("A-100", token, estado=ESTADO_PENDIENTE)
        r = self.c.get(f"/turno/qr/{token}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn(
            'case "atendido": return "Su atención finalizó. Puede cerrar esta pestaña. ¡Gracias por su visita!";',
            html,
        )

    # =========================================================================
    # P04: Identidad institucional y de servicio verificada
    # =========================================================================
    def test_p04_identidad_en_consulta_qr(self):
        """La vista de consulta QR muestra la identidad verificada QLine y el servicio oficial."""
        token = str(uuid.uuid4())
        self.turno_con_token("A-101", token, estado=ESTADO_PENDIENTE)
        r = self.c.get(f"/turno/qr/{token}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        self.assertIn("QLine", html)
        self.assertIn(SERVICIO_NOMBRE, html)
        self.assertIn(f"QLine · {SERVICIO_NOMBRE}", html)

    def test_p04_identidad_en_quiosco_y_confirmacion(self):
        """El quiosco y su ticket de confirmación muestran QLine y el servicio Atención General."""
        r_quiosco = self.c.get("/quiosco")
        self.assertEqual(r_quiosco.status_code, 200)
        self.assertIn("Bienvenido a QLine", r_quiosco.text)
        self.assertIn(SERVICIO_NOMBRE, r_quiosco.text)

    # =========================================================================
    # P05: Instrucciones de espera en consulta QR
    # =========================================================================
    def test_p05_instrucciones_claras_de_espera(self):
        """La página QR contiene instrucciones claras: mantener abierta, autoactualización, no recargar, no cancela turno."""
        token = str(uuid.uuid4())
        self.turno_con_token("A-102", token, estado=ESTADO_PENDIENTE)
        r = self.c.get(f"/turno/qr/{token}")
        self.assertEqual(r.status_code, 200)
        html = r.text
        # Mantener disponible mientras espera
        self.assertIn("Conserve esta página abierta", html)
        # Actualización automática en tiempo real
        self.assertIn("actualiza automáticamente", html)
        # Recarga manual innecesaria
        self.assertIn("no es necesario recargarla", html)
        # Reasegurar que cerrar no cancela el turno
        self.assertIn("su turno sigue activo en el sistema", html)

    # =========================================================================
    # S4-M02: Ticket imprimible y estilos de impresión
    # =========================================================================
    def test_s4_m02_ticket_confirmacion_quiosco_tiene_accion_imprimir_y_pausa(self):
        """La vista quiosco_confirmado tiene botón de imprimir y control de temporizador."""
        req = MagicMock()
        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            fake_token = str(uuid.uuid4())
            mock_emitir.return_value = {
                "id": str(uuid.uuid4()),
                "codigo": "A-042",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_NORMAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-11-01T14:00:00+00:00",
                "qr_token": fake_token,
                "qr_url": f"https://grupo2.crnube.net/turno/qr/{fake_token}",
            }
            resp = main.accion_quiosco(req, "normal")
            self.assertEqual(resp.status_code, 200)
            body = resp.body.decode("utf-8")
            # Botón de impresión
            self.assertIn("btn-imprimir", body)
            self.assertIn("Imprimir ticket", body)
            self.assertIn("imprimirTicket()", body)
            # Identidad en el ticket
            self.assertIn(f"QLine · {SERVICIO_NOMBRE}", body)
            # Datos esenciales presentes
            self.assertIn("A-042", body)
            self.assertIn("Prioridad Normal", body)
            self.assertIn("qr-svg", body)
            # Manejo del temporizador para no interrumpir el diálogo de impresión
            self.assertIn("beforeprint", body)
            self.assertIn("afterprint", body)
            self.assertIn("pausado", body)

    def test_s4_m02_ticket_confirmacion_emitir_tiene_accion_imprimir(self):
        """La vista turno_confirmado tiene botón de imprimir y datos completos del ticket."""
        req = MagicMock()
        with patch("app.main.get_db"), patch("app.main.emitir_turno") as mock_emitir, patch("app.main._publicar_evento"):
            fake_token = str(uuid.uuid4())
            mock_emitir.return_value = {
                "id": str(uuid.uuid4()),
                "codigo": "P-007",
                "servicio": SERVICIO_ID,
                "servicio_nombre": SERVICIO_NOMBRE,
                "prioridad": PRIORIDAD_PREFERENCIAL,
                "estado": ESTADO_PENDIENTE,
                "creado": "2026-11-01T14:00:00+00:00",
                "qr_token": fake_token,
                "qr_url": f"https://grupo2.crnube.net/turno/qr/{fake_token}",
            }
            resp = main.accion_emitir(req, "preferencial")
            self.assertEqual(resp.status_code, 200)
            body = resp.body.decode("utf-8")
            # Botón de impresión
            self.assertIn("btn-imprimir", body)
            self.assertIn("Imprimir ticket", body)
            self.assertIn("window.print()", body)
            # Identidad en el ticket
            self.assertIn(f"QLine · {SERVICIO_NOMBRE}", body)
            # Datos esenciales
            self.assertIn("P-007", body)
            self.assertIn("Prioridad Preferencial", body)

    def test_s4_m02_css_contiene_reglas_media_print(self):
        """Verifica que static/style.css defina estilos @media print que oculten controles y limpien el ticket."""
        with open("static/style.css", "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn("@media print", css)
        self.assertIn(".btn-imprimir", css)
        self.assertIn(".ticket-institucion", css)
        self.assertIn("header, footer, nav", css)
        self.assertIn("display: none !important;", css)
        self.assertIn("break-inside: avoid;", css)


if __name__ == "__main__":
    unittest.main()
