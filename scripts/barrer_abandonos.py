"""HU-008 · Barrido de abandono de turnos llamados (TTL 180 s).

    python -m scripts.barrer_abandonos                 # una pasada (MongoDB y Redis reales)
    python -m scripts.barrer_abandonos --continuo --intervalo 10

En producción el barrido corre dentro de la app (app/barrido.py, se inicia con la aplicación);
este script sirve para ejecutarlo a mano, desde cron o para la evidencia.
Código de salida: 0 si no quedó nada a medias, 1 si hubo errores.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from app.abandono import barrer_abandonos
from app.s3_comun import ErrorS3


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--continuo", action="store_true", help="repite el barrido hasta Ctrl+C")
    p.add_argument("--intervalo", type=float, default=10.0, help="segundos entre pasadas con --continuo")
    args = p.parse_args(argv)

    try:
        from app import integracion_s3 as real
        coleccion = real.conectar_mongo()
        deps = real.dependencias_abandono(real.conectar_redis())

        while True:
            resultado = barrer_abandonos(coleccion, **deps)
            print(json.dumps(resultado.resumen(), ensure_ascii=False, indent=2))
            if not args.continuo:
                return 0 if resultado.ok else 1
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        return 0
    except ErrorS3 as err:
        print(f"Error controlado: {err.mensaje}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
