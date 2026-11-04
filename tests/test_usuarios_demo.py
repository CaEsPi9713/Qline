"""Script de usuarios de demostración: crea los tres roles sin guardar contraseñas y sin pisar cuentas ajenas."""
import contextlib
import io
import os
import unittest
from unittest import mock

try:
    import mongomock
    HAY_DEPENDENCIAS = True
except ImportError:           # pragma: no cover
    HAY_DEPENDENCIAS = False

if HAY_DEPENDENCIAS:
    from app import asignaciones, auth, ventanillas
    from app.constantes import VENTANILLAS
    from scripts import crear_usuarios_demo as demo


@unittest.skipUnless(HAY_DEPENDENCIAS, "falta mongomock")
class PruebasDeUsuariosDeDemo(unittest.TestCase):
    def setUp(self):
        self.db = mongomock.MongoClient()["grupo2_db"]
        parche = mock.patch.dict(os.environ, {"SECRETO_SESION": "secreto-de-pruebas-de-demo"})
        parche.start()
        self.addCleanup(parche.stop)
        os.environ.pop("QLINE_DEMO_CLAVE", None)
        auth._con_indice.clear()
        ventanillas._ULTIMAS_CONOCIDAS = tuple(VENTANILLAS)

    def ejecutar(self, *args, entorno=None):
        salida = io.StringIO()
        with mock.patch.dict(os.environ, entorno or {}), contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
            codigo = demo.main(list(args), db=self.db)
        return codigo, salida.getvalue()

    def doc(self, usuario):
        return self.db["usuarios"].find_one({"usuario": usuario})

    def test_crea_los_tres_roles_activos_y_con_nombres_validos(self):
        codigo, _ = self.ejecutar()
        self.assertEqual(codigo, 0)
        roles = {u: self.doc(u)["rol"] for u in ("administrador", "supervisor", "operador")}
        self.assertEqual(roles, {"administrador": "administrador", "supervisor": "supervisor", "operador": "operador"})
        for usuario in roles:
            self.assertEqual(self.doc(usuario)["estado"], "activo")
            self.assertTrue(auth.PATRON_USUARIO.fullmatch(usuario))

    def test_el_operador_queda_con_su_ventanilla(self):
        self.ejecutar()
        self.assertEqual(asignaciones.ventanilla_de(self.db, "operador"), "V-01")
        self.assertIsNone(asignaciones.ventanilla_de(self.db, "supervisor"))

    def test_se_puede_elegir_otra_ventanilla_o_ninguna(self):
        self.ejecutar("--ventanilla", "V-02")
        self.assertEqual(asignaciones.ventanilla_de(self.db, "operador"), "V-02")
        self.setUp()
        self.ejecutar("--sin-asignar")
        self.assertIsNone(asignaciones.ventanilla_de(self.db, "operador"))

    def test_una_ventanilla_inexistente_se_avisa_pero_los_usuarios_se_crean(self):
        codigo, salida = self.ejecutar("--ventanilla", "V-99")
        self.assertEqual(codigo, 1)
        self.assertIn("sin ventanilla", salida)
        self.assertIsNotNone(self.doc("operador"))

    def test_las_contrasenas_son_distintas_cumplen_la_politica_y_permiten_ingresar(self):
        resultados = demo.preparar(self.db)
        claves = [f["clave"] for f in resultados]
        self.assertEqual(len(set(claves)), 3)
        for f in resultados:
            auth.validar_clave(f["clave"], f["usuario"])
            self.assertEqual(auth.autenticar(self.db, f["usuario"], f["clave"])["rol"], f["rol"])
            self.assertFalse(set(f["clave"]) & set("0O1lI"))                    # sin caracteres que se confunden

    def test_solo_se_guarda_el_hash_y_las_claves_se_muestran_una_vez(self):
        _, salida = self.ejecutar()
        claves_impresas = [l.split()[-1] for l in salida.splitlines() if l.strip().startswith(("administrador", "supervisor", "operador"))]
        self.assertEqual(len(claves_impresas), 3)
        for usuario, clave in zip(("administrador", "supervisor", "operador"), claves_impresas):
            guardado = self.doc(usuario)
            self.assertTrue(guardado["hash"].startswith("scrypt$"))
            self.assertNotIn(clave, str(guardado))
            self.assertEqual(salida.count(clave), 1)
        self.assertIn("no se vuelven a mostrar", salida)

    def test_es_idempotente_y_no_toca_lo_que_ya_existe(self):
        demo.preparar(self.db)
        hashes = {u: self.doc(u)["hash"] for u in ("administrador", "supervisor", "operador")}
        codigo, salida = self.ejecutar()
        self.assertEqual(codigo, 0)
        self.assertEqual(self.db["usuarios"].count_documents({}), 3)
        self.assertEqual({u: self.doc(u)["hash"] for u in hashes}, hashes)
        self.assertEqual(salida.count("(sin cambios)"), 3)

    def test_restablecer_pone_claves_nuevas_y_cierra_las_sesiones(self):
        primeras = {f["usuario"]: f["clave"] for f in demo.preparar(self.db)}
        version = self.doc("operador")["version_sesion"]
        nuevas = {f["usuario"]: f["clave"] for f in demo.preparar(self.db, restablecer=True)}
        self.assertNotEqual(primeras, nuevas)
        self.assertGreater(self.doc("operador")["version_sesion"], version)
        with self.assertRaises(auth.AuthError):
            auth.autenticar(self.db, "operador", primeras["operador"])
        self.assertEqual(auth.autenticar(self.db, "operador", nuevas["operador"])["usuario"], "operador")

    def test_una_clave_propia_por_entorno_vale_para_los_tres(self):
        codigo, _ = self.ejecutar(entorno={"QLINE_DEMO_CLAVE": "Clave-de-demo-1"})
        self.assertEqual(codigo, 0)
        for usuario in ("administrador", "supervisor", "operador"):
            self.assertEqual(auth.autenticar(self.db, usuario, "Clave-de-demo-1")["usuario"], usuario)

    def test_una_clave_debil_por_entorno_se_rechaza_sin_crear_nada(self):
        codigo, salida = self.ejecutar(entorno={"QLINE_DEMO_CLAVE": "corta"})
        self.assertEqual(codigo, 1)
        self.assertIn("ERROR", salida)
        self.assertEqual(self.db["usuarios"].count_documents({}), 0)

    def test_no_pisa_una_cuenta_con_ese_nombre_pero_otro_rol_o_deshabilitada(self):
        auth.crear_usuario(self.db, "supervisor", "Clave-segura-1", rol="operador", estado="activo")
        auth.crear_usuario(self.db, "operador", "Clave-segura-1", rol="operador", estado="deshabilitado")
        hashes = {u: self.doc(u)["hash"] for u in ("supervisor", "operador")}
        resultados = demo.preparar(self.db, restablecer=True)
        omitidos = {f["usuario"] for f in resultados if f["accion"] == "omitido"}
        self.assertEqual(omitidos, {"supervisor", "operador"})
        self.assertEqual({u: self.doc(u)["hash"] for u in hashes}, hashes)
        self.assertEqual(self.doc("supervisor")["rol"], "operador")
        self.assertEqual(self.doc("operador")["estado"], "deshabilitado")

    def test_conserva_la_ventanilla_que_ya_tenia_el_operador(self):
        demo.preparar(self.db, ventanilla="V-03")
        resultados = demo.preparar(self.db, ventanilla="V-01")
        self.assertEqual(asignaciones.ventanilla_de(self.db, "operador"), "V-03")
        self.assertIn("conserva", next(f for f in resultados if f["usuario"] == "operador")["aviso"])

    def test_no_escribe_archivos(self):
        import tempfile
        with tempfile.TemporaryDirectory() as t:
            antes = os.getcwd()
            os.chdir(t)
            try:
                self.ejecutar()
                self.assertEqual(os.listdir(t), [])
            finally:
                os.chdir(antes)


if __name__ == "__main__":
    unittest.main()
