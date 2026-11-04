"""La ficha del portal, la estructura de docs/ y el verificador de entrega: la entrega final debe ser coherente."""
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import verificar_entrega as v

RAIZ = Path(__file__).resolve().parents[1]


class PruebasDelFormatoDelPortal(unittest.TestCase):
    def test_lee_valores_listas_comillas_y_comentarios(self):
        d = v.leer_portal("# comentario\nnombre: QLine\nmotores: [Redis, MongoDB]\nvacia: []\ndia:\nurl: https://a.b/c\ncita: \"hola\"\n")
        self.assertEqual(d, {"nombre": "QLine", "motores": ["Redis", "MongoDB"], "vacia": [], "dia": "", "url": "https://a.b/c", "cita": "hola"})

    def test_rechaza_estructuras_anidadas(self):
        with self.assertRaises(ValueError):
            v.leer_portal("proyecto:\n  nombre: QLine\n")
        with self.assertRaises(ValueError):
            v.leer_portal("sin dos puntos\n")


class PruebasDelPortalReal(unittest.TestCase):
    def setUp(self):
        self.portal = v.leer_portal((RAIZ / "portal.yml").read_text(encoding="utf-8"))

    def test_tiene_exactamente_los_campos_del_enunciado(self):
        self.assertEqual(sorted(self.portal), sorted(v.CAMPOS_PORTAL))

    def test_valores_conocidos(self):
        p = self.portal
        self.assertEqual((p["nombre"], p["grupo"], p["dia"], p["periodo"], p["lenguaje"], p["licencia"]),
                         ("QLine", "2", "martes", "II-2026", "Python", "MIT"))
        self.assertEqual(p["motores"], ["Redis", "MongoDB"])
        self.assertTrue(p["repositorio"].startswith("https://github.com/"))
        self.assertTrue(p["demo_url"].startswith("https://"))

    def test_la_captura_existe(self):
        self.assertTrue((RAIZ / self.portal["captura"]).is_file())

    def test_el_repositorio_coincide_con_el_del_readme(self):
        self.assertIn(self.portal["repositorio"], (RAIZ / "README.md").read_text(encoding="utf-8"))

    def test_la_licencia_coincide_con_el_archivo_license(self):
        self.assertIn("MIT License", (RAIZ / "LICENSE").read_text(encoding="utf-8"))

    def test_no_publica_nombres_sin_autorizacion(self):
        self.assertEqual(self.portal["autores_publicos"], [])


class PruebasDeLaEstructuraDeDocs(unittest.TestCase):
    def test_ningun_enlace_de_los_markdown_esta_roto(self):
        self.assertEqual(v._enlaces_rotos(RAIZ), [])

    def test_estan_los_documentos_que_pide_la_entrega(self):
        self.assertEqual([a for a in v.ARCHIVOS_OBLIGATORIOS if not (RAIZ / a).exists()], [])

    def test_las_capturas_del_readme_existen(self):
        imagenes = sorted((RAIZ / "docs" / "img").glob("*.jpg"))
        self.assertGreaterEqual(len(imagenes), 8)
        readme = (RAIZ / "README.md").read_text(encoding="utf-8")
        for imagen in imagenes:
            self.assertIn(f"docs/img/{imagen.name}", readme)

    def test_docs_no_conserva_documentos_internos_de_trabajo(self):
        internos = ("00_PLAN_", "01_PLAN_", "02_DISENO_", "GUION_VERIFICACION", "UI_07_", "S4_AARON", "S4_abigail", "P07_PREPARACION")
        presentes = [p.name for p in (RAIZ / "docs" / "seguimientos").glob("*.md") if p.name.startswith(internos)]
        self.assertEqual(presentes, [])


class PruebasDelVerificador(unittest.TestCase):
    def estados(self, raiz):
        return {(e, n) for e, n, _ in v.revisar(raiz)}

    def test_el_repositorio_actual_no_tiene_errores(self):
        errores = [(n, d) for e, n, d in v.revisar(RAIZ) if e == "ERROR"]
        self.assertEqual(errores, [])

    def test_los_pendientes_son_los_datos_que_solo_el_equipo_puede_dar(self):
        pendientes = {n for e, n, _ in v.revisar(RAIZ) if e == "PENDIENTE"}
        permitidos = {"CHANGELOG · v1.0.0", "Tags"}
        self.assertLessEqual(pendientes, permitidos)

    def test_una_carpeta_vacia_da_errores(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn(("ERROR", "Archivos obligatorios"), self.estados(Path(t)))

    def test_detecta_enlaces_rotos_y_formato_de_portal_invalido(self):
        with tempfile.TemporaryDirectory() as t:
            raiz = Path(t)
            (raiz / "README.md").write_text("[roto](no-existe.md)\n", encoding="utf-8")
            (raiz / "portal.yml").write_text("proyecto:\n  nombre: x\n", encoding="utf-8")
            estados = self.estados(raiz)
        self.assertIn(("ERROR", "Enlaces de la documentación"), estados)
        self.assertIn(("ERROR", "portal.yml"), estados)

    def test_el_video_es_opcional_pero_si_existe_debe_estar_en_el_readme(self):
        portal = "".join(f"{c}: x\n" for c in v.CAMPOS_PORTAL if c not in ("motores", "autores_publicos", "demo_video", "dia", "captura"))
        base = portal + "motores: [Redis]\nautores_publicos: []\ndia: martes\ncaptura: c.jpg\n"
        with tempfile.TemporaryDirectory() as t:
            raiz = Path(t)
            (raiz / "c.jpg").write_bytes(b"x")
            (raiz / "README.md").write_text("sin video\n", encoding="utf-8")
            (raiz / "portal.yml").write_text(base + "demo_video:\n", encoding="utf-8")
            self.assertIn(("AVISO", "Video de demostración"), self.estados(raiz))
            (raiz / "portal.yml").write_text(base + "demo_video: https://youtu.be/abc\n", encoding="utf-8")
            self.assertIn(("PENDIENTE", "README · video"), self.estados(raiz))
            (raiz / "README.md").write_text("video: https://youtu.be/abc\n", encoding="utf-8")
            self.assertIn(("OK", "README · video"), self.estados(raiz))

    def test_detecta_credenciales_versionadas_pero_no_las_de_las_pruebas_ni_las_de_ejemplo(self):
        with tempfile.TemporaryDirectory() as t:
            raiz = Path(t)

            def git(*args):
                return subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=prueba", *args], cwd=raiz,
                                      capture_output=True, text=True)
            if git("init").returncode != 0:
                self.skipTest("git no está disponible")
            (raiz / "tests").mkdir()
            (raiz / "tests" / "t.py").write_text('X = "mongodb://u:p@h"\n', encoding="utf-8")          # credencial falsa de una prueba
            (raiz / "app.py").write_text('uri = f"mongodb://{user}:{pwd}@{host}"\n', encoding="utf-8")  # armada con variables
            (raiz / ".env.example").write_text("MONGO_PASS=tu_clave_aqui\n", encoding="utf-8")         # el ejemplo no cuenta
            (raiz / "tests" / "u.py").write_text('E = "MONGO_PASS=ejemplo123"\n', encoding="utf-8")   # tampoco las pruebas
            git("add", "-A")
            git("commit", "-m", "base")
            self.assertIn(("OK", "Secretos"), self.estados(raiz))
            (raiz / "config.py").write_text('URI = "mongodb://admin:Secreta123@servidor:27017/db"\n', encoding="utf-8")
            git("add", "-A")
            git("commit", "-m", "fuga")
            self.assertIn(("ERROR", "Secretos"), self.estados(raiz))

    def test_el_modo_estricto_falla_con_pendientes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(v.main(["--estricto"]), 1)


if __name__ == "__main__":
    unittest.main()
