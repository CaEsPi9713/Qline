"""Fase 5 · Vista de trabajo del operador: datos, pantalla, API de estado y script que la mantiene al día."""
import json
import re
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tests.apoyo_sesion import ClienteConSesion
from tests.test_asignaciones import BaseAsignaciones
from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, doc

if HAY_DEPENDENCIAS:
    from redis.exceptions import RedisError

    import app.main as main
    from app import cola, vista_operador
    from app.constantes import MOTIVOS_CIERRE, NOTA_CIERRE_MAX
    from app.llamado import llamar_siguiente_turno

RAIZ = Path(__file__).resolve().parents[1]
JS = (RAIZ / "static" / "operador.js").read_text(encoding="utf-8")


def datos_de(html: str, id_: str) -> dict:
    return json.loads(re.search(rf'<script type="application/json" id="{id_}">(.*?)</script>', html, re.S).group(1))


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDelEstado(BaseAsignaciones):
    def estado(self, ventanilla="V-02", operador="ana"):
        return vista_operador.estado_operador(self.db, ventanilla, operador)

    def test_sin_turno_en_curso_y_con_la_cola_en_orden_de_atencion(self):
        self.pendiente("A-001", "normal", 1000)
        self.pendiente("A-002", "preferencial", 2000)
        self.pendiente("A-003", "normal", 3000)
        e = self.estado()
        self.assertIsNone(e["turno"])
        self.assertEqual([(c["posicion"], c["codigo"], c["prioridad"]) for c in e["cola"]],
                         [(1, "A-002", "preferencial"), (2, "A-001", "normal"), (3, "A-003", "normal")])
        self.assertEqual((e["en_espera"], e["preferenciales"]), (3, 1))
        self.assertTrue(all(isinstance(c["creado_ms"], int) for c in e["cola"]))

    def test_el_estado_es_serializable_a_json(self):
        self.pendiente("A-001")
        llamar_siguiente_turno(self.db, "V-02", operador="ana")
        json.dumps(self.estado())

    def test_turno_llamado_con_cuenta_regresiva(self):
        self.pendiente("A-001")
        llamar_siguiente_turno(self.db, "V-02", operador="ana")
        t = self.estado()["turno"]
        self.assertEqual((t["codigo"], t["estado"], t["puede_iniciar"], t["puede_finalizar"]), ("A-001", "llamado", True, False))
        self.assertTrue(0 < t["segundos_restantes"] <= 180)
        self.assertIsInstance(t["llamado_ms"], int)
        self.assertIsNone(t["inicio_ms"])
        e = self.estado()
        self.assertAlmostEqual(e["turno"]["vence_ms"], e["servidor_ms"] + e["turno"]["segundos_restantes"] * 1000, delta=1500)

    def test_turno_en_atencion_con_su_inicio(self):
        self.pendiente("A-001")
        c = self.operador_en("V-02")
        c.post("/cola/llamar")
        c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-02"})
        t = self.estado()["turno"]
        self.assertEqual((t["estado"], t["puede_iniciar"], t["puede_finalizar"]), ("en_atencion", False, True))
        self.assertIsInstance(t["inicio_ms"], int)
        self.assertIsNone(t["vence_ms"])

    def test_el_turno_de_otra_ventanilla_no_aparece(self):
        self.db["turnos"].insert_one(doc("A-009", "llamado", "V-01"))
        self.assertIsNone(self.estado("V-02")["turno"])
        self.assertEqual(self.estado("V-01")["turno"]["codigo"], "A-009")

    def test_mis_numeros_de_hoy_solo_cuentan_los_mios(self):
        ahora = datetime.now(timezone.utc)

        def atendido(codigo, operador, finalizado, seg):
            d = doc(codigo, "atendido", "V-02")
            d.update(operador=operador)
            d["timestamps"]["finalizado"] = finalizado
            d["metricas"]["atencion_seg"] = seg
            self.db["turnos"].insert_one(d)

        atendido("A-001", "ana", ahora - timedelta(minutes=5), 100)
        atendido("A-002", "ana", ahora - timedelta(minutes=2), 200)
        atendido("A-003", "luis", ahora - timedelta(minutes=2), 999)         # de otro operador
        atendido("A-004", "ana", ahora - timedelta(days=2), 999)             # de otro día
        e = self.estado()
        self.assertEqual((e["mis_atendidos_hoy"], e["mi_atencion_media_seg"]), (2, 150))

    def test_sin_atendidos_la_media_es_nula(self):
        e = self.estado()
        self.assertEqual((e["mis_atendidos_hoy"], e["mi_atencion_media_seg"]), (0, None))

    def test_la_cola_visible_se_limita_pero_se_cuenta_completa(self):
        for n in range(1, 36):
            self.pendiente(f"A-{n:03d}", "preferencial" if n == 35 else "normal", 1000 + n)
        e = self.estado()
        self.assertEqual((len(e["cola"]), e["en_espera"], e["preferenciales"]), (vista_operador.LIMITE_COLA_VISIBLE, 35, 1))
        self.assertEqual(e["cola"][0]["codigo"], "A-035")

    def test_con_redis_caido_avisa_y_conserva_el_turno_de_mongodb(self):
        self.db["turnos"].insert_one(doc("A-001", "llamado", "V-02"))
        with mock.patch.object(cola, "ver_cola", side_effect=RedisError("caído")):
            e = self.estado()
        self.assertFalse(e["redis_ok"])
        self.assertEqual((e["cola"], e["en_espera"]), ([], 0))
        self.assertEqual(e["turno"]["codigo"], "A-001")
        self.assertTrue(any("Redis" in a for a in e["avisos"]))

    def test_dos_turnos_activos_en_la_misma_ventanilla_se_avisan(self):
        self.db["turnos"].insert_one(doc("A-001", "en_atencion", "V-02"))
        self.db["turnos"].insert_one(doc("A-002", "llamado", "V-02"))
        e = self.estado()
        self.assertTrue(any("A-002" in a or "A-001" in a for a in e["avisos"]))

    def test_el_estado_vacio_sirve_para_mostrar_la_pantalla_sin_datos(self):
        e = vista_operador.estado_vacio("V-02", "ana", "sin datos")
        self.assertEqual((e["turno"], e["cola"], e["en_espera"], e["avisos"]), (None, [], 0, ["sin datos"]))


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeLaPantalla(BaseAsignaciones):
    def test_estructura_y_estado_inicial(self):
        self.pendiente("A-001", "preferencial", 1000)
        self.pendiente("A-002", "normal", 2000)
        html = self.operador_en("V-02").get("/cola").text
        for texto in ('id="oper"', 'data-ventanilla="V-02"', 'data-operador="1"', 'id="cola-lista"', 'id="conexion"',
                      'id="alertas"', 'aria-live="polite"', "/static/operador.js", "<kbd>N</kbd>", "Cola de espera"):
            self.assertIn(texto, html)
        inicial = datos_de(html, "estado-inicial")
        self.assertEqual((inicial["ventanilla"], inicial["operador"], inicial["en_espera"]), ("V-02", "ana", 2))
        self.assertEqual([c["codigo"] for c in inicial["cola"]], ["A-001", "A-002"])
        config = datos_de(html, "config-operador")
        self.assertEqual((config["motivos"], config["nota_max"]), (MOTIVOS_CIERRE, NOTA_CIERRE_MAX))

    def test_libre_con_cola_ofrece_llamar_y_sin_cola_lo_desactiva(self):
        c = self.operador_en("V-02")
        vacio = c.get("/cola").text
        self.assertRegex(vacio, r'id="btn-llamar"[^>]*disabled')
        self.assertIn("No hay turnos en espera", vacio)
        self.pendiente("A-001")
        con_cola = c.get("/cola").text
        self.assertNotRegex(con_cola, r'id="btn-llamar"[^>]*disabled')
        self.assertIn("Llamar siguiente", con_cola)
        self.assertIn('<form method="post" action="/cola/llamar" class="js-accion" data-api="/api/llamar"', con_cola)

    def test_turno_llamado_muestra_cuenta_regresiva_e_iniciar_y_no_la_cola_de_cierre(self):
        self.pendiente("A-001", "preferencial")
        c = self.operador_en("V-02")
        c.post("/cola/llamar")
        html = c.get("/cola").text
        self.assertIn('id="codigo-actual">A-001<', html)
        self.assertRegex(html, r'id="cuenta">\d+ s<')
        self.assertIn('action="/panel/iniciar"', html)
        self.assertIn('data-api="/api/atencion/iniciar"', html)
        for ausente in ('id="btn-llamar"', 'id="form-cierre"', 'id="btn-finalizar"'):
            self.assertNotIn(ausente, html)

    def test_turno_en_atencion_muestra_cronometro_y_cierre_con_motivos(self):
        self.pendiente("A-001")
        c = self.operador_en("V-02")
        c.post("/cola/llamar")
        c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-02"})
        html = c.get("/cola").text
        self.assertRegex(html, r'id="cron">\d\d:\d\d<')
        self.assertIn('id="form-cierre"', html)
        self.assertIn('action="/panel/finalizar"', html)
        for clave in MOTIVOS_CIERRE:
            self.assertIn(f'<option value="{clave}">', html)
        self.assertIn(f'maxlength="{NOTA_CIERRE_MAX}"', html)
        self.assertIn('id="btn-finalizar"', html)
        self.assertNotIn('id="btn-iniciar"', html)

    def test_cada_turno_en_espera_lleva_su_hora_de_llegada_para_el_cronometro(self):
        self.pendiente("A-001")
        html = self.operador_en("V-02").get("/cola").text
        self.assertRegex(html, r'<li class="oper-item oper-item--normal" data-creado-ms="\d+">')

    def test_el_operador_no_ve_la_tarjeta_antigua_de_llamar_ni_selector(self):
        html = self.operador_en("V-02").get("/cola").text
        self.assertNotIn("Llamar siguiente turno", html)
        self.assertNotIn('<select name="ventanilla"', html)
        self.assertNotIn('id="cambiar-ventanilla"', html)

    def test_sin_ventanilla_solo_el_aviso(self):
        html = self.operador_en(None).get("/cola").text
        self.assertIn("Pida a su supervisor que le asigne una", html)
        for ausente in ('id="oper"', "operador.js", 'id="estado-inicial"'):
            self.assertNotIn(ausente, html)

    def test_con_redis_caido_la_pantalla_carga_con_un_aviso(self):
        self.db["turnos"].insert_one(doc("A-001", "llamado", "V-02"))
        c = self.operador_en("V-02")
        with mock.patch.object(cola, "ver_cola", side_effect=RedisError("caído")):
            r = c.get("/cola")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Redis no responde", r.text)
        self.assertIn("A-001", r.text)

    def test_si_mongodb_falla_la_pantalla_carga_vacia_y_avisa_sin_detalles(self):
        c = self.operador_en("V-02")
        with mock.patch.object(vista_operador, "estado_operador", side_effect=RuntimeError("secreto interno")):
            r = c.get("/cola")
        self.assertEqual(r.status_code, 200)
        self.assertIn("MongoDB no responde", r.text)
        self.assertNotIn("secreto interno", r.text)

    def test_un_codigo_con_html_se_escapa_en_la_pagina_y_en_el_json(self):
        self.db["turnos"].insert_one(doc("<b>x</b>", "llamado", "V-02"))
        html = self.operador_en("V-02").get("/cola").text
        self.assertNotIn("<b>x</b>", html)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)
        crudo = re.search(r'id="estado-inicial">(.*?)</script>', html, re.S).group(1)
        self.assertNotIn("<b>", crudo)
        self.assertEqual(json.loads(crudo)["turno"]["codigo"], "<b>x</b>")

    def test_la_respuesta_no_se_guarda_en_cache(self):
        self.assertEqual(self.operador_en("V-02").get("/cola").headers["cache-control"], "no-store")


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeLaApiDeEstado(BaseAsignaciones):
    def test_el_operador_recibe_el_estado_de_su_ventanilla(self):
        self.pendiente("A-001")
        r = self.operador_en("V-02").get("/api/operador/estado")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-store")
        j = r.json()
        self.assertEqual((j["ok"], j["ventanilla"], j["operador"], j["en_espera"]), (True, "V-02", "ana", 1))
        for campo in ("turno", "cola", "preferenciales", "mis_atendidos_hoy", "mi_atencion_media_seg", "servidor_ms", "avisos"):
            self.assertIn(campo, j)

    def test_el_operador_no_puede_espiar_otra_ventanilla(self):
        self.db["turnos"].insert_one(doc("A-009", "llamado", "V-01"))
        j = self.operador_en("V-02").get("/api/operador/estado?ventanilla=V-01").json()
        self.assertEqual(j["ventanilla"], "V-02")
        self.assertIsNone(j["turno"])

    def test_sin_ventanilla_responde_403_con_el_motivo(self):
        r = self.operador_en(None).get("/api/operador/estado")
        self.assertEqual(r.status_code, 403)
        self.assertIn("Pida a su supervisor", r.json()["error"])

    def test_el_supervisor_elige_la_ventanilla(self):
        self.db["turnos"].insert_one(doc("A-009", "llamado", "V-03"))
        c = self.como("supervisor", "sol")
        j = c.get("/api/operador/estado?ventanilla=V-03").json()
        self.assertEqual((j["ventanilla"], j["operador"], j["turno"]["codigo"]), ("V-03", "sol", "A-009"))

    def test_el_supervisor_debe_indicar_una_ventanilla_valida(self):
        c = self.como("supervisor", "sol")
        for url in ("/api/operador/estado", "/api/operador/estado?ventanilla=V-99", "/api/operador/estado?ventanilla=x"):
            r = c.get(url)
            self.assertEqual(r.status_code, 400, url)
            self.assertFalse(r.json()["ok"])

    def test_si_falla_el_calculo_responde_503_sin_detalles(self):
        c = self.operador_en("V-02")
        with mock.patch.object(vista_operador, "estado_operador", side_effect=RuntimeError("secreto interno")):
            r = c.get("/api/operador/estado")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn("secreto interno", r.text)


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class PruebasDeLaVistaDeSupervision(BaseAsignaciones):
    def test_el_supervisor_abre_la_vista_de_una_ventanilla_con_selector(self):
        html = self.como("supervisor", "sol").get("/cola?ventanilla=V-03").text
        self.assertIn('data-ventanilla="V-03"', html)
        self.assertIn('data-operador="0"', html)
        self.assertIn('id="cambiar-ventanilla"', html)
        self.assertIn("Volver a la supervisión", html)

    def test_sin_elegir_ventanilla_sigue_la_vista_de_supervision_de_siempre(self):
        html = self.como("administrador", "adm").get("/cola").text
        self.assertIn('<select name="ventanilla"', html)
        self.assertIn("Llamar siguiente turno", html)
        self.assertNotIn('id="oper"', html)
        self.assertIn("/cola?ventanilla=V-01", html)                       # enlaces a la vista de cada ventanilla

    def test_una_ventanilla_invalida_vuelve_a_la_supervision(self):
        html = self.como("supervisor", "sol").get("/cola?ventanilla=V-99").text
        self.assertIn("Llamar siguiente turno", html)

    def test_el_supervisor_llama_desde_la_vista_de_trabajo_y_queda_su_usuario(self):
        self.pendiente("A-001")
        c = self.como("supervisor", "sol")
        self.assertEqual(c.post("/api/llamar", data={"ventanilla": "V-03"}).status_code, 200)
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["operador"], "sol")
        self.assertIn('id="codigo-actual">A-001<', c.get("/cola?ventanilla=V-03").text)

    def test_el_panel_de_todas_las_ventanillas_sigue_para_supervisor_y_administrador(self):
        for rol in ("supervisor", "administrador"):
            html = self.como(rol, rol[:3]).get("/panel").text
            for v in ("V-01", "V-02", "V-03"):
                self.assertIn(f"<h2>{v}</h2>", html, rol)


class PruebasDelScript(unittest.TestCase):
    def test_la_sintaxis_es_valida(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node no está instalado")
        r = subprocess.run([node, "--check", str(RAIZ / "static" / "operador.js")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_nunca_inserta_datos_como_html(self):
        for peligroso in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(peligroso, JS, peligroso)

    def test_usa_las_rutas_y_los_atajos_acordados(self):
        for texto in ("/api/operador/estado", "/ws/eventos", "/api/llamar", "/api/atencion/iniciar", "/api/atencion/finalizar",
                      "textContent", "qline_sonido", 'tecla === "n"', 'tecla === "i"', 'tecla === "f"'):
            self.assertIn(texto, JS, texto)

    def test_finalizar_nunca_se_dispara_con_una_sola_tecla(self):
        bloque = JS[JS.index('tecla === "f"'):]
        self.assertIn("focus()", bloque[:400])
        self.assertNotIn('pulsar("btn-finalizar")', JS)

    def test_los_atajos_se_ignoran_al_escribir(self):
        for texto in ('"input"', '"textarea"', '"select"', "isContentEditable", "ev.ctrlKey"):
            self.assertIn(texto, JS, texto)

    def test_tiene_respaldo_cuando_el_socket_cae(self):
        for texto in ("empezarSondeo", "setInterval(refrescar, 5000)", "setInterval(refrescar, 30000)", "onclose", "visibilitychange"):
            self.assertIn(texto, JS, texto)

    def test_se_sirve_como_archivo_estatico_publico(self):
        from fastapi.testclient import TestClient
        r = TestClient(main.app).get("/static/operador.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Vista de trabajo del operador", r.text)


if __name__ == "__main__":
    unittest.main()
