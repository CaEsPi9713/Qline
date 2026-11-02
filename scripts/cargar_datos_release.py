"""
TT-028 · Script reproducible de inicialización y carga de MongoDB para release.

Responsable: Carlos Espinoza (cespinoza)
Objetivo:
  - Configurar las colecciones `turnos` y `ventanillas` con sus validadores e índices oficiales.
  - Cargar el dataset representativo de release/demostración de forma idempotente (upsert por código).
  - Validar la consistencia de los datos contra el JSON Schema oficial (TT-002).
  - Ejecutar un health check del aggregation pipeline de métricas y SLA (HU-011).

Uso:
  python scripts/cargar_datos_release.py
  python scripts/cargar_datos_release.py --turnos 60 --json
  python scripts/cargar_datos_release.py --limpiar --confirmar
  python scripts/cargar_datos_release.py --simulado
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import sys
from typing import Any, Optional

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from app.constantes import (  # noqa: E402
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    SERVICIO_ID,
    VENTANILLAS,
)
from app.dashboard import calcular_metricas_dashboard  # noqa: E402
from app.turnos_schema import (  # noqa: E402
    COLECCION_TURNOS,
    INDICES_TURNOS,
    obtener_validador_turnos,
    validar_documento_turno,
)
from app.ventanillas import (  # noqa: E402
    COLECCION_VENTANILLAS,
    inicializar_ventanillas_base,
    listar_ventanillas,
)


def preparar_colecciones_e_indices(db: Any) -> dict:
    """Aplica validadores JSON Schema e índices oficiales en MongoDB."""
    resultado = {
        "turnos_validador": False,
        "turnos_indices": [],
        "ventanillas_inicializadas": 0,
    }

    # 1. Colección turnos y validador
    col_names = db.list_collection_names()
    if COLECCION_TURNOS not in col_names:
        try:
            db.create_collection(
                COLECCION_TURNOS,
                validator=obtener_validador_turnos(),
                validationLevel="strict",
                validationAction="error",
            )
            resultado["turnos_validador"] = True
        except Exception:
            # En servidores compartidos sin permisos de administración, crear normal
            db.create_collection(COLECCION_TURNOS)
    else:
        try:
            db.command({
                "collMod": COLECCION_TURNOS,
                "validator": obtener_validador_turnos(),
                "validationLevel": "strict",
                "validationAction": "error",
            })
            resultado["turnos_validador"] = True
        except Exception:
            # Si el usuario no tiene permiso collMod, continuar con validación en aplicación
            pass

    # 2. Índices de turnos
    col_t = db[COLECCION_TURNOS]
    for idx in INDICES_TURNOS:
        nombre = idx["options"].get("name", "idx")
        try:
            col_t.create_index(idx["keys"], **idx["options"])
            resultado["turnos_indices"].append(nombre)
        except Exception:
            pass

    # 3. Inicializar ventanillas base
    ventanillas_base = inicializar_ventanillas_base(db)
    resultado["ventanillas_inicializadas"] = len(ventanillas_base)

    return resultado


def generar_dataset_release(cantidad: int = 50, semilla: int = 42) -> list[dict]:
    """Genera turnos consistentes y realistas para release con cumplimiento de SLA y distribución equilibrada."""
    rng = random.Random(semilla)
    docs = []
    ahora = datetime.now(timezone.utc)
    base_tiempo = ahora - timedelta(hours=4)

    for i in range(1, cantidad + 1):
        codigo = f"A-{i:03d}"
        es_preferencial = (i % 4 == 0)
        prioridad = PRIORIDAD_PREFERENCIAL if es_preferencial else PRIORIDAD_NORMAL

        # Distribución de estados: primeros son atendidos, algunos abandonados, y los últimos activos
        if i <= int(cantidad * 0.70):
            estado = ESTADO_ATENDIDO
        elif i <= int(cantidad * 0.80):
            estado = ESTADO_ABANDONADO
        elif i <= int(cantidad * 0.90):
            estado = ESTADO_EN_ATENCION
        elif i <= int(cantidad * 0.95):
            estado = ESTADO_LLAMADO
        else:
            estado = ESTADO_PENDIENTE

        creado = base_tiempo + timedelta(minutes=(i * 4))
        llamado = None
        inicio_atencion = None
        finalizado = None
        abandonado = None
        ventanilla = None
        operador = None
        espera_seg = None
        atencion_seg = None

        if estado != ESTADO_PENDIENTE:
            ventanilla = rng.choice(VENTANILLAS)
            operador = f"operador_{ventanilla.lower().replace('-', '_')}"
            # Esperas realistas: la mayoría entre 60 y 240s, algunos más altos
            espera_seg = rng.randint(45, 260) if (i % 7 != 0) else rng.randint(310, 500)
            llamado = creado + timedelta(seconds=espera_seg)

            if estado in (ESTADO_EN_ATENCION, ESTADO_ATENDIDO):
                t_presentacion = rng.randint(15, 30)
                inicio_atencion = llamado + timedelta(seconds=t_presentacion)

                if estado == ESTADO_ATENDIDO:
                    atencion_seg = rng.randint(90, 240)
                    finalizado = inicio_atencion + timedelta(seconds=atencion_seg)
            elif estado == ESTADO_ABANDONADO:
                abandonado = llamado + timedelta(seconds=180)

        doc = {
            "codigo": codigo,
            "servicio": SERVICIO_ID,
            "prioridad": prioridad,
            "estado": estado,
            "ventanilla": ventanilla,
            "operador": operador,
            "qr_token": None,
            "timestamps": {
                "creado": creado,
                "llamado": llamado,
                "inicio_atencion": inicio_atencion,
                "finalizado": finalizado,
                "abandonado": abandonado,
            },
            "metricas": {
                "espera_seg": espera_seg,
                "atencion_seg": atencion_seg,
            },
        }

        # Validar consistencia técnica del turno contra el esquema oficial
        validar_documento_turno(doc)
        docs.append(doc)

    return docs


def cargar_datos_release(
    db: Any,
    cantidad: int = 50,
    limpiar: bool = False,
) -> dict:
    """Carga de forma reproducible e idempotente los datos de release en MongoDB."""
    col_turnos = db[COLECCION_TURNOS]

    if limpiar:
        col_turnos.delete_many({"servicio": SERVICIO_ID})

    # Asegurar colecciones e índices
    meta_prep = preparar_colecciones_e_indices(db)

    # Generar y cargar turnos
    dataset = generar_dataset_release(cantidad=cantidad)
    insertados = 0
    actualizados = 0

    for doc in dataset:
        res = col_turnos.update_one(
            {"codigo": doc["codigo"], "servicio": doc["servicio"]},
            {"$set": doc},
            upsert=True,
        )
        if res.upserted_id:
            insertados += 1
        elif res.modified_count > 0:
            actualizados += 1

    # Verificación de salud con aggregation pipelines (HU-011)
    health = calcular_metricas_dashboard(db)

    return {
        "ok": True,
        "servicio": SERVICIO_ID,
        "turnos_solicitados": cantidad,
        "insertados": insertados,
        "actualizados": actualizados,
        "total_en_coleccion": col_turnos.count_documents({"servicio": SERVICIO_ID}),
        "indices_configurados": meta_prep["turnos_indices"],
        "ventanillas_activas": len(listar_ventanillas(db, solo_activas=True)),
        "health_check": {
            "total_turnos": health["totales"]["total_turnos"],
            "atendidos": health["totales"]["atendidos"],
            "porcentaje_cumplimiento_sla": health["sla"]["porcentaje_cumplimiento"],
            "estado_sla": health["sla"]["estado"],
        },
    }


def main(argumentos=None) -> int:
    parser = argparse.ArgumentParser(
        description="Script reproducible de inicialización y carga de MongoDB para release (TT-028).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--turnos", type=int, default=50, help="Cantidad de turnos representativos a sembrar (default: 50).")
    parser.add_argument("--limpiar", action="store_true", help="Limpia los turnos previos antes de cargar.")
    parser.add_argument("--confirmar", action="store_true", help="Confirmación obligatoria para usar con --limpiar.")
    parser.add_argument("--simulado", action="store_true", help="Ejecuta en base de datos en memoria (mongomock) para pruebas y CI.")
    parser.add_argument("--json", action="store_true", help="Imprime el resultado en formato JSON estructurado.")

    args = parser.parse_args(argumentos)

    if args.limpiar and not args.confirmar:
        print("Error: --limpiar requiere --confirmar.", file=sys.stderr)
        return 2

    if args.simulado:
        import mongomock
        db = mongomock.MongoClient().db
    else:
        try:
            from app.main import get_db
            db = get_db()
        except Exception as e:
            print(f"Error conectando con MongoDB: {e}", file=sys.stderr)
            return 1

    try:
        resultado = cargar_datos_release(
            db,
            cantidad=args.turnos,
            limpiar=args.limpiar,
        )
    except Exception as e:
        print(f"Error cargando datos de release: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    else:
        print(f"[OK] Inicialización y carga de release completada con éxito (TT-028).")
        print(f"     - Servicio: {resultado['servicio']}")
        print(f"     - Total turnos en colección: {resultado['total_en_coleccion']}")
        print(f"     - Ventanillas activas: {resultado['ventanillas_activas']}")
        print(f"     - Índices configurados: {len(resultado['indices_configurados'])}")
        print(f"     - Health check SLA: {resultado['health_check']['porcentaje_cumplimiento_sla']}% ({resultado['health_check']['estado_sla']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
