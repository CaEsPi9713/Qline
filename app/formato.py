"""Formato de fechas y horas para las pantallas.

MongoDB y las APIs guardan y entregan fechas en UTC (ISO 8601, por ejemplo `2026-10-27T01:12:49.757Z`): es el formato correcto
para las descargas y para otras máquinas. Las pantallas, en cambio, muestran la hora local con un formato de lectura:
`26/10/2026` y `19:12:49`.

La zona horaria se elige con la variable de entorno `ZONA_HORARIA` (nombre IANA; por defecto `America/Costa_Rica`).
Si el nombre no existe o el sistema no tiene la base de zonas horarias, se usa UTC y las pantallas lo indican.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from typing import Any

ZONA_POR_DEFECTO = "America/Costa_Rica"
VACIO = "-"


@lru_cache(maxsize=8)
def _cargar_zona(nombre: str) -> tuple[tzinfo, bool]:
    """(zona, es_la_pedida). Si no se puede cargar, devuelve UTC y False."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(nombre), True
    except Exception:                      # nombre inválido o sin base de zonas horarias
        return timezone.utc, False


def nombre_zona() -> str:
    return os.getenv("ZONA_HORARIA", "").strip() or ZONA_POR_DEFECTO


def zona() -> tzinfo:
    return _cargar_zona(nombre_zona())[0]


def a_datetime(valor: Any) -> datetime | None:
    """datetime con zona (UTC) a partir de un datetime o de un texto ISO 8601. Sin zona se asume UTC. None si no se entiende."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        dt = valor
    elif isinstance(valor, str):
        texto = valor.strip()
        if texto.endswith(("Z", "z")):
            texto = texto[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(texto)
        except ValueError:
            return None
    else:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _local(valor: Any) -> datetime | None:
    dt = a_datetime(valor)
    return dt.astimezone(zona()) if dt else None


def fecha(valor: Any) -> str:
    """`26/10/2026` en hora local (`-` si no hay fecha)."""
    dt = _local(valor)
    return dt.strftime("%d/%m/%Y") if dt else (VACIO if valor in (None, "") else str(valor))


def hora(valor: Any, segundos: bool = True) -> str:
    """`19:12:49` (o `19:12`) en hora local."""
    dt = _local(valor)
    return dt.strftime("%H:%M:%S" if segundos else "%H:%M") if dt else (VACIO if valor in (None, "") else str(valor))


def fecha_hora(valor: Any, segundos: bool = True) -> str:
    """`26/10/2026 19:12:49` en hora local."""
    dt = _local(valor)
    if not dt:
        return VACIO if valor in (None, "") else str(valor)
    return dt.strftime("%d/%m/%Y %H:%M:%S" if segundos else "%d/%m/%Y %H:%M")


def iso_utc(valor: Any) -> str:
    """`2026-10-27T01:12:49.757Z`: el valor exacto, para mostrarlo en el detalle (`title`) y en `<time datetime>`."""
    dt = a_datetime(valor)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z") if dt else ""


def etiqueta_zona() -> str:
    """Texto para el encabezado de las tablas: `hora de Costa Rica (UTC−6)` o `UTC` si no se pudo cargar la zona."""
    tz, pedida = _cargar_zona(nombre_zona())
    if not pedida:
        return "UTC"
    ahora = datetime.now(timezone.utc).astimezone(tz)
    desplazamiento = ahora.utcoffset() or timedelta(0)
    minutos = int(desplazamiento.total_seconds() // 60)
    signo = "+" if minutos >= 0 else "−"
    horas, resto = divmod(abs(minutos), 60)
    utc = f"UTC{signo}{horas}" + (f":{resto:02d}" if resto else "")
    lugar = nombre_zona().split("/")[-1].replace("_", " ")
    return f"hora de {lugar} ({utc})"


def registrar(entorno) -> None:
    """Agrega los filtros a un entorno de Jinja: fecha, hora, fecha_hora, iso_utc y la variable global etiqueta_zona."""
    entorno.filters.update({"fecha": fecha, "hora": hora, "fecha_hora": fecha_hora, "iso_utc": iso_utc})
    entorno.globals["etiqueta_zona"] = etiqueta_zona
