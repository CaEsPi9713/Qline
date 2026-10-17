"""
Conexión a Redis (TT-006).

Cliente único reutilizable (redis-py maneja su propio pool). Las credenciales
se leen del .env; REDIS_PASS vacío significa Redis sin contraseña.
Todas las claves del proyecto deben usar el prefijo de app.constantes.
"""
import os
from pathlib import Path

import redis
from dotenv import load_dotenv
from redis.exceptions import RedisError

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASS = os.getenv("REDIS_PASS", "") or None

_client = None


class RedisNoDisponible(Exception):
    """Redis no responde o rechazó la conexión."""


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASS,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _client


def verificar_conexion() -> dict:
    """PING controlado: nunca lanza, devuelve el estado para mostrar en la app."""
    try:
        r = get_redis()
        r.ping()
        return {"ok": True, "host": REDIS_HOST, "port": REDIS_PORT,
                "version": r.info("server").get("redis_version")}
    except RedisError as e:
        return {"ok": False, "host": REDIS_HOST, "port": REDIS_PORT, "error": str(e)}
