"""TT-019 (módulos de Alessandro): casos normal, datos inválidos y Redis caído, y el programa que los prueba.

Requiere fakeredis, mongomock y httpx; si faltan, las pruebas se omiten.
"""

import unittest
import uuid
from datetime import datetime, timezone

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS, BaseRedisMongo

if HAY_DEPENDENCIAS:
    from fastapi.testclient import TestClient
    from redis.exceptions import ConnectionError as RedisConexion

    import app.main as main
    import app.redis_client as redis_client
    import scripts.probar_fallos_redis as pf


class RedisCaido:
    """Sustituto de Redis que no responde: cualquier operación lanza ConnectionError."""

    def __getattr__(self, nombre):
        def fallar(*a, **k):
            raise RedisConexion("Redis no responde (simulado)")
        return fallar


class BaseFallos(BaseRedisMongo):
    def setUp(self):
        super().setUp()
        self.cliente = pf.ClientePrueba(TestClient(main.app))
        # El Redis simulado no implementa INFO (versión): se sustituye solo el estado "normal".
        self._verificar_orig = main.verificar_redis
        main.verificar_redis = lambda: {"ok": True, "host": "127.0.0.1", "port": 6379, "version": "simulado"}

    def tearDown(self):
        main.verificar_redis = self._verificar_orig
        super().tearDown()

    def fallos(self, resultados):
        return [x for x in resultados if not x["ok"]]


class PruebasCasosNormalesEInvalidos(BaseFallos):
    def test_caso_normal(self):
        resultados = pf.ejecutar(self.cliente, pf.casos_normales())
        self.assertEqual(self.fallos(resultados), [])
        self.assertEqual(len(resultados), len(pf.casos_normales()))

    def test_datos_invalidos_responden_con_el_codigo_esperado_y_nunca_500(self):
        resultados = pf.ejecutar(self.cliente, pf.casos_datos_invalidos())
        self.assertEqual(self.fallos(resultados), [])
        self.assertNotIn(500, [x["estado"] for x in resultados])

    def test_los_datos_invalidos_no_crean_ni_modifican_nada(self):
        antes = (self.db["turnos"].count_documents({}), self.redis.keys("*"))
        pf.ejecutar(self.cliente, pf.casos_datos_invalidos())
        self.assertEqual((self.db["turnos"].count_documents({}), self.redis.keys("*")), antes)

    def test_se_cubren_los_casos_exigidos_por_el_plan(self):
        """Sección 18.4: prioridad inválida, turno inexistente, transición inválida en las rutas propias."""
        nombres = " ".join(c[0] for c in pf.casos_datos_invalidos()).lower()
        for esperado in ("prioridad inválida", "ventanilla inexistente", "uuid", "inexistente", "inyección"):
            self.assertIn(esperado, nombres)


class PruebasRedisCaido(BaseFallos):
    def setUp(self):
        super().setUp()
        self.token = str(uuid.uuid4())
        ahora = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
        self.db["turnos"].insert_one({
            "codigo": "A-9998", "qr_token": self.token, "servicio": "atencion_general", "prioridad": "normal",
            "estado": "pendiente", "ventanilla": None, "operador": None,
            "timestamps": {"creado": ahora, "llamado": None, "inicio_atencion": None, "finalizado": None, "abandonado": None},
            "metricas": {"espera_seg": None, "atencion_seg": None}})
        redis_client._client = RedisCaido()            # tearDown restaura el cliente original
        main.verificar_redis = self._verificar_orig    # aquí se usa la comprobación real: debe informar ok=false

    def test_cada_ruta_responde_de_forma_controlada_con_redis_caido(self):
        resultados = pf.ejecutar(self.cliente, pf.casos_redis_caido(self.token))
        self.assertEqual(self.fallos(resultados), [], resultados)
        self.assertNotIn(500, [x["estado"] for x in resultados])

    def test_la_consulta_por_qr_sigue_mostrando_el_estado_de_mongodb(self):
        estado, texto, _ = self.cliente.pedir("GET", f"/api/turnos/qr/{self.token}")
        self.assertEqual(estado, 200)
        turno = pf._json(texto)["turno"]
        self.assertEqual(turno["estado"], "pendiente")
        self.assertIn("posición", turno["aviso"])

    def test_emitir_con_redis_caido_no_deja_un_turno_a_medias(self):
        antes = self.db["turnos"].count_documents({})
        estado, _, _ = self.cliente.pedir("POST", "/api/turnos/emitir", {"prioridad": "normal"})
        self.assertEqual(estado, 503)
        self.assertEqual(self.db["turnos"].count_documents({}), antes)

    def test_llamar_con_redis_caido_no_cambia_ningun_turno(self):
        estado, _, _ = self.cliente.pedir("POST", "/api/llamar", {"ventanilla": "V-01"})
        self.assertEqual(estado, 503)
        self.assertEqual(self.db["turnos"].find_one({"codigo": "A-9998"})["estado"], "pendiente")


class PruebasFallarRapido(BaseFallos):
    """Con Redis caído, una página no debe repetir el intento fallido por cada ventanilla."""

    def _contar_intentos(self, ruta):
        intentos = []

        class Contador(RedisCaido):
            def __getattr__(self, nombre):
                def fallar(*a, **k):
                    intentos.append(nombre)
                    raise RedisConexion("Redis no responde (simulado)")
                return fallar

        redis_client._client = Contador()
        self.cliente.pedir("GET", ruta)
        return intentos

    def test_la_cola_consulta_redis_una_sola_vez_cuando_no_responde(self):
        self.assertEqual(len(self._contar_intentos("/cola")), 1)

    def test_el_panel_consulta_redis_una_sola_vez_cuando_no_responde(self):
        self.assertEqual(len(self._contar_intentos("/panel")), 1)

    def test_el_panel_avisa_una_sola_vez_que_redis_no_responde(self):
        redis_client._client = RedisCaido()
        _, texto, _ = self.cliente.pedir("GET", "/panel")
        self.assertEqual(texto.count("Redis no disponible"), 1)

    def test_con_redis_funcionando_el_panel_sigue_consultandolo_por_ventanilla(self):
        intentos = []
        original = self.redis.get
        self.redis.get = lambda *a, **k: (intentos.append(1), original(*a, **k))[1]
        self.cliente.pedir("GET", "/panel")
        self.assertEqual(len(intentos), 3)                          # una por ventanilla


class PruebasEjecutorEInforme(BaseFallos):
    def test_un_500_nunca_cuenta_como_correcto(self):
        class Cliente500:
            def pedir(self, metodo, ruta, datos=None):
                return 500, "Traceback", 3.0
        resultados = pf.ejecutar(Cliente500(), [("x", "GET", "/x", None, {200, 500}, None, "200")])
        self.assertFalse(resultados[0]["ok"])

    def test_un_estado_distinto_del_esperado_es_una_falla(self):
        resultados = pf.ejecutar(self.cliente, [("x", "GET", "/redis/estado", None, {404}, None, "404")])
        self.assertFalse(resultados[0]["ok"])

    def test_el_informe_resume_lo_ejecutado_y_cuenta_los_500(self):
        resultados = pf.ejecutar(self.cliente, pf.casos_normales())
        texto = pf.generar_informe({"fecha": "x", "python": "3.12", "sistema": "Linux", "url": "http://127.0.0.1:18002",
                                    "url_sin_redis": "no ejecutada"}, [("1. Caso normal", "explicación", resultados)])
        self.assertIn("**OK**", texto)
        self.assertIn("**0 respuestas 500**", texto)
        self.assertIn("1. Caso normal", texto)

    def test_el_informe_marca_la_falla(self):
        resultados = pf.ejecutar(self.cliente, [("x", "GET", "/redis/estado", None, {404}, None, "404")])
        texto = pf.generar_informe({"fecha": "x", "python": "x", "sistema": "x", "url": "x", "url_sin_redis": "x"},
                                   [("1", "e", resultados)])
        self.assertIn("**FALLA**", texto)

    def test_si_la_app_no_responde_el_programa_lo_dice_y_no_escribe_informe(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "fallos.md"
            codigo = pf.main(["--url", "http://127.0.0.1:1", "--informe", str(ruta)])
            self.assertEqual(codigo, 1)
            self.assertFalse(ruta.exists())


if __name__ == "__main__":
    unittest.main()
