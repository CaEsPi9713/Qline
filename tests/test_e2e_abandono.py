"""Integración de punta a punta de HU-008 y HU-012 con el resto del sistema (Seguimiento 3).

Recorre el flujo real por HTTP: emitir -> llamar -> el cliente no se presenta -> barrido -> abandonado,
y comprueba lo que ven el panel, el QR del cliente, la pantalla pública, el canal de eventos,
el historial y el dashboard. El paso del tiempo se simula envejeciendo el llamado en MongoDB y
dejando expirar el Hash de Redis, que es exactamente lo que ocurre a los 180 s.
"""
import io
import os
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.test_ventanilla_unica import HAY_DEPENDENCIAS
from tests.test_eventos_negocio import BaseNegocio

if HAY_DEPENDENCIAS:
    import app.main as main
    from app import integracion_s3 as integ
    from app.constantes import CLAVE_COLA, TTL_ABANDONO_SEG, clave_turno, clave_ventanilla_actual
    from app.panel_atencion import estado_ventanillas
    from app.tiempo_real import hub


@unittest.skipUnless(HAY_DEPENDENCIAS, "faltan fakeredis, mongomock o httpx")
class BaseE2E(BaseNegocio):
    def turnos(self):
        return self.db["turnos"]

    def emitir_con_token(self, prioridad="normal"):
        codigo = self.emitir(prioridad)
        return codigo, self.turnos().find_one({"codigo": codigo})["qr_token"]

    def llamar(self, ventanilla="V-01"):
        return self.c.post("/api/llamar", data={"ventanilla": ventanilla})

    def vencer(self, codigo, seg=TTL_ABANDONO_SEG + 1):
        """Pasan `seg` segundos desde el llamado: el Hash expira en Redis y el llamado queda viejo en MongoDB."""
        llamado = datetime.now(timezone.utc) - timedelta(seconds=seg)
        self.turnos().update_one({"codigo": codigo}, {"$set": {"timestamps.llamado": llamado}})
        self.redis.delete(clave_turno(codigo))
        return llamado

    def barrer(self):
        with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": "1"}):
            return integ.crear_barrido_abandono().ejecutar_una_vez()

    def esperar_hub(self):
        for _ in range(80):
            if hub.suscrito:
                return
            time.sleep(0.05)
        self.fail("el receptor de eventos no se suscribió")


class PruebasFlujoCompleto(BaseE2E):
    def test_un_cliente_que_no_se_presenta_se_abandona_y_todo_lo_refleja(self):
        a, token_a = self.emitir_con_token()
        b = self.emitir()
        self.recibidos()                                                         # vacía los eventos de emisión

        # 1 · Se llama a A-001: ventanilla ocupada, Hash con TTL, visible en pantalla y en el QR
        self.assertEqual(self.llamar().status_code, 200)
        self.assertEqual(self.redis.get(clave_ventanilla_actual("V-01")), a)
        self.assertTrue(0 < self.redis.ttl(clave_turno(a)) <= TTL_ABANDONO_SEG)
        self.assertIn(a, [x["codigo"] for x in self.c.get("/api/llamados").json()["llamados"]])
        qr = self.c.get(f"/api/turnos/qr/{token_a}").json()["turno"]
        self.assertEqual(qr["estado"], "llamado")
        self.assertEqual(qr["ventanilla"], "V-01")

        # 2 · La ventanilla única impide llamar a otro turno mientras A-001 no se resuelva
        segunda = self.llamar()
        self.assertGreaterEqual(segunda.status_code, 400)
        self.assertEqual(self.redis.zrange(CLAVE_COLA, 0, -1), [b])
        self.recibidos()

        # 3 · Antes de los 180 s el barrido no hace nada (Redis manda mientras el Hash viva)
        llamado = datetime.now(timezone.utc) - timedelta(seconds=TTL_ABANDONO_SEG + 1)
        self.turnos().update_one({"codigo": a}, {"$set": {"timestamps.llamado": llamado}})
        res = self.barrer()
        self.assertEqual(res.omitidos_vigentes, [a])
        self.assertEqual(self.turnos().find_one({"codigo": a})["estado"], "llamado")

        # 4 · Pasan los 180 s: el Hash expira y el barrido abandona el turno
        self.redis.delete(clave_turno(a))
        with self.c.websocket_connect(f"/ws/turno/qr/{token_a}") as ws:
            self.assertEqual(ws.receive_json()["tipo"], "conectado")
            self.esperar_hub()
            res = self.barrer()
            self.assertEqual(res.abandonados, [a])
            self.assertTrue(res.ok)
            self.assertEqual(ws.receive_json()["tipo"], "actualizar")            # el QR del cliente se entera al instante

        doc = self.turnos().find_one({"codigo": a})
        self.assertEqual(doc["estado"], "abandonado")
        self.assertEqual(doc["ventanilla"], "V-01")                              # se conserva para el historial
        esperado = llamado + timedelta(seconds=TTL_ABANDONO_SEG)
        self.assertLess(abs((doc["timestamps"]["abandonado"].replace(tzinfo=timezone.utc) - esperado).total_seconds()), 1)

        # 5 · Lo que ve cada parte del sistema
        eventos = [e for e in self.recibidos() if e["tipo"] == "turno_abandonado"]
        self.assertEqual([(e["codigo"], e["estado"], e["ventanilla"]) for e in eventos], [(a, "abandonado", "V-01")])
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))
        ventanillas, _ = estado_ventanillas(self.db)
        self.assertIsNone(next(v for v in ventanillas if v["id"] == "V-01")["turno"])
        self.assertNotIn(a, [x["codigo"] for x in self.c.get("/api/llamados").json()["llamados"]])
        self.assertEqual(self.c.get(f"/api/turnos/qr/{token_a}").json()["turno"]["estado"], "abandonado")
        pagina = self.c.get(f"/turno/qr/{token_a}")
        self.assertEqual(pagina.status_code, 200)
        self.assertIn("no se presentó a tiempo", pagina.text)
        hist = self.c.get("/api/historial?estado=abandonado").json()
        self.assertEqual([t["codigo"] for t in hist["turnos"]], [a])
        self.assertIsNotNone(hist["turnos"][0]["timestamps"]["abandonado"])
        dash = self.c.get("/api/dashboard")
        if dash.status_code == 200:                                              # mongomock no soporta todo $facet/$group
            self.assertEqual(dash.json()["totales"]["abandonados"], 1)

        # 6 · Un turno abandonado no se puede atender y la ventanilla vuelve a servir
        self.assertGreaterEqual(self.c.post("/api/atencion/iniciar", data={"codigo": a, "ventanilla": "V-01"}).status_code, 400)
        self.assertEqual(self.turnos().find_one({"codigo": a})["estado"], "abandonado")
        r = self.llamar()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["codigo"], b)

        # 7 · Repetir el barrido no cambia nada ni vuelve a publicar
        self.recibidos()
        res = self.barrer()
        self.assertEqual(res.abandonados, [])
        self.assertEqual([e for e in self.recibidos() if e["tipo"] == "turno_abandonado"], [])

    def test_el_barrido_automatico_de_la_app_abandona_sin_intervencion(self):
        a = self.emitir()
        self.assertEqual(self.llamar().status_code, 200)
        self.vencer(a)
        with mock.patch.dict(os.environ, {"BARRIDO_ABANDONO": "1", "BARRIDO_INTERVALO_SEG": "0.05"}):
            with self.c:                                                         # arranca el lifespan de la app
                for _ in range(100):
                    if self.turnos().find_one({"codigo": a})["estado"] == "abandonado":
                        break
                    time.sleep(0.05)
        self.assertEqual(self.turnos().find_one({"codigo": a})["estado"], "abandonado")
        self.assertIsNone(self.redis.get(clave_ventanilla_actual("V-01")))

    def test_un_cliente_que_se_presenta_a_tiempo_no_se_abandona(self):
        a = self.emitir()
        self.llamar()
        self.vencer(a)
        self.redis.hset(clave_turno(a), mapping={"estado": "llamado"})            # el Hash sigue vivo
        self.assertEqual(self.barrer().abandonados, [])
        self.assertEqual(self.c.post("/api/atencion/iniciar", data={"codigo": a, "ventanilla": "V-01"}).status_code, 200)
        self.assertEqual(self.turnos().find_one({"codigo": a})["estado"], "en_atencion")

    def test_un_turno_en_atencion_nunca_se_abandona(self):
        a = self.emitir()
        self.llamar()
        self.c.post("/api/atencion/iniciar", data={"codigo": a, "ventanilla": "V-01"})
        self.vencer(a, seg=900)
        self.assertEqual(self.barrer().abandonados, [])
        self.assertEqual(self.turnos().find_one({"codigo": a})["estado"], "en_atencion")


class PruebasRecuperacionDeLaCola(BaseE2E):
    def test_tras_perder_la_cola_se_rehidrata_y_se_atiende_en_orden(self):
        normal1 = self.emitir()
        pref = self.emitir("preferencial")
        normal2 = self.emitir()
        self.redis.delete(CLAVE_COLA)                                            # Redis pierde la cola
        vacia = self.llamar()                                                    # nada que llamar, sin romper
        self.assertEqual((vacia.status_code, vacia.json()["codigo"]), (200, None))

        from scripts import rehidratar_cola
        with redirect_stdout(io.StringIO()):
            self.assertEqual(rehidratar_cola.main(["--aplicar"]), 0)

        self.assertEqual(self.redis.zrange(CLAVE_COLA, 0, -1), [pref, normal1, normal2])
        orden = []
        for v in ("V-01", "V-02", "V-03"):
            r = self.llamar(v)
            self.assertEqual(r.status_code, 200)
            orden.append(r.json()["codigo"])
        self.assertEqual(orden, [pref, normal1, normal2])

    def test_la_rehidratacion_no_trae_de_vuelta_a_los_abandonados(self):
        a = self.emitir()
        b = self.emitir()
        self.llamar()
        self.vencer(a)
        self.barrer()
        self.redis.delete(CLAVE_COLA)
        from scripts import rehidratar_cola
        with redirect_stdout(io.StringIO()):
            rehidratar_cola.main(["--aplicar"])
        self.assertEqual(self.redis.zrange(CLAVE_COLA, 0, -1), [b])


if __name__ == "__main__":
    unittest.main()
