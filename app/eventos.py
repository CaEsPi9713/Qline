"""
Eventos de cambio de estado de los turnos (TT-013, lado publicación).

Cada transición relevante se publica en el canal Redis Pub/Sub
`grupo2:qline:eventos` como un JSON pequeño. Las vistas en vivo (pantalla
pública, consulta por QR) lo reciben a través de app.tiempo_real.

Reglas:
- La publicación es de MEJOR ESFUERZO: si Redis falla, la operación de negocio
  ya hecha (emitir, llamar, iniciar, finalizar) no se deshace ni se rompe.
- El mensaje no contiene datos personales ni credenciales: solo código, estado,
  ventanilla, prioridad y la hora.
"""
import json
import logging
from datetime import datetime, timezone

from redis.exceptions import RedisError

from app.constantes import CLAVE_EVENTOS
from app.redis_client import get_redis

log = logging.getLogger("qline.eventos")

# Tipos de evento (contrato con la pantalla pública y la consulta por QR)
TURNO_EMITIDO = "turno_emitido"
TURNO_LLAMADO = "turno_llamado"
ATENCION_INICIADA = "atencion_iniciada"
ATENCION_FINALIZADA = "atencion_finalizada"
TURNO_ABANDONADO = "turno_abandonado"
PRUEBA = "prueba"   # solo para verificar el canal (/ws-prueba)

TIPOS = (TURNO_EMITIDO, TURNO_LLAMADO, ATENCION_INICIADA, ATENCION_FINALIZADA,
         TURNO_ABANDONADO, PRUEBA)


def construir_evento(tipo: str, codigo: str = None, estado: str = None,
                     ventanilla: str = None, prioridad: str = None) -> dict:
    """Mensaje oficial de un evento. Los campos sin valor se omiten."""
    if tipo not in TIPOS:
        raise ValueError(f"Tipo de evento desconocido: {tipo!r}")
    evento = {"tipo": tipo, "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    for campo, valor in (("codigo", codigo), ("estado", estado),
                         ("ventanilla", ventanilla), ("prioridad", prioridad)):
        if valor is not None:
            evento[campo] = valor
    return evento


def publicar(tipo: str, codigo: str = None, estado: str = None,
             ventanilla: str = None, prioridad: str = None):
    """
    Publica un evento. Devuelve la cantidad de suscriptores que lo recibieron
    (PUBLISH), o None si no se pudo publicar. Nunca lanza por fallos de Redis.
    """
    evento = construir_evento(tipo, codigo, estado, ventanilla, prioridad)   # ValueError si el tipo es inválido
    try:
        return get_redis().publish(CLAVE_EVENTOS, json.dumps(evento, ensure_ascii=False))
    except RedisError as e:
        log.warning("No se pudo publicar el evento %s (%s): %s", tipo, codigo, e)
        return None
