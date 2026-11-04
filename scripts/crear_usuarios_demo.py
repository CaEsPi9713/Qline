"""
Crea los usuarios de demostración (administrador, supervisor y operador) para la exposición y para el PDF de entrega.

    python -m scripts.crear_usuarios_demo                       # crea los que falten, con contraseñas generadas
    python -m scripts.crear_usuarios_demo --ventanilla V-02     # asigna esa ventanilla al operador (por defecto V-01)
    python -m scripts.crear_usuarios_demo --sin-asignar         # no asigna ventanilla al operador
    python -m scripts.crear_usuarios_demo --restablecer         # nuevas contraseñas para los que ya existen

Las contraseñas se generan al azar y **se muestran una sola vez** en el terminal: cópielas al PDF de entrega. No se
guardan en ningún archivo ni en el repositorio (en la base de datos solo queda su hash). Para usar una contraseña propia,
igual para los tres, defina la variable de entorno QLINE_DEMO_CLAVE; nunca se acepta como argumento porque quedaría en el
historial del terminal.

El script es idempotente: un usuario que ya existe no se toca (salvo con --restablecer) y nunca se cambia el rol ni se
reactiva a una cuenta que no coincida con la de demostración. Código de salida: 0 si todo salió bien, 1 si hubo errores.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

POR = "scripts.crear_usuarios_demo"
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"       # sin caracteres que se confunden (0 O 1 l I)
LARGO_CLAVE = 12


def generar_clave() -> str:
    return "".join(secrets.choice(ALFABETO) for _ in range(LARGO_CLAVE))


def usuarios_de_demo() -> tuple:
    from app import auth
    return (("administrador", auth.ROL_ADMINISTRADOR), ("supervisor", auth.ROL_SUPERVISOR), ("operador", auth.ROL_OPERADOR))


def preparar(db, clave_unica: str | None = None, restablecer: bool = False, ventanilla: str | None = "V-01") -> list:
    """
    Crea (o restablece) los usuarios de demostración. Devuelve, por usuario:
    {usuario, rol, accion: creado | existente | restablecido | omitido, clave, aviso}; `clave` solo viene si se acaba de fijar.
    """
    from app import asignaciones, auth

    if clave_unica is not None:
        auth.validar_clave(clave_unica)
    resultados = []
    for usuario, rol in usuarios_de_demo():
        fila = {"usuario": usuario, "rol": rol, "accion": "existente", "clave": None, "aviso": ""}
        existente = auth.obtener_usuario(db, usuario)
        clave = clave_unica or generar_clave()
        if existente is None:
            auth.crear_usuario(db, usuario, clave, rol=rol, estado=auth.ESTADO_ACTIVO, habilitado_por=POR)
            fila.update(accion="creado", clave=clave)
        elif existente.get("rol") != rol or existente.get("estado") != auth.ESTADO_ACTIVO:
            fila.update(accion="omitido", aviso=f"ya existe como {existente.get('rol')} ({existente.get('estado')}); no se modifica")
        elif restablecer:
            auth.restablecer_clave(db, usuario, clave, por=POR)
            fila.update(accion="restablecido", clave=clave)
        resultados.append(fila)

    operador = next(f for f in resultados if f["rol"] == auth.ROL_OPERADOR)
    if ventanilla and operador["accion"] != "omitido":
        try:
            if asignaciones.ventanilla_de(db, operador["usuario"]):
                operador["aviso"] = f"conserva su ventanilla {asignaciones.ventanilla_de(db, operador['usuario'])}"
            else:
                asignaciones.asignar_ventanilla(db, operador["usuario"], ventanilla, por=POR)
                operador["aviso"] = f"ventanilla {ventanilla} asignada"
        except auth.AuthError as e:
            operador["aviso"] = f"sin ventanilla: {e}"
            operador["error"] = True
    return resultados


def imprimir(resultados: list) -> None:
    print(f"\n  {'Usuario':<15} {'Rol':<15} {'Acción':<13} Contraseña")
    print(f"  {'-' * 15} {'-' * 15} {'-' * 13} {'-' * 14}")
    for f in resultados:
        print(f"  {f['usuario']:<15} {f['rol']:<15} {f['accion']:<13} {f['clave'] or '(sin cambios)'}")
        if f["aviso"]:
            print(f"      · {f['aviso']}")
    if any(f["clave"] for f in resultados):
        print("\n  Copie las contraseñas al PDF de entrega: no se vuelven a mostrar y no se guardan en ningún archivo.")


def main(argv=None, db=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ventanilla", default="V-01", metavar="V-NN", help="ventanilla que se asigna al operador (por defecto V-01)")
    p.add_argument("--sin-asignar", action="store_true", help="no asignar ventanilla al operador")
    p.add_argument("--restablecer", action="store_true", help="poner contraseñas nuevas a los usuarios de demostración que ya existen")
    args = p.parse_args(argv)

    from app import auth
    try:
        if db is None:
            from app.main import get_db                   # se importa aquí: lee el .env y crea la conexión
            db = get_db()
        resultados = preparar(db, clave_unica=os.getenv("QLINE_DEMO_CLAVE") or None, restablecer=args.restablecer,
                              ventanilla=None if args.sin_asignar else args.ventanilla)
    except auth.AuthError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    imprimir(resultados)
    return 1 if any(f.get("error") for f in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
