"""La guía /demo cubre el recorrido de la demo del Seguimiento 3, de la emisión a la evidencia."""
import re
import unittest
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main


class BaseDemo(BaseRedisMongo):
    def pedir(self, **env):
        with mock.patch("app.main.verificar_redis", return_value={"ok": True, "version": "7"}), \
                mock.patch.dict("os.environ", env):
            return TestClient(main.app).get("/demo").text


class PruebasGuiaDemo(BaseDemo):
    def setUp(self):
        super().setUp()
        self.html = self.pedir(PUBLIC_BASE_URL="https://grupo2.crnube.net", BASE_PATH="")

    def test_tiene_los_24_pasos_numerados_sin_repetir(self):
        numeros = re.findall(r'data-paso="(\d+)"', self.html)
        self.assertEqual(numeros, [str(i) for i in range(1, 25)])
        self.assertIn("0 de 24 pasos", self.html)

    def test_esta_organizada_en_siete_bloques_en_orden(self):
        titulos = re.findall(r"<h2>(\d) · ", self.html)
        self.assertEqual(titulos, [str(i) for i in range(1, 8)])

    def test_el_flujo_va_del_cliente_a_la_evidencia(self):
        ordenados = ["Emitir un turno normal desde el quiosco", "Abrir la pantalla de sala",
                     "Llamar al siguiente desde V-01", "Una ventanilla, un turno", "Iniciar la atención",
                     "Llamar a <code>A-001</code> y no atenderlo", "Aplicar la rehidratación",
                     "Descargar el historial y el dashboard", "Los índices se usan de verdad",
                     "10 solicitudes simultáneas", "Rehidratación probada y medida"]
        posiciones = [self.html.index(t) for t in ordenados]
        self.assertEqual(posiciones, sorted(posiciones))

    def test_cubre_cada_historia_y_tarea_de_la_demo(self):
        for texto in ("/quiosco", "/emitir", "/pantalla", "/ws-prueba", "/panel", "/historial", "/dashboard",
                      "scripts.barrer_abandonos", "scripts.rehidratar_cola", "scripts.probar_recuperacion",
                      "scripts.medir_recuperacion", "scripts.probar_fallos_recuperacion",
                      "scripts/probar_fallos_redis.py", "scripts/medir_rendimiento.py",
                      "scripts/prueba_concurrencia.py", "scripts/medir_indices_mongo.py", "scripts.probar_qr_token",
                      "sin usuario ni contraseña", "no-es-un-uuid", "redis-cli ttl"):
            self.assertIn(texto, self.html, texto)

    def test_los_comandos_no_usan_opciones_que_ya_no_existen(self):
        self.assertNotIn("--simulado", self.html)
        self.assertNotIn("FLUSHALL", self.html.replace("nunca <code>FLUSHALL</code>", ""))

    def test_cada_informe_apunta_a_docs_evidencia(self):
        informes = re.findall(r"--informe (docs/evidencia/[\w.]+\.md)", self.html)
        self.assertGreaterEqual(len(informes), 8)
        self.assertEqual(len(informes), len(set(informes)))

    def test_conserva_la_marca_de_cada_paso_en_su_propia_clave(self):
        self.assertIn("qline-demo-s3", self.html)


class PruebasEstadoDeLaDemo(BaseDemo):
    def test_muestra_a_donde_apuntan_los_qr(self):
        html = self.pedir(PUBLIC_BASE_URL="https://grupo2.crnube.net", BASE_PATH="/proyecto/qline")
        self.assertIn("QR apunta a https://grupo2.crnube.net/proyecto/qline", html)
        self.assertNotIn("una dirección local", html)

    def test_avisa_si_el_qr_apunta_a_una_direccion_local(self):
        html = self.pedir(PUBLIC_BASE_URL="http://localhost:8000", BASE_PATH="")
        self.assertIn("una dirección local", html)
        self.assertIn("PUBLIC_BASE_URL", html)

    def test_avisa_si_el_abandono_automatico_esta_apagado(self):
        html = self.pedir(PUBLIC_BASE_URL="https://grupo2.crnube.net")
        self.assertIn("Abandono automático", html)
        self.assertIn("apagado", html)                           # en las pruebas el barrido está apagado


if __name__ == "__main__":
    unittest.main()
