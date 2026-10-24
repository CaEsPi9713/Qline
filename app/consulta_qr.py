"""
HU-013: consulta de un turno a partir de su QR.

El QR contiene una URL con un UUID v4 (`qr_token`) generado al emitir el turno
(HU-003). Aquí se valida ese UUID, se busca el turno en MongoDB y se reutiliza
la lógica de HU-002 (`consultar_turno`) para el estado y la posición: no hay una
segunda semántica de consulta.

Es de SOLO LECTURA: no modifica el turno, la cola ni ninguna clave de Redis.
No devuelve el token, el `_id` ni datos personales.

Errores distinguidos (cada uno con su código HTTP):
  400  el UUID no tiene el formato de un UUID v4
  404  ningún turno tiene ese token
  503  MongoDB no está disponible (sin MongoDB no hay estado que mostrar)
Una falla de Redis NO es un error: se muestra el estado de MongoDB con un aviso.
"""
import re

from pymongo.errors import PyMongoError

from app import cola
from app.consultar import ConsultaError, consultar_turno
from app.constantes import ESTADO_LLAMADO

COLECCION = "turnos"

# UUID versión 4: el tercer grupo empieza con 4 y el cuarto con 8, 9, a o b.
PATRON_UUID4 = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z", re.IGNORECASE
)


class QRError(Exception):
    """Error controlado de la consulta por QR; `status` es el código HTTP sugerido."""

    def __init__(self, mensaje: str, status: int = 500):
        super().__init__(mensaje)
        self.status = status


def validar_token(token) -> str:
    """Devuelve el UUID v4 normalizado (minúsculas) o lanza QRError 400."""
    if not isinstance(token, str) or not PATRON_UUID4.fullmatch(token.strip()):
        raise QRError("El enlace no es válido. Escanee de nuevo el código QR de su ticket.", 400)
    return token.strip().lower()


def consultar_por_token(db, token: str) -> dict:
    """Estado y posición del turno asociado al token. Solo lectura."""
    token = validar_token(token)
    try:
        documento = db[COLECCION].find_one({"qr_token": token}, {"_id": 0, "codigo": 1})
    except PyMongoError as exc:
        raise QRError("No es posible consultar el turno en este momento. Intente de nuevo en unos segundos.", 503) from exc
    if documento is None:
        raise QRError("Este código QR no corresponde a ningún turno.", 404)

    try:
        turno = consultar_turno(db, documento["codigo"])
    except ConsultaError as exc:
        if exc.status == 503:
            raise QRError("No es posible consultar el turno en este momento. Intente de nuevo en unos segundos.", 503) from exc
        raise QRError("No se pudo mostrar el estado de este turno.", exc.status) from exc

    turno["segundos_restantes"] = _segundos_restantes(turno)
    return turno


def _segundos_restantes(turno: dict):
    """Segundos que le quedan a un turno llamado antes de considerarse abandonado (mejor esfuerzo)."""
    if turno.get("estado") != ESTADO_LLAMADO:
        return None
    try:
        return cola.segundos_restantes(turno["codigo"])
    except Exception:
        return None
