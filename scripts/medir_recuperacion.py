"""TT-018 · Mediciones de rehidratación de la cola y barrido de abandono.

    python -m scripts.medir_recuperacion --informe docs/evidencia/rendimiento_recuperacion.md   # servidor
    python -m scripts.medir_recuperacion --simulado --tamanos 50 100                            # demostración

Cada medición: mínimo 3 ejecuciones (default 5); se reporta mínimo, máximo y MEDIANA.
Aviso: en el servidor el barrido procesa también cualquier turno llamado vencido de otros
integrantes (es su comportamiento real); coordine el momento de la medición con el equipo.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.mediciones_s3 import informe, medir_barrido, medir_rehidratacion
from app.s3_comun import ErrorS3
from app.simulacion import EntornoSimulado


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tamanos", type=int, nargs="+", default=[50, 200, 500], help="turnos por medición")
    p.add_argument("--ejecuciones", type=int, default=5, help="ejecuciones por medición (mínimo 3)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    p.add_argument("--simulado", action="store_true", help="usa MongoDB y Redis simulados (no es evidencia)")
    args = p.parse_args(argv)
    if args.ejecuciones < 3:
        print("El seguimiento exige al menos 3 ejecuciones por medición.", file=sys.stderr)
        return 2

    try:
        if args.simulado:
            env = EntornoSimulado()
            coleccion, deps, ahora = env.coleccion, env.redis.dependencias_cola(), env.reloj.ahora
            dep_aband = env.dependencias_abandono()
            print("SIMULADO — esto no es evidencia del servidor", file=sys.stderr)
        else:
            from app import integracion_s3 as real
            coleccion = real.conectar_mongo()
            r = real.conectar_redis()
            deps, dep_aband, ahora = real.dependencias_cola(r), real.dependencias_abandono(r), datetime.now(timezone.utc)

        resultados = []
        for n in args.tamanos:
            resultados.append((f"Rehidratar la cola ({n} pendientes)",
                               medir_rehidratacion(coleccion, deps, ahora, n, args.ejecuciones)))
            resultados.append((f"Barrido de abandono ({n} llamados vencidos)",
                               medir_barrido(coleccion, deps, dep_aband, ahora, n, args.ejecuciones)))
    except (ErrorS3, RuntimeError) as err:
        print(f"Error: {getattr(err, 'mensaje', err)}", file=sys.stderr)
        return 1

    md = informe(resultados, args.simulado, args.tamanos, args.ejecuciones)
    print(md)
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(md, encoding="utf-8")
        print(f"Informe escrito: {args.informe}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
