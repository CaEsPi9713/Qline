"""Carga y limpieza de turnos sintéticos en MongoDB.

Lee MONGO_* del .env (nunca del código). La carga es un upsert por `codigo`,
por lo que ejecutarla varias veces no duplica turnos. La limpieza solo afecta
a los códigos con el prefijo sintético (por defecto S-NNN), nunca a la serie
A-NNN de la operación real.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pymongo import MongoClient, ReplaceOne
from pymongo.errors import PyMongoError

COLECCION = "turnos"


class ErrorCarga(Exception):
    """Fallo controlado de configuración o conexión con MongoDB."""


def _resumir(e: Exception) -> str:
    return f"{type(e).__name__}: {str(e)[:120]}"


def conectar():
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    try:
        user = quote_plus(os.environ["MONGO_USER"])
        pwd = quote_plus(os.environ["MONGO_PASS"])
        db = os.environ["MONGO_DB"]
    except KeyError as e:
        raise ErrorCarga(f"Falta la variable de entorno {e.args[0]} (revise el .env)") from e
    host = os.environ.get("MONGO_HOST", "127.0.0.1")
    port = os.environ.get("MONGO_PORT", "27017")
    cliente = MongoClient(
        f"mongodb://{user}:{pwd}@{host}:{port}/{quote_plus(db)}?authSource={quote_plus(db)}",
        serverSelectionTimeoutMS=5000,
    )
    return cliente[db][COLECCION]


def cargar(coleccion, docs: list[dict]) -> int:
    """Upsert por código. Devuelve la cantidad de documentos procesados."""
    if not docs:
        return 0
    try:
        coleccion.bulk_write([ReplaceOne({"codigo": d["codigo"]}, d, upsert=True) for d in docs])
    except PyMongoError as e:
        raise ErrorCarga(f"No se pudo cargar en MongoDB (revise MONGO_* en .env): {_resumir(e)}") from e
    return len(docs)


def limpiar(coleccion, prefijo: str) -> int:
    """Elimina solo los turnos sintéticos con ese prefijo (p. ej. S-001...)."""
    if not re.fullmatch(r"[A-Z]", prefijo):
        raise ErrorCarga("El prefijo debe ser una letra mayúscula")
    try:
        return coleccion.delete_many({"codigo": {"$regex": "^" + prefijo + r"-\d+$"}}).deleted_count
    except PyMongoError as e:
        raise ErrorCarga(f"No se pudo limpiar en MongoDB (revise MONGO_* en .env): {_resumir(e)}") from e
