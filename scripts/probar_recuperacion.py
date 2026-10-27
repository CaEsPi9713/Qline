"""TT-017 · Prueba de caída y rehidratación (genera la evidencia de HU-012).

    python -m scripts.probar_recuperacion --informe docs/evidencia/recuperacion.md

En el servidor compartido la pérdida se simula sacando de la cola solo los códigos R-*
(no se reinicia Redis ni se usa FLUSHALL/FLUSHDB) y el contador se prueba con una clave
aislada. Los turnos R-* se borran al terminar (use --conservar para inspeccionarlos).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.constantes import REDIS_PREFIJO
from app.mediciones_s3 import ADELANTO_RELOJ_SEG
from app.prueba_recuperacion import a_markdown, ejecutar_prueba
from app.s3_comun import ErrorS3

CLAVE_CONTADOR_PRUEBA = f"{REDIS_PREFIJO}prueba:contador:R"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pendientes", type=int, default=12, help="turnos pendientes de la prueba (default: %(default)s)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    p.add_argument("--conservar", action="store_true", help="no borra los turnos R-* al terminar")
    args = p.parse_args(argv)

    try:
        from app import integracion_s3 as real
        coleccion = real.conectar_mongo()
        r = real.conectar_redis()
        deps = real.dependencias_cola(r)
        deps_contador = real.dependencias_cola(r, clave_contador=CLAVE_CONTADOR_PRUEBA)

        def perder():
            for c in [c for c in deps.leer_cola() if c.startswith("R-")]:
                deps.quitar(c)

        try:
            res = ejecutar_prueba(coleccion, deps, base=datetime.now(timezone.utc) + timedelta(seconds=ADELANTO_RELOJ_SEG),
                                  perder=perder,
                                  pendientes=args.pendientes, limpiar=not args.conservar,
                                  deps_contador=deps_contador,
                                  perder_contador=lambda: r.delete(CLAVE_CONTADOR_PRUEBA))
        finally:
            r.delete(CLAVE_CONTADOR_PRUEBA)
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
