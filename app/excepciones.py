"""Errores de negocio controlados del ciclo de atención (HU-006 y HU-007).

Cada excepción lleva el código HTTP con el que el router la traduce,
para que ningún caso termine en un error 500 sin controlar.
"""


class ErrorAtencion(Exception):
    """Base de los errores controlados del ciclo de atención."""

    status_code = 400
    mensaje = "Error de atención"

    def __init__(self, mensaje: str | None = None):
        self.mensaje = mensaje or self.mensaje
        super().__init__(self.mensaje)


class DatosInvalidos(ErrorAtencion):
    status_code = 422
    mensaje = "Datos de entrada inválidos"


class TurnoNoEncontrado(ErrorAtencion):
    status_code = 404
    mensaje = "Turno no encontrado"


class TransicionNoPermitida(ErrorAtencion):
    status_code = 409
    mensaje = "El turno no está en estado llamado"


class VentanillaNoCoincide(ErrorAtencion):
    status_code = 409
    mensaje = "El turno fue llamado por otra ventanilla"


class TurnoInconsistente(ErrorAtencion):
    status_code = 409
    mensaje = "El turno está en un estado incoherente con sus datos"


class ServicioNoDisponible(ErrorAtencion):
    status_code = 503
    mensaje = "Servicio temporalmente no disponible"
