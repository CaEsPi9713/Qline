"""
Crea turnos de demostración con `qr_token` para probar la consulta por QR (HU-013)
mientras la emisión (HU-003, Aaron) no los genere sola.

Cada turno se emite por el flujo real (contador de Redis, MongoDB y cola) y, si
todavía no tiene `qr_token`, se le agrega un UUID v4. No toca el esquema ni los
índices. Imprime la URL de consulta de cada turno: ábrala en el celular, o
genere su QR con cualquier generador, para comprobar la actualización automática.

    python scripts/crear_turnos_qr_demo.py
    python scripts/crear_turnos_qr_demo.py --cantidad 3 --prioridad preferencial
    python scripts/crear_turnos_qr_demo.py --url-base https://grupo2.crnube.net/proyecto/qline

Los turnos creados son turnos reales de la serie A-NNN: bórrelos del CRUD si no
se van a usar en la demostración.
"""
import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.constantes import PRIORIDADES  # noqa: E402
from app.emitir import EmisionError, emitir_turno  # noqa: E402

URL_BASE_POR_DEFECTO = "https://grupo2.crnube.net/proyecto/qline"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cantidad", type=int, default=2, help="turnos a crear (default: %(default)s)")
    ap.add_argument("--prioridad", choices=PRIORIDADES, default="normal")
    ap.add_argument("--url-base", default=URL_BASE_POR_DEFECTO,
                    help="URL pública del sistema, sin barra final (default: %(default)s)")
    args = ap.parse_args()
    if not 1 <= args.cantidad <= 20:
        print("La cantidad debe estar entre 1 y 20.", file=sys.stderr)
        return 2

    from app.main import get_db   # se importa aquí: lee el .env y crea la conexión
    db = get_db()
    base = args.url_base.rstrip("/")
    try:
        for _ in range(args.cantidad):
            turno = emitir_turno(db, args.prioridad)
            doc = db["turnos"].find_one({"codigo": turno["codigo"]}, {"qr_token": 1})
            token = (doc or {}).get("qr_token")
            if not token:
                token = str(uuid.uuid4())
                db["turnos"].update_one({"codigo": turno["codigo"]}, {"$set": {"qr_token": token}})
            print(f"{turno['codigo']}  ({args.prioridad})  {base}/turno/qr/{token}")
    except EmisionError as e:
        print(f"No se pudo emitir: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
