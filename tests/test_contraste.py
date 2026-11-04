"""UI-06 · Los pares de colores principales cumplen el contraste WCAG AA (4,5:1) en texto normal."""
import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(encoding="utf-8")


def _variable(nombre: str) -> str:
    return re.findall(rf"{re.escape(nombre)}:\s*(#[0-9A-Fa-f]{{6}})", CSS)[-1]       # la última definición es la vigente


def _lum(color: str) -> float:
    r, g, b = (int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


class PruebasDeContraste(unittest.TestCase):
    def test_botones_y_enlaces(self):
        self.assertGreaterEqual(contraste("#FFFFFF", _variable("--c-marca")), 4.5)           # botón primario
        self.assertGreaterEqual(contraste(_variable("--c-marca"), _variable("--c-fondo")), 4.5)   # enlaces
        self.assertGreaterEqual(contraste("#FFFFFF", _variable("--viv-teal")), 4.5)          # banda de acción

    def test_etiquetas_de_color_sobre_su_fondo_suave(self):
        for nombre in ("teal", "azul", "verde", "ambar", "coral"):
            fuerte, suave = _variable(f"--viv-{nombre}"), _variable(f"--viv-{nombre}-suave")
            self.assertGreaterEqual(contraste(fuerte, suave), 4.5, nombre)
            self.assertGreaterEqual(contraste(fuerte, "#FFFFFF"), 4.5, nombre)

    def test_texto_de_la_aplicacion(self):
        fondo = _variable("--c-fondo")
        for variable in ("--c-texto", "--c-texto-suave", "--c-texto-tenue"):
            self.assertGreaterEqual(contraste(_variable(variable), "#FFFFFF"), 4.5, variable)
        self.assertGreaterEqual(contraste(_variable("--c-texto-suave"), fondo), 4.5)

    def test_etiquetas_del_menu_sobre_azul_marino(self):
        marino = "#0B111C"
        for nombre in ("teal", "azul", "verde", "ambar", "coral"):
            self.assertGreaterEqual(contraste(_variable(f"--viv-{nombre}-claro"), marino), 4.5, nombre)

    def test_menu_activo_con_texto_blanco(self):
        for nombre in ("teal", "azul", "verde", "ambar"):
            self.assertGreaterEqual(contraste("#FFFFFF", _variable(f"--viv-{nombre}")), 4.5, nombre)

    def test_usuario_y_cierre_de_sesion_del_menu_sobre_azul_marino(self):
        """Los colores de .sesion-usuario y .sesion-salir se leen de la hoja de estilos, no se repiten aquí."""
        marino = _variable("--c-nav")
        for regla in (".sesion-usuario", ".sesion-salir"):
            color = re.search(rf"{re.escape(regla)}\s*\{{[^}}]*?(?<![-\w])color:\s*(#[0-9A-Fa-f]{{6}})", CSS).group(1)
            self.assertGreaterEqual(contraste(color, marino), 4.5, regla)

    def test_portada_sobre_azul_marino(self):
        marino = "#0B111C"
        for texto in ("#5BB6C5", "#B8CBD8", "#FFFFFF"):
            self.assertGreaterEqual(contraste(texto, marino), 4.5, texto)


if __name__ == "__main__":
    unittest.main()
