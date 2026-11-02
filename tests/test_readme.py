"""El README final (TT-022) debe ser coherente con el repositorio: enlaces vivos, variables completas y sin secretos."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
README = (RAIZ / "README.md").read_text(encoding="utf-8")


class PruebasReadme(unittest.TestCase):
    def test_los_enlaces_relativos_apuntan_a_archivos_que_existen(self):
        rotos = []
        for destino in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", README):
            if destino.startswith(("http://", "https://", "mailto:")):
                continue
            if not (RAIZ / destino).exists():
                rotos.append(destino)
        self.assertEqual(rotos, [])

    def test_las_anclas_del_contenido_existen(self):
        titulos = {re.sub(r"[^\wáéíóúñ -]", "", t.lower()).strip().replace(" ", "-")
                   for t in re.findall(r"(?m)^#{2,3} (.+)$", README)}
        for ancla in re.findall(r"\]\(#([^)]+)\)", README):
            self.assertIn(ancla, titulos, ancla)

    def test_documenta_todas_las_variables_del_env_example(self):
        ejemplo = (RAIZ / ".env.example").read_text(encoding="utf-8")
        variables = set(re.findall(r"(?m)^([A-Z][A-Z0-9_]+)=", ejemplo))
        faltan = sorted(v for v in variables if f"`{v}`" not in README)
        self.assertEqual(faltan, [])

    def test_no_incluye_credenciales_ni_cadenas_de_conexion(self):
        self.assertNotRegex(README, r"mongodb(\+srv)?://[^\s]*:[^\s]*@")
        self.assertNotRegex(README, r"(?i)(password|contraseña|pass)\s*[:=]\s*\S{6,}")

    def test_enlaza_el_mapa_de_claves_y_el_changelog_y_nombra_la_version(self):
        for texto in ("docs/arquitectura/redis_claves.md", "CHANGELOG.md", "portal.yml", "v0.9.0"):
            self.assertIn(texto, README)

    def test_menciona_las_rutas_clave_de_la_operacion(self):
        for ruta in ("/salud", "/administracion", "/demo", "/turno/qr/{uuid}", "scripts.preparar_demo"):
            self.assertIn(ruta, README)

    def test_el_readme_ya_no_dice_seguimiento_1(self):
        self.assertNotIn("Seguimiento%201", README)


if __name__ == "__main__":
    unittest.main()
