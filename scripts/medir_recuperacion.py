"""TT-018 · Mediciones de rehidratación de la cola, barrido de abandono y reconciliación sin cambios.

    python -m scripts.medir_recuperacion --informe docs/evidencia/rendimiento_recuperacion.md

Cada medición: mínimo 3 ejecuciones (default 5); se reporta mínimo, máximo y MEDIANA.
Los datos son de la serie M-* y usan una cola y un canal de eventos propios (claves
grupo2:qline:prueba:*), que se eliminan al terminar: no se toca la operación real.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.constantes import REDIS_PREFIJO
from app.mediciones_s3 import (MINIMO_EJECUCIONES, informe, medir_barrido, medir_reconciliacion_sin_cambios,
                               medir_rehidratacion)
from app.s3_comun import ErrorS3

CLAVE_COLA_PRUEBA = f"{REDIS_PREFIJO}prueba:cola:M"
CLAVE_CONTADOR_PRUEBA = f"{REDIS_PREFIJO}prueba:contador:M"
CLAVE_EVENTOS_PRUEBA = f"{REDIS_PREFIJO}prueba:eventos"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tamanos", type=int, nargs="+", default=[50, 200, 500], help="turnos por medición")
    p.add_argument("--ejecuciones", type=int, default=5, help="ejecuciones por medición (mínimo 3)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    args = p.parse_args(argv)
    if args.ejecuciones < MINIMO_EJECUCIONES:
        print(f"El seguimiento exige al menos {MINIMO_EJECUCIONES} ejecuciones por medición.", file=sys.stderr)
        return 2

    r = None
    try:
        from app import integracion_s3 as real
        coleccion = real.conectar_mongo()
        r = real.conectar_redis()
        deps = real.dependencias_cola(r, clave_cola=CLAVE_COLA_PRUEBA, clave_contador=CLAVE_CONTADOR_PRUEBA)
        dep_aband = real.dependencias_abandono(r, clave_eventos=CLAVE_EVENTOS_PRUEBA)
        ahora = datetime.now(timezone.utc)

        resultados = []
        for n in args.tamanos:
            resultados.append(medir_rehidratacion(coleccion, deps, ahora, n, args.ejecuciones))
            resultados.append(medir_reconciliacion_sin_cambios(coleccion, deps, ahora, n, args.ejecuciones))
            resultados.append(medir_barrido(coleccion, deps, dep_aband, ahora, n, args.ejecuciones))
    except (ErrorS3, RuntimeError) as err:
        print(f"Error: {getattr(err, 'mensaje', err)}", file=sys.stderr)
        return 1
    finally:
        if r is not None:
            r.delete(CLAVE_COLA_PRUEBA, CLAVE_CONTADOR_PRUEBA, CLAVE_EVENTOS_PRUEBA)

    md = informe(resultados, args.tamanos, args.ejecuciones)
    print(md)
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(md, encoding="utf-8")
        print(f"Informe escrito: {args.informe}", file=sys.stderr)
    return 0 if all(m.correcta for m in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
