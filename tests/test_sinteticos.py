"""TT-005 · Datos sintéticos: reproducibilidad, contrato y carga sin duplicados."""

import copy
import unittest
from datetime import date

from app.constantes import ESTADOS, PRIORIDADES, VENTANILLAS
from scripts.sinteticos import cargador
from scripts.sinteticos.generador import Parametros, generar_turnos
from scripts.sinteticos.serializacion import a_jsonl, desde_jsonl
from scripts.sinteticos.validador import resumen, validar_conjunto, validar_turno


class ColeccionBulk:
    """Colección mínima con upsert por código, bulk_write y delete_many por prefijo."""

    def __init__(self, docs=()):
        self.docs = {d["codigo"]: copy.deepcopy(d) for d in docs}

    def bulk_write(self, operaciones):
        for op in operaciones:
            doc = copy.deepcopy(op._doc)
            self.docs[op._filter["codigo"]] = doc

    def delete_many(self, filtro):
        import re
        patron = re.compile(filtro["codigo"]["$regex"])
        borrar = [c for c in self.docs if patron.match(c)]
        for c in borrar:
            del self.docs[c]

        class R:
            deleted_count = len(borrar)

        return R()


class PruebasGenerador(unittest.TestCase):
    def test_reproducible_con_la_misma_semilla(self):
        self.assertEqual(a_jsonl(generar_turnos()), a_jsonl(generar_turnos()))

    def test_semilla_distinta_cambia_los_datos(self):
        self.assertNotEqual(a_jsonl(generar_turnos(Parametros(semilla=1))),
                            a_jsonl(generar_turnos(Parametros(semilla=2))))

    def test_cumple_el_contrato_y_las_reglas_entre_turnos(self):
        docs = generar_turnos()
        self.assertEqual(validar_conjunto(docs), [])

    def test_por_defecto_no_deja_turnos_activos(self):
        estados = {d["estado"] for d in generar_turnos()}
        self.assertFalse(estados & {"llamado", "en_atencion"})
        self.assertEqual(estados, {"pendiente", "atendido", "abandonado"})

    def test_con_activos_deja_llamado_y_en_atencion_y_sigue_valido(self):
        docs = generar_turnos(Parametros(dejar_turnos_activos=True))
        self.assertEqual({d["estado"] for d in docs}, set(ESTADOS))
        self.assertEqual(validar_conjunto(docs), [])

    def test_pendientes_no_tienen_ventanilla_y_el_resto_si(self):
        for d in generar_turnos():
            self.assertEqual(d["ventanilla"] is None, d["estado"] == "pendiente")

    def test_incluye_estados_y_valores_oficiales(self):
        docs = generar_turnos(Parametros(dejar_turnos_activos=True))
        self.assertEqual({d["estado"] for d in docs}, set(ESTADOS))
        self.assertTrue({d["prioridad"] for d in docs} <= set(PRIORIDADES))
        self.assertTrue({d["ventanilla"] for d in docs if d["ventanilla"]} <= set(VENTANILLAS))
        self.assertEqual({d["servicio"] for d in docs}, {"atencion_general"})

    def test_codigos_unicos_y_serie_sintetica_distinta_de_la_real(self):
        codigos = [d["codigo"] for d in generar_turnos()]
        self.assertEqual(len(codigos), len(set(codigos)))
        self.assertTrue(all(c.startswith("S-") for c in codigos))   # la serie real es A-NNN

    def test_campos_pendientes_son_null(self):
        for d in generar_turnos():
            if d["estado"] == "pendiente":
                self.assertIsNone(d["ventanilla"])
                self.assertIsNone(d["timestamps"]["llamado"])
                self.assertIsNone(d["metricas"]["espera_seg"])

    def test_parametros_invalidos(self):
        for malo in (Parametros(dias=0), Parametros(prefijo_codigo="ab"), Parametros(prob_abandono=2)):
            with self.subTest(parametros=malo):
                with self.assertRaises(ValueError):
                    generar_turnos(malo)

    def test_fecha_fin_fija_no_depende_de_hoy(self):
        docs = generar_turnos(Parametros(dias=1, fecha_fin=date(2026, 10, 16)))
        self.assertTrue(all(d["timestamps"]["creado"].date() == date(2026, 10, 16) for d in docs))

    def test_jsonl_ida_y_vuelta(self):
        docs = generar_turnos(Parametros(dias=1))
        self.assertEqual(desde_jsonl(a_jsonl(docs)), docs)

    def test_resumen(self):
        docs = generar_turnos()
        self.assertEqual(resumen(docs)["total"], len(docs))


class PruebasValidador(unittest.TestCase):
    def setUp(self):
        self.turno = next(d for d in generar_turnos() if d["estado"] == "atendido")

    def test_turno_valido(self):
        self.assertEqual(validar_turno(self.turno), [])

    def test_detecta_datos_invalidos(self):
        casos = {
            "prioridad": ("prioridad", "urgente"),
            "estado": ("estado", "perdido"),
            "ventanilla": ("ventanilla", "V-99"),
            "servicio": ("servicio", "otro"),
            "codigo": ("codigo", "xx"),
        }
        for nombre, (campo, valor) in casos.items():
            with self.subTest(campo=nombre):
                malo = copy.deepcopy(self.turno)
                malo[campo] = valor
                self.assertNotEqual(validar_turno(malo), [])

    def test_detecta_metrica_inconsistente_y_campo_extra(self):
        malo = copy.deepcopy(self.turno)
        malo["metricas"]["atencion_seg"] += 5
        self.assertNotEqual(validar_turno(malo), [])
        extra = copy.deepcopy(self.turno)
        extra["nombre_cliente"] = "no permitido"
        self.assertNotEqual(validar_turno(extra), [])

    def test_detecta_codigos_duplicados(self):
        self.assertNotEqual(validar_conjunto([self.turno, copy.deepcopy(self.turno)]), [])


class PruebasCargador(unittest.TestCase):
    def test_cargar_dos_veces_no_duplica(self):
        docs = generar_turnos(Parametros(dias=1))
        col = ColeccionBulk()
        self.assertEqual(cargador.cargar(col, docs), len(docs))
        cargador.cargar(col, docs)
        self.assertEqual(len(col.docs), len(docs))

    def test_limpiar_solo_borra_la_serie_sintetica(self):
        docs = generar_turnos(Parametros(dias=1))
        col = ColeccionBulk([{"codigo": "A-001"}, {"codigo": "A-016"}])
        cargador.cargar(col, docs)
        borrados = cargador.limpiar(col, "S")
        self.assertEqual(borrados, len(docs))
        self.assertEqual(set(col.docs), {"A-001", "A-016"})

    def test_prefijo_invalido_en_limpiar(self):
        with self.assertRaises(cargador.ErrorCarga):
            cargador.limpiar(ColeccionBulk(), ".*")

    def test_falta_configuracion(self):
        import os
        guardado = {k: os.environ.pop(k) for k in ("MONGO_USER", "MONGO_PASS", "MONGO_DB") if k in os.environ}
        original = cargador.load_dotenv
        cargador.load_dotenv = lambda *a, **k: None
        try:
            with self.assertRaises(cargador.ErrorCarga):
                cargador.conectar()
        finally:
            cargador.load_dotenv = original
            os.environ.update(guardado)


if __name__ == "__main__":
    unittest.main()
