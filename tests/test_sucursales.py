"""
Pruebas Unitarias y de Integración para el Módulo de Sucursales y Ventanillas Parametrizables (RFC-004).

Responsable: Carlos Espinoza (cespinoza)
Verifica:
  - Gobernanza de esquemas y validación de identificadores de sucursal.
  - Creación de sucursales con auto-onboarding atómico de N ventanillas.
  - Ajuste dinámico de capacidad instalada (incremento y reducción protegida).
  - Guardián de seguridad: bloqueo de cierre ante turnos en atención.
  - Endpoints de la API administrativa y vistas web en FastAPI.
  - Compatibilidad canónica con 'central'.
"""
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import mongomock

from app.constantes import (
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    SERVICIO_ID,
)
from app.main import app
from app.sucursales import (
    COLECCION_SUCURSALES,
    COLECCION_TURNOS,
    COLECCION_VENTANILLAS,
    SUCURSAL_DEFECTO,
    SucursalError,
    actualizar_sucursal,
    configurar_indices_sucursales,
    crear_sucursal_con_ventanillas,
    desactivar_sucursal_segura,
    inicializar_sucursal_base,
    listar_sucursales,
    obtener_sucursal,
    reactivar_sucursal,
    validar_codigo_sucursal,
)


class TestSucursalesLogica(unittest.TestCase):
    def setUp(self):
        self.client_mongo = mongomock.MongoClient()
        self.db = self.client_mongo["qline_test"]

    def test_validar_codigo_sucursal(self):
        """Valida que los códigos de sucursal cumplan con el patrón canónico."""
        self.assertEqual(validar_codigo_sucursal("central"), "central")
        self.assertEqual(validar_codigo_sucursal("  HEREDIA  "), "heredia")
        self.assertEqual(validar_codigo_sucursal("sede_este"), "sede_este")
        self.assertEqual(validar_codigo_sucursal("sucursal-01"), "sucursal-01")

        # Códigos inválidos
        with self.assertRaises(SucursalError):
            validar_codigo_sucursal("")
        with self.assertRaises(SucursalError):
            validar_codigo_sucursal("ab")  # demasiado corto (< 3)
        with self.assertRaises(SucursalError):
            validar_codigo_sucursal("a" * 25)  # demasiado largo (> 20)
        with self.assertRaises(SucursalError):
            validar_codigo_sucursal("sede@central")  # caracteres inválidos

    def test_inicializar_sucursal_base(self):
        """Verifica que la inicialización cree la sucursal 'central' con sus 3 ventanillas base."""
        res = inicializar_sucursal_base(self.db)
        self.assertEqual(res["codigo"], SUCURSAL_DEFECTO)
        self.assertEqual(res["estado"], "activa")

        # Verificar documentos en las colecciones
        col_s = self.db[COLECCION_SUCURSALES]
        self.assertEqual(col_s.count_documents({"codigo": SUCURSAL_DEFECTO}), 1)

        col_v = self.db[COLECCION_VENTANILLAS]
        ventanillas = list(col_v.find({"sucursal": SUCURSAL_DEFECTO}))
        self.assertEqual(len(ventanillas), 3)

        # Idempotencia: ejecutar nuevamente no duplica
        res2 = inicializar_sucursal_base(self.db)
        self.assertEqual(res2["codigo"], SUCURSAL_DEFECTO)
        self.assertEqual(col_s.count_documents({"codigo": SUCURSAL_DEFECTO}), 1)

    def test_crear_sucursal_con_auto_onboarding_ventanillas(self):
        """Crea una nueva sucursal y aprovisiona automáticamente sus 5 ventanillas."""
        res = crear_sucursal_con_ventanillas(
            self.db,
            codigo="sede_este",
            nombre="Sede Este - Curridabat",
            direccion="Plaza del Sol",
            telefono="+506 2200-1111",
            cantidad_ventanillas=5,
            prefijo_ventanilla="V",
            objetivo_max_espera_seg=180,
            tasa_minima_cumplimiento=85.0,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["codigo"], "sede_este")
        self.assertEqual(res["cantidad_ventanillas"], 5)
        self.assertEqual(len(res["ventanillas"]), 5)
        self.assertIn("V-01", res["ventanillas"])
        self.assertIn("V-05", res["ventanillas"])

        # Verificar en colección ventanillas
        col_v = self.db[COLECCION_VENTANILLAS]
        docs_v = list(col_v.find({"sucursal": "sede_este"}))
        self.assertEqual(len(docs_v), 5)
        codigos = [d["codigo"] for d in docs_v]
        self.assertEqual(codigos, ["V-01", "V-02", "V-03", "V-04", "V-05"])

        # Rechaza duplicados
        with self.assertRaises(SucursalError):
            crear_sucursal_con_ventanillas(
                self.db,
                codigo="sede_este",
                nombre="Sede Duplicada",
            )

    def test_actualizar_sucursal_incrementar_ventanillas(self):
        """Aumenta la capacidad de ventanillas de una sede existente."""
        crear_sucursal_con_ventanillas(
            self.db,
            codigo="alajuela",
            nombre="Sede Alajuela",
            cantidad_ventanillas=3,
        )
        col_v = self.db[COLECCION_VENTANILLAS]
        self.assertEqual(col_v.count_documents({"sucursal": "alajuela"}), 3)

        # Incrementar de 3 a 6 ventanillas
        res = actualizar_sucursal(
            self.db,
            codigo="alajuela",
            nombre="Sede Alajuela - Modificada",
            cantidad_ventanillas=6,
        )
        self.assertTrue(res["ok"])

        # Deben existir 6 ventanillas activas
        docs_v = list(col_v.find({"sucursal": "alajuela", "estado": "activa"}).sort("codigo", 1))
        self.assertEqual(len(docs_v), 6)
        self.assertEqual(docs_v[-1]["codigo"], "V-06")

    def test_actualizar_sucursal_reducir_ventanillas_seguro(self):
        """Reduce la capacidad de ventanillas marcando las excedentes como inactivas."""
        crear_sucursal_con_ventanillas(
            self.db,
            codigo="cartago",
            nombre="Sede Cartago",
            cantidad_ventanillas=4,
        )
        col_v = self.db[COLECCION_VENTANILLAS]

        # Reducir de 4 a 2 ventanillas (V-03 y V-04 pasan a inactiva)
        res = actualizar_sucursal(
            self.db,
            codigo="cartago",
            cantidad_ventanillas=2,
        )
        self.assertTrue(res["ok"])

        activas = col_v.count_documents({"sucursal": "cartago", "estado": "activa"})
        self.assertEqual(activas, 2)
        inactivas = col_v.count_documents({"sucursal": "cartago", "estado": "inactiva"})
        self.assertEqual(inactivas, 2)

    def test_actualizar_sucursal_bloqueo_reduccion_turnos_activos(self):
        """Bloquea la reducción de capacidad si la ventanilla a remover está atendiendo un turno."""
        crear_sucursal_con_ventanillas(
            self.db,
            codigo="puntarenas",
            nombre="Sede Puntarenas",
            cantidad_ventanillas=3,
        )
        col_t = self.db[COLECCION_TURNOS]
        col_t.insert_one({
            "codigo": "A-010",
            "sucursal": "puntarenas",
            "servicio": SERVICIO_ID,
            "ventanilla": "V-03",
            "estado": ESTADO_EN_ATENCION,
        })

        # Intentar reducir de 3 a 2 (V-03 saldría) -> Debe fallar
        with self.assertRaises(SucursalError) as ctx:
            actualizar_sucursal(
                self.db,
                codigo="puntarenas",
                cantidad_ventanillas=2,
            )
        self.assertIn("tiene activo el turno 'A-010'", str(ctx.exception))

    def test_desactivar_y_reactivar_sucursal(self):
        """Valida desactivación segura y reactivación de una sucursal."""
        crear_sucursal_con_ventanillas(
            self.db,
            codigo="limon",
            nombre="Sede Limón",
            cantidad_ventanillas=2,
        )

        # Desactivar
        res_des = desactivar_sucursal_segura(self.db, "limon")
        self.assertTrue(res_des["ok"])
        self.assertEqual(res_des["estado"], "inactiva")

        # Reactivar
        res_act = reactivar_sucursal(self.db, "limon")
        self.assertTrue(res_act["ok"])
        self.assertEqual(res_act["estado"], "activa")

    def test_desactivar_sucursal_bloqueo_si_hay_turnos_en_curso(self):
        """Guardián: no permite desactivar una sucursal con turnos activos en sala."""
        crear_sucursal_con_ventanillas(
            self.db,
            codigo="guanacaste",
            nombre="Sede Guanacaste",
            cantidad_ventanillas=2,
        )
        col_t = self.db[COLECCION_TURNOS]
        col_t.insert_one({
            "codigo": "G-001",
            "sucursal": "guanacaste",
            "servicio": SERVICIO_ID,
            "ventanilla": "V-01",
            "estado": ESTADO_LLAMADO,
        })

        with self.assertRaises(SucursalError) as ctx:
            desactivar_sucursal_segura(self.db, "guanacaste")
        self.assertIn("en atención activa", str(ctx.exception))

    def test_listar_y_obtener_sucursal(self):
        """Verifica listados de sucursales con métricas de capacidad calculadas."""
        inicializar_sucursal_base(self.db)
        crear_sucursal_con_ventanillas(
            self.db,
            codigo="san_pedro",
            nombre="Sede San Pedro",
            cantidad_ventanillas=4,
        )

        lista = listar_sucursales(self.db)
        self.assertTrue(len(lista) >= 2)
        codigos = [s["codigo"] for s in lista]
        self.assertIn("central", codigos)
        self.assertIn("san_pedro", codigos)

        detalle = obtener_sucursal(self.db, "san_pedro")
        self.assertIsNotNone(detalle)
        self.assertEqual(detalle["codigo"], "san_pedro")
        self.assertEqual(len(detalle["ventanillas"]), 4)


class TestSucursalesEndpointsFastAPI(unittest.TestCase):
    def setUp(self):
        self.client_mongo = mongomock.MongoClient()
        self.db = self.client_mongo["qline_api_test"]
        inicializar_sucursal_base(self.db)
        self.client = TestClient(app)

    @patch("app.main.get_db")
    def test_api_listar_sucursales(self, mock_get_db):
        """Endpoint GET /api/admin/sucursales entrega lista JSON con código 200."""
        mock_get_db.return_value = self.db
        resp = self.client.get("/api/admin/sucursales")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(len(data["sucursales"]) >= 1)
        self.assertEqual(data["sucursales"][0]["codigo"], "central")

    @patch("app.main.get_db")
    def test_api_crear_y_obtener_sucursal(self, mock_get_db):
        """Endpoint POST /api/admin/sucursales crea sucursal y GET devuelve su detalle."""
        mock_get_db.return_value = self.db
        payload = {
            "codigo": "tres_rios",
            "nombre": "Sede Tres Ríos",
            "direccion": "Calle Central",
            "cantidad_ventanillas": 4,
            "prefijo_ventanilla": "V",
            "objetivo_max_espera_seg": 300,
        }
        resp = self.client.post("/api/admin/sucursales", json=payload)
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["codigo"], "tres_rios")
        self.assertEqual(body["cantidad_ventanillas"], 4)

        # GET detalle
        resp_det = self.client.get("/api/admin/sucursales/tres_rios")
        self.assertEqual(resp_det.status_code, 200)
        det = resp_det.json()["sucursal"]
        self.assertEqual(det["codigo"], "tres_rios")
        self.assertEqual(len(det["ventanillas"]), 4)

    @patch("app.main.get_db")
    def test_api_desactivar_y_activar_sucursal(self, mock_get_db):
        """Endpoints POST /api/admin/sucursales/{codigo}/desactivar y /activar."""
        mock_get_db.return_value = self.db
        crear_sucursal_con_ventanillas(self.db, codigo="moravia", nombre="Sede Moravia", cantidad_ventanillas=2)

        resp_des = self.client.post("/api/admin/sucursales/moravia/desactivar")
        self.assertEqual(resp_des.status_code, 200)
        self.assertEqual(resp_des.json()["estado"], "inactiva")

        resp_act = self.client.post("/api/admin/sucursales/moravia/activar")
        self.assertEqual(resp_act.status_code, 200)
        self.assertEqual(resp_act.json()["estado"], "activa")

    @patch("app.main.get_db")
    def test_vista_html_admin_sucursales(self, mock_get_db):
        """Endpoint GET /admin/sucursales renderiza plantilla con catálogo y formularios."""
        mock_get_db.return_value = self.db
        resp = self.client.get("/admin/sucursales")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("Mantenimiento de Sucursales", html)
        self.assertIn("Sucursales Registradas", html)
        self.assertIn("Ajustar Capacidad de Ventanillas", html)
        self.assertIn("Crear Nueva Sucursal", html)
        self.assertIn("central", html)

    @patch("app.main.get_db")
    def test_panel_crud_mongo_muestra_card_sucursales(self, mock_get_db):
        """Verifica que la página principal de administración (Paso 7 /) incluya la tarjeta de sucursales."""
        mock_get_db.return_value = self.db
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.text
        self.assertIn("Sucursales del Sistema (RFC-004)", html)
        self.assertIn("Mantenimiento de Sucursales", html)


if __name__ == "__main__":
    unittest.main()
