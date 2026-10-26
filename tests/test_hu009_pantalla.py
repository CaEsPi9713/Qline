"""
Pruebas automáticas de HU-009 · Pantalla pública de llamados.

Verifica:
1. PantallaPública.registrar_llamado / llamados_vigentes (estado en memoria).
2. procesar_evento reacciona correctamente a cada tipo de evento.
3. No filtra datos personales (los campos devueltos son solo código, ventanilla y estado).
4. Turnos atendidos/abandonados se retiran de la lista.
5. La lista nunca supera MAX_LLAMADOS.
6. TTL: un llamado con ts vencido no aparece en llamados_vigentes.
7. consultar_desde_mongo devuelve datos correctos y maneja fallo silenciosamente.
8. La ruta GET /api/llamados devuelve ok=True y la lista (con db simulada).
9. La ruta GET /pantalla devuelve 200 y el HTML contiene el código del turno.
10. Un llamado duplicado (mismo código) se actualiza en lugar de duplicarse.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.pantalla_publica import PantallaPública, MAX_LLAMADOS, TTL_LLAMADO_SEG
from app.eventos import (
    TURNO_LLAMADO, ATENCION_INICIADA, ATENCION_FINALIZADA, TURNO_ABANDONADO,
)
from app.constantes import ESTADO_LLAMADO, ESTADO_EN_ATENCION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pantalla_nueva(**kwargs) -> PantallaPública:
    return PantallaPública(**kwargs)


def _evento(tipo, codigo="A-001", ventanilla="V-01", estado=None):
    e = {"tipo": tipo, "codigo": codigo, "ventanilla": ventanilla,
         "ts": datetime.now(timezone.utc).isoformat()}
    if estado:
        e["estado"] = estado
    return e


# ---------------------------------------------------------------------------
# Tests de la lógica en memoria
# ---------------------------------------------------------------------------

class TestRegistrarLlamado(unittest.TestCase):

    def test_llamado_aparece_en_lista(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        llamados = p.llamados_vigentes()
        self.assertEqual(len(llamados), 1)
        self.assertEqual(llamados[0]["codigo"], "A-001")
        self.assertEqual(llamados[0]["ventanilla"], "V-01")

    def test_campos_devueltos_son_solo_codigo_ventanilla_estado(self):
        """No debe haber datos personales; solo los 3 campos definidos."""
        p = _pantalla_nueva()
        p.registrar_llamado("B-002", "V-02")
        item = p.llamados_vigentes()[0]
        self.assertEqual(set(item.keys()), {"codigo", "ventanilla", "estado"})

    def test_estado_inicial_es_llamado(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        self.assertEqual(p.llamados_vigentes()[0]["estado"], ESTADO_LLAMADO)

    def test_duplicado_no_duplica_entrada(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.registrar_llamado("A-001", "V-02")  # misma código, ventanilla distinta
        llamados = p.llamados_vigentes()
        self.assertEqual(len(llamados), 1)
        self.assertEqual(llamados[0]["ventanilla"], "V-02")

    def test_limite_max_llamados(self):
        p = _pantalla_nueva(max_llamados=3)
        for i in range(5):
            p.registrar_llamado(f"A-{i:03d}", "V-01")
        self.assertLessEqual(len(p.llamados_vigentes()), 3)

    def test_mas_reciente_al_frente(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.registrar_llamado("A-002", "V-02")
        llamados = p.llamados_vigentes()
        self.assertEqual(llamados[0]["codigo"], "A-002")

    def test_ttl_expirado_no_aparece(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        # Forzar ts en el pasado más allá del TTL
        p._llamados[0].ts = datetime.now(timezone.utc).timestamp() - TTL_LLAMADO_SEG - 1
        self.assertEqual(p.llamados_vigentes(), [])


class TestRetirarYMarcar(unittest.TestCase):

    def test_retirar_elimina_entrada(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.retirar("A-001")
        self.assertEqual(p.llamados_vigentes(), [])

    def test_retirar_otro_no_elimina(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.retirar("B-999")
        self.assertEqual(len(p.llamados_vigentes()), 1)

    def test_marcar_en_atencion_cambia_estado(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.marcar_en_atencion("A-001")
        self.assertEqual(p.llamados_vigentes()[0]["estado"], ESTADO_EN_ATENCION)

    def test_en_atencion_sigue_vigente(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.marcar_en_atencion("A-001")
        self.assertEqual(len(p.llamados_vigentes()), 1)


class TestProcesarEvento(unittest.TestCase):

    def test_turno_llamado_registra(self):
        p = _pantalla_nueva()
        p.procesar_evento(_evento(TURNO_LLAMADO, "A-001", "V-01"))
        llamados = p.llamados_vigentes()
        self.assertEqual(len(llamados), 1)
        self.assertEqual(llamados[0]["codigo"], "A-001")
        self.assertEqual(llamados[0]["ventanilla"], "V-01")

    def test_atencion_iniciada_marca_en_atencion(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.procesar_evento(_evento(ATENCION_INICIADA, "A-001", "V-01"))
        self.assertEqual(p.llamados_vigentes()[0]["estado"], ESTADO_EN_ATENCION)

    def test_atencion_finalizada_retira(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.procesar_evento(_evento(ATENCION_FINALIZADA, "A-001", "V-01"))
        self.assertEqual(p.llamados_vigentes(), [])

    def test_turno_abandonado_retira(self):
        p = _pantalla_nueva()
        p.registrar_llamado("A-001", "V-01")
        p.procesar_evento(_evento(TURNO_ABANDONADO, "A-001", "V-01"))
        self.assertEqual(p.llamados_vigentes(), [])

    def test_evento_sin_codigo_no_rompe(self):
        p = _pantalla_nueva()
        p.procesar_evento({"tipo": TURNO_LLAMADO})  # sin codigo
        self.assertEqual(p.llamados_vigentes(), [])

    def test_evento_desconocido_ignorado(self):
        p = _pantalla_nueva()
        p.procesar_evento({"tipo": "prueba", "codigo": "A-001"})
        self.assertEqual(p.llamados_vigentes(), [])

    def test_no_expone_datos_personales_en_evento(self):
        """procesar_evento ignora campos extra del evento; solo usa código y ventanilla."""
        p = _pantalla_nueva()
        evento = _evento(TURNO_LLAMADO, "A-001", "V-01")
        evento["nombre_cliente"] = "Juan Pérez"   # campo que NO debe aparecer en pantalla
        p.procesar_evento(evento)
        item = p.llamados_vigentes()[0]
        self.assertNotIn("nombre_cliente", item)


# ---------------------------------------------------------------------------
# Tests del fallback MongoDB
# ---------------------------------------------------------------------------

class TestConsultarDesdeMongo(unittest.TestCase):

    def _db_fake(self):
        """DB falsa con una colección de turnos llamados."""
        doc_llamado = {
            "codigo": "A-001", "ventanilla": "V-01", "estado": ESTADO_LLAMADO,
        }
        doc_en_atencion = {
            "codigo": "A-002", "ventanilla": "V-02", "estado": ESTADO_EN_ATENCION,
        }

        class _Col:
            def find(self, filtro, proj=None):
                return [doc_llamado, doc_en_atencion]

            def sort(self, *a, **kw):
                return self

            def limit(self, n):
                return self

            def __iter__(self):
                return iter([doc_llamado, doc_en_atencion])

        class _FakeCol:
            def find(self, filtro, proj=None):
                return _FakeResult()

        class _FakeResult:
            def sort(self, *a, **kw): return self
            def limit(self, n): return self
            def __iter__(self):
                return iter([doc_llamado, doc_en_atencion])

        class _FakeDB:
            def __getitem__(self, name):
                return _FakeCol()

        return _FakeDB()

    def test_devuelve_lista_desde_mongo(self):
        p = _pantalla_nueva()
        db = self._db_fake()
        resultado = p.consultar_desde_mongo(db)
        self.assertIsNotNone(resultado)
        self.assertIsInstance(resultado, list)
        # Solo 3 campos
        for item in resultado:
            self.assertEqual(set(item.keys()), {"codigo", "ventanilla", "estado"})

    def test_mongo_caido_devuelve_none(self):
        p = _pantalla_nueva()

        class _DBRotaPorError:
            def __getitem__(self, name):
                raise ConnectionError("MongoDB caído")

        resultado = p.consultar_desde_mongo(_DBRotaPorError())
        self.assertIsNone(resultado)


# ---------------------------------------------------------------------------
# Tests de las rutas HTTP (con TestClient, sin MongoDB ni Redis reales)
# ---------------------------------------------------------------------------

class TestRutasHU009(unittest.TestCase):

    def setUp(self):
        # Parchear TODAS las dependencias externas antes de importar el cliente
        self._patches = [
            patch("app.main.get_db", return_value=MagicMock()),
            patch("app.main.verificar_redis", return_value={"ok": True}),
        ]
        for p in self._patches:
            p.start()

        # Parchear pantalla global para tener control total en los tests
        from app import pantalla_publica
        self._pantalla_orig = pantalla_publica.pantalla
        pantalla_publica.pantalla = _pantalla_nueva()

        # Importar el parche en main también
        import app.main as m
        self._main_pantalla_orig = m._pantalla
        m._pantalla = pantalla_publica.pantalla

        from fastapi.testclient import TestClient
        from app.main import app
        self.client = TestClient(app, raise_server_exceptions=True)
        self._m = m
        self._pp = pantalla_publica

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._pp.pantalla = self._pantalla_orig
        self._m._pantalla = self._main_pantalla_orig

    def test_api_llamados_vacio(self):
        r = self.client.get("/api/llamados")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["llamados"], list)

    def test_api_llamados_con_datos(self):
        self._m._pantalla.registrar_llamado("A-001", "V-01")
        r = self.client.get("/api/llamados")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["llamados"]), 1)
        self.assertEqual(data["llamados"][0]["codigo"], "A-001")
        self.assertEqual(data["llamados"][0]["ventanilla"], "V-01")

    def test_api_llamados_no_expone_datos_extra(self):
        self._m._pantalla.registrar_llamado("B-002", "V-02")
        r = self.client.get("/api/llamados")
        item = r.json()["llamados"][0]
        self.assertEqual(set(item.keys()), {"codigo", "ventanilla", "estado"})

    def test_vista_pantalla_200(self):
        r = self.client.get("/pantalla")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    def test_vista_pantalla_contiene_codigo_turno(self):
        self._m._pantalla.registrar_llamado("C-007", "V-03")
        r = self.client.get("/pantalla")
        self.assertIn("C-007", r.text)
        self.assertIn("V-03", r.text)

    def test_vista_pantalla_sin_datos_personales(self):
        """La plantilla no debe renderizar campos personales."""
        r = self.client.get("/pantalla")
        # El template nunca incluye el token ni el _id de MongoDB
        self.assertNotIn("qr_token", r.text)
        self.assertNotIn("ObjectId", r.text)

    def test_api_llamados_turno_retirado_desaparece(self):
        self._m._pantalla.registrar_llamado("D-010", "V-01")
        self._m._pantalla.retirar("D-010")
        r = self.client.get("/api/llamados")
        codigos = [item["codigo"] for item in r.json()["llamados"]]
        self.assertNotIn("D-010", codigos)

    def test_pantalla_no_modifica_estado_turnos(self):
        """GET /pantalla y GET /api/llamados son de solo lectura."""
        # Registrar un estado previo y verificar que la ruta no lo muta
        self._m._pantalla.registrar_llamado("E-011", "V-01")
        estado_antes = self._m._pantalla.llamados_vigentes()[0]["estado"]
        self.client.get("/pantalla")
        self.client.get("/api/llamados")
        estado_despues = self._m._pantalla.llamados_vigentes()[0]["estado"]
        self.assertEqual(estado_antes, estado_despues)


if __name__ == "__main__":
    unittest.main(verbosity=2)
