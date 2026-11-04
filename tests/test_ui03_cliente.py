"""UI-03 · pantallas del cliente: quiosco con panel sólido y vidrio solo en las opciones, ticket y QR sin estilos en línea."""
import re
import unittest
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main

RAIZ = Path(__file__).resolve().parents[1]
PLANTILLAS = RAIZ / "app" / "templates"
CSS = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
CLIENTE = ("quiosco.html", "quiosco_confirmado.html", "turno_confirmado.html", "turno_qr.html",
           "_ticket.html", "emitir.html", "consultar.html")


def _regla(selector: str) -> str:
    cuerpos = [c for s, c in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
               if selector in [x.strip() for x in s.split(",")]]
    return " ".join(cuerpos)


class PruebasPlantillasDelCliente(unittest.TestCase):
    def test_ninguna_pantalla_del_cliente_usa_estilos_en_linea(self):
        for nombre in CLIENTE:
            self.assertNotIn("style=", (PLANTILLAS / nombre).read_text(encoding="utf-8"), nombre)

    def test_el_quiosco_conserva_el_formulario_y_sus_valores(self):
        texto = (PLANTILLAS / "quiosco.html").read_text(encoding="utf-8")
        self.assertIn('method="post" action="{{ base }}/quiosco"', texto)
        self.assertIn('name="prioridad" value="normal"', texto)
        self.assertIn('name="prioridad" value="preferencial"', texto)

    def test_quiosco_y_emision_envian_valores_que_acepta_el_servidor(self):
        for nombre in ("quiosco.html", "emitir.html"):
            self.assertNotIn('value="regular"', (PLANTILLAS / nombre).read_text(encoding="utf-8"), nombre)

    def test_las_dos_confirmaciones_comparten_el_ticket(self):
        for nombre in ("quiosco_confirmado.html", "turno_confirmado.html"):
            self.assertIn('{% include "_ticket.html" %}', (PLANTILLAS / nombre).read_text(encoding="utf-8"), nombre)

    def test_la_emision_ya_no_usa_la_cabecera_de_operacion(self):
        self.assertIn("base_publico.html", (PLANTILLAS / "turno_confirmado.html").read_text(encoding="utf-8"))


class PruebasDeVidrio(unittest.TestCase):
    def test_el_vidrio_solo_esta_en_las_opciones_del_quiosco(self):
        reglas = re.findall(r"([^{}]+)\{([^{}]*backdrop-filter[^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S))
        self.assertTrue(reglas)
        for selector, _ in reglas:
            self.assertEqual(selector.strip(), ".opcion-turno")

    def test_el_panel_bienvenido_y_el_ticket_son_solidos(self):
        for selector in (".quiosco-panel", ".ticket", ".ticket-qr-marco"):
            cuerpo = _regla(selector)
            self.assertNotIn("backdrop-filter", cuerpo, selector)
            self.assertNotIn("rgba(", cuerpo, selector)
        self.assertIn("background: var(--superficie)", _regla(".quiosco-panel"))

    def test_el_vidrio_es_discreto(self):
        alfa = re.search(r"background:\s*rgba\([^)]*,\s*([\d.]+)\)", _regla(".opcion-turno"))
        self.assertLessEqual(float(alfa.group(1)), 0.2)


class PruebasRenderizado(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app)

    def test_el_quiosco_usa_la_escena_sobria_y_el_enlace_para_saltar(self):
        html = self.c.get("/quiosco").text
        for texto in ('class="publico quiosco"', "quiosco-escena", "quiosco-panel", "opcion-turno",
                      'href="#contenido"', 'id="contenido"'):
            self.assertIn(texto, html)

    def test_el_quiosco_tiene_la_navegacion_publica_y_ningun_enlace_interno(self):
        html = self.c.get("/quiosco").text
        self.assertIn("publico-nav", html)
        for texto in ("Inicio", "Sacar turno", "Consultar turno", "Acerca de"):
            self.assertIn(texto, html)
        for ruta in ("/cola", "/panel", "/historial", "/dashboard", "/administracion", "/demo"):
            self.assertNotIn(ruta, html)

    def test_el_quiosco_es_claro_y_no_oscuro(self):
        self.assertNotIn("body.quiosco { background: var(--azul-marino", CSS)
        self.assertIn("background: transparent", _regla(".quiosco-escena"))

    def test_las_paginas_publicas_tienen_enlace_para_saltar_al_contenido(self):
        for ruta in ("/", "/acerca", "/consultar", "/emitir", "/no-existe"):
            self.assertIn('href="#contenido"', self.c.get(ruta).text, ruta)

    def test_la_confirmacion_de_emision_es_publica_y_no_enlaza_a_la_cola(self):
        html = self.c.post("/emitir", data={"prioridad": "normal"}).text
        self.assertIn("publico-nav", html)
        self.assertNotIn("/cola", html)
        self.assertIn("btn-imprimir", html)

    def test_el_aviso_del_qr_usa_el_atributo_hidden(self):
        r = self.c.post("/quiosco", data={"prioridad": "normal"})
        token = re.search(r"/turno/qr/([0-9a-f-]{36})", r.text).group(1)
        html = self.c.get(f"/turno/qr/{token}").text
        self.assertRegex(html, r'id="aviso"\s+hidden')
        self.assertIn("aviso.hidden = false", html)


if __name__ == "__main__":
    unittest.main()
