"""Acentos de color por módulo en las pantallas internas: un color por rol, siempre sólidos y sin romper los botones."""
import re
import unittest
from tests.apoyo_sesion import ClienteConSesion
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(encoding="utf-8")
BLOQUE = CSS.split("Acentos de color en las pantallas internas")[1]


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeLasPantallas(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = ClienteConSesion(main.app)

    def test_cada_pantalla_interna_lleva_la_clase_de_su_rol(self):
        esperado = {"/cola": "rol-operador", "/panel": "rol-operador", "/historial": "rol-supervisor",
                    "/dashboard": "rol-supervisor", "/administracion": "rol-administracion", "/admin/sucursales": "rol-administracion",
                    "/demo": "rol-demo"}
        for ruta, clase in esperado.items():
            self.assertIn(clase, self.c.get(ruta).text, ruta)

    def test_el_menu_agrupa_por_color(self):
        html = self.c.get("/panel").text
        for grupo in ("grupo-cliente", "grupo-operador", "grupo-supervisor", "grupo-administracion"):
            self.assertIn(grupo, html)


class PruebasDelCss(unittest.TestCase):
    def test_hay_un_color_por_modulo(self):
        for rol in ("cliente", "operador", "supervisor", "administracion"):
            self.assertRegex(BLOQUE, rf"\.rol-{rol}[^{{]*\{{[^}}]*--mod:")

    def test_los_acentos_son_solidos(self):
        for prohibido in ("gradient", "backdrop-filter"):
            self.assertNotIn(prohibido, BLOQUE)

    def test_no_se_recolorean_todos_los_enlaces_de_la_pagina(self):
        """Una regla `.pagina a { color }` dejaría los botones con el texto del mismo color que su fondo."""
        self.assertNotRegex(BLOQUE, r"\.pagina\s+a\s*\{")

    def test_los_graficos_del_dashboard_usan_colores_de_la_paleta(self):
        for variable in ("--viv-teal", "--viv-ambar", "--viv-coral", "--viv-verde"):
            self.assertIn(f"background: var({variable})", BLOQUE)


if __name__ == "__main__":
    unittest.main()
