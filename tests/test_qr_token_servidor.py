"""Prueba de qr_token e índice parcial único (la versión del servidor se ejecuta con scripts.probar_qr_token)."""
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS

if HAY_DEPENDENCIAS:
    import mongomock

    from app import main, prueba_qr_token as pq
    from app.turnos_schema import INDICES_TURNOS


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasQrToken(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient()["g"]
        self.col = self.db["turnos"]
        for i in INDICES_TURNOS:
            self.col.create_index(i["keys"], **i["options"])
        self._get_db = main.get_db
        main.get_db = lambda: self.db

    def tearDown(self):
        main.get_db = self._get_db

    def test_con_el_indice_parcial_unico_todo_cumple(self):
        res = pq.ejecutar(self.col)
        fallas = [(c.nombre, c.detalle) for c in res.comprobaciones if c.ok is False]
        self.assertEqual(fallas, [])
        self.assertTrue(res.ok)
        nombres = [c.nombre for c in res.comprobaciones]
        self.assertIn("Un segundo turno con el mismo qr_token se rechaza", nombres)
        self.assertIn("Varios turnos sin qr_token (ausente o null) conviven", nombres)

    def test_sin_el_indice_unico_la_prueba_lo_detecta(self):
        self.col.drop_index("idx_turnos_qr_token_unico")
        res = pq.ejecutar(self.col)
        self.assertFalse(res.ok)
        duplicado = next(c for c in res.comprobaciones if c.nombre.startswith("Un segundo turno"))
        self.assertFalse(duplicado.ok)

    def test_el_plan_es_informativo_si_no_hay_explain(self):
        res = pq.ejecutar(self.col)
        plan = next(c for c in res.comprobaciones if c.nombre.startswith("La consulta por token"))
        self.assertIn(plan.ok, (True, None))            # mongomock no implementa explain: queda informativo

    def test_limpia_sus_turnos_siempre(self):
        self.col.insert_one({"codigo": "A-001", "servicio": "atencion_general"})
        pq.ejecutar(self.col)
        self.assertEqual(self.col.count_documents({"codigo": {"$in": pq.CODIGOS}}), 0)
        self.assertEqual(self.col.count_documents({"codigo": "A-001"}), 1)

    def test_el_validador_de_python_rechaza_tokens_invalidos(self):
        res = pq.ejecutar(self.col)
        c = next(c for c in res.comprobaciones if c.nombre.startswith("El validador de Python"))
        self.assertTrue(c.ok)

    def test_informe_y_script(self):
        from scripts import probar_qr_token
        ruta = Path(tempfile.mkdtemp()) / "q.md"
        with redirect_stdout(io.StringIO()) as salida:
            codigo = probar_qr_token.main(["--informe", str(ruta)])
        self.assertEqual(codigo, 0)
        md = ruta.read_text(encoding="utf-8")
        self.assertIn("CORRECTO", md)
        self.assertIn("informativo", md)
        self.assertNotIn("SIMULADO", md)


if __name__ == "__main__":
    unittest.main()
