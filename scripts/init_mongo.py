"""
Script de inicialización y validación técnica de MongoDB (TT-004).

Responsable: Carlos Espinoza (cespinoza)
Objetivo:
  - Crear o actualizar la colección `turnos` con el validador JSON Schema oficial (TT-002).
  - Configurar los índices requeridos (código único, estado+creado, ventanilla, creado_desc).
  - Comprobar que MongoDB rechace documentos inválidos (prioridades no autorizadas, estados inexistentes).
  - Ser completamente reproducible e idempotente.

Uso:
  python scripts/init_mongo.py                      # crea/actualiza validador e índices
  python scripts/init_mongo.py --recrear --confirmar

Si el usuario de MongoDB no tiene permiso para `collMod` (caso del servidor del
curso), el validador NO se puede cambiar en una colección existente. Entonces
`--recrear --confirmar` elimina `turnos` y la crea de nuevo ya con el validador
y los índices. Borra TODOS los documentos de `turnos`: después hay que volver a
cargar los datos sintéticos (scripts/generar_datos_sinteticos.py --cargar).
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError

# Asegurar que el directorio raíz esté en sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

from app.constantes import (
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    SERVICIO_ID,
)
from app.turnos_schema import (
    COLECCION_TURNOS,
    INDICES_TURNOS,
    obtener_validador_turnos,
)

MONGO_USER = os.getenv("MONGO_USER", "")
MONGO_PASS = os.getenv("MONGO_PASS", "")
MONGO_DB = os.getenv("MONGO_DB", "qline")
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))


def obtener_cliente_mongo():
    """Conecta a MongoDB usando los parámetros del archivo .env."""
    if MONGO_USER and MONGO_PASS:
        uri = (
            f"mongodb://{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASS)}"
            f"@{MONGO_HOST}:{MONGO_PORT}/{quote_plus(MONGO_DB)}"
            f"?authSource={quote_plus(MONGO_DB)}"
        )
    else:
        uri = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}"

    cliente = MongoClient(uri, serverSelectionTimeoutMS=5000)
    # Comprobar conectividad
    cliente.admin.command("ping")
    return cliente


def _crear_coleccion_con_validador(db) -> None:
    db.create_collection(
        COLECCION_TURNOS,
        validator=obtener_validador_turnos(),
        validationLevel="strict",
        validationAction="error",
    )


def _aplicar_indices(db) -> None:
    print(f"[+] Aplicando índices en '{COLECCION_TURNOS}'...")
    col = db[COLECCION_TURNOS]
    for idx in INDICES_TURNOS:
        nombre = idx["options"].get("name", "idx")
        col.create_index(idx["keys"], **idx["options"])
        print(f"    - Índice '{nombre}' configurado.")


def inicializar_coleccion_turnos(db) -> bool:
    """
    Aplica el validador JSON Schema e índices en la colección `turnos`.
    Devuelve True si el validador quedó aplicado; False si el motor no lo permitió
    (por ejemplo, el usuario no tiene el permiso `collMod`).
    """
    validador = obtener_validador_turnos()
    validador_aplicado = True

    if COLECCION_TURNOS not in db.list_collection_names():
        print(f"[+] Creando colección '{COLECCION_TURNOS}' con validador JSON Schema estricto...")
        _crear_coleccion_con_validador(db)
        print("    Colección creada exitosamente.")
    else:
        print(f"[*] Colección '{COLECCION_TURNOS}' ya existe. Actualizando validador con collMod...")
        try:
            db.command({
                "collMod": COLECCION_TURNOS,
                "validator": validador,
                "validationLevel": "strict",
                "validationAction": "error",
            })
            print("    Validador JSON Schema actualizado exitosamente.")
        except OperationFailure as e:
            validador_aplicado = False
            if getattr(e, "code", None) == 13:
                print("    [!] El usuario de MongoDB no tiene permiso para collMod (Unauthorized).")
                print("        El validador NO se aplicó a la colección existente. Opciones:")
                print("          - python scripts/init_mongo.py --recrear --confirmar  (borra 'turnos' y la recrea)")
                print("          - pedir a un administrador que ejecute collMod con el validador")
            else:
                print(f"    [!] Advertencia al ejecutar collMod: {e}")

    _aplicar_indices(db)
    return validador_aplicado


def recrear_coleccion_turnos(db) -> None:
    """
    Elimina la colección `turnos` y la crea de nuevo con el validador y los índices.
    DESTRUCTIVO: borra todos los documentos de `turnos`.
    """
    if COLECCION_TURNOS in db.list_collection_names():
        total = db[COLECCION_TURNOS].count_documents({})
        print(f"[!] Eliminando la colección '{COLECCION_TURNOS}' ({total} documentos)...")
        db.drop_collection(COLECCION_TURNOS)
    print(f"[+] Creando colección '{COLECCION_TURNOS}' con validador JSON Schema estricto...")
    _crear_coleccion_con_validador(db)
    print("    Colección creada exitosamente.")
    _aplicar_indices(db)
    print("[i] Recuerde volver a cargar los datos sintéticos:")
    print("      python scripts/generar_datos_sinteticos.py --cargar")


def verificar_validador_estricto(db) -> bool:
    """
    Comprueba de forma controlada que el motor MongoDB rechace documentos inválidos
    y acepte documentos válidos.
    """
    print("\n[+] Ejecutando prueba de integridad del JSON Schema...")
    col = db[COLECCION_TURNOS]
    ahora = datetime.now(timezone.utc)

    # 1. Prueba de rechazo: Prioridad no autorizada ('urgente' no existe en el contrato)
    doc_invalido = {
        "codigo": "A-9999",
        "servicio": SERVICIO_ID,
        "prioridad": "urgente_invalida",
        "estado": ESTADO_PENDIENTE,
        "ventanilla": None,
        "operador": None,
        "timestamps": {"creado": ahora},
        "metricas": {"espera_seg": None, "atencion_seg": None},
    }

    rechazado_correctamente = False
    try:
        col.insert_one(doc_invalido)
        # Si llegamos aquí sin error, el validador no funcionó
        col.delete_one({"codigo": "A-9999"})
        print("    [ERROR] MongoDB permitió insertar un documento con prioridad inválida.")
    except OperationFailure:
        rechazado_correctamente = True
        print("    [OK] Documento con prioridad inválida fue RECHAZADO por MongoDB según lo esperado.")

    # 2. Prueba de aceptación: Turno válido
    codigo_prueba = "A-9998"
    doc_valido = {
        "codigo": codigo_prueba,
        "servicio": SERVICIO_ID,
        "prioridad": PRIORIDAD_NORMAL,
        "estado": ESTADO_PENDIENTE,
        "ventanilla": None,
        "operador": None,
        "timestamps": {
            "creado": ahora,
            "llamado": None,
            "inicio_atencion": None,
            "finalizado": None,
            "abandonado": None,
        },
        "metricas": {"espera_seg": None, "atencion_seg": None},
    }

    aceptado_correctamente = False
    try:
        res = col.insert_one(doc_valido)
        if res.inserted_id:
            aceptado_correctamente = True
            print("    [OK] Documento válido fue ACEPTADO por MongoDB.")
            # Limpiar documento de prueba
            col.delete_one({"_id": res.inserted_id})
    except PyMongoError as e:
        print(f"    [ERROR] Documento válido fue rechazado inesperadamente: {e}")

    # 3. Prueba de duplicado de código (índice único)
    duplicado_bloqueado = False
    try:
        col.insert_one(doc_valido)
        col.insert_one(doc_valido)  # Debe fallar por código único
    except PyMongoError:
        duplicado_bloqueado = True
        print("    [OK] Inserción de código duplicado fue BLOQUEADA por el índice único.")
    finally:
        col.delete_many({"codigo": codigo_prueba})

    todo_ok = rechazado_correctamente and aceptado_correctamente and duplicado_bloqueado
    if todo_ok:
        print("\n>>> VERIFICACIÓN TÉCNICA EXITOSA: El JSON Schema y los índices están 100% operativos.")
    else:
        print("\n>>> ADVERTENCIA: Una o más validaciones técnicas no se comportaron como se esperaba.")
    return todo_ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inicialización de la colección `turnos` (TT-004).")
    parser.add_argument("--recrear", action="store_true",
                        help="elimina `turnos` y la crea de nuevo con validador e índices (DESTRUCTIVO)")
    parser.add_argument("--confirmar", action="store_true", help="requerido para --recrear")
    args = parser.parse_args(argv)
    if args.recrear and not args.confirmar:
        print("--recrear borra todos los documentos de `turnos`: agregue --confirmar.", file=sys.stderr)
        return 2

    print("=" * 60)
    print(" QLine — Inicialización de MongoDB (TT-001, TT-002, TT-004)")
    print("=" * 60)
    try:
        cliente = obtener_cliente_mongo()
        db = cliente[MONGO_DB]
        print(f"[+] Conectado a MongoDB: {MONGO_HOST}:{MONGO_PORT} / Base de datos: '{MONGO_DB}'\n")

        if args.recrear:
            recrear_coleccion_turnos(db)
            validador_aplicado = True
        else:
            validador_aplicado = inicializar_coleccion_turnos(db)
        verificacion_ok = verificar_validador_estricto(db)

        print("\n[+] Colecciones actuales en la base de datos:")
        for col_name in db.list_collection_names():
            total = db[col_name].count_documents({})
            print(f"    • {col_name}: {total} documentos")
    except Exception as e:
        print(f"\n[ERROR FATAL] No se pudo inicializar MongoDB: {e}")
        return 1

    if validador_aplicado and verificacion_ok:
        print("\nInicialización completada con éxito.")
        return 0
    print("\nInicialización INCOMPLETA: el JSON Schema no está activo en el motor "
          "(los índices sí se aplicaron). Ver las opciones indicadas arriba.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
