"""La evidencia de S4-M03 (que se ejecuta en el servidor) funciona con una base simulada y limpia lo que crea."""
import unittest

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from app import prueba_cierre as pc


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasEvidenciaDelCierre(BaseRedisMongo):
    def test_todos_los_casos_cumplen(self):
        resultados, _ = pc.ejecutar(self.db)
        self.assertGreaterEqual(len(resultados), 7)
        self.assertEqual([r["caso"] for r in resultados if not r["ok"]], [])

    def test_no_deja_turnos_de_prueba_y_no_toca_los_reales(self):
        self.db["turnos"].insert_one({"codigo": "A-001", "marca": "real"})
        pc.ejecutar(self.db)
        self.assertEqual(self.db["turnos"].count_documents({"codigo": {"$in": list(pc.CODIGOS)}}), 0)
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["marca"], "real")

    def test_informa_que_el_servidor_no_valida_si_acepta_un_cierre_invalido(self):
        _, servidor = pc.ejecutar(self.db)           # mongomock no aplica validadores
        self.assertIn("NO valida", servidor)

    def test_el_informe_describe_la_limitacion_de_collmod(self):
        resultados, servidor = pc.ejecutar(self.db)
        md = pc.a_markdown(resultados, servidor)
        for texto in ("S4-M03", "**OK**", "collMod", "Qué valida el servidor"):
            self.assertIn(texto, md)


if __name__ == "__main__":
    unittest.main()
