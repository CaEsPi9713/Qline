"""P09 conectado a la operación: una ventanilla del catálogo puede llamar, atender, verse en el panel y filtrarse en el historial."""
import threading
import unittest
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo, doc

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient

    import app.main as main
    from app import cola, ventanillas
    from app.constantes import VENTANILLAS, clave_ventanilla_actual
    from app.llamado import LlamadoError, llamar_siguiente_turno
    from app.panel_atencion import estado_ventanillas
    from app.turnos_schema import TurnoValidationError, validar_documento_turno


class BaseCatalogo(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.c = TestClient(main.app, follow_redirects=False)
        ventanillas._ULTIMAS_CONOCIDAS = tuple(VENTANILLAS)

    def alta(self, codigo):
        ventanillas.registrar_ventanilla(self.db, codigo=codigo, nombre=f"Ventanilla {codigo}")


class PruebasDelCatalogoOperativo(BaseCatalogo):
    def test_sin_catalogo_son_las_tres_ventanillas_base(self):
        self.assertEqual(ventanillas.ventanillas_activas(self.db), tuple(VENTANILLAS))

    def test_una_ventanilla_nueva_pasa_a_ser_operativa_y_en_orden_numerico(self):
        ventanillas.inicializar_ventanillas_base(self.db)
        self.alta("V-10")
        self.alta("V-04")
        self.assertEqual(ventanillas.ventanillas_activas(self.db), ("V-01", "V-02", "V-03", "V-04", "V-10"))

    def test_una_ventanilla_desactivada_deja_de_operar_y_las_demas_siguen(self):
        ventanillas.inicializar_ventanillas_base(self.db)
        ventanillas.desactivar_ventanilla(self.db, "V-02")
        self.assertEqual(ventanillas.ventanillas_activas(self.db), ("V-01", "V-03"))

    def test_si_mongodb_falla_se_usa_el_ultimo_catalogo_conocido(self):
        ventanillas.inicializar_ventanillas_base(self.db)
        self.alta("V-04")
        ventanillas.ventanillas_activas(self.db)
        roto = mock.MagicMock()
        roto.__getitem__.side_effect = RuntimeError("Connection refused 10.0.0.7:27017")
        self.assertEqual(ventanillas.ventanillas_activas(roto), ("V-01", "V-02", "V-03", "V-04"))

    def test_ignora_codigos_con_formato_invalido_en_el_catalogo(self):
        self.db["ventanillas"].insert_many([{"codigo": "V-01", "estado": "activa"}, {"codigo": "raro", "estado": "activa"}])
        self.assertEqual(ventanillas.ventanillas_activas(self.db), ("V-01",))

    def test_el_esquema_acepta_cualquier_ventanilla_con_formato_valido(self):
        base = doc("A-001", "llamado", "V-04")
        base["timestamps"]["llamado"] = base["timestamps"]["creado"]
        self.assertTrue(validar_documento_turno(base))
        for malo in ("X-99", "V-1", "v-04", 5):
            base["ventanilla"] = malo
            with self.assertRaises(TurnoValidationError, msg=str(malo)):
                validar_documento_turno(base)


class PruebasDelFlujoConUnaVentanillaNueva(BaseCatalogo):
    def setUp(self):
        super().setUp()
        ventanillas.inicializar_ventanillas_base(self.db)
        self.alta("V-04")

    def test_el_ciclo_completo_con_v04(self):
        self.pendiente("A-001")
        r = self.c.post("/api/llamar", data={"ventanilla": "V-04"})
        self.assertEqual((r.status_code, r.json()["codigo"]), (200, "A-001"))
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["ventanilla"], "V-04")
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-04")), "A-001")

        r = self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-04"})
        self.assertEqual(r.status_code, 200)
        r = self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-04", "motivo": "resuelto"})
        self.assertEqual((r.status_code, r.json()["estado"]), (200, "atendido"))
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-04")))

    def test_v04_aparece_en_el_panel_y_en_la_lista_de_la_cola(self):
        self.pendiente("A-001")
        self.c.post("/api/llamar", data={"ventanilla": "V-04"})
        panel = self.c.get("/panel").text
        self.assertIn("<h2>V-04</h2>", panel)
        self.assertIn("A-001", panel)
        self.assertIn('<option value="V-04"', self.c.get("/cola").text)

    def test_el_historial_filtra_por_la_ventanilla_nueva(self):
        self.pendiente("A-001")
        self.c.post("/api/llamar", data={"ventanilla": "V-04"})
        self.c.post("/api/atencion/iniciar", data={"codigo": "A-001", "ventanilla": "V-04"})
        self.c.post("/api/atencion/finalizar", data={"codigo": "A-001", "ventanilla": "V-04"})
        turnos = self.c.get("/api/historial?ventanilla=V-04").json()["turnos"]
        self.assertEqual([t["codigo"] for t in turnos], ["A-001"])
        self.assertIn('value="V-04"', self.c.get("/historial").text)

    def test_una_ventanilla_no_registrada_no_puede_llamar(self):
        self.pendiente("A-001")
        r = self.c.post("/api/llamar", data={"ventanilla": "V-05"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-001"})["estado"], "pendiente")
        self.assertEqual(cola.tamano_cola(), 1)

    def test_una_ventanilla_desactivada_no_puede_llamar(self):
        ventanillas.desactivar_ventanilla(self.db, "V-04")
        self.pendiente("A-001")
        self.assertEqual(self.c.post("/api/llamar", data={"ventanilla": "V-04"}).status_code, 400)
        self.assertEqual(self.c.post("/api/llamar", data={"ventanilla": "V-01"}).status_code, 200)

    def test_no_se_puede_desactivar_una_ventanilla_con_turno_en_curso(self):
        self.pendiente("A-001")
        self.c.post("/api/llamar", data={"ventanilla": "V-04"})
        with self.assertRaises(ventanillas.VentanillaError):
            ventanillas.desactivar_ventanilla(self.db, "V-04")

    def test_una_ventanilla_desactivada_con_turno_en_curso_sigue_visible_en_el_panel(self):
        self.pendiente("A-001")
        self.c.post("/api/llamar", data={"ventanilla": "V-04"})
        self.db["ventanillas"].update_one({"codigo": "V-04"}, {"$set": {"estado": "inactiva"}})
        panel, _ = estado_ventanillas(self.db)
        self.assertIn("V-04", [v["id"] for v in panel])

    def test_la_ventanilla_nueva_libera_su_clave_en_redis(self):
        self.pendiente("A-001")
        self.c.post("/api/llamar", data={"ventanilla": "V-04"})
        cola.liberar_ventanilla_si("V-04", "A-001")
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-04")))


class PruebasDeConcurrenciaConCuatroVentanillas(BaseCatalogo):
    def test_cuatro_ventanillas_a_la_vez_no_repiten_turnos_y_cada_una_atiende_uno(self):
        ventanillas.inicializar_ventanillas_base(self.db)
        self.alta("V-04")
        for n in range(1, 9):
            self.pendiente(f"A-{n:03d}", llegada_ms=n)
        resultados, errores = [], []
        candado = threading.Lock()

        def intentar(v):
            try:
                r = llamar_siguiente_turno(self.db, v)
                with candado:
                    resultados.append((v, r["codigo"]))
            except LlamadoError as e:                    # la 2.ª llamada de una ventanilla ocupada se rechaza (409)
                with candado:
                    errores.append((v, e.status))

        hilos = [threading.Thread(target=intentar, args=(v,)) for v in ("V-01", "V-02", "V-03", "V-04") * 2]
        [h.start() for h in hilos]
        [h.join() for h in hilos]

        codigos = [c for _, c in resultados]
        self.assertEqual(len(codigos), len(set(codigos)), "turno asignado a dos ventanillas")
        self.assertEqual(sorted(v for v, _ in resultados), ["V-01", "V-02", "V-03", "V-04"])
        self.assertEqual({s for _, s in errores}, {409})
        for v, codigo in resultados:
            self.assertEqual(self.redis.get(clave_ventanilla_actual(v)), codigo)
            self.assertEqual(self.db["turnos"].find_one({"codigo": codigo})["ventanilla"], v)
        self.assertEqual(cola.tamano_cola(), 4)


if __name__ == "__main__":
    unittest.main()
