"""Fase 1 de la entrega a sucursal: contraseñas con hash, usuarios, bloqueo por intentos, sesión firmada y roles."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

try:
    import mongomock
    from fastapi import Depends, FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    HAY_DEPENDENCIAS = True
except ImportError:           # pragma: no cover
    HAY_DEPENDENCIAS = False

if HAY_DEPENDENCIAS:
    from app import auth
    from app.auth import AuthError

SECRETO = "secreto-de-prueba-que-no-es-el-real"
CLAVE = "Clave-segura-1"


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan mongomock, fastapi o httpx")
class BaseAuth(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient()["grupo2_db"]
        parche = mock.patch.dict(os.environ, {"SECRETO_SESION": SECRETO})
        parche.start()
        self.addCleanup(parche.stop)
        auth._con_indice.clear()

    def activo(self, usuario="ana", rol="operador", clave=CLAVE):
        return auth.crear_usuario(self.db, usuario, clave, rol=rol, estado="activo")

    def doc(self, usuario="ana"):
        return self.db["usuarios"].find_one({"usuario": usuario})


class PruebasDeContrasenas(BaseAuth):
    def test_el_hash_no_contiene_la_contrasena_y_usa_scrypt(self):
        h = auth.hashear_clave(CLAVE)
        self.assertTrue(h.startswith("scrypt$"))
        self.assertNotIn(CLAVE, h)

    def test_cada_hash_lleva_una_sal_distinta(self):
        self.assertNotEqual(auth.hashear_clave(CLAVE), auth.hashear_clave(CLAVE))

    def test_verifica_la_correcta_y_rechaza_la_incorrecta(self):
        h = auth.hashear_clave(CLAVE)
        self.assertTrue(auth.verificar_clave(CLAVE, h))
        self.assertFalse(auth.verificar_clave(CLAVE + "x", h))
        self.assertFalse(auth.verificar_clave("", h))

    def test_un_hash_ilegible_nunca_coincide_ni_lanza(self):
        for roto in ("", "texto", "scrypt$1$2", "md5$1$2$3$4$5", "scrypt$x$8$1$aa$bb", None):
            self.assertFalse(auth.verificar_clave(CLAVE, roto), roto)

    def test_politica_de_contrasena(self):
        for mala in ("corta", "x" * 129, "", None, 12345678):
            with self.assertRaises(AuthError, msg=repr(mala)):
                auth.validar_clave(mala)
        with self.assertRaises(AuthError):
            auth.validar_clave("operador01", "operador01")
        auth.validar_clave("x" * 8)
        auth.validar_clave("x" * 128)


class PruebasDeUsuarios(BaseAuth):
    def test_el_registro_publico_queda_pendiente_y_sin_rol(self):
        u = auth.crear_usuario(self.db, "Pedro", CLAVE)
        self.assertEqual((u["usuario"], u["estado"], u["rol"]), ("pedro", "pendiente", None))

    def test_se_guarda_el_hash_y_nunca_la_contrasena(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        guardado = self.doc("pedro")
        self.assertTrue(guardado["hash"].startswith("scrypt$"))
        self.assertNotIn(CLAVE, str(guardado))

    def test_lo_publico_no_incluye_hash_ni_campos_internos(self):
        u = self.activo()
        for campo in ("hash", "version_sesion", "intentos_fallidos", "bloqueado_hasta", "_id"):
            self.assertNotIn(campo, u)

    def test_no_se_repite_el_usuario_ni_con_otras_mayusculas(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        with self.assertRaises(AuthError) as ctx:
            auth.crear_usuario(self.db, "PEDRO", CLAVE)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(self.db["usuarios"].count_documents({}), 1)

    def test_el_indice_unico_tambien_frena_un_alta_simultanea(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        with self.assertRaises(Exception):
            self.db["usuarios"].insert_one({"usuario": "pedro"})

    def test_el_usuario_acepta_mayusculas_y_minusculas(self):
        for nombre in ("Ana", "BRUNO", "carLA", "DanielaPerez", "a" * 30, "Pedro"):
            self.assertEqual(auth.crear_usuario(self.db, nombre, CLAVE)["usuario"], nombre.lower())
        self.assertEqual(self.db["usuarios"].count_documents({}), 6)

    def test_el_usuario_no_acepta_numeros_ni_caracteres_especiales(self):
        for malo in ("ana1", "1ana", "ana2024", "123", "ana_lopez", "ana-lopez", "ana.lopez", "ana lopez", "ana@mail",
                     "anaó", "Ñandú", "José", "ana!", "ana/", "<ana>", "ana\u200b", "ａｎａ", "٣٣٣"):
            with self.assertRaises(AuthError, msg=repr(malo)) as ctx:
                auth.crear_usuario(self.db, malo, CLAVE)
            self.assertIn("letras", str(ctx.exception))
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)

    def test_el_mensaje_explica_la_regla(self):
        with self.assertRaises(AuthError) as ctx:
            auth.crear_usuario(self.db, "ana1", CLAVE)
        for texto in ("solo puede tener letras", "mayúsculas o minúsculas", "sin números"):
            self.assertIn(texto, str(ctx.exception))

    def test_ana_y_ANA_son_la_misma_cuenta(self):
        auth.crear_usuario(self.db, "Ana", CLAVE, rol="operador", estado="activo")
        with self.assertRaises(AuthError) as ctx:
            auth.crear_usuario(self.db, "aNA", CLAVE)
        self.assertEqual(ctx.exception.status, 409)
        for escrito in ("ana", "ANA", " Ana "):
            self.assertEqual(auth.autenticar(self.db, escrito, CLAVE)["usuario"], "ana")

    def test_nombres_no_validos(self):
        for malo in ("", "ab", "x" * 31, "con espacio", "Ñandú", "a/b", "-guion", None, 7):
            with self.assertRaises(AuthError, msg=repr(malo)):
                auth.crear_usuario(self.db, malo, CLAVE)

    def test_rol_y_estado_deben_ser_validos(self):
        with self.assertRaises(AuthError):
            auth.crear_usuario(self.db, "pedro", CLAVE, rol="dueño")
        with self.assertRaises(AuthError):
            auth.crear_usuario(self.db, "pedro", CLAVE, estado="vip")
        with self.assertRaises(AuthError):
            auth.crear_usuario(self.db, "pedro", CLAVE, estado="activo")          # activo exige rol
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)

    def test_si_mongodb_falla_el_alta_responde_503(self):
        col = mock.MagicMock()
        col.find_one.return_value = None
        col.insert_one.side_effect = auth.PyMongoError("caído")
        with self.assertRaises(AuthError) as ctx:
            auth.crear_usuario({"usuarios": col}, "pedro", CLAVE)
        self.assertEqual(ctx.exception.status, 503)


class PruebasDeAutenticacion(BaseAuth):
    def test_credenciales_correctas_devuelven_el_usuario_y_registran_el_acceso(self):
        self.activo()
        doc = auth.autenticar(self.db, " ANA ", CLAVE)
        self.assertEqual(doc["usuario"], "ana")
        self.assertIsNotNone(self.doc()["ultimo_acceso"])

    def test_contrasena_incorrecta_y_usuario_inexistente_dan_el_mismo_mensaje(self):
        self.activo()
        with self.assertRaises(AuthError) as a:
            auth.autenticar(self.db, "ana", "otra-clave-mala")
        with self.assertRaises(AuthError) as b:
            auth.autenticar(self.db, "fantasma", CLAVE)
        self.assertEqual((str(a.exception), a.exception.status), (str(b.exception), b.exception.status))
        self.assertEqual(str(a.exception), auth.MENSAJE_CREDENCIALES)

    def test_entradas_raras_no_rompen(self):
        self.activo()
        for u, c in (("", ""), (None, None), (123, 456), ("ana", None), ("ana", "")):
            with self.assertRaises(AuthError):
                auth.autenticar(self.db, u, c)

    def test_cuenta_pendiente_solo_se_avisa_con_la_contrasena_correcta(self):
        auth.crear_usuario(self.db, "pedro", CLAVE)
        with self.assertRaises(AuthError) as bien:
            auth.autenticar(self.db, "pedro", CLAVE)
        self.assertEqual(bien.exception.status, 403)
        self.assertIn("pendiente", str(bien.exception))
        with self.assertRaises(AuthError) as mal:
            auth.autenticar(self.db, "pedro", "incorrecta-1")
        self.assertEqual(str(mal.exception), auth.MENSAJE_CREDENCIALES)

    def test_cuenta_deshabilitada_no_entra(self):
        self.activo()
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"estado": "deshabilitado"}})
        with self.assertRaises(AuthError) as ctx:
            auth.autenticar(self.db, "ana", CLAVE)
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("deshabilitado", str(ctx.exception))

    def test_un_usuario_activo_sin_rol_no_entra(self):
        self.activo()
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"rol": None}})
        with self.assertRaises(AuthError):
            auth.autenticar(self.db, "ana", CLAVE)

    def test_bloqueo_tras_cinco_intentos_fallidos_incluso_con_la_clave_correcta(self):
        self.activo()
        ahora = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(AuthError) as ctx:
                auth.autenticar(self.db, "ana", "mala-clave-1", ahora)
            self.assertEqual(ctx.exception.status, 401)
        with self.assertRaises(AuthError) as ctx:
            auth.autenticar(self.db, "ana", CLAVE, ahora + timedelta(seconds=30))
        self.assertEqual(ctx.exception.status, 429)

    def test_el_bloqueo_termina_con_el_tiempo(self):
        self.activo()
        ahora = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
        for _ in range(auth.MAX_INTENTOS):
            with self.assertRaises(AuthError):
                auth.autenticar(self.db, "ana", "mala-clave-1", ahora)
        despues = ahora + timedelta(seconds=auth.BLOQUEO_SEG + 1)
        self.assertEqual(auth.autenticar(self.db, "ana", CLAVE, despues)["usuario"], "ana")

    def test_un_acceso_correcto_reinicia_el_contador(self):
        self.activo()
        for _ in range(auth.MAX_INTENTOS - 1):
            with self.assertRaises(AuthError):
                auth.autenticar(self.db, "ana", "mala-clave-1")
        auth.autenticar(self.db, "ana", CLAVE)
        self.assertEqual(self.doc()["intentos_fallidos"], 0)
        with self.assertRaises(AuthError) as ctx:
            auth.autenticar(self.db, "ana", "mala-clave-1")
        self.assertEqual(ctx.exception.status, 401)             # no se acumularon los anteriores


class PruebasDeSesion(BaseAuth):
    def test_ida_y_vuelta(self):
        self.activo()
        carga = auth.leer_token(auth.crear_token(self.doc()))
        self.assertEqual((carga["u"], carga["v"]), ("ana", 1))

    def test_el_token_no_lleva_hash_ni_contrasena(self):
        self.activo()
        token = auth.crear_token(self.doc())
        self.assertNotIn("scrypt", auth._desb64(token.split(".")[0]).decode())

    def test_token_manipulado_se_rechaza(self):
        self.activo("ana", "operador")
        cuerpo, firma = auth.crear_token(self.doc()).split(".")
        otro = auth._b64(auth._desb64(cuerpo).replace(b"ana", b"adm"))
        for falso in (f"{otro}.{firma}", f"{cuerpo}.{firma[:-2]}xx", f"{cuerpo}.", cuerpo, "", "a.b.c", ".", "!!.!!"):
            self.assertIsNone(auth.leer_token(falso), falso)

    def test_token_caducado(self):
        self.activo()
        token = auth.crear_token(self.doc(), ahora=1_000_000, duracion=60)
        self.assertIsNotNone(auth.leer_token(token, ahora=1_000_030))
        self.assertIsNone(auth.leer_token(token, ahora=1_000_061))

    def test_un_token_firmado_con_otro_secreto_no_vale(self):
        self.activo()
        token = auth.crear_token(self.doc())
        with mock.patch.dict(os.environ, {"SECRETO_SESION": "otro-secreto"}):
            self.assertIsNone(auth.leer_token(token))

    def test_sin_secreto_en_el_entorno_se_usa_uno_temporal_estable_en_el_proceso(self):
        self.activo()
        with mock.patch.dict(os.environ, {"SECRETO_SESION": ""}):
            self.assertFalse(auth.secreto_configurado())
            self.assertIsNotNone(auth.leer_token(auth.crear_token(self.doc())))

    def test_atributos_de_la_cookie(self):
        a = auth.atributos_cookie(secure=True)
        self.assertTrue(a["httponly"])
        self.assertTrue(a["secure"])
        self.assertEqual(a["samesite"], "lax")
        self.assertFalse(auth.atributos_cookie(secure=False)["secure"])


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan mongomock, fastapi o httpx")
class PruebasDeRoles(BaseAuth):
    def setUp(self):
        super().setUp()
        app = FastAPI()

        @app.exception_handler(auth.NoAutenticado)
        def _sin_sesion(request, exc):
            return JSONResponse({"error": "login"}, status_code=401)

        @app.exception_handler(auth.SinPermiso)
        def _sin_permiso(request, exc):
            return JSONResponse({"error": "403"}, status_code=403)

        solo_operador = auth.requiere_rol("operador", obtener_db=lambda: self.db)
        sup_o_admin = auth.requiere_rol("supervisor", "administrador", obtener_db=lambda: self.db)

        @app.get("/cola")
        def cola(u=Depends(solo_operador)):
            return {"usuario": u["usuario"]}

        @app.post("/cola/llamar")
        def llamar(u=Depends(solo_operador)):
            return {"ok": True}

        @app.get("/historial")
        def historial(u=Depends(sup_o_admin)):
            return {"usuario": u["usuario"]}

        self.c = TestClient(app)

    def entrar(self, usuario="ana"):
        self.c.cookies.set(auth.NOMBRE_COOKIE, auth.crear_token(self.doc(usuario)))

    def test_sin_sesion_pide_login(self):
        self.assertEqual(self.c.get("/cola").status_code, 401)

    def test_cookie_basura_pide_login(self):
        self.c.cookies.set(auth.NOMBRE_COOKIE, "basura.basura")
        self.assertEqual(self.c.get("/cola").status_code, 401)

    def test_el_rol_correcto_entra(self):
        self.activo("ana", "operador")
        self.entrar()
        self.assertEqual(self.c.get("/cola").json(), {"usuario": "ana"})

    def test_un_rol_distinto_recibe_403(self):
        self.activo("ana", "operador")
        self.entrar()
        self.assertEqual(self.c.get("/historial").status_code, 403)

    def test_varios_roles_permitidos(self):
        self.activo("sol", "supervisor")
        self.activo("adm", "administrador")
        for u in ("sol", "adm"):
            self.entrar(u)
            self.assertEqual(self.c.get("/historial").status_code, 200, u)

    def test_deshabilitar_corta_la_sesion_en_la_peticion_siguiente(self):
        self.activo()
        self.entrar()
        self.assertEqual(self.c.get("/cola").status_code, 200)
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"estado": "deshabilitado"}})
        self.assertEqual(self.c.get("/cola").status_code, 401)

    def test_cambiar_el_rol_surte_efecto_de_inmediato(self):
        self.activo()
        self.entrar()
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"rol": "supervisor"}})
        self.assertEqual(self.c.get("/cola").status_code, 403)
        self.assertEqual(self.c.get("/historial").status_code, 200)

    def test_cerrar_sesiones_invalida_los_tokens_anteriores(self):
        self.activo()
        self.entrar()
        auth.cerrar_sesiones(self.db, "ana")
        self.assertEqual(self.c.get("/cola").status_code, 401)

    def test_un_usuario_borrado_no_conserva_la_sesion(self):
        self.activo()
        self.entrar()
        self.db["usuarios"].delete_one({"usuario": "ana"})
        self.assertEqual(self.c.get("/cola").status_code, 401)

    def test_post_desde_otro_sitio_se_rechaza(self):
        self.activo()
        self.entrar()
        r = self.c.post("/cola/llamar", headers={"Origin": "https://sitio-malo.example"})
        self.assertEqual(r.status_code, 403)

    def test_post_desde_la_misma_pagina_se_acepta(self):
        self.activo()
        self.entrar()
        self.assertEqual(self.c.post("/cola/llamar", headers={"Origin": "http://testserver"}).status_code, 200)
        self.assertEqual(self.c.post("/cola/llamar", headers={"Referer": "http://testserver/cola"}).status_code, 200)
        self.assertEqual(self.c.post("/cola/llamar").status_code, 200)          # sin cabeceras: no es un navegador

    def test_origen_null_y_detras_del_proxy(self):
        self.activo()
        self.entrar()
        self.assertEqual(self.c.post("/cola/llamar", headers={"Origin": "null"}).status_code, 403)
        proxy = {"Origin": "https://grupo2.crnube.net", "X-Forwarded-Host": "grupo2.crnube.net"}
        self.assertEqual(self.c.post("/cola/llamar", headers=proxy).status_code, 200)

    def test_sec_fetch_site_manda_cuando_el_navegador_lo_envia(self):
        self.activo()
        self.entrar()
        # Con no-referrer el navegador manda Origin: null aunque sea el mismo sitio.
        for valor in ("same-origin", "none"):
            r = self.c.post("/cola/llamar", headers={"Sec-Fetch-Site": valor, "Origin": "null"})
            self.assertEqual(r.status_code, 200, valor)
        for valor in ("cross-site", "same-site"):
            r = self.c.post("/cola/llamar", headers={"Sec-Fetch-Site": valor, "Origin": "http://testserver"})
            self.assertEqual(r.status_code, 403, valor)

    def test_el_dominio_publico_configurado_tambien_vale_detras_de_apache(self):
        self.activo()
        self.entrar()
        # Apache entrega la petición como 127.0.0.1:18002 pero el navegador envía el dominio público.
        interno = {"Origin": "https://grupo2.crnube.net", "Host": "127.0.0.1:18002"}
        self.assertEqual(self.c.post("/cola/llamar", headers=interno).status_code, 403)
        with mock.patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://grupo2.crnube.net"}):
            self.assertEqual(self.c.post("/cola/llamar", headers=interno).status_code, 200)
            ajeno = {"Origin": "https://sitio-malo.example", "Host": "127.0.0.1:18002"}
            self.assertEqual(self.c.post("/cola/llamar", headers=ajeno).status_code, 403)

    def test_un_rol_desconocido_se_detecta_al_declarar_la_ruta(self):
        with self.assertRaises(ValueError):
            auth.requiere_rol("dueño", obtener_db=lambda: self.db)


if __name__ == "__main__":
    unittest.main()
