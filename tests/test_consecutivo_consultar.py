"""Ventanillas con código consecutivo (V-04, V-05, ...) y resultado visible en /consultar."""
import re
import unittest

from tests.test_p09_operacion import HAY_DEPENDENCIAS, BaseCatalogo, doc

if HAY_DEPENDENCIAS:
    from app import ventanillas


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDelConsecutivo(BaseCatalogo):
    def test_sin_catalogo_el_primero_es_v04(self):
        self.assertEqual(ventanillas.siguiente_codigo_ventanilla(self.db), "V-04")

    def test_sin_base_de_datos_tambien_parte_de_v04(self):
        self.assertEqual(ventanillas.siguiente_codigo_ventanilla(), "V-04")

    def test_registrar_sin_codigo_asigna_consecutivos_con_dos_digitos(self):
        codigos = [ventanillas.registrar_ventanilla(self.db, nombre="Módulo")["codigo"] for _ in range(5)]
        self.assertEqual(codigos, ["V-04", "V-05", "V-06", "V-07", "V-08"])

    def test_cuenta_tambien_las_inactivas_para_no_reutilizar_un_codigo(self):
        ventanillas.registrar_ventanilla(self.db)                       # V-04
        ventanillas.registrar_ventanilla(self.db)                       # V-05
        ventanillas.desactivar_ventanilla(self.db, "V-05")
        self.assertEqual(ventanillas.siguiente_codigo_ventanilla(self.db), "V-06")

    def test_la_ventanilla_de_prueba_no_altera_la_numeracion(self):
        self.alta(ventanillas.VENTANILLA_PRUEBA)
        self.assertEqual(ventanillas.siguiente_codigo_ventanilla(self.db), "V-04")

    def test_el_formulario_web_asigna_el_codigo_aunque_se_envie_otro(self):
        r = self.c.post("/ventanillas/crear", data={"codigo": "V-77", "nombre": "Rápida"})
        self.assertEqual(r.status_code, 303)
        self.assertIn("ventanilla=V-04", r.headers["location"])
        self.assertIsNone(self.db["ventanillas"].find_one({"codigo": "V-77"}))
        self.assertIsNotNone(self.db["ventanillas"].find_one({"codigo": "V-04"}))

    def test_la_api_asigna_el_siguiente_codigo(self):
        r = self.c.post("/api/ventanillas", data={"nombre": "Módulo"})
        self.assertEqual(r.json()["codigo"], "V-04")
        self.assertEqual(self.c.post("/api/ventanillas", data={"nombre": "Otro"}).json()["codigo"], "V-05")

    def test_la_pantalla_de_administracion_muestra_el_proximo_codigo_y_no_pide_escribirlo(self):
        html = self.c.get("/administracion").text
        self.assertIn("Se asigna solo", html)
        self.assertIn("<strong>V-04</strong>", html)
        self.assertNotIn('id="codigo_v"', html)

    def test_el_aviso_de_alta_nombra_la_ventanilla_creada(self):
        html = self.c.get("/administracion?ok=ventanilla_creada&ventanilla=V-08").text
        self.assertIn("Ventanilla V-08 registrada", html)
        self.assertNotIn("{codigo}", self.c.get("/administracion?ok=ventanilla_creada&ventanilla=<x>").text)

    def test_un_codigo_explicito_sigue_validandose(self):
        with self.assertRaises(ventanillas.VentanillaError):
            ventanillas.registrar_ventanilla(self.db, codigo="X-1")


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeConsultar(BaseCatalogo):
    def test_el_formulario_sin_codigo_no_muestra_resultado(self):
        r = self.c.get("/consultar")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("Resultado de la consulta", r.text)

    def test_un_turno_existente_muestra_codigo_estado_y_prioridad(self):
        self.db["turnos"].insert_one(doc("A-001", "atendido", "V-01"))
        html = self.c.get("/consultar?codigo=a-001").text
        for texto in ("Resultado de la consulta", "A-001", "badge-atendido", "Atendido", "V-01"):
            self.assertIn(texto, html)

    def test_un_turno_pendiente_muestra_su_posicion_en_la_cola(self):
        from app import cola
        self.db["turnos"].insert_one(doc("A-002", "pendiente", None))
        cola.encolar("A-002", "normal")
        html = self.c.get("/consultar?codigo=A-002").text
        self.assertIn("badge-pendiente", html)
        self.assertIn("Posición en la cola", html)

    def test_un_codigo_inexistente_dice_que_no_se_encontro(self):
        r = self.c.get("/consultar?codigo=A-999")
        self.assertEqual(r.status_code, 404)
        self.assertIn("No se encontró el turno A-999", r.text)
        self.assertNotIn("Resultado de la consulta", r.text)

    def test_un_codigo_mal_escrito_pide_uno_valido(self):
        r = self.c.get("/consultar?codigo=hola")
        self.assertEqual(r.status_code, 400)
        self.assertRegex(r.text, r"c.digo de turno v.lido")

    def test_el_enlace_directo_por_codigo_tambien_muestra_el_resultado(self):
        self.db["turnos"].insert_one(doc("A-003", "llamado", "V-02"))
        html = self.c.get("/turno/A-003").text
        self.assertIn("Resultado de la consulta", html)
        self.assertIn("V-02", html)


if __name__ == "__main__":
    unittest.main()
