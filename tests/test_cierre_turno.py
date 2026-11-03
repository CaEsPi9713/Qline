"""S4-M03 · motivo y nota opcionales al finalizar la atención (campo raíz `cierre`, compatible con turnos anteriores)."""
import unittest
from tests.apoyo_sesion import ClienteConSesion
from datetime import datetime, timedelta, timezone

from app.atencion import finalizar_atencion, validar_cierre
from app.constantes import ESTADOS, MOTIVOS_CIERRE, NOTA_CIERRE_MAX
from app.excepciones import DatosInvalidos, TransicionNoPermitida
from app.turnos_schema import SCHEMA_TURNOS, TurnoValidationError, validar_documento_turno

from .fakes import ColeccionFalsa, turno, utc
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.datos_prueba import construir_turno

FIN = utc(14, 14)
SCRIPT = "<script>alert(1)</script>"


class PruebasFinalizarConCierre(unittest.TestCase):
    def setUp(self):
        self.col = ColeccionFalsa([turno("A-030", "en_atencion", "V-01", inicio=utc(14, 10))])

    def doc(self):
        return self.col.docs["A-030"]

    def test_sin_motivo_ni_nota_funciona_igual_que_antes(self):
        r = finalizar_atencion(self.col, "A-030", "V-01", ahora=FIN)
        self.assertEqual((r["estado"], r["atencion_seg"], r["cierre"]), ("atendido", 240, None))
        self.assertNotIn("cierre", self.doc())

    def test_con_motivo_y_nota_se_guardan_en_la_raiz_en_la_misma_escritura(self):
        r = finalizar_atencion(self.col, "A-030", "V-01", ahora=FIN, motivo="derivado", nota="  Pasa a cajas  ")
        esperado = {"motivo": "derivado", "nota": "Pasa a cajas"}
        self.assertEqual(r["cierre"], esperado)
        self.assertEqual(self.doc()["cierre"], esperado)
        self.assertEqual((self.doc()["estado"], self.doc()["metricas"]["atencion_seg"]), ("atendido", 240))

    def test_solo_nota_o_solo_motivo(self):
        self.assertEqual(validar_cierre("", "algo"), {"motivo": None, "nota": "algo"})
        self.assertEqual(validar_cierre("resuelto", ""), {"motivo": "resuelto", "nota": None})
        self.assertIsNone(validar_cierre("", "   "))
        self.assertIsNone(validar_cierre(None, None))

    def test_motivo_invalido_se_rechaza_sin_escribir(self):
        with self.assertRaises(DatosInvalidos) as ctx:
            finalizar_atencion(self.col, "A-030", "V-01", ahora=FIN, motivo="inventado")
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self.doc()["estado"], "en_atencion")
        self.assertNotIn("cierre", self.doc())

    def test_motivo_o_nota_con_tipo_incorrecto(self):
        for motivo, nota in ((["resuelto"], ""), ("", 123)):
            with self.assertRaises(DatosInvalidos):
                validar_cierre(motivo, nota)

    def test_nota_de_200_caracteres_pasa_y_de_201_se_rechaza(self):
        self.assertEqual(len(validar_cierre("", "x" * NOTA_CIERRE_MAX)["nota"]), NOTA_CIERRE_MAX)
        with self.assertRaises(DatosInvalidos):
            finalizar_atencion(self.col, "A-030", "V-01", ahora=FIN, nota="x" * (NOTA_CIERRE_MAX + 1))
        self.assertEqual(self.doc()["estado"], "en_atencion")

    def test_la_nota_se_limpia_de_caracteres_de_control_y_espacios(self):
        self.assertEqual(validar_cierre("", "uno\n\ndos\t\x00tres   cuatro")["nota"], "uno dos tres cuatro")

    def test_la_nota_con_html_se_guarda_como_texto_sin_modificar(self):
        self.assertEqual(validar_cierre("", SCRIPT)["nota"], SCRIPT)

    def test_un_reintento_no_sobrescribe_el_cierre(self):
        finalizar_atencion(self.col, "A-030", "V-01", ahora=FIN, motivo="resuelto", nota="primera")
        with self.assertRaises(TransicionNoPermitida):
            finalizar_atencion(self.col, "A-030", "V-01", ahora=FIN, motivo="otro", nota="segunda")
        self.assertEqual(self.doc()["cierre"], {"motivo": "resuelto", "nota": "primera"})


class PruebasEsquemaDelCierre(unittest.TestCase):
    def base(self, **extra):
        doc = turno("A-001", "atendido", "V-01", inicio=utc(14, 10))
        doc["servicio"] = "atencion_general"
        doc.update(extra)
        return doc

    def test_el_documento_antiguo_sin_cierre_sigue_validando(self):
        self.assertTrue(validar_documento_turno(self.base()))

    def test_acepta_cierres_validos(self):
        for cierre in ({"motivo": "otro", "nota": "ok"}, {"motivo": None, "nota": None}, {"nota": "solo nota"}, {}):
            self.assertTrue(validar_documento_turno(self.base(cierre=cierre)), cierre)

    def test_rechaza_cierres_invalidos(self):
        for cierre in ({"motivo": "x"}, {"nota": "y" * 201}, {"extra": 1}, "texto", {"nota": 5}):
            with self.assertRaises(TurnoValidationError, msg=str(cierre)):
                validar_documento_turno(self.base(cierre=cierre))

    def test_el_esquema_de_mongodb_declara_el_campo_y_no_cambia_los_estados(self):
        props = SCHEMA_TURNOS["$jsonSchema"]["properties"]
        self.assertEqual(props["cierre"]["properties"]["motivo"]["enum"], list(MOTIVOS_CIERRE) + [None])
        self.assertEqual(props["cierre"]["properties"]["nota"]["maxLength"], NOTA_CIERRE_MAX)
        self.assertFalse(props["cierre"]["additionalProperties"])
        self.assertEqual(props["estado"]["enum"], list(ESTADOS))
        self.assertNotIn("cierre", props["metricas"]["properties"])
        self.assertNotIn("cierre", props["timestamps"]["properties"])
        self.assertIn("cierre", SCHEMA_TURNOS["$jsonSchema"]["properties"])
        self.assertNotIn("cierre", SCHEMA_TURNOS["$jsonSchema"]["required"])


class PruebasRutasDeCierre(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = ClienteConSesion(main.app, follow_redirects=False)
        ahora = datetime.now(timezone.utc)
        for n in (1, 2):
            self.db["turnos"].insert_one(construir_turno(
                f"A-00{n}", "en_atencion", "normal", ahora - timedelta(minutes=9), f"V-0{n}", ahora - timedelta(minutes=5)))

    def turno(self, codigo):
        return self.db["turnos"].find_one({"codigo": codigo})

    def test_api_finalizar_con_motivo_y_nota(self):
        r = self.c.post("/api/atencion/finalizar", data={
            "codigo": "A-001", "ventanilla": "V-01", "motivo": "resuelto", "nota": "todo bien"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["cierre"], {"motivo": "resuelto", "nota": "todo bien"})
        self.assertEqual(self.turno("A-001")["cierre"], {"motivo": "resuelto", "nota": "todo bien"})

    def test_api_finalizar_sin_campos_opcionales_no_crea_cierre(self):
        r = self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-01"})
        self.assertEqual((r.status_code, r.json()["cierre"]), (200, None))
        self.assertNotIn("cierre", self.turno("A-001"))

    def test_api_motivo_invalido_responde_422_y_no_cambia_el_turno(self):
        r = self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-01", "motivo": "zzz"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.turno("A-001")["estado"], "en_atencion")

    def test_api_nota_demasiado_larga_responde_422(self):
        r = self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-01", "nota": "x" * 201})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.turno("A-001")["estado"], "en_atencion")

    def test_el_panel_finaliza_con_cierre_y_redirige(self):
        r = self.c.post("/panel/finalizar", data={
            "codigo": "A-002", "ventanilla": "V-02", "motivo": "documentacion_incompleta", "nota": "falta cédula"})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.turno("A-002")["cierre"]["motivo"], "documentacion_incompleta")

    def test_el_panel_muestra_el_error_de_un_motivo_invalido(self):
        r = self.c.post("/panel/finalizar", data={"codigo": "A-002", "ventanilla": "V-02", "motivo": "zzz"})
        self.assertEqual(r.status_code, 303)
        self.assertIn("error=", r.headers["location"])
        self.assertEqual(self.turno("A-002")["estado"], "en_atencion")

    def test_el_panel_ofrece_motivo_y_nota_con_limite(self):
        html = self.c.get("/panel").text
        self.assertIn('name="motivo"', html)
        self.assertIn(f'maxlength="{NOTA_CIERRE_MAX}"', html)
        for etiqueta in ("Resuelto", "Derivado a otra área", "Documentación incompleta", "Otro"):
            self.assertIn(etiqueta, html)

    def test_una_nota_con_html_se_muestra_escapada(self):
        self.c.post("/panel/finalizar", data={"codigo": "A-001", "ventanilla": "V-01", "nota": SCRIPT})
        html = self.c.get("/administracion?coleccion=turnos").text
        self.assertNotIn(SCRIPT, html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_historial_y_descargas_aceptan_turnos_con_y_sin_cierre(self):
        self.c.post("/api/atencion/finalizar", data={
            "codigo": "A-001", "ventanilla": "V-01", "motivo": "otro", "nota": "n"})
        for ruta in ("/api/historial", "/api/historial/descargar", "/api/dashboard", "/historial", "/dashboard"):
            r = self.c.get(ruta)
            self.assertEqual(r.status_code, 200, ruta)
        self.assertEqual(len(self.c.get("/api/historial").json()["turnos"]), 2)


if __name__ == "__main__":
    unittest.main()
