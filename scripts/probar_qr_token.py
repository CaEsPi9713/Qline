"""TT-001 / TT-002 / HU-003 · Prueba en el servidor de `qr_token` y su índice parcial único.

    python -m scripts.probar_qr_token --informe docs/evidencia/qr_token.md

Inserta y elimina solo los turnos Q-9901 a Q-9905. Código de salida: 0 si todo cumple, 1 si algo falla.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.prueba_qr_token import a_markdown, ejecutar
from app.s3_comun import ErrorS3


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    args = p.parse_args(argv)
    try:
        from app import integracion_s3 as real
        res = ejecutar(real.conectar_mongo())
    except ErrorS3 as err:
        print(f"Error controlado: {err.mensaje}", file=sys.stderr)
        return 1
    md = a_markdown(res)
    print(md)
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(md, encoding="utf-8")
        print(f"Informe escrito: {args.informe}", file=sys.stderr)
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
