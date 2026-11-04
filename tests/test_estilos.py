"""La hoja de estilos única no debe romperse al integrar el trabajo de varias personas (merge de S4)."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "static" / "style.css").read_text(encoding="utf-8")
SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


class PruebasHojaDeEstilos(unittest.TestCase):
    def test_toda_variable_usada_esta_definida(self):
        definidas = set(re.findall(r"(--[\w-]+)\s*:", SIN_COMENTARIOS))
        usadas = set(re.findall(r"var\((--[\w-]+)", SIN_COMENTARIOS))
        self.assertEqual(sorted(usadas - definidas), [], "variables CSS sin definir (todo se vería sin color)")

    def test_las_llaves_estan_balanceadas(self):
        self.assertEqual(SIN_COMENTARIOS.count("{"), SIN_COMENTARIOS.count("}"))

    def test_las_dos_familias_de_variables_existen(self):
        for variable in ("--c-nav", "--c-marca", "--c-texto", "--azul-marino", "--turquesa", "--blanco"):
            self.assertIn(f"{variable}:", SIN_COMENTARIOS)

    def test_contenedor_es_solo_el_de_la_portada_y_el_crud_usa_admin_layout(self):
        reglas = re.findall(r"(?m)^\.contenedor\s*\{([^}]*)\}", SIN_COMENTARIOS)
        self.assertEqual(len(reglas), 1)
        self.assertNotIn("display: flex", reglas[0])
        self.assertIn(".admin-layout {", SIN_COMENTARIOS)

    def test_las_plantillas_usan_las_clases_renombradas(self):
        plantillas = RAIZ / "app" / "templates"
        self.assertIn("admin-layout", (plantillas / "administracion.html").read_text(encoding="utf-8"))
        self.assertIn("paso-inicio", (plantillas / "index.html").read_text(encoding="utf-8"))

    def test_las_paginas_publicas_comparten_la_navegacion(self):
        plantillas = RAIZ / "app" / "templates"
        for nombre in ("index.html", "acerca.html", "emitir.html", "consultar.html", "error_base.html"):
            self.assertIn("_nav_publica.html", (plantillas / nombre).read_text(encoding="utf-8"), nombre)

    def test_el_formulario_de_emision_envia_los_valores_que_acepta_el_servidor(self):
        texto = (RAIZ / "app" / "templates" / "emitir.html").read_text(encoding="utf-8")
        self.assertIn('value="normal"', texto)
        self.assertNotIn('value="regular"', texto)


if __name__ == "__main__":
    unittest.main()
