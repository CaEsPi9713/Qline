"""La guía /demo cubre el recorrido completo de los Seguimientos 2 y 3."""
import re
import unittest
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main


class PruebasGuiaDemo(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        with mock.patch("app.main.verificar_redis", return_value={"ok": True, "version": "7"}):
            self.html = TestClient(main.app).get("/demo").text

    def test_tiene_los_23_pasos_numerados_sin_repetir(self):
        numeros = re.findall(r'data-paso="(\d+)"', self.html)
        self.assertEqual(numeros, [str(i) for i in range(1, 24)])
        self.assertIn("0 de 23 pasos", self.html)

    def test_incluye_quiosco_pantalla_abandono_y_recuperacion(self):
        for texto in ("/quiosco", "/pantalla", "scripts.barrer_abandonos", "scripts.rehidratar_cola --aplicar",
                      "scripts.probar_recuperacion", "scripts.medir_recuperacion",
                      "scripts.probar_fallos_recuperacion", "estado=abandonado",
                      "scripts/medir_indices_mongo.py", "scripts.probar_qr_token", "Descargar JSON", "sin usuario ni contraseña"):
            self.assertIn(texto, self.html, texto)

    def test_los_comandos_no_usan_opciones_que_ya_no_existen(self):
        self.assertNotIn("--simulado", self.html)
        self.assertNotIn("FLUSHALL", self.html.replace("nunca <code>FLUSHALL</code>", ""))


if __name__ == "__main__":
    unittest.main()
