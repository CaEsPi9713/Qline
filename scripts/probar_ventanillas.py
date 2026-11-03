"""
P09 · Evidencia de las ventanillas dinámicas contra el MongoDB real.

    python -m scripts.probar_ventanillas
    python -m scripts.probar_ventanillas --informe docs/evidencia/ventanillas_dinamicas.md

Usa la ventanilla V-98 y el turno Z-901 (se eliminan al terminar). Dice con honestidad si el motor de MongoDB acepta o rechaza
turnos con una ventanilla fuera de V-01 a V-03. Código de salida: 1 solo si falla la aplicación; el límite del motor no cuenta.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.main import get_db  # noqa: E402
from app.prueba_ventanillas import a_markdown, ejecutar, hay_fallos_de_aplicacion  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--informe", type=Path, help="escribe el informe en Markdown en esta ruta")
    args = p.parse_args(argv)
    try:
        resultados, veredicto = ejecutar(get_db())
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo ejecutar la prueba: {type(e).__name__}", file=sys.stderr)
        return 1
    for r in resultados:
        marca = "OK    " if r["ok"] else ("LIMITE" if r["caso"].startswith("El motor") else "FALLA ")
        print(f"  {marca} {r['caso']}")
    print(f"El motor {veredicto}.")
    fallos = hay_fallos_de_aplicacion(resultados)
    print("HAY FALLOS EN LA APLICACIÓN" if fallos else "Aplicación OK")
    if args.informe:
        args.informe.parent.mkdir(parents=True, exist_ok=True)
        args.informe.write_text(a_markdown(resultados, veredicto), encoding="utf-8")
        print(f"Informe escrito: {args.informe}")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
