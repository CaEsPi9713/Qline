"""TT-019 · Casos de fallo del abandono (HU-008) y la recuperación (HU-012).

    python -m scripts.probar_fallos_recuperacion --informe docs/evidencia/fallos_recuperacion.md

Casos: normal, Redis caído, MongoDB caído, datos inválidos y carreras/idempotencia.
No se detiene ningún servicio: el Redis "caído" es un cliente apuntado a un puerto sin servidor y
el MongoDB "caído" una colección que lanza ConnectionError. Los datos son de la serie F-* con cola,
eventos y ventanillas propios (grupo2:qline:prueba:*), que se eliminan al terminar.
Código de salida: 0 si todos los casos dieron lo esperado, 1 si alguno falló.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.fallos_s3 import cliente_redis_caido, ejecutar_casos, informe
from app.s3_comun import ErrorS3


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--puerto-redis-caido", type=int, default=6390, help="puerto donde NO hay Redis (default: %(default)s)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    args = p.parse_args(argv)

    try:
        from app import integracion_s3 as real
        coleccion = real.conectar_mongo()
        r = real.conectar_redis()
        casos = ejecutar_casos(coleccion, r, cliente_redis_caido(args.puerto_redis_caido))
    except ErrorS3 as err:
        print(f"Error controlado: {err.mensaje}", file=sys.stderr)
        return 1

    md = informe(casos)
    print(md)
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(md, encoding="utf-8")
        print(f"Informe escrito: {args.informe}", file=sys.stderr)
    return 0 if all(c.ok for c in casos) else 1


if __name__ == "__main__":
    sys.exit(main())
