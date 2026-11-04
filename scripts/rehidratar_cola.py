"""HU-012 · Reconstruir/reconciliar la cola de Redis desde MongoDB.

    python -m scripts.rehidratar_cola                       # PLAN (no escribe nada)
    python -m scripts.rehidratar_cola --aplicar             # ejecuta la rehidratación
    python -m scripts.rehidratar_cola --aplicar --quitar-sobrantes
    python -m scripts.rehidratar_cola --aplicar --informe docs/evidencia/recuperacion_cola.md

Es idempotente: ejecutarla otra vez no duplica nada.

Conviene ejecutarla con la atención detenida (nadie llamando turnos): si un turno se llama
justo mientras se reencola, queda un código obsoleto en la cola que el siguiente llamado
rechazará con un aviso de inconsistencia (no se pierde ni se duplica ninguna atención).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.informe import encabezado
from app.recuperacion import reconciliar_cola
from app.s3_comun import ErrorS3


def _markdown(rep) -> str:
    md = encabezado("Evidencia · Rehidratación de la cola (HU-012)")
    md += "\n## Comparación antes / después\n\n"
    md += f"- Cola antes ({len(rep.antes_cola)}): `{', '.join(rep.antes_cola) or '(vacía)'}`\n"
    md += f"- Pendientes esperados según MongoDB ({len(rep.esperados)}): `{', '.join(rep.esperados) or '(ninguno)'}`\n"
    if rep.despues_cola is not None:
        md += f"- Cola después ({len(rep.despues_cola)}): `{', '.join(rep.despues_cola) or '(vacía)'}`\n"
    md += "\n## Reporte\n\n```json\n" + json.dumps(rep.resumen(), ensure_ascii=False, indent=2) + "\n```\n"
    return md


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--aplicar", action="store_true", help="escribe en Redis (sin esto solo muestra el plan)")
    p.add_argument("--quitar-sobrantes", action="store_true",
                   help="saca de la cola los códigos que MongoDB no considera pendientes")
    p.add_argument("--sin-contador", action="store_true", help="no restaura el contador de códigos")
    p.add_argument("--serie", default="A", help="serie operativa de códigos para el contador (default: %(default)s)")
    p.add_argument("--informe", type=Path, help="escribe el informe Markdown en esta ruta")
    args = p.parse_args(argv)

    try:
        from app import integracion_s3 as real
        coleccion = real.conectar_mongo()
        deps = real.dependencias_cola(real.conectar_redis())

        rep = reconciliar_cola(coleccion, deps, aplicar=args.aplicar, quitar_sobrantes=args.quitar_sobrantes,
                               restaurar_contador=not args.sin_contador, serie=args.serie)
    except ErrorS3 as err:
        print(f"Error controlado: {err.mensaje}", file=sys.stderr)
        return 1

    print(json.dumps(rep.resumen(), ensure_ascii=False, indent=2))
    if not args.aplicar:
        print("(plan: no se escribió nada; use --aplicar)", file=sys.stderr)
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(_markdown(rep), encoding="utf-8")
        print(f"Informe escrito: {args.informe}", file=sys.stderr)
    return 0 if rep.ok in (True, None) else 1


if __name__ == "__main__":
    sys.exit(main())
