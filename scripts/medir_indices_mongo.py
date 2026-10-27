"""TT-014 y TT-015 · Medición de índices con explain() y de los aggregation pipelines del dashboard.

    python scripts/medir_indices_mongo.py --informe docs/evidencia/indices_mongo.md

Mide contra el MongoDB real de la aplicación (no existe modo simulado: un informe de evidencia debe salir
de una medición). Requiere los índices de app/turnos_schema.py creados y al menos 50 turnos; si faltan,
el script lo dice y explica cómo resolverlo. Código de salida: 0 si midió, 1 si no pudo, 2 si los
argumentos no son válidos.
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.mediciones_indices import (DEFECTO_EJECUCIONES, DEFECTO_OPERACIONES, MIN_EJECUCIONES,  # noqa: E402
                                    MedicionError, ejecutar)


def main(argumentos=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ejecuciones", type=int, default=DEFECTO_EJECUCIONES,
                   help=f"ejecuciones independientes por consulta (mínimo {MIN_EJECUCIONES}, default: %(default)s)")
    p.add_argument("--operaciones", type=int, default=DEFECTO_OPERACIONES,
                   help="operaciones por ejecución (default: %(default)s)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    args = p.parse_args(argumentos)
    if args.ejecuciones < MIN_EJECUCIONES:
        print(f"Error: se requieren al menos {MIN_EJECUCIONES} ejecuciones (se pidieron {args.ejecuciones}).",
              file=sys.stderr)
        return 2

    try:
        from app.main import get_db
        informe = ejecutar(get_db(), args.ejecuciones, args.operaciones)
    except MedicionError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(informe, encoding="utf-8")
        print(f"Informe escrito: {args.informe}", file=sys.stderr)
    print(informe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
