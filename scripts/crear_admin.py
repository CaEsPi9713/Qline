"""
Crea al primer administrador de QLine (o le restablece la contraseña si se bloqueó).

    python -m scripts.crear_admin --usuario admin                 # pide la contraseña dos veces, sin mostrarla
    python -m scripts.crear_admin --usuario admin --restablecer   # nueva contraseña, cuenta activa y sesiones cerradas

La contraseña también puede venir de la variable de entorno QLINE_ADMIN_CLAVE (para instalaciones automáticas);
nunca se acepta como argumento porque quedaría en el historial del terminal. Solo se guarda su hash.
Código de salida: 0 si se creó o restableció, 1 si no se pudo.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))


def _clave(args) -> str:
    del_entorno = os.getenv("QLINE_ADMIN_CLAVE", "")
    if del_entorno:
        return del_entorno
    primera = getpass.getpass("Contraseña del administrador: ")
    if primera != getpass.getpass("Repita la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    return primera


def main(argv=None, db=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--usuario", required=True, help="nombre del administrador (3 a 30 letras A-Z, sin números ni símbolos)")
    p.add_argument("--restablecer", action="store_true", help="cambia la contraseña de un administrador que ya existe")
    args = p.parse_args(argv)

    from app import auth
    try:
        clave = _clave(args)
        if db is None:
            from app.main import get_db                   # se importa aquí: lee el .env y crea la conexión
            db = get_db()
        resultado = auth.asegurar_administrador(db, args.usuario, clave, restablecer=args.restablecer)
    except auth.AuthError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"Administrador {args.usuario.strip().lower()!r} {resultado}. Ya puede ingresar en /login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
