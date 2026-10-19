"""Exporta/lee los turnos como JSON Lines en Extended JSON.

Las fechas se escriben como {"$date": "...Z"}, de modo que el archivo puede
cargarse también con ``mongoimport`` (ver README).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

CAMPOS_FECHA = ("creado", "llamado", "inicio_atencion", "finalizado", "abandonado")


def _fecha_a_json(valor: datetime | None):
    if valor is None:
        return None
    return {"$date": valor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def _fecha_desde_json(valor):
    if valor is None:
        return None
    return datetime.strptime(valor["$date"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def a_jsonl(docs: list[dict]) -> str:
    lineas = []
    for d in docs:
        copia = {**d, "timestamps": {k: _fecha_a_json(v) for k, v in d["timestamps"].items()}}
        lineas.append(json.dumps(copia, ensure_ascii=False, sort_keys=False))
    return "\n".join(lineas) + ("\n" if lineas else "")


def desde_jsonl(texto: str) -> list[dict]:
    docs = []
    for linea in texto.splitlines():
        if not linea.strip():
            continue
        d = json.loads(linea)
        d["timestamps"] = {k: _fecha_desde_json(v) for k, v in d["timestamps"].items()}
        docs.append(d)
    return docs
