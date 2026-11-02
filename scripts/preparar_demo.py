"""
P07 · Prepara la demostración en vivo. Idempotente: comprueba y, si se pide, completa; no borra nada.

    python -m scripts.preparar_demo                          # solo comprueba y resume
    python -m scripts.preparar_demo --cargar-sinteticos      # además carga el historial S-NNN si falta (upsert)
    python -m scripts.preparar_demo --en-espera 4            # deja al menos 4 turnos en la cola (emite solo los que faltan)

Comprueba MongoDB, Redis, los 6 índices de `turnos`, los datos sintéticos, la dirección de los QR, la zona horaria
y el estado de partida (cola y ventanillas). Código de salida: 0 si no hay errores (los avisos no cuentan), 1 si los hay.
Para reiniciar la demo desde A-001 vea la guía `/demo`: ese borrado es manual a propósito.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

SIMBOLO = {"ok": "OK   ", "aviso": "AVISO", "error": "ERROR"}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cargar-sinteticos", action="store_true", help="carga el historial S-NNN si hay menos de 500")
    p.add_argument("--en-espera", type=int, default=0, metavar="N", help="deja al menos N turnos en la cola (máx. 20)")
    args = p.parse_args(argv)
    if not 0 <= args.en_espera <= 20:
        print("--en-espera debe estar entre 0 y 20.", file=sys.stderr)
        return 2

    from app.main import get_db                      # se importa aquí: lee el .env y crea la conexión
    from app.preparar_demo import hay_errores, preparar
    from app.redis_client import get_redis

    resultados = preparar(get_db(), get_redis(), en_espera=args.en_espera, cargar_sinteticos=args.cargar_sinteticos)
    for r in resultados:
        print(f"  {SIMBOLO[r['estado']]} {r['nombre']}: {r['detalle']}")
    errores = sum(1 for r in resultados if r["estado"] == "error")
    avisos = sum(1 for r in resultados if r["estado"] == "aviso")
    if errores:
        print(f"La demo NO está lista: {errores} error(es) y {avisos} aviso(s).")
    else:
        print(f"Lista para la demo ({avisos} aviso(s)).")
    return 1 if hay_errores(resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
