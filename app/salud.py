"""Estado de salud de la aplicación (S4-M06).

`comprobar` responde solo con estados («ok» / «error»): nunca incluye el texto de una excepción,
servidores, puertos, usuarios ni versiones. El detalle de un fallo va al registro del servidor.
Nunca lanza: una caída de Redis o de MongoDB produce un 503 controlado, no un 500.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

registro = logging.getLogger("qline.salud")


def _probar(nombre: str, accion: Callable[[], Any]) -> str:
    try:
        accion()
        return "ok"
    except Exception as exc:  # noqa: BLE001 · cualquier fallo del servicio es «error», sin filtrar su texto
        registro.warning("salud: %s no responde (%s)", nombre, type(exc).__name__)
        return "error"


def comprobar(get_db: Callable[[], Any], get_redis: Callable[[], Any], barrido: Any = None) -> tuple[dict, int]:
    """Devuelve (cuerpo, código HTTP): 200 si Redis y MongoDB responden, 503 si falla alguno."""
    redis_estado = _probar("redis", lambda: get_redis().ping())
    mongo_estado = _probar("mongo", lambda: get_db().command("ping"))
    sano = redis_estado == "ok" and mongo_estado == "ok"
    cuerpo = {
        "estado": "ok" if sano else "degradado",
        "app": "ok",
        "redis": redis_estado,
        "mongo": mongo_estado,
        "barrido": bool(barrido is not None and getattr(barrido, "activo", False)),
    }
    return cuerpo, 200 if sano else 503
