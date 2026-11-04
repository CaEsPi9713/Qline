"""TT-014 / TT-015 · la medición de índices solo informa lo que midió."""
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from app import mediciones_indices as mi
from app.dashboard import calcular_metricas_dashboard, pipeline_conteo_estados, pipeline_tiempos_sla

try:
    import mongomock
    HAY_MONGOMOCK = True
except Exception:                      # pragma: no cover
    HAY_MONGOMOCK = False


def explain(*etapas, docs=1, claves=1, devueltos=1):
    """Arma un explain("executionStats") con las etapas dadas, de la raíz a la hoja."""
    plan = None
    for nombre in reversed(etapas):
        plan = {"stage": nombre, **({"inputStage": plan} if plan else {})}
    return {"executionStats": {"executionStages": plan, "totalDocsExamined": docs, "totalKeysExamined": claves,
                               "nReturned": devueltos, "executionTimeMillis": 0}}


def consulta(clave="codigo", indice=("IXSCAN",), scan=("COLLSCAN",), **kw):
    q = mi.Consulta(clave, "Consulta de prueba", "idx_x", "find(...)")
    q.con_indice = mi.analizar_explain(explain(*indice, docs=kw.get("d_idx", 1), claves=kw.get("d_idx", 1)))
    q.sin_indice = mi.analizar_explain(explain(*scan, docs=kw.get("d_scan", 554), claves=0))
    q.lat_indice, q.lat_scan = mi.resumen([0.2, 0.21, 0.2]), mi.resumen([0.6, 0.62, 0.61])
    return q


class PruebasExplain(unittest.TestCase):
    def test_camino_de_etapas_de_la_raiz_a_la_hoja(self):
        self.assertEqual(mi.camino_etapas(explain("LIMIT", "FETCH", "IXSCAN")["executionStats"]["executionStages"]),
                         ["LIMIT", "FETCH", "IXSCAN"])
        self.assertEqual(mi.camino_etapas({}), [])

    def test_analizar_explain(self):
        a = mi.analizar_explain(explain("SORT", "COLLSCAN", docs=554, claves=0, devueltos=20))
        self.assertEqual(a["plan"], "SORT -> COLLSCAN")
        self.assertTrue(a["ordena_en_memoria"] and a["recorrido_completo"] and not a["usa_indice"])
        self.assertEqual((a["docs_examinados"], a["claves_examinadas"], a["devueltos"]), (554, 0, 20))
        b = mi.analizar_explain(explain("FETCH", "IXSCAN"))
        self.assertTrue(b["usa_indice"] and not b["ordena_en_memoria"])

    def test_cae_al_plan_ganador_si_no_hay_executionstages(self):
        e = {"queryPlanner": {"winningPlan": {"stage": "FETCH", "inputStage": {"stage": "IXSCAN"}}}}
        self.assertEqual(mi.analizar_explain(e)["plan"], "FETCH -> IXSCAN")


class PruebasInforme(unittest.TestCase):
    def informe(self, consultas):
        pipelines = [mi.Pipeline("Conteo por estados", "$match -> $group", mi.resumen([0.3, 0.31, 0.3]))]
        return mi.generar_informe({"version": "7.0.45", "documentos": 554, "ejecuciones": 3, "operaciones": 50},
                                  consultas, pipelines)

    def test_el_informe_muestra_lo_medido(self):
        md = self.informe([consulta()])
        for texto in ("7.0.45", "554", "IXSCAN", "COLLSCAN", "TT-014", "TT-015", "Mediana (ms)", "3 ejecuciones"):
            self.assertIn(texto, md)
        self.assertIn("Todas las consultas medidas usaron su índice", md)
        self.assertNotIn("SIMULADO", md)

    def test_si_el_plan_no_usa_el_indice_el_informe_lo_dice(self):
        md = self.informe([consulta(indice=("COLLSCAN",))])
        self.assertIn("no usa el índice", md)
        self.assertIn("estas consultas no usaron un índice", md)
        self.assertNotIn("Todas las consultas medidas usaron su índice", md)

    def test_el_orden_en_memoria_se_informa_segun_el_plan_y_no_por_texto_fijo(self):
        sin_sort = self.informe([consulta("historial", indice=("LIMIT", "FETCH", "IXSCAN"), scan=("SORT", "COLLSCAN"))])
        self.assertIn("no ordena en memoria", sin_sort)
        self.assertIn("el recorrido completo ordena en memoria", sin_sort)
        con_sort = self.informe([consulta("historial", indice=("SORT", "FETCH", "IXSCAN"), scan=("SORT", "COLLSCAN"))])
        self.assertIn("**ordena en memoria**", con_sort)

    def test_los_documentos_examinados_salen_del_explain(self):
        md = self.informe([consulta(d_idx=3, d_scan=777)])
        self.assertIn("examina 3 documento(s)", md)
        self.assertIn("sin índice 777", md)
        self.assertNotIn("exactamente 1", md)


class _Col:
    def __init__(self, documentos=100, indices=()):
        self._n, self._i = documentos, indices

    def count_documents(self, _):
        return self._n

    def index_information(self):
        return {n: {} for n in self._i}


class _Db:
    def __init__(self, col, falla=False):
        self.col, self.falla = col, falla
        self.client = self

    def command(self, _):
        if self.falla:
            raise ConnectionError("sin conexión")

    def server_info(self):
        return {"version": "7.0.45"}

    def __getitem__(self, _):
        return self.col


class PruebasErrores(unittest.TestCase):
    def test_menos_de_tres_ejecuciones(self):
        with self.assertRaises(mi.MedicionError):
            mi.ejecutar(_Db(_Col()), ejecuciones=2)

    def test_sin_conexion_no_inventa_resultados(self):
        with self.assertRaises(mi.MedicionError) as e:
            mi.ejecutar(_Db(_Col(), falla=True))
        self.assertIn("No se pudo conectar", str(e.exception))

    def test_pocos_documentos(self):
        with self.assertRaises(mi.MedicionError) as e:
            mi.ejecutar(_Db(_Col(documentos=10)))
        self.assertIn("generar_datos_sinteticos", str(e.exception))

    def test_faltan_indices_y_dice_como_crearlos(self):
        with self.assertRaises(mi.MedicionError) as e:
            mi.ejecutar(_Db(_Col(indices=["idx_turnos_codigo_unico"])))
        self.assertIn("idx_turnos_qr_token_unico", str(e.exception))
        self.assertIn("create_index", str(e.exception))

    def test_el_script_sale_con_1_y_sin_informe_si_no_hay_conexion(self):
        import scripts.medir_indices_mongo as script
        ruta = Path(tempfile.mkdtemp()) / "i.md"
        with patch("app.main.get_db", return_value=_Db(_Col(), falla=True)), \
                redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
            codigo = script.main(["--informe", str(ruta)])
        self.assertEqual(codigo, 1)
        self.assertFalse(ruta.exists())
        self.assertIn("No se pudo conectar", err.getvalue())

    def test_indices_requeridos_existen_en_el_esquema(self):
        from app.turnos_schema import INDICES_TURNOS
        definidos = {i["options"]["name"] for i in INDICES_TURNOS}
        self.assertTrue(set(mi.INDICES_REQUERIDOS.values()) <= definidos)


class PruebasFiltroQr(unittest.TestCase):
    """Medido en el servidor: con {"qr_token": t} a secas el índice parcial no se usaba (COLLSCAN)."""

    def test_el_filtro_incluye_el_tipo_del_indice_parcial(self):
        from app.consulta_qr import filtro_por_token
        from app.turnos_schema import INDICES_TURNOS
        f = filtro_por_token("abc")
        self.assertEqual(f, {"qr_token": {"$eq": "abc", "$type": "string"}})
        idx = next(i for i in INDICES_TURNOS if i["options"]["name"] == "idx_turnos_qr_token_unico")
        condicion_indice = idx["options"]["partialFilterExpression"]["qr_token"]["$type"]
        self.assertEqual(f["qr_token"]["$type"], condicion_indice)      # la consulta repite la condición del índice

    @unittest.skipUnless(HAY_MONGOMOCK, "falta mongomock")
    def test_la_consulta_por_token_sigue_encontrando_el_turno(self):
        from app.consulta_qr import filtro_por_token
        col = mongomock.MongoClient()["g"]["turnos"]
        col.insert_many([{"codigo": "A-001", "qr_token": "t-1"}, {"codigo": "A-002", "qr_token": None},
                         {"codigo": "A-003"}])
        self.assertEqual(col.find_one(filtro_por_token("t-1"))["codigo"], "A-001")
        self.assertIsNone(col.find_one(filtro_por_token("otro")))

    @unittest.skipUnless(HAY_MONGOMOCK, "falta mongomock")
    def test_el_turno_temporal_solo_existe_durante_la_consulta_qr(self):
        """Las consultas por código, historial y barrido no deben ver el documento temporal."""
        col = mongomock.MongoClient()["g"]["turnos"]
        col.insert_one({"codigo": "A-001", "servicio": "atencion_general"})
        vistos = []
        original = mi._medir

        def espia(c, q, construir, ejecuciones, operaciones):
            vistos.append((q.clave, c.count_documents({})))
            q.con_indice = q.sin_indice = mi.analizar_explain(explain("IXSCAN"))
            q.lat_indice = q.lat_scan = mi.resumen([0.1, 0.1, 0.1])
            return q

        mi._medir = espia
        try:
            mi.medir_consultas(col, 3, 5)
        finally:
            mi._medir = original
        por_clave = dict(vistos)
        self.assertEqual(por_clave["codigo"], 1)
        self.assertEqual(por_clave["historial"], 1)
        self.assertEqual(por_clave["barrido"], 1)
        self.assertEqual(por_clave["qr"], 2)                      # aquí sí está el temporal
        self.assertEqual(col.count_documents({}), 1)              # y se eliminó


@unittest.skipUnless(HAY_MONGOMOCK, "falta mongomock")
class PruebasPipelines(unittest.TestCase):
    def test_los_pipelines_medidos_son_los_del_dashboard_y_se_ejecutan(self):
        col = mongomock.MongoClient()["g"]["turnos"]
        col.insert_many([
            {"codigo": "A-001", "servicio": "atencion_general", "estado": "atendido",
             "metricas": {"espera_seg": 100, "atencion_seg": 50}},
            {"codigo": "A-002", "servicio": "atencion_general", "estado": "abandonado",
             "metricas": {"espera_seg": 400, "atencion_seg": None}},
        ])
        medidos = mi.medir_pipelines(col, 3, 5)
        self.assertEqual([p.nombre for p in medidos],
                         ["Conteo por estados", "Tiempos promedio y cumplimiento de SLA"])
        self.assertTrue(all(p.lat["ejecuciones"] == 3 for p in medidos))
        db = mongomock.MongoClient()["g2"]
        db["turnos"].insert_many(list(col.find({}, {"_id": 0})))
        totales = calcular_metricas_dashboard(db)["totales"]
        self.assertEqual((totales["atendidos"], totales["abandonados"]), (1, 1))

    def test_el_pipeline_de_sla_usa_el_umbral_indicado(self):
        self.assertEqual(pipeline_tiempos_sla(120)[1]["$group"]["cumplen_sla"]["$sum"]["$cond"][0]["$and"][1]["$lte"][1], 120)
        self.assertEqual(pipeline_conteo_estados()[0]["$match"], {"servicio": "atencion_general"})


if __name__ == "__main__":
    unittest.main()
