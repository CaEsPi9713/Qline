"""RFC-004 (sucursales) se presenta como un extra del trabajo y sin aparentar que el sistema es multisucursal."""
import unittest
from tests.apoyo_sesion import ClienteConSesion
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main

RAIZ = Path(__file__).resolve().parents[1]


def _leer(ruta: str) -> str:
    return (RAIZ / ruta).read_text(encoding="utf-8")


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeLasPantallas(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = ClienteConSesion(main.app)

    def test_la_pantalla_de_sucursales_dice_que_es_un_extra_y_su_alcance(self):
        html = self.c.get("/admin/sucursales").text
        self.assertIn("Extra del proyecto", html)
        self.assertIn("fuera del alcance del Plan Alternativo", html)
        self.assertIn("un solo servicio y de una sola sede", html)

    def test_la_administracion_rotula_la_tarjeta_de_sucursales_como_extra(self):
        html = self.c.get("/administracion").text
        self.assertIn("Sucursales del Sistema (RFC-004)", html)
        self.assertRegex(html, r"Sucursales del Sistema \(RFC-004\) <span[^>]*>Extra</span>")


class PruebasDeLaDocumentacion(unittest.TestCase):
    def test_cada_documento_lo_presenta_como_extra(self):
        for ruta in ("README.md", "CHANGELOG.md", "docs/arquitectura/spec_mantenimiento_sucursales.md",
                     "docs/presentacion/PRESENTACION_FINAL.md", "docs/decisiones.md", "docs/seguimientos/S4.md"):
            texto = _leer(ruta)
            self.assertRegex(texto, r"(?i)extra", ruta)

    def test_ningun_documento_lo_presenta_como_multisucursal_operativa(self):
        for ruta in ("README.md", "CHANGELOG.md", "docs/presentacion/PRESENTACION_FINAL.md"):
            texto = _leer(ruta).lower()
            self.assertNotIn("sistema multisucursal", texto.replace("no vuelve multisucursal al sistema", ""), ruta)

    def test_la_decision_d34_existe_y_dice_lo_que_no_hace(self):
        decisiones = _leer("docs/decisiones.md")
        self.assertIn("### D-34 · El mantenimiento de sucursales (RFC-004) se presenta como un extra del trabajo", decisiones)
        self.assertIn("No** hay colas, claves de Redis, emisión, quiosco, QR ni pantalla de sala por sucursal", decisiones)

    def test_el_mapa_de_claves_de_redis_no_tiene_sucursales(self):
        self.assertNotIn("sucursal", _leer("docs/arquitectura/redis_claves.md").lower())

    def test_el_codigo_operativo_no_distingue_sucursales(self):
        for modulo in ("app/emitir.py", "app/llamado.py", "app/cola.py", "app/panel_atencion.py", "app/consulta_qr.py"):
            self.assertNotIn("sucursal", _leer(modulo).lower(), modulo)


if __name__ == "__main__":
    unittest.main()
