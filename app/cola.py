"""
Cola activa en Redis (TT-007).

- Contador atómico de códigos (INCR).
- Cola Sorted Set: prioridad primero, FIFO dentro de la misma prioridad.
- Extracción atómica del siguiente turno (ZPOPMIN).

Solo toca claves con el prefijo grupo2:qline: (ver app.constantes).
"""
import time

from app.constantes import (
    CLAVE_COLA,
    CLAVE_CONTADOR,
    PRIORIDAD_PREFERENCIAL,
    PRIORIDADES,
    VENTANILLAS,
    clave_ventanilla_actual,
)
from app.redis_client import get_redis

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


def extraer_siguiente(ventanilla: str, clave_cola: str = CLAVE_COLA):
    """
    Extrae el siguiente turno con ZPOPMIN (atómico: dos ventanillas simultáneas
    nunca reciben el mismo miembro) y lo registra como actual de la ventanilla.
    Devuelve (codigo, score), o None si la cola está vacía.
    """
    if ventanilla not in VENTANILLAS:
        raise ColaError(f"Ventanilla inválida: {ventanilla!r}")
    r = get_redis()
    salida = r.zpopmin(clave_cola, 1)
    if not salida:
        return None
    codigo, score = salida[0]
    r.set(clave_ventanilla_actual(ventanilla), codigo)
    return codigo, score


def llamar_siguiente(ventanilla: str, clave_cola: str = CLAVE_COLA):
    """Como extraer_siguiente, pero devuelve solo el código (o None)."""
    res = extraer_siguiente(ventanilla, clave_cola)
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
