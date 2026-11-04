"""Fase 2 · Pantallas de ingreso y registro del personal, cierre de sesión y script del primer administrador."""
import os
import unittest
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app import auth

CLAVE = "Clave-segura-1"


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseLogin(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        parche = mock.patch.dict(os.environ, {"SECRETO_SESION": "secreto-de-pruebas-del-login"})
        parche.start()
        self.addCleanup(parche.stop)
        auth._con_indice.clear()
        # Sin prefijo público: el cliente de pruebas pide /cola, no /proyecto/qline/cola, y la cookie lleva Path=BASE.
        for parche in (mock.patch.object(main, "BASE", ""), mock.patch.dict(main.templates.env.globals, {"base": ""})):
            parche.start()
            self.addCleanup(parche.stop)
        self.c = TestClient(main.app, follow_redirects=False)

    def alta(self, usuario="ana", rol="operador", estado="activo"):
        return auth.crear_usuario(self.db, usuario, CLAVE, rol=rol, estado=estado)

    def entrar(self, usuario="ana", clave=CLAVE, **extra):
        return self.c.post("/login", data={"usuario": usuario, "clave": clave, **extra})


class PruebasDelIngreso(BaseLogin):
    def test_el_formulario_se_muestra_y_no_se_guarda_en_cache(self):
        r = self.c.get("/login")
        self.assertEqual(r.status_code, 200)
        for texto in ('name="usuario"', 'name="clave"', 'type="password"', "Solicítelo aquí"):
            self.assertIn(texto, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")

    def test_cada_rol_llega_a_su_pagina(self):
        for usuario, rol, destino in (("ana", "operador", "/cola"), ("sol", "supervisor", "/dashboard"),
                                      ("adm", "administrador", "/administracion")):
            self.alta(usuario, rol)
            r = self.entrar(usuario)
            self.assertEqual((r.status_code, r.headers["location"]), (303, main.BASE + destino), usuario)

    def test_la_cookie_es_httponly_samesite_y_no_lleva_la_contrasena(self):
        self.alta()
        cookie = self.entrar().headers["set-cookie"]
        self.assertIn(auth.NOMBRE_COOKIE + "=", cookie)
        for atributo in ("HttpOnly", "SameSite=lax", f"Path={main.BASE or '/'}", "Max-Age="):
            self.assertIn(atributo, cookie)
        self.assertNotIn(CLAVE, cookie)
        self.assertNotIn("Secure", cookie)                                   # http de pruebas

    def test_detras_de_https_la_cookie_es_secure(self):
        self.alta()
        r = self.c.post("/login", data={"usuario": "ana", "clave": CLAVE}, headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Secure", r.headers["set-cookie"])

    def test_tras_ingresar_se_puede_abrir_la_pagina_protegida(self):
        self.alta()
        self.entrar()
        self.assertEqual(self.c.get("/cola").status_code, 200)

    def test_vuelve_a_la_pagina_que_se_pidio(self):
        self.alta("sol", "supervisor")
        r = self.entrar("sol", siguiente="/historial?estado=atendido")
        self.assertEqual(r.headers["location"], main.BASE + "/historial?estado=atendido")

    def test_no_se_puede_usar_el_ingreso_para_redirigir_a_otro_sitio(self):
        self.alta()
        for malo in ("//sitio-malo.example", "https://sitio-malo.example", "/\\sitio-malo.example", "javascript:alert(1)",
                     "sitio-malo.example", "/a b", "/<script>"):
            r = self.entrar(siguiente=malo)
            self.assertEqual(r.headers["location"], main.BASE + "/cola", malo)

    def test_credenciales_malas_no_revelan_si_el_usuario_existe(self):
        self.alta()
        mala = self.entrar(clave="otra-clave-1")
        fantasma = self.entrar("fantasma")
        self.assertEqual((mala.status_code, fantasma.status_code), (401, 401))
        self.assertIn(auth.MENSAJE_CREDENCIALES, mala.text)
        self.assertIn(auth.MENSAJE_CREDENCIALES, fantasma.text)
        self.assertNotIn("set-cookie", mala.headers)

    def test_el_formulario_conserva_el_usuario_pero_nunca_la_contrasena(self):
        self.alta()
        html = self.entrar(clave="otra-clave-1").text
        self.assertIn('value="ana"', html)
        self.assertNotIn("otra-clave-1", html)

    def test_cuenta_pendiente_o_deshabilitada_no_ingresa(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        self.alta("luis", estado="deshabilitado")
        self.assertIn("pendiente", self.entrar("pedro").text)
        self.assertIn("deshabilitado", self.entrar("luis").text)
        self.assertEqual(self.c.get("/cola").status_code, 303)

    def test_el_bloqueo_por_intentos_se_informa(self):
        self.alta()
        for _ in range(auth.MAX_INTENTOS):
            self.entrar(clave="otra-clave-1")
        r = self.entrar()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Demasiados intentos", r.text)

    def test_un_ingreso_enviado_desde_otro_sitio_se_rechaza(self):
        self.alta()
        r = self.c.post("/login", data={"usuario": "ana", "clave": CLAVE}, headers={"Origin": "https://sitio-malo.example"})
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("set-cookie", r.headers)

    def test_el_ingreso_funciona_con_la_politica_no_referrer_de_las_paginas_publicas(self):
        """Con `no-referrer` el navegador envía `Origin: null` en el formulario; Sec-Fetch-Site indica que es el mismo sitio."""
        self.alta()
        r = self.c.post("/login", data={"usuario": "ana", "clave": CLAVE},
                        headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(r.status_code, 303)
        r = self.c.post("/login", data={"usuario": "ana", "clave": CLAVE},
                        headers={"Origin": "null", "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)

    def test_con_sesion_abierta_el_login_lleva_a_la_pagina_del_rol(self):
        self.alta()
        self.entrar()
        r = self.c.get("/login")
        self.assertEqual((r.status_code, r.headers["location"]), (303, main.BASE + "/cola"))

    def test_si_mongodb_falla_el_ingreso_responde_503_sin_detalles(self):
        class Caida:
            def __getitem__(self, _):
                raise auth.PyMongoError("secreto interno")
        with mock.patch.object(main, "get_db", lambda: Caida()):
            r = self.entrar()
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("secreto interno", r.text)


class PruebasDelPrefijoPublico(BaseLogin):
    def test_detras_de_apache_la_cookie_y_las_redirecciones_llevan_el_prefijo(self):
        self.alta()
        with mock.patch.object(main, "BASE", "/proyecto/qline"):
            r = self.entrar()
            self.assertEqual(r.headers["location"], "/proyecto/qline/cola")
            self.assertIn("Path=/proyecto/qline", r.headers["set-cookie"])
            salida = self.c.post("/salir")
            self.assertEqual(salida.headers["location"], "/proyecto/qline/login?salio=1")
            self.assertIn("Path=/proyecto/qline", salida.headers["set-cookie"])


class PruebasDelCierreDeSesion(BaseLogin):
    def test_salir_borra_la_cookie_y_quita_el_acceso(self):
        self.alta()
        self.entrar()
        r = self.c.post("/salir")
        self.assertEqual((r.status_code, r.headers["location"]), (303, main.BASE + "/login?salio=1"))
        self.assertIn(f'{auth.NOMBRE_COOKIE}=""', r.headers["set-cookie"])
        self.assertEqual(self.c.get("/cola").status_code, 303)
        self.assertIn("Cerró la sesión", self.c.get("/login?salio=1").text)

    def test_salir_sin_sesion_no_falla(self):
        self.assertEqual(self.c.post("/salir").status_code, 303)

    def test_el_menu_ofrece_cerrar_sesion_con_un_formulario_post(self):
        self.alta()
        self.entrar()
        self.assertIn(f'<form method="post" action="{main.BASE}/salir">', self.c.get("/cola").text)


class PruebasDelRegistro(BaseLogin):
    def registrar(self, usuario="pedro", clave=CLAVE, confirmacion=None, **extra):
        return self.c.post("/registro", data={"usuario": usuario, "clave": clave,
                                              "confirmacion": CLAVE if confirmacion is None else confirmacion, **extra})

    def test_el_formulario_se_muestra(self):
        r = self.c.get("/registro")
        self.assertEqual(r.status_code, 200)
        for texto in ('name="usuario"', 'name="clave"', 'name="confirmacion"'):
            self.assertIn(texto, r.text)

    def test_el_registro_queda_pendiente_sin_rol_y_sin_acceso(self):
        r = self.registrar()
        self.assertEqual(r.status_code, 201)
        self.assertIn("pedro", r.text)
        self.assertIn("aprobarla", r.text)
        doc = self.db["usuarios"].find_one({"usuario": "pedro"})
        self.assertEqual((doc["estado"], doc["rol"]), ("pendiente", None))
        self.assertTrue(doc["hash"].startswith("scrypt$"))
        self.assertNotIn(CLAVE, str(doc))
        self.assertEqual(self.entrar("pedro").status_code, 403)

    def test_no_se_puede_elegir_el_rol_al_registrarse(self):
        self.registrar(rol="administrador", estado="activo")
        doc = self.db["usuarios"].find_one({"usuario": "pedro"})
        self.assertEqual((doc["estado"], doc["rol"]), ("pendiente", None))

    def test_contrasenas_distintas(self):
        r = self.registrar(confirmacion="otra-clave-1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("no coinciden", r.text)
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)

    def test_el_registro_acepta_letras_en_mayusculas_y_minusculas(self):
        r = self.registrar("MariaPerez")
        self.assertEqual(r.status_code, 201)
        self.assertIsNotNone(self.db["usuarios"].find_one({"usuario": "mariaperez"}))
        self.assertEqual(self.registrar("MARIAPEREZ").status_code, 409)       # misma cuenta con otro uso de mayúsculas

    def test_el_registro_rechaza_numeros_y_caracteres_especiales_con_el_motivo(self):
        for malo in ("maria1", "maria_perez", "maria.perez", "maria-perez", "maria perez", "maría", "maria@", "123"):
            r = self.registrar(malo)
            self.assertEqual(r.status_code, 400, malo)
            self.assertIn("solo puede tener letras", r.text, malo)
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)

    def test_el_formulario_de_registro_pide_solo_letras(self):
        html = self.c.get("/registro").text
        self.assertIn('pattern="[A-Za-z]{3,30}"', html)
        self.assertIn("Solo letras, mayúsculas o minúsculas", html)
        self.assertNotIn("punto, guion", html)

    def test_usuario_repetido_contrasena_debil_y_nombre_invalido(self):
        self.registrar()
        self.assertEqual(self.registrar().status_code, 409)
        self.assertEqual(self.registrar("otro", "corta", "corta").status_code, 400)
        self.assertEqual(self.registrar("Mal Nombre!").status_code, 400)
        self.assertEqual(self.db["usuarios"].count_documents({}), 1)

    def test_hay_un_tope_de_solicitudes_pendientes(self):
        with mock.patch.object(auth, "MAX_PENDIENTES", 2):
            self.registrar("uno")
            self.registrar("dos")
            r = self.registrar("tres")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.db["usuarios"].count_documents({}), 2)

    def test_un_registro_enviado_desde_otro_sitio_se_rechaza(self):
        r = self.c.post("/registro", data={"usuario": "pedro", "clave": CLAVE, "confirmacion": CLAVE},
                        headers={"Origin": "https://sitio-malo.example"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)

    def test_el_html_no_devuelve_la_contrasena(self):
        html = self.registrar(confirmacion="otra-clave-1").text
        self.assertNotIn(CLAVE, html)
        self.assertNotIn("otra-clave-1", html)


class PruebasDeLaNavegacionPublica(BaseLogin):
    def test_las_paginas_publicas_ofrecen_el_ingreso_del_personal(self):
        for ruta in ("/", "/consultar", "/quiosco", "/acerca"):
            self.assertIn(f'href="{main.BASE}/login"', self.c.get(ruta).text, ruta)


class PruebasDelScriptDeAdministrador(BaseLogin):
    def ejecutar(self, *args, clave=CLAVE):
        from scripts import crear_admin
        with mock.patch.dict(os.environ, {"QLINE_ADMIN_CLAVE": clave}):
            return crear_admin.main(list(args), db=self.db)

    def test_crea_al_administrador_con_hash_y_puede_ingresar(self):
        self.assertEqual(self.ejecutar("--usuario", "Admin"), 0)
        doc = self.db["usuarios"].find_one({"usuario": "admin"})
        self.assertEqual((doc["rol"], doc["estado"]), ("administrador", "activo"))
        self.assertNotIn(CLAVE, str(doc))
        r = self.entrar("admin")
        self.assertEqual(r.headers["location"], main.BASE + "/administracion")

    def test_no_pisa_a_un_usuario_existente_sin_restablecer(self):
        self.ejecutar("--usuario", "admin")
        self.assertEqual(self.ejecutar("--usuario", "admin", clave="Otra-clave-9"), 1)
        self.assertEqual(self.entrar("admin").status_code, 303)             # sigue valiendo la clave original

    def test_restablecer_cambia_la_clave_reactiva_desbloquea_y_cierra_sesiones(self):
        self.ejecutar("--usuario", "admin")
        self.entrar("admin")
        self.assertEqual(self.c.get("/administracion").status_code, 200)
        self.db["usuarios"].update_one({"usuario": "admin"}, {"$set": {"estado": "deshabilitado", "intentos_fallidos": 3}})
        self.assertEqual(self.ejecutar("--usuario", "admin", "--restablecer", clave="Nueva-clave-9"), 0)
        self.assertEqual(self.c.get("/administracion").status_code, 303)    # la sesión anterior ya no vale
        self.assertEqual(self.entrar("admin", clave=CLAVE).status_code, 401)
        self.assertEqual(self.entrar("admin", clave="Nueva-clave-9").status_code, 303)

    def test_no_restablece_a_quien_no_es_administrador(self):
        self.alta("ana", "operador")
        self.assertEqual(self.ejecutar("--usuario", "ana", "--restablecer", clave="Nueva-clave-9"), 1)
        self.assertEqual(self.entrar("ana").status_code, 303)

    def test_rechaza_una_contrasena_debil(self):
        self.assertEqual(self.ejecutar("--usuario", "admin", clave="corta"), 1)
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)


if __name__ == "__main__":
    unittest.main()
