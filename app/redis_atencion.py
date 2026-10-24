"""Limpieza del estado en Redis al finalizar la atención de un turno (HU-007).

Mantiene la consistencia MongoDB/Redis (sección 17 del plan): un turno
``atendido`` no puede seguir como actual de una ventanilla ni en la cola.
Solo toca claves grupo2:qline: (ver app.constantes).
"""

from app.constantes import CLAVE_COLA, clave_turno, clave_ventanilla_actual
from app.redis_client import get_redis


def liberar_turno(codigo: str, ventanilla: str) -> None:
    """Libera la ventanilla solo si todavía atiende este turno, y lo saca de la cola."""
    r = get_redis()
    clave = clave_ventanilla_actual(ventanilla)
    if r.get(clave) == codigo:
        r.delete(clave)
    r.zrem(CLAVE_COLA, codigo)
    r.delete(clave_turno(codigo))   # el turno terminó: su estado temporal ya no vence
