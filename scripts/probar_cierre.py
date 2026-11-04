"""
S4-M03 · Evidencia del cierre con motivo y nota contra el MongoDB real, sin `collMod`.

    python -m scripts.probar_cierre
    python -m scripts.probar_cierre --informe docs/evidencia/cierre.md

Usa turnos propios (serie Z-9NN) que elimina al terminar. No toca turnos reales ni Redis.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.main import get_db  # noqa: E402
from app.prueba_cierre import a_markdown, ejecutar  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--informe", type=Path, help="escribe el informe en Markdown en esta ruta")
    args = p.parse_args(argv)
    try:
        resultados, servidor = ejecutar(get_db())
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo ejecutar la prueba: {type(e).__name__}", file=sys.stderr)
        return 1
    for r in resultados:
        print(f"  {'OK   ' if r['ok'] else 'FALLA'} {r['caso']}")
    print(f"El validador del servidor {servidor}")
    fallos = sum(1 for r in resultados if not r["ok"])
    print("Todo OK" if fallos == 0 else f"HAY FALLOS: {fallos}")
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(a_markdown(resultados, servidor), encoding="utf-8")
        print(f"Informe escrito: {args.informe}")
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
