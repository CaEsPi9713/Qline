"""Fase 4 · El supervisor asigna una ventanilla a cada operador y el operador solo opera la suya."""
import os
import unittest
from unittest import mock

from tests.apoyo_sesion import ClienteConSesion, sembrar_usuario
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo, doc

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app import asignaciones, auth, cola, ventanillas
    from app.auth import AuthError
    from app.constantes import VENTANILLAS
    from app.turnos_schema import validar_documento_turno

CLAVE = "Clave-segura-1"


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseAsignaciones(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        parche = mock.patch.dict(os.environ, {"SECRETO_SESION": "secreto-de-pruebas-de-asignaciones"})
        parche.start()
        self.addCleanup(parche.stop)
        auth._con_indice.clear()
        for p in (mock.patch.object(main, "BASE", ""), mock.patch.dict(main.templates.env.globals, {"base": ""})):
            p.start()
            self.addCleanup(p.stop)
        ventanillas._ULTIMAS_CONOCIDAS = tuple(VENTANILLAS)
        auth.asegurar_indices(self.db)

    def alta(self, usuario, rol="operador", estado="activo"):
        return auth.crear_usuario(self.db, usuario, CLAVE, rol=rol, estado=estado)

    def u(self, usuario):
        return self.db["usuarios"].find_one({"usuario": usuario})

    def como(self, rol, usuario=None):
        return ClienteConSesion(main.app, rol=None, follow_redirects=False).iniciar_sesion_en(self.db, rol, usuario)

    def operador_en(self, ventanilla, usuario="ana"):
        sembrar_usuario(self.db, "operador", usuario)
        if ventanilla:
            asignaciones.asignar_ventanilla(self.db, usuario, ventanilla, por="sup")
        return self.como("operador", usuario)


class PruebasDeAsignar(BaseAsignaciones):
    def test_asignar_deja_la_ventanilla_en_el_operador_y_anota_quien_lo_hizo(self):
        self.alta("ana")
        res = asignaciones.asignar_ventanilla(self.db, "ana", "v-02", por="sol")
        self.assertEqual((res["ventanilla"], res["cambio"]), ("V-02", True))
        self.assertEqual(self.u("ana")["ventanilla_asignada"], "V-02")
        self.assertEqual(self.u("ana")["ultimo_cambio"]["accion"], "asignar_ventanilla")
        self.assertEqual(self.u("ana")["ultimo_cambio"]["por"], "sol")

    def test_asignar_no_cierra_la_sesion_del_operador(self):
        self.alta("ana")
        version = self.u("ana")["version_sesion"]
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.assertEqual(self.u("ana")["version_sesion"], version)

    def test_misma_ventanilla_no_cambia_nada(self):
        self.alta("ana")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.assertFalse(asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")["cambio"])

    def test_una_ventanilla_pertenece_a_un_solo_operador(self):
        self.alta("ana")
        self.alta("luis")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        with self.assertRaises(AuthError) as ctx:
            asignaciones.asignar_ventanilla(self.db, "luis", "V-01", por="sol")
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("ya está asignada a ana", str(ctx.exception))
        self.assertIsNone(self.u("luis")["ventanilla_asignada"])

    def test_el_indice_unico_frena_una_asignacion_simultanea(self):
        self.alta("ana")
        self.alta("luis")
        self.db["usuarios"].update_one({"usuario": "ana"}, {"$set": {"ventanilla_asignada": "V-01"}})
        with self.assertRaises(Exception):
            self.db["usuarios"].update_one({"usuario": "luis"}, {"$set": {"ventanilla_asignada": "V-01"}})
        self.db["usuarios"].update_one({"usuario": "luis"}, {"$set": {"ventanilla_asignada": None}})   # varios sin ventanilla: bien

    def test_solo_ventanillas_activas_del_catalogo(self):
        self.alta("ana")
        for mala in ("V-99", "", None, "X-01", "V-1"):
            with self.assertRaises(AuthError, msg=repr(mala)) as ctx:
                asignaciones.asignar_ventanilla(self.db, "ana", mala, por="sol")
            self.assertEqual(ctx.exception.status, 400)
        ventanillas.registrar_ventanilla(self.db)                                    # V-04
        ventanillas.desactivar_ventanilla(self.db, "V-04")
        with self.assertRaises(AuthError):
            asignaciones.asignar_ventanilla(self.db, "ana", "V-04", por="sol")

    def test_una_ventanilla_nueva_del_catalogo_ya_se_puede_asignar(self):
        self.alta("ana")
        ventanillas.registrar_ventanilla(self.db)
        self.assertEqual(asignaciones.asignar_ventanilla(self.db, "ana", "V-04", por="sol")["ventanilla"], "V-04")

    def test_solo_a_operadores_activos(self):
        self.alta("sol", "supervisor")
        self.alta("luis", "operador", "deshabilitado")
        auth.crear_usuario(self.db, "pedro", CLAVE)
        for usuario, status in (("sol", 409), ("luis", 409), ("pedro", 409), ("fantasma", 404)):
            with self.assertRaises(AuthError, msg=usuario) as ctx:
                asignaciones.asignar_ventanilla(self.db, usuario, "V-01", por="sol")
            self.assertEqual(ctx.exception.status, status, usuario)

    def test_reasignar_libera_la_anterior_para_otro_operador(self):
        self.alta("ana")
        self.alta("luis")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-02", por="sol")
        asignaciones.asignar_ventanilla(self.db, "luis", "V-01", por="sol")
        self.assertEqual((self.u("ana")["ventanilla_asignada"], self.u("luis")["ventanilla_asignada"]), ("V-02", "V-01"))

    def test_deshabilitar_a_un_operador_libera_su_ventanilla(self):
        self.alta("ana")
        self.alta("luis")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        auth.deshabilitar_usuario(self.db, "ana", por="root")
        asignaciones.asignar_ventanilla(self.db, "luis", "V-01", por="sol")
        self.assertEqual(self.u("luis")["ventanilla_asignada"], "V-01")


class PruebasConTurnoEnCurso(BaseAsignaciones):
    def test_no_se_reasigna_mientras_la_ventanilla_tiene_un_turno_en_curso(self):
        self.alta("ana")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.db["turnos"].insert_one(doc("A-001", "llamado", "V-01"))
        with self.assertRaises(AuthError) as ctx:
            asignaciones.asignar_ventanilla(self.db, "ana", "V-02", por="sol")
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("A-001", str(ctx.exception))
        self.assertEqual(self.u("ana")["ventanilla_asignada"], "V-01")

    def test_tampoco_se_quita(self):
        self.alta("ana")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.db["turnos"].insert_one(doc("A-001", "en_atencion", "V-01"))
        with self.assertRaises(AuthError):
            asignaciones.quitar_ventanilla(self.db, "ana", por="sol")
        self.assertEqual(self.u("ana")["ventanilla_asignada"], "V-01")

    def test_al_finalizar_el_turno_ya_se_puede(self):
        self.alta("ana")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.db["turnos"].insert_one(doc("A-001", "atendido", "V-01"))
        self.assertEqual(asignaciones.asignar_ventanilla(self.db, "ana", "V-02", por="sol")["ventanilla"], "V-02")
        asignaciones.quitar_ventanilla(self.db, "ana", por="sol")
        self.assertIsNone(self.u("ana")["ventanilla_asignada"])

    def test_quitar_sin_ventanilla_es_un_error(self):
        self.alta("ana")
        with self.assertRaises(AuthError) as ctx:
            asignaciones.quitar_ventanilla(self.db, "ana", por="sol")
        self.assertEqual(ctx.exception.status, 409)

    def test_un_turno_en_curso_en_otra_ventanilla_no_estorba(self):
        self.alta("ana")
        self.db["turnos"].insert_one(doc("A-001", "llamado", "V-03"))
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.assertEqual(self.u("ana")["ventanilla_asignada"], "V-01")


class PruebasDelListado(BaseAsignaciones):
    def test_lista_operadores_activos_y_ventanillas_con_su_turno(self):
        self.alta("ana")
        self.alta("luis")
        self.alta("sol", "supervisor")
        self.alta("ruiz", "operador", "deshabilitado")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.db["turnos"].insert_one(doc("A-005", "llamado", "V-01"))
        datos = asignaciones.listar(self.db)
        self.assertEqual([o["usuario"] for o in datos["operadores"]], ["ana", "luis"])
        ana = datos["operadores"][0]
        self.assertEqual((ana["ventanilla"], ana["turno"]), ("V-01", "A-005"))
        self.assertEqual([v["codigo"] for v in datos["ventanillas"]], ["V-01", "V-02", "V-03"])
        v01 = datos["ventanillas"][0]
        self.assertEqual((v01["operador"], v01["turno"]), ("ana", ("A-005", "llamado")))

    def test_las_opciones_de_cada_operador_excluyen_las_ocupadas_por_otros(self):
        self.alta("ana")
        self.alta("luis")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        asignaciones.asignar_ventanilla(self.db, "luis", "V-02", por="sol")
        datos = {o["usuario"]: o["libres"] for o in asignaciones.listar(self.db)["operadores"]}
        self.assertEqual(datos["ana"], ["V-01", "V-03"])
        self.assertEqual(datos["luis"], ["V-02", "V-03"])


class PruebasDelOperadorSinVentanilla(BaseAsignaciones):
    def test_la_cola_explica_que_debe_pedirla_y_no_ofrece_llamar(self):
        c = self.operador_en(None)
        html = c.get("/cola").text
        self.assertIn("Pida a su supervisor que le asigne una", html)
        self.assertNotIn('action="/cola/llamar"', html)

    def test_no_puede_llamar_ni_por_el_formulario_ni_por_la_api(self):
        self.pendiente("A-001")
        c = self.operador_en(None)
        r = c.post("/cola/llamar", data={"ventanilla": "V-01"})
        self.assertEqual(r.status_code, 303)
        self.assertIn("Pida+a+su+supervisor", r.headers["location"])
        api = c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.assertEqual(api.status_code, 403)
        self.assertIn("Pida a su supervisor", api.json()["error"])
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "pendiente")
        self.assertEqual(cola.tamano_cola(), 1)

    def test_el_panel_lo_lleva_a_la_vista_de_trabajo_que_tambien_lo_avisa(self):
        c = self.operador_en(None)
        r = c.get("/panel?msg=hola")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/cola?msg=hola"))
        self.assertIn("Pida a su supervisor que le asigne una", c.get("/cola").text)

    def test_no_puede_iniciar_ni_finalizar(self):
        self.db["turnos"].insert_one(doc("A-001", "llamado", "V-01"))
        c = self.operador_en(None)
        self.assertEqual(c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"}).status_code, 403)
        self.assertEqual(c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-01"}).status_code, 403)
        r = c.post("/panel/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertIn("Pida+a+su+supervisor", r.headers["location"])
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "llamado")


class PruebasDelOperadorConVentanilla(BaseAsignaciones):
    def test_la_cola_muestra_su_ventanilla_sin_selector(self):
        html = self.operador_en("V-02").get("/cola").text
        self.assertIn("Ventanilla <strong>V-02</strong>", html)
        self.assertIn('<input type="hidden" name="ventanilla" value="V-02">', html)
        self.assertNotIn("<select id=\"cambiar-ventanilla\"", html)

    def test_llama_desde_la_suya_aunque_no_envie_la_ventanilla(self):
        self.pendiente("A-001")
        c = self.operador_en("V-02")
        r = c.post("/cola/llamar")
        self.assertEqual(r.status_code, 303)
        t = self.db["turnos"].find_one({"codigo": "A-001"})
        self.assertEqual((t["estado"], t["ventanilla"], t["operador"]), ("llamado", "V-02", "ana"))

    def test_anota_el_usuario_en_el_turno_y_el_turno_sigue_siendo_valido(self):
        self.pendiente("A-001")
        self.operador_en("V-02").post("/api/llamar", data={"ventanilla": "V-02"})
        t = self.db["turnos"].find_one({"codigo": "A-001"})
        self.assertEqual(t["operador"], "ana")
        validar_documento_turno({k: v for k, v in t.items() if k != "_id"})

    def test_no_puede_llamar_desde_la_ventanilla_de_otro(self):
        self.pendiente("A-001")
        c = self.operador_en("V-02")
        r = c.post("/api/llamar", data={"ventanilla": "V-01"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("Su ventanilla es V-02", r.json()["error"])
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "pendiente")
        redir = c.post("/cola/llamar", data={"ventanilla": "V-01"})
        self.assertIn("Su+ventanilla+es+V-02", redir.headers["location"])

    def test_no_puede_iniciar_ni_finalizar_turnos_de_otra_ventanilla(self):
        self.db["turnos"].insert_one(doc("A-001", "llamado", "V-01"))
        c = self.operador_en("V-02")
        self.assertEqual(c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-01"}).status_code, 403)
        r = c.post("/panel/finalizar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertIn("Su+ventanilla+es+V-02", r.headers["location"])
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "llamado")

    def test_atiende_su_turno_de_principio_a_fin(self):
        self.pendiente("A-001")
        c = self.operador_en("V-02")
        c.post("/cola/llamar")
        self.assertEqual(c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-02"}).status_code, 200)
        r = c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-02"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "atendido")

    def test_el_panel_de_todas_las_ventanillas_no_es_del_operador(self):
        c = self.operador_en("V-02")
        r = c.get("/panel")
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/cola"))
        html = c.get("/cola").text
        self.assertNotIn("<h2>V-01</h2>", html)
        self.assertNotIn("<h2>V-03</h2>", html)

    def test_con_un_turno_en_curso_ya_no_ofrece_llamar_otro(self):
        self.pendiente("A-001")
        c = self.operador_en("V-02")
        c.post("/cola/llamar")
        html = c.get("/cola").text
        self.assertIn('id="codigo-actual">A-001<', html)
        self.assertIn('id="btn-iniciar"', html)
        self.assertNotIn('id="btn-llamar"', html)

    def test_el_cambio_de_ventanilla_vale_sin_volver_a_ingresar(self):
        c = self.operador_en("V-02")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-03", por="sol")
        self.assertIn("<strong>V-03</strong>", c.get("/cola").text)


class PruebasDeSupervisionYAdministracion(BaseAsignaciones):
    def test_el_supervisor_elige_cualquier_ventanilla_y_queda_su_usuario_en_el_turno(self):
        self.pendiente("A-001")
        c = self.como("supervisor", "sol")
        self.assertEqual(c.post("/api/llamar", data={"ventanilla": "V-03"}).status_code, 200)
        t = self.db["turnos"].find_one({"codigo": "A-001"})
        self.assertEqual((t["ventanilla"], t["operador"]), ("V-03", "sol"))

    def test_el_supervisor_debe_indicar_la_ventanilla(self):
        self.pendiente("A-001")
        r = self.como("supervisor", "sol").post("/api/llamar")
        self.assertEqual(r.status_code, 422)
        self.assertIn("Indique la ventanilla", r.json()["error"])
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "pendiente")

    def test_el_administrador_tambien_y_la_cola_le_muestra_el_selector(self):
        html = self.como("administrador", "adm").get("/cola").text
        self.assertIn("<select", html)
        self.assertNotIn("Usted atiende en la ventanilla", html)

    def test_el_supervisor_ve_todas_las_ventanillas_en_el_panel(self):
        html = self.como("supervisor", "sol").get("/panel").text
        for v in ("V-01", "V-02", "V-03"):
            self.assertIn(f"<h2>{v}</h2>", html)


class PruebasDeLaPantalla(BaseAsignaciones):
    def test_lista_operadores_ventanillas_y_ofrece_asignar(self):
        self.alta("ana")
        self.alta("luis")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        html = self.como("supervisor", "sol").get("/supervisor/asignaciones").text
        for texto in ("ana", "luis", "Sin ventanilla", "Asignar", "Cambiar", "Quitar", "Operadores: 2", "Ventanillas activas: 3"):
            self.assertIn(texto, html)
        self.assertEqual(html.count('action="/supervisor/asignaciones/asignar"'), 2)

    def test_asignar_desde_la_pantalla_y_aviso(self):
        self.alta("ana")
        c = self.como("supervisor", "sol")
        r = c.post("/supervisor/asignaciones/asignar", data={"operador": "ana", "ventanilla": "V-02"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.u("ana")["ventanilla_asignada"], "V-02")
        self.assertIn("ana atenderá en la ventanilla V-02", c.get(r.headers["location"]).text)

    def test_quitar_desde_la_pantalla_y_aviso(self):
        self.alta("ana")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-02", por="sol")
        c = self.como("supervisor", "sol")
        r = c.post("/supervisor/asignaciones/quitar", data={"operador": "ana"})
        self.assertEqual(r.status_code, 303)
        self.assertIsNone(self.u("ana")["ventanilla_asignada"])
        self.assertIn("ana quedó sin ventanilla", c.get(r.headers["location"]).text)

    def test_los_errores_se_muestran_en_la_misma_pantalla(self):
        self.alta("ana")
        self.alta("luis")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        c = self.como("supervisor", "sol")
        r = c.post("/supervisor/asignaciones/asignar", data={"operador": "luis", "ventanilla": "V-01"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("V-01 ya está asignada a ana", r.text)
        self.assertEqual(c.post("/supervisor/asignaciones/asignar", data={"operador": "luis", "ventanilla": "V-77"}).status_code, 400)
        self.assertEqual(c.post("/supervisor/asignaciones/asignar", data={"operador": "fantasma", "ventanilla": "V-01"}).status_code, 404)

    def test_con_un_turno_en_curso_los_controles_se_desactivan_y_se_explica(self):
        self.alta("ana")
        asignaciones.asignar_ventanilla(self.db, "ana", "V-01", por="sol")
        self.db["turnos"].insert_one(doc("A-007", "llamado", "V-01"))
        html = self.como("supervisor", "sol").get("/supervisor/asignaciones").text
        self.assertIn("Finalice el turno A-007 en el panel", html)
        self.assertRegex(html, r'<button type="submit" class="btn-secundario btn-sm" disabled>Quitar')

    def test_sin_operadores_explica_donde_habilitarlos(self):
        self.assertIn("El administrador los habilita", self.como("supervisor", "sol").get("/supervisor/asignaciones").text)
        self.assertIn("/admin/usuarios", self.como("administrador", "adm").get("/supervisor/asignaciones").text)

    def test_el_menu_del_supervisor_ofrece_asignaciones_y_el_del_operador_no(self):
        self.assertIn("/supervisor/asignaciones", self.como("supervisor", "sol").get("/dashboard").text)
        self.assertNotIn("/supervisor/asignaciones", self.operador_en("V-01").get("/cola").text)

    def test_solo_supervisor_y_administrador(self):
        c = self.operador_en(None)
        self.assertEqual(c.get("/supervisor/asignaciones").status_code, 403)
        self.assertEqual(c.post("/supervisor/asignaciones/asignar", data={"operador": "ana", "ventanilla": "V-01"}).status_code, 403)
        self.assertEqual(TestClient(main.app, follow_redirects=False).get("/supervisor/asignaciones").status_code, 303)

    def test_un_post_desde_otro_sitio_no_asigna(self):
        self.alta("ana")
        r = self.como("supervisor", "sol").post("/supervisor/asignaciones/asignar", data={"operador": "ana", "ventanilla": "V-01"},
                                                headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.u("ana")["ventanilla_asignada"])

    def test_los_avisos_de_la_url_no_inyectan_html(self):
        html = self.como("supervisor", "sol").get("/supervisor/asignaciones?ok=asignada&usuario=%3Cb%3E&ventanilla=%3Cscript%3E").text
        self.assertNotIn("<script>", html)
        self.assertIn("el operador atenderá en la ventanilla", html)


if __name__ == "__main__":
    unittest.main()
