"""
Cola activa en Redis (TT-007).

- Contador atómico de códigos (INCR).
- Cola Sorted Set: prioridad primero, FIFO dentro de la misma prioridad.
- Extracción atómica del siguiente turno (ZPOPMIN).
- Una ventanilla atiende un turno a la vez (reserva atómica con SET NX).
- Estado temporal del turno llamado: Hash `turno:{codigo}` con TTL de 180 s
  (TT-011/TT-012), que se elimina cuando el cliente se presenta (inicia la atención).

Solo toca claves con el prefijo grupo2:qline: (ver app.constantes).
"""
import time

from redis.exceptions import RedisError

from app.constantes import (
    CLAVE_COLA,
    CLAVE_CONTADOR,
    PRIORIDAD_PREFERENCIAL,
    PRIORIDADES,
    TTL_ABANDONO_SEG,
    VENTANILLAS,
    clave_turno,
    clave_ventanilla_actual,
)
from app.redis_client import get_redis

# Valor temporal de reserva de una ventanilla mientras se le asigna un turno, y
# su vida máxima: si el proceso muere a mitad de la asignación, la reserva
# expira sola y la ventanilla no queda bloqueada.
RESERVA = "__asignando__"
TTL_RESERVA_SEG = 10

# score = nivel_de_prioridad * ESCALA + hora_de_llegada_ms
# nivel 0 = preferencial (sale primero), nivel 1 = normal.
# ESCALA > cualquier timestamp en ms, así la prioridad siempre domina a la
# llegada y, a igual prioridad, gana el que llegó antes (FIFO).
# Máximo ~1.2e13: exacto como double (límite 2^53 ≈ 9e15).
ESCALA = 10**13
PREFIJO_CODIGO = "A"


class ColaError(ValueError):
    """Entrada inválida para una operación de cola."""


def calcular_score(prioridad: str, llegada_ms: int) -> int:
    if prioridad not in PRIORIDADES:
        raise ColaError(f"Prioridad inválida: {prioridad!r}")
    nivel = 0 if prioridad == PRIORIDAD_PREFERENCIAL else 1
    return nivel * ESCALA + llegada_ms


def siguiente_codigo(clave_contador: str = CLAVE_CONTADOR) -> str:
    """Código único y consecutivo (INCR es atómico): A-001, A-002, ..."""
    n = get_redis().incr(clave_contador)
    return f"{PREFIJO_CODIGO}-{n:03d}"


def encolar(codigo: str, prioridad: str, llegada_ms: int = None,
            clave_cola: str = CLAVE_COLA) -> bool:
    """
    Agrega el turno a la cola. NX evita duplicar o reordenar un código que ya
    está en cola (reintentos seguros). Devuelve True si se agregó.
    """
    if not codigo:
        raise ColaError("Código de turno vacío.")
    if llegada_ms is None:
        llegada_ms = int(time.time() * 1000)
    score = calcular_score(prioridad, llegada_ms)
    return get_redis().zadd(clave_cola, {codigo: score}, nx=True) == 1


def ver_cola(limite: int = 100, clave_cola: str = CLAVE_COLA) -> list:
    """Turnos disponibles en orden de atención. Solo lectura: no remueve nada."""
    items = get_redis().zrange(clave_cola, 0, limite - 1, withscores=True)
    return [
        {
            "codigo": codigo,
            "prioridad": "preferencial" if score < ESCALA else "normal",
            "posicion": i + 1,
        }
        for i, (codigo, score) in enumerate(items)
    ]


def tamano_cola(clave_cola: str = CLAVE_COLA) -> int:
    return get_redis().zcard(clave_cola)


def posicion_en_cola(codigo: str, clave_cola: str = CLAVE_COLA):
    """Cantidad de turnos antes que `codigo`, o None si no está en cola."""
    return get_redis().zrank(clave_cola, codigo)


class VentanillaOcupada(Exception):
    """La ventanilla ya tiene un turno asignado (una ventanilla atiende un turno a la vez)."""

    def __init__(self, ventanilla: str, codigo: str = None):
        self.ventanilla = ventanilla
        self.codigo = codigo  # None: otra solicitud la está asignando en este instante
        super().__init__(
            f"{ventanilla} ya tiene el turno {codigo}" if codigo
            else f"{ventanilla} está asignando un turno en este momento"
        )


def turno_actual(ventanilla: str):
    """Código asignado ahora a la ventanilla según Redis, o None (libre o reserva en curso)."""
    valor = get_redis().get(clave_ventanilla_actual(ventanilla))
    return None if valor in (None, RESERVA) else valor


def liberar_ventanilla_si(ventanilla: str, codigo: str) -> bool:
    """Libera la ventanilla solo si todavía apunta a `codigo`. Devuelve True si la liberó."""
    r = get_redis()
    clave = clave_ventanilla_actual(ventanilla)
    if r.get(clave) == codigo:
        r.delete(clave)
        return True
    return False


def reservar_y_extraer(ventanilla: str, clave_cola: str = CLAVE_COLA, clave_actual: str = None,
                       validar_ventanilla: bool = True):
    """
    Primera mitad de la asignación: reserva la ventanilla y extrae el turno.

    1. SET NX reserva la ventanilla: si ya tiene un turno (o está recibiendo uno
       en este instante) lanza VentanillaOcupada. Es atómico, así que dos
       solicitudes simultáneas de la misma ventanilla nunca asignan dos turnos.
    2. ZPOPMIN extrae el turno (atómico: dos ventanillas nunca reciben el mismo).

    La ventanilla queda con la reserva (que expira sola en TTL_RESERVA_SEG) hasta
    que se llame a confirmar_asignacion(); si algo falla, devolver_a_cola() o
    liberar_ventanilla() la liberan. Devuelve (codigo, score), o None si la cola
    está vacía (la reserva se libera). `clave_actual` permite usar otra clave
    (pruebas); por defecto la oficial. `validar_ventanilla=False` (solo pruebas de
    concurrencia) permite consumidores simulados que no son ventanillas del sistema.
    """
    if validar_ventanilla and ventanilla not in VENTANILLAS:
        raise ColaError(f"Ventanilla inválida: {ventanilla!r}")
    r = get_redis()
    clave = clave_actual or clave_ventanilla_actual(ventanilla)
    if not r.set(clave, RESERVA, nx=True, ex=TTL_RESERVA_SEG):
        actual = r.get(clave)
        raise VentanillaOcupada(ventanilla, None if actual in (None, RESERVA) else actual)

    extraido = None
    try:
        salida = r.zpopmin(clave_cola, 1)
        if not salida:
            r.delete(clave)
            return None
        extraido = salida[0]
        return extraido
    except RedisError:
        # Compensación: no dejar la ventanilla bloqueada ni perder el turno extraído.
        try:
            if extraido:
                r.zadd(clave_cola, {extraido[0]: extraido[1]}, nx=True)
            r.delete(clave)
        except RedisError:
            pass
        raise


def confirmar_asignacion(ventanilla: str, codigo: str, clave_actual: str = None,
                         prioridad: str = None, ttl: int = TTL_ABANDONO_SEG) -> None:
    """
    Segunda mitad: el turno queda asignado a la ventanilla (reemplaza la reserva,
    sin TTL) y se registra su Hash temporal con TTL, todo en una transacción
    (MULTI/EXEC). Con `clave_actual` personalizada (pruebas) no se crea el Hash.
    """
    r = get_redis()
    if clave_actual is not None:
        r.set(clave_actual, codigo)
        return
    pipe = r.pipeline(transaction=True)
    pipe.set(clave_ventanilla_actual(ventanilla), codigo)
    _hash_llamado(pipe, codigo, ventanilla, prioridad, int(time.time() * 1000), ttl)
    pipe.execute()


def extraer_siguiente(ventanilla: str, clave_cola: str = CLAVE_COLA, clave_actual: str = None,
                      validar_ventanilla: bool = True):
    """Reserva, extrae y confirma en un solo paso. Devuelve (codigo, score) o None."""
    res = reservar_y_extraer(ventanilla, clave_cola, clave_actual, validar_ventanilla)
    if res is not None:
        confirmar_asignacion(ventanilla, res[0], clave_actual, prioridad=prioridad_de_score(res[1]))
    return res


# --- Estado temporal del turno llamado (Hash + TTL) -----------------------------
#
#   grupo2:qline:turno:{codigo}   Hash   expira a los TTL_ABANDONO_SEG (180 s)
#     codigo      código del turno
#     ventanilla  ventanilla que lo llamó
#     prioridad   normal | preferencial
#     llamado_ms  instante de la llamada (epoch ms)
#     vence_ms    instante en que el turno se considera abandonado (epoch ms)
#
# Existe solo mientras el cliente no se ha presentado. Si desaparece (expiró o
# se perdió Redis) el turno llamado es candidato a abandono; la transición
# `llamado -> abandonado` en MongoDB es de HU-008. Nunca se confía solo en la
# ausencia del Hash: MongoDB conserva `timestamps.llamado`.

def _hash_llamado(pipe, codigo, ventanilla, prioridad, ahora_ms, ttl):
    clave = clave_turno(codigo)
    pipe.hset(clave, mapping={
        "codigo": codigo,
        "ventanilla": ventanilla or "",
        "prioridad": prioridad or "",
        "llamado_ms": ahora_ms,
        "vence_ms": ahora_ms + ttl * 1000,
    })
    pipe.expire(clave, ttl)


def registrar_llamado(codigo: str, ventanilla: str, prioridad: str = None,
                      ttl: int = TTL_ABANDONO_SEG, ahora_ms: int = None) -> None:
    """Crea (o reinicia) el Hash temporal de un turno llamado, con su TTL."""
    if not codigo:
        raise ColaError("Código de turno vacío.")
    if ttl < 1:
        raise ColaError("El TTL debe ser de al menos 1 segundo.")
    pipe = get_redis().pipeline(transaction=True)
    _hash_llamado(pipe, codigo, ventanilla, prioridad, ahora_ms or int(time.time() * 1000), ttl)
    pipe.execute()


def turno_llamado(codigo: str):
    """Datos del Hash temporal de un turno llamado, o None si no existe o ya expiró."""
    r = get_redis()
    clave = clave_turno(codigo)
    datos = r.hgetall(clave)
    if not datos:
        return None
    restante = r.ttl(clave)
    return {
        "codigo": datos.get("codigo", codigo),
        "ventanilla": datos.get("ventanilla") or None,
        "prioridad": datos.get("prioridad") or None,
        "llamado_ms": int(datos["llamado_ms"]) if datos.get("llamado_ms") else None,
        "vence_ms": int(datos["vence_ms"]) if datos.get("vence_ms") else None,
        "segundos_restantes": restante if restante >= 0 else None,
    }


def segundos_restantes(codigo: str):
    """Segundos que faltan para que el turno llamado se considere abandonado, o None."""
    restante = get_redis().ttl(clave_turno(codigo))
    return restante if restante >= 0 else None   # -2: no existe, -1: sin TTL


def confirmar_presencia(codigo: str) -> bool:
    """
    El cliente se presentó (inicia la atención) o el turno terminó: se elimina el
    Hash temporal para que ya no venza. Devuelve True si existía.
    """
    return get_redis().delete(clave_turno(codigo)) == 1


def llamar_siguiente(ventanilla: str, clave_cola: str = CLAVE_COLA, clave_actual: str = None):
    """Como extraer_siguiente, pero devuelve solo el código (o None)."""
    res = extraer_siguiente(ventanilla, clave_cola, clave_actual)
    return res[0] if res else None


def prioridad_de_score(score: float) -> str:
    return "preferencial" if score < ESCALA else "normal"


def devolver_a_cola(codigo: str, score: float, ventanilla: str,
                    clave_cola: str = CLAVE_COLA) -> None:
    """Compensación: regresa el turno a la cola con su score original y libera la ventanilla."""
    r = get_redis()
    r.zadd(clave_cola, {codigo: score}, nx=True)
    r.delete(clave_ventanilla_actual(ventanilla))


def liberar_ventanilla(ventanilla: str) -> None:
    get_redis().delete(clave_ventanilla_actual(ventanilla))


def reencolar(codigo: str, prioridad: str, llegada_ms: int,
              clave_cola: str = CLAVE_COLA) -> bool:
    """Devuelve un turno a la cola conservando su llegada original (compensación)."""
    return encolar(codigo, prioridad, llegada_ms, clave_cola)
