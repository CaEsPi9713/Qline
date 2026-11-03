"""Fase 2 · Matriz de permisos: qué rol puede abrir cada ruta, comprobada contra la aplicación real.

La tabla de abajo es la política de acceso. La prueba recorre TODAS las rutas registradas en la app: si aparece una
que no está en la tabla, o una que exige un rol distinto, falla. Así no se puede añadir una pantalla de personal sin
decidir quién entra.
"""
import re
import unittest

from tests.apoyo_sesion import ClienteConSesion
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.routing import APIRoute
    from starlette.routing import WebSocketRoute

    import app.main as main
    from app import auth

PUBLICO = ()
OPERACION = ("operador", "supervisor", "administrador")
SUPERVISION = ("supervisor", "administrador")
ADMIN = ("administrador",)

POLITICA = {
    # --- sin inicio de sesión: cliente, sala, QR, salud y el propio acceso ---
    **{("GET", r): PUBLICO for r in ("/", "/acerca", "/emitir", "/quiosco", "/consultar", "/turno/{codigo}",
                                     "/turno/qr/{token}", "/api/turnos/qr/{token}", "/api/turnos/{codigo}", "/salud",
                                     "/pantalla", "/api/llamados", "/login", "/registro")},
    **{("POST", r): PUBLICO for r in ("/emitir", "/quiosco", "/api/turnos/emitir", "/login", "/registro", "/salir")},
    # --- operación (el supervisor y el administrador también, para la guía y para supervisar) ---
    **{("GET", r): OPERACION for r in ("/cola", "/panel", "/api/cola", "/api/operador/estado")},
    **{("POST", r): OPERACION for r in ("/cola/llamar", "/panel/iniciar", "/panel/finalizar", "/api/llamar",
                                        "/api/atencion/iniciar", "/api/atencion/finalizar")},
    # --- supervisión ---
    **{("GET", r): SUPERVISION for r in ("/demo", "/historial", "/api/historial", "/api/historial/descargar",
                                         "/dashboard", "/api/dashboard", "/api/dashboard/descargar", "/api/ventanillas",
                                         "/supervisor/asignaciones")},
    **{("POST", r): SUPERVISION for r in ("/supervisor/asignaciones/asignar", "/supervisor/asignaciones/quitar")},
    # --- administración ---
    **{("GET", r): ADMIN for r in ("/administracion", "/ws-prueba", "/redis/estado", "/api/eventos/estado",
                                   "/admin/sucursales", "/api/admin/sucursales", "/api/admin/sucursales/{codigo}",
                                   "/admin/usuarios")},
    **{("POST", r): ADMIN for r in ("/crear_coleccion", "/insertar", "/actualizar", "/eliminar", "/api/ventanillas",
                                    "/ventanillas/crear", "/ventanillas/desactivar", "/ventanillas/reactivar",
                                    "/api/eventos/prueba", "/api/admin/sucursales",
                                    "/api/admin/sucursales/{codigo}/desactivar", "/api/admin/sucursales/{codigo}/activar",
                                    "/admin/sucursales/crear", "/admin/sucursales/actualizar",
                                    "/admin/sucursales/desactivar", "/admin/sucursales/activar",
                                    "/admin/usuarios/habilitar", "/admin/usuarios/deshabilitar", "/admin/usuarios/rol",
                                    "/admin/usuarios/clave")},
    ("PUT", "/api/admin/sucursales/{codigo}"): ADMIN,
}
WEBSOCKETS_PUBLICOS = {"/ws/ping", "/ws/eventos", "/ws/turno/qr/{token}"}
CAMINO = {"{codigo}": "A-001", "{token}": "0b2d7a5e-3c1f-4e8a-9a61-5f2f4c7d8e90"}


def roles_exigidos(ruta) -> tuple:
    """Los roles que exige una ruta, leídos de sus dependencias (vacío si es pública)."""
    for dep in ruta.dependant.dependencies:
        roles = getattr(dep.call, "roles", None)
        if roles:
            return tuple(roles)
    return ()


def rutas_http():
    for r in main.app.routes:
        if isinstance(r, APIRoute):
            for metodo in sorted(r.methods - {"HEAD", "OPTIONS"}):
                yield metodo, r


def concreta(ruta: str) -> str:
    for marca, valor in CAMINO.items():
        ruta = ruta.replace(marca, valor)
    return ruta


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDelInventario(unittest.TestCase):
    def test_toda_ruta_esta_clasificada(self):
        sin_clasificar = [f"{m} {r.path}" for m, r in rutas_http() if (m, r.path) not in POLITICA]
        self.assertEqual(sin_clasificar, [], "rutas nuevas sin decidir quién puede abrirlas")

    def test_cada_ruta_exige_exactamente_los_roles_de_la_politica(self):
        distintas = [f"{m} {r.path}: exige {roles_exigidos(r)}, debería {POLITICA[(m, r.path)]}"
                     for m, r in rutas_http() if (m, r.path) in POLITICA and roles_exigidos(r) != POLITICA[(m, r.path)]]
        self.assertEqual(distintas, [])

    def test_la_politica_no_lista_rutas_que_ya_no_existen(self):
        existentes = {(m, r.path) for m, r in rutas_http()}
        self.assertEqual(sorted(set(POLITICA) - existentes), [])

    def test_los_websockets_son_los_esperados_y_publicos(self):
        sockets = {r.path for r in main.app.routes if isinstance(r, WebSocketRoute)}
        self.assertEqual(sockets, WEBSOCKETS_PUBLICOS)

    def test_no_hay_documentacion_interactiva_publica(self):
        c = ClienteConSesion(main.app, rol=None)
        for ruta in ("/docs", "/redoc", "/openapi.json"):
            self.assertEqual(c.get(ruta).status_code, 404, ruta)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeAccesoPorRol(BaseRedisMongo):
    def cliente(self, rol=None):
        return ClienteConSesion(main.app, rol=rol, follow_redirects=False)

    def pedir(self, c, metodo, ruta):
        url = concreta(ruta)
        return c.get(url) if metodo == "GET" else c.put(url) if metodo == "PUT" else c.post(url)

    def test_sin_sesion_las_rutas_de_personal_piden_login_o_responden_401(self):
        c = self.cliente()
        for (metodo, ruta), roles in sorted(POLITICA.items()):
            if not roles:
                continue
            r = self.pedir(c, metodo, ruta)
            if ruta.startswith("/api/"):
                self.assertEqual(r.status_code, 401, f"{metodo} {ruta}")
            else:
                self.assertEqual(r.status_code, 303, f"{metodo} {ruta}")
                self.assertIn("/login", r.headers["location"], f"{metodo} {ruta}")

    def test_cada_rol_entra_solo_a_lo_que_le_corresponde(self):
        for rol in auth.ROLES:
            c = self.cliente(rol)
            for (metodo, ruta), roles in sorted(POLITICA.items()):
                if not roles:
                    continue
                r = self.pedir(c, metodo, ruta)
                if rol in roles:
                    # El operador de prueba no tiene ventanilla: la API le responde 403 con ese motivo, que no es falta de rol.
                    sin_ventanilla = (rol == "operador" and r.status_code == 403 and "supervisor" in r.text.lower()
                                      and "ventanilla" in r.text.lower())
                    permitido = (r.status_code not in (401, 403) or sin_ventanilla) and "/login" not in r.headers.get("location", "")
                    self.assertTrue(permitido, f"{rol} debería entrar a {metodo} {ruta} y dio {r.status_code}")
                else:
                    self.assertEqual(r.status_code, 403, f"{rol} no debería entrar a {metodo} {ruta}")

    def test_las_rutas_publicas_no_piden_sesion(self):
        c = self.cliente()
        for (metodo, ruta), roles in sorted(POLITICA.items()):
            if roles or (metodo == "POST" and ruta in ("/salir", "/login", "/registro")):
                continue                # estas tres responden según lo que se envíe, no según la sesión
            r = self.pedir(c, metodo, ruta)
            self.assertNotIn(r.status_code, (401, 403), f"{metodo} {ruta}")
            self.assertNotIn("/login", r.headers.get("location", "") if ruta != "/login" else "", f"{metodo} {ruta}")

    def test_los_websockets_publicos_conectan_sin_sesion(self):
        c = self.cliente()
        with c.websocket_connect("/ws/ping") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "bienvenida")
        with c.websocket_connect("/ws/eventos") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "conectado")

    def test_la_pagina_403_indica_a_donde_ir(self):
        r = self.cliente("operador").get("/dashboard")
        self.assertEqual(r.status_code, 403)
        self.assertIn("Acceso no permitido", r.text)
        self.assertIn("/cola", r.text)

    def test_un_acceso_sin_sesion_recuerda_la_pagina_pedida(self):
        r = self.cliente().get("/historial?estado=atendido")
        self.assertEqual(r.headers["location"], f"{main.BASE}/login?siguiente=%2Fhistorial%3Festado%3Datendido")

    def test_las_apis_responden_json_sin_exponer_detalles(self):
        sin = self.cliente().get("/api/historial")
        self.assertEqual((sin.status_code, sin.json()), (401, {"detail": "Inicie sesión para continuar."}))
        prohibido = self.cliente("operador").get("/api/historial")
        self.assertEqual(prohibido.status_code, 403)
        self.assertNotIn("operador", prohibido.text)

    def test_deshabilitar_a_un_usuario_le_quita_el_acceso_en_la_siguiente_peticion(self):
        c = self.cliente("supervisor")
        self.assertEqual(c.get("/dashboard").status_code, 200)
        self.db["usuarios"].update_one({"usuario": "supervisor-prueba"}, {"$set": {"estado": "deshabilitado"}})
        self.assertEqual(c.get("/dashboard").status_code, 303)

    def test_un_post_desde_otro_sitio_se_rechaza_aunque_haya_sesion(self):
        c = self.cliente("administrador")
        r = c.post("/ventanillas/crear", data={"nombre": "X"}, headers={"Origin": "https://sitio-malo.example"})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.db["ventanillas"].find_one({}))


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDelMenuPorRol(BaseRedisMongo):
    def pagina(self, rol, ruta):
        return ClienteConSesion(main.app, rol=rol).get(ruta).text

    def enlaces(self, html):
        menu = re.search(r'<nav class="nav".*?</nav>', html, re.S).group(0)
        return {h[len(main.BASE):] if h.startswith(main.BASE) else h for h in re.findall(r'href="([^"]+)"', menu)}

    def test_el_operador_ve_cliente_y_operador_pero_no_supervision_ni_administracion(self):
        enlaces = self.enlaces(self.pagina("operador", "/cola"))
        self.assertTrue({"/emitir", "/consultar", "/cola", "/panel"} <= enlaces)
        self.assertFalse({"/historial", "/dashboard", "/administracion", "/demo"} & enlaces)

    def test_el_supervisor_ve_supervision_y_la_guia_pero_no_administracion(self):
        enlaces = self.enlaces(self.pagina("supervisor", "/dashboard"))
        self.assertTrue({"/historial", "/dashboard", "/demo", "/cola"} <= enlaces)
        self.assertNotIn("/administracion", enlaces)

    def test_el_administrador_lo_ve_todo(self):
        enlaces = self.enlaces(self.pagina("administrador", "/administracion"))
        self.assertTrue({"/emitir", "/cola", "/historial", "/dashboard", "/administracion", "/demo"} <= enlaces)

    def test_se_muestra_el_usuario_y_el_cierre_de_sesion(self):
        html = self.pagina("operador", "/cola")
        self.assertIn("operador-prueba · operador", html)
        self.assertIn(f'<form method="post" action="{main.BASE}/salir">', html)

    def test_el_operador_no_ve_la_numeracion_de_la_guia(self):
        self.assertNotIn("Paso 3 de 7", self.pagina("operador", "/cola"))
        self.assertIn("Paso 3 de 7", self.pagina("supervisor", "/cola"))

    def test_el_logo_lleva_a_la_pagina_de_cada_rol(self):
        for rol, destino in (("operador", "/cola"), ("supervisor", "/dashboard"), ("administrador", "/administracion")):
            self.assertIn(f'<a class="brand" href="{main.BASE}{destino}">', self.pagina(rol, destino))


if __name__ == "__main__":
    unittest.main()
