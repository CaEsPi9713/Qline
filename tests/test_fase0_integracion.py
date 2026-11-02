"""Fase 0 · lo que la integración de S4 había roto: administración de MongoDB, páginas de error, /acerca y enlaces."""
import re
import unittest
from pathlib import Path
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main

PLANTILLAS = Path(__file__).resolve().parents[1] / "app" / "templates"


class PruebasAdministracion(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app, follow_redirects=False)

    def test_la_raiz_es_la_portada_y_no_el_crud(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Turnos claros", r.text)
        self.assertNotIn("crear_coleccion", r.text)

    def test_administracion_lista_colecciones_y_formularios(self):
        self.db["turnos"].insert_one({"codigo": "A-001"})
        r = self.c.get("/administracion?coleccion=turnos")
        self.assertEqual(r.status_code, 200)
        self.assertIn("crear_coleccion", r.text)
        self.assertIn("/insertar?coleccion=turnos", r.text)
        self.assertIn("A-001", r.text)

    def test_crear_coleccion_redirige_a_administracion(self):
        r = self.c.post("/crear_coleccion", data={"nombre_coleccion": "prueba_admin"})
        self.assertEqual(r.status_code, 303)
        self.assertIn("/administracion?coleccion=prueba_admin", r.headers["location"])
        self.assertIn("prueba_admin", self.db.list_collection_names())

    def test_insertar_actualizar_y_eliminar_documentos(self):
        r = self.c.post("/insertar?coleccion=notas", data={"json": '{"texto": "hola"}'})
        self.assertEqual((r.status_code, "/administracion?coleccion=notas" in r.headers["location"]), (303, True))
        doc = self.db["notas"].find_one({"texto": "hola"})
        self.assertIsNotNone(doc)
        self.c.post("/actualizar?coleccion=notas", data={"id": str(doc["_id"]), "json": '{"texto": "adiós"}'})
        self.assertEqual(self.db["notas"].find_one({"_id": doc["_id"]})["texto"], "adiós")
        r = self.c.post("/eliminar?coleccion=notas", data={"id": str(doc["_id"])})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.db["notas"].count_documents({}), 0)

    def test_un_turno_invalido_se_rechaza_en_la_administracion(self):
        r = self.c.post("/insertar?coleccion=turnos", data={"json": '{"codigo": "mal"}'})
        self.assertEqual(r.status_code, 200)
        self.assertIn("Validación de turno", r.text)
        self.assertEqual(self.db["turnos"].count_documents({}), 0)

    def test_el_menu_de_operacion_apunta_a_administracion(self):
        r = self.c.get("/demo")
        self.assertIn("/administracion?coleccion=turnos", r.text)


class PruebasErroresYAcerca(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app, raise_server_exceptions=False)

    def test_ruta_inexistente_muestra_la_pagina_404(self):
        r = self.c.get("/no-existe")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Página no encontrada", r.text)
        self.assertIn("text/html", r.headers["content-type"])

    def test_el_404_de_la_api_sigue_siendo_json(self):
        r = self.c.get("/api/no-existe")
        self.assertEqual(r.status_code, 404)
        self.assertIn("application/json", r.headers["content-type"])

    def test_error_interno_no_expone_la_traza(self):
        with mock.patch("app.main.cola_redis.ver_cola", side_effect=RuntimeError("clave-secreta mongodb://u:p@h")):
            r = self.c.get("/cola")
        self.assertEqual(r.status_code, 500)
        for prohibido in ("clave-secreta", "mongodb://", "Traceback", "RuntimeError"):
            self.assertNotIn(prohibido, r.text)

    def test_acerca_responde_con_el_repositorio_sin_punto_final(self):
        r = self.c.get("/acerca")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Acerca de QLine", r.text)
        self.assertIn('href="https://github.com/CaEsPi9713/Qline"', r.text)

    def test_los_enlaces_de_las_paginas_de_error_llevan_el_prefijo_de_despliegue(self):
        with mock.patch.object(main.templates.env, "globals", {**main.templates.env.globals, "base": "/proyecto/qline"}):
            texto = self.c.get("/no-existe").text
        self.assertIn('href="/proyecto/qline/"', texto)


class PruebasEnlaces(unittest.TestCase):
    def test_ninguna_plantilla_usa_enlaces_absolutos_sin_el_prefijo_base(self):
        malos = []
        for ruta in sorted(PLANTILLAS.glob("*.html")):
            for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'(?:href|action)="/(?!/)', linea):
                    malos.append(f"{ruta.name}:{n}")
        self.assertEqual(malos, [], f"enlaces sin {{{{ base }}}}: {malos}")


if __name__ == "__main__":
    unittest.main()
