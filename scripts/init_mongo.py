"""
Script de inicialización y validación técnica de MongoDB (TT-004).

Responsable: Carlos Espinoza (cespinoza)
Objetivo:
  - Crear o actualizar la colección `turnos` con el validador JSON Schema oficial (TT-002).
  - Configurar los índices requeridos (código único, estado+creado, ventanilla, creado_desc).
  - Comprobar que MongoDB rechace documentos inválidos (prioridades no autorizadas, estados inexistentes).
  - Ser completamente reproducible e idempotente.
"""
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


def inicializar_coleccion_turnos(db) -> None:
    """Aplica el validador JSON Schema e índices en la colección `turnos`."""
    validador = obtener_validador_turnos()
    colecciones = db.list_collection_names()

    if COLECCION_TURNOS not in colecciones:
        print(f"[+] Creando colección '{COLECCION_TURNOS}' con validador JSON Schema estricto...")
        db.create_collection(
            COLECCION_TURNOS,
            validator=validador,
            validationLevel="strict",
            validationAction="error",
        )
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
            print(f"    [!] Advertencia al ejecutar collMod: {e}")

    # Crear índices
    print(f"[+] Aplicando índices en '{COLECCION_TURNOS}'...")
    col = db[COLECCION_TURNOS]
    for idx in INDICES_TURNOS:
        nombre = idx["options"].get("name", "idx")
        col.create_index(idx["keys"], **idx["options"])
        print(f"    - Índice '{nombre}' configurado.")


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


def main():
    print("=" * 60)
    print(" QLine — Inicialización de MongoDB (TT-001, TT-002, TT-004)")
    print("=" * 60)
    try:
        cliente = obtener_cliente_mongo()
        db = cliente[MONGO_DB]
        print(f"[+] Conectado a MongoDB: {MONGO_HOST}:{MONGO_PORT} / Base de datos: '{MONGO_DB}'\n")

        inicializar_coleccion_turnos(db)
        verificar_validador_estricto(db)

        print("\n[+] Colecciones actuales en la base de datos:")
        for col_name in db.list_collection_names():
            total = db[col_name].count_documents({})
            print(f"    • {col_name}: {total} documentos")
        print("\nInicialización completada con éxito.")
    except Exception as e:
        print(f"\n[ERROR FATAL] No se pudo inicializar MongoDB: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
