"""Fase 3 · Gestión de usuarios y acceso por el administrador: habilitar, deshabilitar, cambiar rol y restablecer clave."""
import os
import unittest
from unittest import mock

from tests.apoyo_sesion import ClienteConSesion
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app import auth
    from app.auth import AuthError

CLAVE = "Clave-segura-1"


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseUsuarios(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        parche = mock.patch.dict(os.environ, {"SECRETO_SESION": "secreto-de-pruebas-de-usuarios"})
        parche.start()
        self.addCleanup(parche.stop)
        auth._con_indice.clear()
        for p in (mock.patch.object(main, "BASE", ""), mock.patch.dict(main.templates.env.globals, {"base": ""})):
            p.start()
            self.addCleanup(p.stop)

    def alta(self, usuario, rol="operador", estado="activo"):
        return auth.crear_usuario(self.db, usuario, CLAVE, rol=rol, estado=estado)

    def doc(self, usuario):
        return self.db["usuarios"].find_one({"usuario": usuario})

    def admin(self):
        return ClienteConSesion(main.app, rol="administrador", follow_redirects=False)


class PruebasDelListado(BaseUsuarios):
    def test_primero_las_solicitudes_pendientes_y_sin_hash(self):
        self.alta("zeta", "operador")
        self.alta("ana", "supervisor")
        auth.crear_usuario(self.db, "pedro", CLAVE)
        self.alta("luis", "operador", "deshabilitado")
        filas = auth.listar_usuarios(self.db)
        self.assertEqual([f["usuario"] for f in filas], ["pedro", "ana", "zeta", "luis"])
        for f in filas:
            self.assertNotIn("hash", f)

    def test_marca_a_quien_esta_bloqueado(self):
        self.alta("ana")
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(AuthError):
                auth.autenticar(self.db, "ana", "mala-clave-1")
        self.assertTrue(auth.listar_usuarios(self.db)[0]["bloqueado"])

    def test_la_pantalla_lista_a_todos_y_nunca_muestra_hashes_ni_contrasenas(self):
        self.alta("ana")
        auth.crear_usuario(self.db, "pedro", CLAVE)
        html = self.admin().get("/admin/usuarios").text
        for texto in ("ana", "pedro", "Pendiente", "Habilitar", "1 solicitud de acceso por revisar"):
            self.assertIn(texto, html)
        self.assertNotIn("scrypt$", html)
        self.assertNotIn(CLAVE, html)

    def test_sin_usuarios_explica_como_crear_el_primero(self):
        c = ClienteConSesion(main.app, rol=None, follow_redirects=False).iniciar_sesion_en(self.db)
        self.db["usuarios"].delete_many({"usuario": {"$ne": "administrador-prueba"}})
        self.assertIn("administrador-prueba", c.get("/admin/usuarios").text)


class PruebasDeHabilitar(BaseUsuarios):
    def test_habilitar_una_solicitud_la_deja_activa_con_el_rol_y_puede_ingresar(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        auth.habilitar_usuario(self.db, "pedro", "supervisor", por="root")
        d = self.doc("pedro")
        self.assertEqual((d["estado"], d["rol"], d["habilitado_por"]), ("activo", "supervisor", "root"))
        self.assertEqual(auth.autenticar(self.db, "pedro", CLAVE)["rol"], "supervisor")

    def test_queda_anotado_quien_lo_hizo(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        auth.habilitar_usuario(self.db, "pedro", "operador", por="root")
        self.assertEqual(self.doc("pedro")["ultimo_cambio"]["accion"], "habilitar")
        self.assertEqual(self.doc("pedro")["ultimo_cambio"]["por"], "root")

    def test_el_rol_debe_ser_valido(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        for malo in ("", "dueño", None, "ADMINISTRADOR"):
            with self.assertRaises(AuthError, msg=repr(malo)):
                auth.habilitar_usuario(self.db, "pedro", malo, por="root")
        self.assertEqual(self.doc("pedro")["estado"], "pendiente")

    def test_no_se_habilita_a_quien_ya_esta_activo_ni_a_quien_no_existe(self):
        self.alta("ana")
        with self.assertRaises(AuthError) as ya:
            auth.habilitar_usuario(self.db, "ana", "supervisor", por="root")
        self.assertEqual(ya.exception.status, 409)
        with self.assertRaises(AuthError) as no:
            auth.habilitar_usuario(self.db, "fantasma", "operador", por="root")
        self.assertEqual(no.exception.status, 404)

    def test_reactivar_a_un_deshabilitado_le_quita_el_bloqueo(self):
        self.alta("ana")
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"estado": "deshabilitado", "intentos_fallidos": 4}})
        auth.habilitar_usuario(self.db, "ana", "operador", por="root")
        self.assertEqual(self.doc("ana")["intentos_fallidos"], 0)
        self.assertEqual(auth.autenticar(self.db, "ana", CLAVE)["usuario"], "ana")

    def test_desde_la_pantalla(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        c = self.admin()
        r = c.post("/admin/usuarios/habilitar", data={"usuario": "pedro", "rol": "operador"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.doc("pedro")["estado"], "activo")
        self.assertIn("Se habilitó a pedro con el rol operador", c.get(r.headers["location"]).text)


class PruebasDeDeshabilitar(BaseUsuarios):
    def test_deshabilitar_quita_el_acceso_y_cierra_la_sesion_abierta(self):
        self.alta("ana", "operador")
        c = ClienteConSesion(main.app, rol=None, follow_redirects=False).iniciar_sesion_en(self.db, "operador", "ana")
        self.assertEqual(c.get("/cola").status_code, 200)
        auth.deshabilitar_usuario(self.db, "ana", por="root")
        self.assertEqual(c.get("/cola").status_code, 303)
        with self.assertRaises(AuthError):
            auth.autenticar(self.db, "ana", CLAVE)

    def test_no_puede_deshabilitarse_a_si_mismo(self):
        self.alta("adm", "administrador")
        with self.assertRaises(AuthError) as ctx:
            auth.deshabilitar_usuario(self.db, "adm", por="adm")
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.doc("adm")["estado"], "activo")

    def test_debe_quedar_al_menos_un_administrador_activo(self):
        self.alta("adm", "administrador")
        with self.assertRaises(AuthError) as ctx:
            auth.deshabilitar_usuario(self.db, "adm", por="otro")
        self.assertIn("al menos un administrador", str(ctx.exception))
        self.alta("admb", "administrador")
        auth.deshabilitar_usuario(self.db, "adm", por="admb")                 # ahora sí: queda adm2
        self.assertEqual(self.doc("adm")["estado"], "deshabilitado")

    def test_un_administrador_deshabilitado_no_cuenta_como_activo(self):
        self.alta("adm", "administrador")
        self.alta("admb", "administrador", "deshabilitado")
        with self.assertRaises(AuthError):
            auth.deshabilitar_usuario(self.db, "adm", por="otro")

    def test_no_se_deshabilita_dos_veces(self):
        self.alta("ana")
        auth.deshabilitar_usuario(self.db, "ana", por="root")
        with self.assertRaises(AuthError) as ctx:
            auth.deshabilitar_usuario(self.db, "ana", por="root")
        self.assertEqual(ctx.exception.status, 409)

    def test_desde_la_pantalla_y_sin_botones_para_la_propia_cuenta(self):
        self.alta("ana")
        c = self.admin()
        self.assertEqual(c.post("/admin/usuarios/deshabilitar", data={"usuario": "ana"}).status_code, 303)
        self.assertEqual(self.doc("ana")["estado"], "deshabilitado")
        r = c.post("/admin/usuarios/deshabilitar", data={"usuario": "administrador-prueba"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("No puede deshabilitar su propia cuenta", r.text)
        self.assertEqual(self.doc("administrador-prueba")["estado"], "activo")


class PruebasDeCambiarRol(BaseUsuarios):
    def test_el_cambio_cierra_la_sesion_y_al_ingresar_de_nuevo_rige_el_rol_nuevo(self):
        self.alta("ana", "operador")
        c = ClienteConSesion(main.app, rol=None, follow_redirects=False).iniciar_sesion_en(self.db, "operador", "ana")
        self.assertEqual(c.get("/historial").status_code, 403)
        auth.cambiar_rol(self.db, "ana", "supervisor", por="root")
        self.assertEqual(c.get("/historial").status_code, 303)                # la sesión anterior ya no vale
        c.cookies.clear()
        c.post("/login", data={"usuario": "ana", "clave": CLAVE})
        self.assertEqual(c.get("/historial").status_code, 200)

    def test_quien_deja_de_ser_operador_pierde_la_ventanilla(self):
        self.alta("ana", "operador")
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"ventanilla_asignada": "V-02"}})
        auth.cambiar_rol(self.db, "ana", "supervisor", por="root")
        self.assertIsNone(self.doc("ana")["ventanilla_asignada"])

    def test_deshabilitar_libera_la_ventanilla_y_reactivar_no_la_devuelve(self):
        self.alta("ana", "operador")
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"ventanilla_asignada": "V-02"}})
        auth.deshabilitar_usuario(self.db, "ana", por="root")
        self.assertIsNone(self.doc("ana")["ventanilla_asignada"])
        auth.habilitar_usuario(self.db, "ana", "operador", por="root")
        self.assertIsNone(self.doc("ana")["ventanilla_asignada"])             # el supervisor debe asignarle una de nuevo

    def test_no_puede_cambiarse_el_propio_rol(self):
        self.alta("adm", "administrador")
        with self.assertRaises(AuthError):
            auth.cambiar_rol(self.db, "adm", "operador", por="adm")

    def test_no_se_degrada_al_ultimo_administrador(self):
        self.alta("adm", "administrador")
        with self.assertRaises(AuthError) as ctx:
            auth.cambiar_rol(self.db, "adm", "operador", por="otro")
        self.assertIn("al menos un administrador", str(ctx.exception))

    def test_solo_se_cambia_el_rol_de_usuarios_activos_y_con_un_rol_distinto(self):
        self.alta("ana", "operador")
        auth.crear_usuario(self.db, "pedro", CLAVE)
        for usuario, rol in (("pedro", "operador"), ("ana", "operador"), ("ana", "dueño")):
            with self.assertRaises(AuthError, msg=(usuario, rol)):
                auth.cambiar_rol(self.db, usuario, rol, por="root")

    def test_desde_la_pantalla(self):
        self.alta("ana")
        c = self.admin()
        r = c.post("/admin/usuarios/rol", data={"usuario": "ana", "rol": "supervisor"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.doc("ana")["rol"], "supervisor")
        self.assertIn("Ahora ana tiene el rol supervisor", c.get(r.headers["location"]).text)
        self.assertEqual(c.post("/admin/usuarios/rol", data={"usuario": "ana", "rol": "jefe"}).status_code, 400)


class PruebasDeRestablecerClave(BaseUsuarios):
    def test_la_nueva_vale_la_vieja_no_y_se_cierran_las_sesiones(self):
        self.alta("ana")
        c = ClienteConSesion(main.app, rol=None, follow_redirects=False).iniciar_sesion_en(self.db, "operador", "ana")
        self.assertEqual(c.get("/cola").status_code, 200)
        auth.restablecer_clave(self.db, "ana", "Nueva-clave-9", por="root")
        self.assertEqual(c.get("/cola").status_code, 303)
        with self.assertRaises(AuthError):
            auth.autenticar(self.db, "ana", CLAVE)
        self.assertEqual(auth.autenticar(self.db, "ana", "Nueva-clave-9")["usuario"], "ana")

    def test_guarda_el_hash_y_nunca_la_clave(self):
        self.alta("ana")
        auth.restablecer_clave(self.db, "ana", "Nueva-clave-9", por="root")
        self.assertTrue(self.doc("ana")["hash"].startswith("scrypt$"))
        self.assertNotIn("Nueva-clave-9", str(self.doc("ana")))

    def test_quita_el_bloqueo_por_intentos(self):
        self.alta("ana")
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(AuthError):
                auth.autenticar(self.db, "ana", "mala-clave-1")
        auth.restablecer_clave(self.db, "ana", "Nueva-clave-9", por="root")
        self.assertEqual(auth.autenticar(self.db, "ana", "Nueva-clave-9")["usuario"], "ana")

    def test_aplica_la_politica_de_contrasenas_y_no_cambia_nada_si_falla(self):
        self.alta("ana")
        anterior = self.doc("ana")["hash"]
        for mala in ("corta", "ana", "x" * 129, ""):
            with self.assertRaises(AuthError, msg=mala):
                auth.restablecer_clave(self.db, "ana", mala, por="root")
        self.assertEqual(self.doc("ana")["hash"], anterior)

    def test_tambien_vale_para_una_solicitud_pendiente_y_no_la_habilita(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        auth.restablecer_clave(self.db, "pedro", "Nueva-clave-9", por="root")
        self.assertEqual(self.doc("pedro")["estado"], "pendiente")

    def test_desde_la_pantalla_sin_devolver_la_clave(self):
        self.alta("ana")
        c = self.admin()
        r = c.post("/admin/usuarios/clave", data={"usuario": "ana", "clave": "Nueva-clave-9"})
        self.assertEqual(r.status_code, 303)
        pagina = c.get(r.headers["location"]).text
        self.assertIn("Se restableció la contraseña de ana", pagina)
        self.assertNotIn("Nueva-clave-9", pagina)
        malo = c.post("/admin/usuarios/clave", data={"usuario": "ana", "clave": "corta"})
        self.assertEqual(malo.status_code, 400)
        self.assertNotIn("corta</", malo.text)


class PruebasDeSeguridad(BaseUsuarios):
    def test_un_usuario_desconocido_responde_404_sin_romper_la_pantalla(self):
        r = self.admin().post("/admin/usuarios/deshabilitar", data={"usuario": "fantasma"})
        self.assertEqual(r.status_code, 404)
        self.assertIn("No existe ese usuario", r.text)

    def test_los_avisos_de_la_url_no_inyectan_html(self):
        html = self.admin().get("/admin/usuarios?ok=habilitado&usuario=%3Cscript%3E&rol=%3Cb%3E").text
        self.assertNotIn("<script>", html)
        self.assertIn("Se habilitó a el usuario", html)

    def test_solo_el_administrador_gestiona_usuarios(self):
        for rol in ("operador", "supervisor"):
            c = ClienteConSesion(main.app, rol=rol, follow_redirects=False)
            self.assertEqual(c.get("/admin/usuarios").status_code, 403, rol)
            self.assertEqual(c.post("/admin/usuarios/habilitar", data={"usuario": "x", "rol": "operador"}).status_code, 403, rol)
        sin = TestClient(main.app, follow_redirects=False)
        self.assertEqual(sin.get("/admin/usuarios").status_code, 303)

    def test_un_post_desde_otro_sitio_no_cambia_nada(self):
        self.alta("ana")
        r = self.admin().post("/admin/usuarios/deshabilitar", data={"usuario": "ana"},
                              headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.doc("ana")["estado"], "activo")


class PruebasDeLaAdministracionDeDatos(BaseUsuarios):
    def test_la_coleccion_usuarios_no_muestra_el_hash(self):
        self.alta("ana")
        html = self.admin().get("/administracion?coleccion=usuarios").text
        self.assertIn("ana", html)
        self.assertIn("[oculto]", html)
        self.assertNotIn("scrypt$", html)

    def test_no_se_editan_usuarios_a_mano(self):
        self.alta("ana")
        c = self.admin()
        antes = self.doc("ana")
        _id = str(antes["_id"])
        for ruta, datos in (("/insertar", {"json": '{"usuario": "intruso", "rol": "administrador", "estado": "activo"}'}),
                            ("/actualizar", {"id": _id, "json": '{"rol": "administrador"}'}),
                            ("/eliminar", {"id": _id})):
            r = c.post(f"{ruta}?coleccion=usuarios", data=datos)
            self.assertIn("pantalla de usuarios", r.text, ruta)
        self.assertEqual(self.doc("ana"), antes)
        self.assertIsNone(self.doc("intruso"))
        self.assertIn("pantalla de usuarios", c.get(f"/administracion?coleccion=usuarios&editar={_id}").text)

    def test_otras_colecciones_siguen_editandose(self):
        c = self.admin()
        r = c.post("/insertar?coleccion=notas", data={"json": '{"a": 1}'})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.db["notas"].count_documents({}), 1)

    def test_la_portada_de_administracion_ofrece_la_gestion_de_usuarios_y_cuenta_pendientes(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        html = self.admin().get("/administracion").text
        self.assertIn("/admin/usuarios", html)
        self.assertIn("1 pendiente", html)

    def test_el_usuario_de_mongodb_ya_no_choca_con_el_de_la_sesion(self):
        html = self.admin().get("/administracion").text
        self.assertIn("administrador-prueba · administrador", html)         # la sesión, en el menú
        self.assertNotIn("<strong>{'", html)                                 # el lead no muestra un diccionario


if __name__ == "__main__":
    unittest.main()
