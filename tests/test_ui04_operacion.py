"""UI-04 · cola, panel y sala: superficies sólidas, estados con texto y símbolo, identificadores del JavaScript intactos."""
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.datos_prueba import construir_turno

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
PLANTILLAS = RAIZ / "app" / "templates"
AHORA = datetime.now(timezone.utc)


def _sin_comentarios(texto: str) -> str:
    return re.sub(r"/\*.*?\*/", "", texto, flags=re.S)


class PruebasHojaDeEstilos(unittest.TestCase):
    def test_las_llaves_estan_balanceadas(self):
        css = _sin_comentarios(CSS)
        self.assertEqual(css.count("{"), css.count("}"))

    def test_el_vidrio_solo_existe_en_las_opciones_del_quiosco(self):
        css = _sin_comentarios(CSS)
        for selector, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if "backdrop-filter" in cuerpo:
                self.assertIn("opcion-turno", selector, f"vidrio fuera del quiosco: {selector.strip()[:60]}")

    def test_el_bloque_ui04_no_usa_degradados_ni_vidrio(self):
        bloque = CSS.split("UI-04 · Cola, panel de atención y pantalla de sala")[1]
        self.assertNotIn("gradient", bloque)
        self.assertNotIn("backdrop-filter", bloque)

    def test_cada_estado_y_la_prioridad_preferencial_llevan_simbolo(self):
        bloque = CSS.split("UI-04 · Cola, panel de atención y pantalla de sala")[1]
        for clase in ("pendiente", "llamado", "en_atencion", "atendido", "abandonado", "preferencial"):
            self.assertRegex(bloque, rf"\.op \.badge-{clase}::before \{{ content: \"\\[0-9A-F]+")


class PruebasPlantillas(unittest.TestCase):
    def test_cola_panel_y_sala_no_usan_estilos_en_linea(self):
        for nombre in ("cola.html", "panel.html", "pantalla.html"):
            self.assertNotIn("style=", (PLANTILLAS / nombre).read_text(encoding="utf-8"), nombre)

    def test_la_sala_conserva_los_identificadores_del_javascript(self):
        texto = (PLANTILLAS / "pantalla.html").read_text(encoding="utf-8")
        for ident in ("n-espera", "n-activos", "btn-sonido", "sala-principal", "sala-otros", "indicador"):
            self.assertIn(f'id="{ident}"', texto)


class PruebasPantallas(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)

    def test_cola_y_panel_van_dentro_de_su_modulo(self):
        self.assertIn('class="op op-cola"', self.c.get("/cola").text)
        self.assertIn('class="op op-panel"', self.c.get("/panel").text)

    def test_el_panel_muestra_el_estado_como_texto(self):
        self.db["turnos"].insert_one(construir_turno(
            "A-010", "en_atencion", "normal", AHORA - timedelta(minutes=5), "V-01", AHORA - timedelta(minutes=2)))
        html = self.c.get("/panel").text
        self.assertIn("badge-en_atencion", html)
        self.assertIn(">en atencion<", html)


if __name__ == "__main__":
    unittest.main()
