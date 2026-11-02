"""
Módulo de Gestión y Onboarding Dinámico de Ventanillas (P09).

Responsable: Carlos Espinoza (cespinoza)
Permite el registro, activación, desactivación y auditoría de ventanillas
de atención institucional en MongoDB preservando la consistencia operativa
y evitando eliminar o desactivar ventanillas con turnos en curso.
"""
from datetime import datetime, timezone
import re
from typing import Any, Optional

from pymongo.database import Database

from app.constantes import (
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    SERVICIO_ID,
    VENTANILLAS,
)

COLECCION_VENTANILLAS = "ventanillas"
COLECCION_TURNOS = "turnos"
PATRON_CODIGO_VENTANILLA = r"^V-[0-9]{2,}$"

TIPOS_VENTANILLA = ("general", "preferencial")


class VentanillaError(Exception):
    """Excepción para errores de validación o lógica de negocio en ventanillas."""
    pass


def validar_codigo_ventanilla(codigo: str) -> str:
    """Valida y normaliza el código de una ventanilla (ej. V-01, V-04)."""
    if not codigo or not isinstance(codigo, str):
        raise VentanillaError("El código de ventanilla es obligatorio y debe ser una cadena de texto.")
    codigo_norm = codigo.strip().upper()
    if not re.fullmatch(PATRON_CODIGO_VENTANILLA, codigo_norm):
        raise VentanillaError(
            f"Código de ventanilla inválido: {codigo!r}. Debe coincidir con el formato 'V-XX' (ej. V-01, V-04)."
        )
    return codigo_norm


def inicializar_ventanillas_base(db: Database) -> list[dict]:
    """
    Asegura que las ventanillas predeterminadas del sistema (V-01, V-02, V-03)
    existan en la colección `ventanillas` con estado 'activa'.
    """
    col = db[COLECCION_VENTANILLAS]
    ahora = datetime.now(timezone.utc)
    registradas = []

    for v in VENTANILLAS:
        doc = col.find_one({"codigo": v})
        if not doc:
            num = v.split("-")[-1]
            nuevo = {
                "codigo": v,
                "nombre": f"Ventanilla {num}",
                "tipo": "general",
                "estado": "activa",
                "creado_en": ahora,
                "actualizado_en": ahora,
            }
            col.insert_one(nuevo)
            registradas.append(nuevo)
        else:
            registradas.append(doc)

    return registradas


def registrar_ventanilla(
    db: Database,
    codigo: str,
    nombre: Optional[str] = None,
    tipo: str = "general",
) -> dict:
    """
    Registra o reactiva una ventanilla en MongoDB (P09).
    Valida el formato del código y garantiza que quede lista para atención.
    """
    codigo_norm = validar_codigo_ventanilla(codigo)
    tipo_norm = tipo.strip().lower() if tipo else "general"
    if tipo_norm not in TIPOS_VENTANILLA:
        tipo_norm = "general"

    nombre_def = nombre.strip() if nombre and nombre.strip() else f"Ventanilla {codigo_norm}"
    ahora = datetime.now(timezone.utc)
    col = db[COLECCION_VENTANILLAS]

    doc_existente = col.find_one({"codigo": codigo_norm})
    if doc_existente:
        col.update_one(
            {"_id": doc_existente["_id"]},
            {
                "$set": {
                    "nombre": nombre_def,
                    "tipo": tipo_norm,
                    "estado": "activa",
                    "actualizado_en": ahora,
                }
            },
        )
        return {
            "ok": True,
            "accion": "actualizada",
            "codigo": codigo_norm,
            "nombre": nombre_def,
            "tipo": tipo_norm,
            "estado": "activa",
        }

    nuevo_doc = {
        "codigo": codigo_norm,
        "nombre": nombre_def,
        "tipo": tipo_norm,
        "estado": "activa",
        "creado_en": ahora,
        "actualizado_en": ahora,
    }
    col.insert_one(nuevo_doc)
    return {
        "ok": True,
        "accion": "creada",
        "codigo": codigo_norm,
        "nombre": nombre_def,
        "tipo": tipo_norm,
        "estado": "activa",
    }


def desactivar_ventanilla(db: Database, codigo: str) -> dict:
    """
    Desactiva una ventanilla verificando que no tenga turnos activos en curso
    (estados 'llamado' o 'en_atencion') para preservar la consistencia operacional.
    """
    codigo_norm = validar_codigo_ventanilla(codigo)
    col_turnos = db[COLECCION_TURNOS]

    turno_activo = col_turnos.find_one({
        "servicio": SERVICIO_ID,
        "ventanilla": codigo_norm,
        "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
    })
    if turno_activo:
        raise VentanillaError(
            f"No se puede desactivar la ventanilla {codigo_norm} porque tiene el turno "
            f"'{turno_activo.get('codigo')}' activo en estado '{turno_activo.get('estado')}'."
        )

    col_ventanillas = db[COLECCION_VENTANILLAS]
    ahora = datetime.now(timezone.utc)
    res = col_ventanillas.update_one(
        {"codigo": codigo_norm},
        {"$set": {"estado": "inactiva", "actualizado_en": ahora}},
    )

    if res.matched_count == 0:
        # Si no existía en colección, la crea como inactiva
        col_ventanillas.insert_one({
            "codigo": codigo_norm,
            "nombre": f"Ventanilla {codigo_norm}",
            "tipo": "general",
            "estado": "inactiva",
            "creado_en": ahora,
            "actualizado_en": ahora,
        })

    return {
        "ok": True,
        "accion": "desactivada",
        "codigo": codigo_norm,
        "estado": "inactiva",
    }


def reactivar_ventanilla(db: Database, codigo: str) -> dict:
    """Reactiva una ventanilla que estaba en estado 'inactiva'."""
    codigo_norm = validar_codigo_ventanilla(codigo)
    col = db[COLECCION_VENTANILLAS]
    ahora = datetime.now(timezone.utc)

    col.update_one(
        {"codigo": codigo_norm},
        {"$set": {"estado": "activa", "actualizado_en": ahora}},
        upsert=True,
    )
    return {
        "ok": True,
        "accion": "reactivada",
        "codigo": codigo_norm,
        "estado": "activa",
    }


def listar_ventanillas(db: Optional[Database] = None, solo_activas: bool = False) -> list[dict]:
    """
    Devuelve la lista de ventanillas registradas con su estado y metadatos.
    Si la base de datos no tiene la colección poblada, devuelve las ventanillas
    base predeterminadas.
    """
    if db is not None:
        try:
            col = db[COLECCION_VENTANILLAS]
            filtro = {"estado": "activa"} if solo_activas else {}
            docs = list(col.find(filtro).sort("codigo", 1))
            if docs:
                resultado = []
                for d in docs:
                    resultado.append({
                        "codigo": d.get("codigo"),
                        "nombre": d.get("nombre", f"Ventanilla {d.get('codigo')}"),
                        "tipo": d.get("tipo", "general"),
                        "estado": d.get("estado", "activa"),
                    })
                return resultado
        except Exception:
            pass

    # Fallback predeterminado a las constantes del sistema
    return [
        {
            "codigo": v,
            "nombre": f"Ventanilla {v.split('-')[-1]}",
            "tipo": "general",
            "estado": "activa",
        }
        for v in VENTANILLAS
    ]


def obtener_codigos_ventanillas(db: Optional[Database] = None, solo_activas: bool = True) -> list[str]:
    """Devuelve únicamente la lista de strings con los códigos de ventanilla."""
    ventanillas = listar_ventanillas(db=db, solo_activas=solo_activas)
    return [v["codigo"] for v in ventanillas]
