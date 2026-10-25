"""TT-017 · Prueba de caída y rehidratación (genera la evidencia de HU-012).

    python -m scripts.probar_recuperacion --informe docs/evidencia/recuperacion.md   # servidor
    python -m scripts.probar_recuperacion --simulado                                 # demostración

En el servidor compartido la pérdida se simula sacando de la cola solo los códigos R-*
(no se reinicia Redis ni se usa FLUSHALL/FLUSHDB). Los turnos R-* se borran al terminar
(use --conservar para inspeccionarlos).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.prueba_recuperacion import a_markdown, ejecutar_prueba
from app.s3_comun import ErrorS3
from app.simulacion import EntornoSimulado


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pendientes", type=int, default=12, help="turnos pendientes de la prueba (default: %(default)s)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    p.add_argument("--conservar", action="store_true", help="no borra los turnos R-* al terminar")
    p.add_argument("--simulado", action="store_true", help="usa MongoDB y Redis simulados (no es evidencia)")
    args = p.parse_args(argv)

    try:
        if args.simulado:
            env = EntornoSimulado()
            coleccion, deps, base = env.coleccion, env.redis.dependencias_cola(), env.reloj.ahora
            perder, simulado = env.redis.perder_todo, True     # en simulado sí se pierde TODO (incluido el contador)
            restaurar_contador = True
            print("SIMULADO — esto no es evidencia del servidor", file=sys.stderr)
        else:
            from app import integracion_s3 as real
            coleccion = real.conectar_mongo()
            deps = real.dependencias_cola(real.conectar_redis())
            base, simulado, restaurar_contador = datetime.now(timezone.utc), False, False
            perder = None                                      # se define abajo (necesita deps)

        if perder is None:
            def perder():
                for c in [c for c in deps.leer_cola() if c.startswith("R-")]:
                    deps.quitar(c)

        res = ejecutar_prueba(coleccion, deps, base=base, perder=perder, simulado=simulado,
                              pendientes=args.pendientes, restaurar_contador=restaurar_contador,
                              limpiar=not args.conservar)
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
