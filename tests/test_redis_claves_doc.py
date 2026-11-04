"""TT-027 · Toda familia de claves `grupo2:qline:` que usa el código está en el mapa de claves de Redis."""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MAPA = RAIZ / "docs" / "arquitectura" / "redis_claves.md"
PREFIJO = "grupo2:qline:"
# Literal completo, o f-string con {REDIS_PREFIJO}; captura el primer segmento y, en las claves de prueba, el segundo.
PATRON = re.compile(r"(?:grupo2:qline:|\{REDIS_PREFIJO\})([a-z_]+)(?::([a-z_]+))?")
FAMILIAS_DE_PRUEBA = {"prueba", "test"}


def _claves_usadas() -> set:
    usadas = set()
    fuentes = [*(RAIZ / "app").rglob("*.py"), *(RAIZ / "app" / "templates").glob("*.html"),
               *(RAIZ / "scripts").glob("*.py")]
    for ruta in fuentes:
        for primero, segundo in PATRON.findall(ruta.read_text(encoding="utf-8")):
            usadas.add(PREFIJO + primero + (f":{segundo}" if primero in FAMILIAS_DE_PRUEBA and segundo else ""))
    return usadas


class PruebasMapaDeClaves(unittest.TestCase):
    def test_el_mapa_existe(self):
        self.assertTrue(MAPA.is_file())

    def test_todas_las_claves_usadas_estan_documentadas(self):
        documento = MAPA.read_text(encoding="utf-8")
        usadas = _claves_usadas()
        self.assertGreaterEqual(len(usadas), 8, "el escaneo no encontró las claves esperadas")
        faltan = sorted(c for c in usadas if c not in documento)
        self.assertEqual(faltan, [], f"claves sin documentar en {MAPA.name}: {faltan}")

    def test_las_claves_del_contrato_siguen_en_las_constantes(self):
        from app import constantes
        documento = MAPA.read_text(encoding="utf-8")
        for clave in (constantes.CLAVE_CONTADOR, constantes.CLAVE_COLA, constantes.CLAVE_EVENTOS):
            self.assertIn(clave, documento)
        self.assertIn(constantes.clave_ventanilla_actual("{id}"), documento)
        self.assertIn(constantes.clave_turno("{codigo}"), documento)


if __name__ == "__main__":
    unittest.main()
