"""El .htaccess deja sin contraseña solo las rutas del cliente (QR) y mantiene protegido todo lo demás.

No ejecuta Apache: lee las reglas `SetEnvIf Request_URI` del archivo y comprueba, con la misma expresión,
qué direcciones quedarían públicas. La verificación real se hace en el servidor (GUION_VERIFICACION_S3.md).
"""
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
UUID = "123e4567-e89b-42d3-a456-426614174000"
BASE = "/proyecto/qline"


def lineas() -> list[str]:
    return [l.strip() for l in (RAIZ / ".htaccess").read_text(encoding="utf-8").splitlines()]


def patrones_publicos() -> list[re.Pattern]:
    encontrados = []
    for l in lineas():
        m = re.fullmatch(r'SetEnvIf Request_URI "(.+)" ACCESO_PUBLICO', l)
        if m:
            encontrados.append(re.compile(m.group(1)))
    return encontrados


def es_publica(ruta: str) -> bool:
    return any(p.search(ruta) for p in patrones_publicos())


class PruebasHtaccess(unittest.TestCase):
    def test_sigue_pidiendo_autenticacion_para_el_resto(self):
        texto = "\n".join(lineas())
        self.assertIn("AuthType Basic", texto)
        self.assertIn("Require valid-user", texto)
        self.assertIn("Require env ACCESO_PUBLICO", texto)
        self.assertIn("<RequireAny>", texto)

    def test_las_rutas_del_cliente_son_publicas(self):
        for ruta in (f"{BASE}/turno/qr/{UUID}", f"{BASE}/api/turnos/qr/{UUID}", f"{BASE}/ws/turno/qr/{UUID}",
                     f"/turno/qr/{UUID}", f"{BASE}/static/style.css"):
            self.assertTrue(es_publica(ruta), ruta)

    def test_todo_lo_demas_sigue_protegido(self):
        for ruta in (f"{BASE}/", f"{BASE}/panel", f"{BASE}/cola", f"{BASE}/historial", f"{BASE}/dashboard",
                     f"{BASE}/quiosco", f"{BASE}/pantalla", f"{BASE}/api/llamados", f"{BASE}/emitir",
                     f"{BASE}/api/llamar", f"{BASE}/api/turnos/A-001", f"{BASE}/api/turnos/emitir",
                     f"{BASE}/api/historial/descargar", f"{BASE}/api/dashboard/descargar",
                     f"{BASE}/ws/eventos", f"{BASE}/ws-prueba", f"{BASE}/redis/estado",
                     f"{BASE}/insertar", f"{BASE}/eliminar", f"{BASE}/crear_coleccion", f"{BASE}/demo"):
            self.assertFalse(es_publica(ruta), ruta)

    def test_el_token_debe_tener_forma_de_uuid(self):
        for ruta in (f"{BASE}/turno/qr/basura", f"{BASE}/turno/qr/", f"{BASE}/turno/qr/{UUID[:-1]}",
                     f"{BASE}/turno/qr/{UUID}0", f"{BASE}/api/turnos/qr/{UUID}/extra",
                     f"{BASE}/turno/qr/{UUID}/../../panel"):
            self.assertFalse(es_publica(ruta), ruta)

    def test_la_consulta_no_publica_otros_turnos_ni_la_pantalla(self):
        self.assertFalse(es_publica(f"{BASE}/turno/A-001"))
        self.assertFalse(es_publica(f"{BASE}/consultar"))

    def test_las_reglas_de_reenvio_y_websocket_se_conservan(self):
        texto = "\n".join(lineas())
        self.assertIn("RewriteEngine On", texto)
        self.assertIn("RewriteCond %{HTTP:Upgrade} =websocket [NC]", texto)
        orden = [i for i, l in enumerate(lineas()) if l.startswith("RewriteRule")]
        self.assertEqual(len(orden), 3)
        self.assertIn("ws://127.0.0.1:18002", lineas()[orden[0]])       # el WebSocket va antes que las reglas HTTP

    def test_solo_ascii_y_sin_directivas_inesperadas(self):
        datos = (RAIZ / ".htaccess").read_bytes()
        self.assertTrue(all(b < 128 for b in datos), "el .htaccess debe ser ASCII")
        self.assertEqual(len(patrones_publicos()), 2)


if __name__ == "__main__":
    unittest.main()
