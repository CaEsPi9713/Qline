"""Inserta los turnos sintéticos de prueba de HU-006 (A-015 ... A-020).

Datos 100 % sintéticos, sin información personal. Es idempotente: puede
ejecutarse varias veces sin duplicar códigos (usa upsert por ``codigo``).

Uso:
    python scripts/sembrar_turnos_hu006.py            # inserta/restaura
    python scripts/sembrar_turnos_hu006.py --limpiar  # borra solo A-015..A-020

Lee las variables de entorno de .env.example (MONGO_*). No contiene secretos.
Nota: esto cubre solo los casos de HU-006; el script completo es TT-005.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from pymongo import MongoClient

BASE = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)


def turno(codigo, estado, ventanilla, prioridad="normal", minutos=0):
    creado = BASE + timedelta(minutes=minutos)
    llamado = creado + timedelta(minutes=5) if estado != "pendiente" else None
    inicio = llamado + timedelta(minutes=1) if estado in ("en_atencion", "atendido") else None
    final = inicio + timedelta(minutes=4) if estado == "atendido" else None
    abandonado = llamado + timedelta(seconds=180) if estado == "abandonado" else None
    return {
        "codigo": codigo,
        "servicio": "atencion_general",
        "prioridad": prioridad,
        "estado": estado,
        "ventanilla": ventanilla,
        "operador": None,
        "timestamps": {
            "creado": creado,
            "llamado": llamado,
            "inicio_atencion": inicio,
            "finalizado": final,
            "abandonado": abandonado,
        },
        "metricas": {
            "espera_seg": int((llamado - creado).total_seconds()) if llamado else None,
            "atencion_seg": int((final - inicio).total_seconds()) if final else None,
        },
    }


TURNOS = [
    turno("A-015", "llamado", "V-01", minutos=0),                     # caso feliz
    turno("A-016", "pendiente", None, "preferencial", minutos=1),     # estado inválido
    turno("A-017", "en_atencion", "V-02", minutos=2),                 # doble inicio
    turno("A-018", "atendido", "V-01", minutos=3),                    # transición prohibida
    turno("A-019", "abandonado", "V-03", minutos=4),                  # transición prohibida
    turno("A-020", "llamado", "V-02", "preferencial", minutos=5),     # ventanilla no coincide
]


def conectar():
    user = quote_plus(os.environ["MONGO_USER"])
    pwd = quote_plus(os.environ["MONGO_PASS"])
    host = os.environ["MONGO_HOST"]
    port = os.environ.get("MONGO_PORT", "27017")
    db = os.environ.get("MONGO_DB", "grupo2_db")
    cliente = MongoClient(f"mongodb://{user}:{pwd}@{host}:{port}/{db}", serverSelectionTimeoutMS=5000)
    return cliente[db]["turnos"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limpiar", action="store_true", help="elimina solo A-015..A-020")
    args = parser.parse_args()

    coleccion = conectar()
    codigos = [t["codigo"] for t in TURNOS]
    if args.limpiar:
        r = coleccion.delete_many({"codigo": {"$in": codigos}})
        print(f"Eliminados {r.deleted_count} turnos de prueba")
        return
    for t in TURNOS:
        coleccion.replace_one({"codigo": t["codigo"]}, t, upsert=True)
    print(f"Sembrados/restaurados {len(TURNOS)} turnos de prueba: {', '.join(codigos)}")


if __name__ == "__main__":
    main()
