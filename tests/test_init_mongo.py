"""TT-004 · init_mongo: validador, falta de permiso para collMod y recreación de `turnos`."""

import contextlib
import io
import unittest

from pymongo.errors import DuplicateKeyError, OperationFailure

from app.turnos_schema import COLECCION_TURNOS, INDICES_TURNOS
from scripts import init_mongo


class ColeccionFalsa:
    def __init__(self, db):
        self.db = db
        self.docs = []
        self.indices = []

    def insert_one(self, doc):
        if self.db.validador and doc.get("prioridad") not in ("normal", "preferencial"):
            raise OperationFailure("Document failed validation", code=121)
        if any(d["codigo"] == doc["codigo"] for d in self.docs):
            raise DuplicateKeyError("duplicate key")
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": len(self.docs)})()

    def delete_one(self, filtro):
        for d in self.docs:
            if all(d.get(k) == v for k, v in filtro.items()):
                self.docs.remove(d)
                break

    def delete_many(self, filtro):
        self.docs[:] = [d for d in self.docs if d["codigo"] != filtro["codigo"]]

    def count_documents(self, filtro):
        return len(self.docs)

    def create_index(self, keys, **opciones):
        self.indices.append(opciones.get("name"))


class BaseFalsa:
    """MongoDB mínimo: un validador activo o no, y permiso de collMod configurable."""

    def __init__(self, existe=True, permite_collmod=True, docs=0):
        self.permite_collmod = permite_collmod
        self.validador = False
        self.colecciones = {}
        if existe:
            col = self.colecciones[COLECCION_TURNOS] = ColeccionFalsa(self)
            col.docs = [{"codigo": f"S-{i:03d}", "prioridad": "normal"} for i in range(docs)]

    def __getitem__(self, nombre):
        return self.colecciones[nombre]

    def list_collection_names(self):
        return list(self.colecciones)

    def command(self, comando):
        if not self.permite_collmod:
            raise OperationFailure("not authorized on grupo2_db to execute command { collMod }", code=13)
        self.validador = True

    def create_collection(self, nombre, validator=None, **opciones):
        self.colecciones[nombre] = ColeccionFalsa(self)
        self.validador = validator is not None

    def drop_collection(self, nombre):
        self.colecciones.pop(nombre, None)


def silencio(funcion, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()) as salida:
        resultado = funcion(*args, **kwargs)
    return resultado, salida.getvalue()


class PruebasInitMongo(unittest.TestCase):
    def test_crea_la_coleccion_con_validador_si_no_existe(self):
        db = BaseFalsa(existe=False)
        aplicado, _ = silencio(init_mongo.inicializar_coleccion_turnos, db)
        self.assertTrue(aplicado)
        self.assertTrue(db.validador)
        self.assertEqual(len(db[COLECCION_TURNOS].indices), len(INDICES_TURNOS))

    def test_con_permiso_collmod_aplica_el_validador(self):
        db = BaseFalsa(existe=True, permite_collmod=True)
        aplicado, _ = silencio(init_mongo.inicializar_coleccion_turnos, db)
        self.assertTrue(aplicado)
        self.assertTrue(db.validador)

    def test_sin_permiso_collmod_lo_informa_y_no_aplica_el_validador(self):
        db = BaseFalsa(existe=True, permite_collmod=False)
        aplicado, salida = silencio(init_mongo.inicializar_coleccion_turnos, db)
        self.assertFalse(aplicado)
        self.assertFalse(db.validador)
        self.assertIn("--recrear", salida)
        self.assertEqual(len(db[COLECCION_TURNOS].indices), len(INDICES_TURNOS))   # los índices sí

    def test_verificacion_detecta_que_el_motor_no_valida(self):
        db = BaseFalsa(existe=True, permite_collmod=False)
        ok, _ = silencio(init_mongo.verificar_validador_estricto, db)
        self.assertFalse(ok)

    def test_verificacion_pasa_con_validador_activo(self):
        db = BaseFalsa(existe=False)
        silencio(init_mongo.inicializar_coleccion_turnos, db)
        ok, _ = silencio(init_mongo.verificar_validador_estricto, db)
        self.assertTrue(ok)

    def test_recrear_borra_los_documentos_y_deja_validador_e_indices(self):
        db = BaseFalsa(existe=True, permite_collmod=False, docs=5)
        _, salida = silencio(init_mongo.recrear_coleccion_turnos, db)
        self.assertTrue(db.validador)
        self.assertEqual(db[COLECCION_TURNOS].docs, [])
        self.assertEqual(len(db[COLECCION_TURNOS].indices), len(INDICES_TURNOS))
        self.assertIn("5 documentos", salida)
        ok, _ = silencio(init_mongo.verificar_validador_estricto, db)
        self.assertTrue(ok)

    def test_recrear_sin_confirmar_no_toca_nada(self):
        db = BaseFalsa(existe=True, docs=3)
        original, init_mongo.obtener_cliente_mongo = init_mongo.obtener_cliente_mongo, lambda: self.fail("no debe conectar")
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(init_mongo.main(["--recrear"]), 2)
        finally:
            init_mongo.obtener_cliente_mongo = original
        self.assertEqual(len(db[COLECCION_TURNOS].docs), 3)

    def _main_con(self, db, argumentos):
        original = init_mongo.obtener_cliente_mongo
        init_mongo.obtener_cliente_mongo = lambda: {init_mongo.MONGO_DB: db}
        try:
            return silencio(init_mongo.main, argumentos)
        finally:
            init_mongo.obtener_cliente_mongo = original

    def test_main_termina_con_error_si_el_validador_no_quedo_activo(self):
        db = BaseFalsa(existe=True, permite_collmod=False)
        codigo, salida = self._main_con(db, [])
        self.assertEqual(codigo, 1)
        self.assertIn("INCOMPLETA", salida)
        self.assertNotIn("completada con éxito", salida)

    def test_main_con_recrear_confirmado_termina_bien(self):
        db = BaseFalsa(existe=True, permite_collmod=False, docs=4)
        codigo, salida = self._main_con(db, ["--recrear", "--confirmar"])
        self.assertEqual(codigo, 0)
        self.assertIn("completada con éxito", salida)
        self.assertTrue(db.validador)


if __name__ == "__main__":
    unittest.main()
