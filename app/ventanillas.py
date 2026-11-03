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

# Código reservado para la ventanilla temporal de la prueba de P09: nunca cuenta para la numeración consecutiva.
VENTANILLA_PRUEBA = "V-98"


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


def siguiente_codigo_ventanilla(db: Optional[Database] = None) -> str:
    """
    Próximo código consecutivo con el formato V-NN (V-04, V-05, ... V-08): el número más alto
    registrado (activas o inactivas, de cualquier sede) más uno, y nunca menos que las base.
    """
    mayor = max(int(v.split("-")[1]) for v in VENTANILLAS)
    if db is not None:
        for d in db[COLECCION_VENTANILLAS].find({}, {"codigo": 1}):
            codigo = d.get("codigo")
            if (isinstance(codigo, str) and codigo != VENTANILLA_PRUEBA
                    and re.fullmatch(PATRON_CODIGO_VENTANILLA, codigo)):
                mayor = max(mayor, int(codigo.split("-")[1]))
    return f"V-{mayor + 1:02d}"


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
    codigo: Optional[str] = None,
    nombre: Optional[str] = None,
    tipo: str = "general",
    sucursal: str = "central",
) -> dict:
    """
    Registra o reactiva una ventanilla en MongoDB (P09 / RFC-004).
    Valida el formato del código, asocia la sucursal y garantiza que quede lista para atención.
    Sin código, asigna el siguiente consecutivo (V-04, V-05, ...).
    """
    codigo_norm = validar_codigo_ventanilla(codigo) if codigo and codigo.strip() else siguiente_codigo_ventanilla(db)
    tipo_norm = tipo.strip().lower() if tipo else "general"
    if tipo_norm not in TIPOS_VENTANILLA:
        tipo_norm = "general"

    nombre_def = nombre.strip() if nombre and nombre.strip() else f"Ventanilla {codigo_norm}"
    ahora = datetime.now(timezone.utc)
    col = db[COLECCION_VENTANILLAS]

    filtro = {"codigo": codigo_norm}
    if sucursal:
        filtro["sucursal"] = sucursal

    doc_existente = col.find_one(filtro)
    if doc_existente:
        col.update_one(
            {"_id": doc_existente["_id"]},
            {
                "$set": {
                    "sucursal": sucursal,
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
            "sucursal": sucursal,
            "codigo": codigo_norm,
            "nombre": nombre_def,
            "tipo": tipo_norm,
            "estado": "activa",
        }

    nuevo_doc = {
        "sucursal": sucursal,
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
        "sucursal": sucursal,
        "codigo": codigo_norm,
        "nombre": nombre_def,
        "tipo": tipo_norm,
        "estado": "activa",
    }


def desactivar_ventanilla(db: Database, codigo: str, sucursal: Optional[str] = None) -> dict:
    """
    Desactiva una ventanilla verificando que no tenga turnos activos en curso
    (estados 'llamado' o 'en_atencion') para preservar la consistencia operacional.
    """
    codigo_norm = validar_codigo_ventanilla(codigo)
    col_turnos = db[COLECCION_TURNOS]

    filtro_turno = {
        "servicio": SERVICIO_ID,
        "ventanilla": codigo_norm,
        "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
    }
    if sucursal:
        filtro_turno["sucursal"] = sucursal

    turno_activo = col_turnos.find_one(filtro_turno)
    if turno_activo:
        raise VentanillaError(
            f"No se puede desactivar la ventanilla {codigo_norm} porque tiene el turno "
            f"'{turno_activo.get('codigo')}' activo en estado '{turno_activo.get('estado')}'."
        )

    col_ventanillas = db[COLECCION_VENTANILLAS]
    ahora = datetime.now(timezone.utc)
    filtro_v = {"codigo": codigo_norm}
    if sucursal:
        filtro_v["sucursal"] = sucursal

    res = col_ventanillas.update_one(
        filtro_v,
        {"$set": {"estado": "inactiva", "actualizado_en": ahora}},
    )

    if res.matched_count == 0:
        # Si no existía en colección, la crea como inactiva
        col_ventanillas.insert_one({
            "sucursal": sucursal or "central",
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


def reactivar_ventanilla(db: Database, codigo: str, sucursal: Optional[str] = None) -> dict:
    """Reactiva una ventanilla que estaba en estado 'inactiva'."""
    codigo_norm = validar_codigo_ventanilla(codigo)
    col = db[COLECCION_VENTANILLAS]
    ahora = datetime.now(timezone.utc)

    filtro = {"codigo": codigo_norm}
    if sucursal:
        filtro["sucursal"] = sucursal

    col.update_one(
        filtro,
        {
            "$set": {
                "estado": "activa",
                "actualizado_en": ahora,
            },
            "$setOnInsert": {
                "sucursal": sucursal or "central",
                "nombre": f"Ventanilla {codigo_norm}",
                "tipo": "general",
                "creado_en": ahora,
            },
        },
        upsert=True,
    )
    return {
        "ok": True,
        "accion": "reactivada",
        "codigo": codigo_norm,
        "estado": "activa",
    }


def listar_ventanillas(
    db: Optional[Database] = None,
    solo_activas: bool = False,
    sucursal: Optional[str] = None,
) -> list[dict]:
    """
    Devuelve la lista de ventanillas registradas con su estado y metadatos.
    Si se especifica sucursal, filtra por dicha sede (con fallback canónico a 'central').
    """
    if db is not None:
        try:
            col = db[COLECCION_VENTANILLAS]
            filtro = {}
            if solo_activas:
                filtro["estado"] = "activa"
            if sucursal:
                if sucursal == "central":
                    filtro["$or"] = [{"sucursal": "central"}, {"sucursal": {"$exists": False}}]
                else:
                    filtro["sucursal"] = sucursal

            docs = list(col.find(filtro).sort("codigo", 1))
            if docs:
                resultado = []
                for d in docs:
                    resultado.append({
                        "sucursal": d.get("sucursal", "central"),
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
            "sucursal": "central",
            "codigo": v,
            "nombre": f"Ventanilla {v.split('-')[-1]}",
            "tipo": "general",
            "estado": "activa",
        }
        for v in VENTANILLAS
    ]


def obtener_codigos_ventanillas(
    db: Optional[Database] = None,
    solo_activas: bool = True,
    sucursal: Optional[str] = None,
) -> list[str]:
    """Devuelve únicamente la lista de strings con los códigos de ventanilla."""
    ventanillas = listar_ventanillas(db=db, solo_activas=solo_activas, sucursal=sucursal)
    return [v["codigo"] for v in ventanillas]



# --- Catálogo operativo (P09 conectado a la operación) ------------------------------------------

_ULTIMAS_CONOCIDAS: tuple = tuple(VENTANILLAS)


def _orden_ventanilla(codigo: str):
    return (int(codigo.split("-")[1]), codigo)


def ventanillas_activas(db: Optional[Database] = None) -> tuple:
    """
    Códigos de las ventanillas que pueden operar (llamar y atender), según el catálogo de MongoDB.

    - Con el catálogo vacío o sin inicializar, son las tres ventanillas base (V-01 a V-03).
    - Una ventanilla desactivada deja de poder llamar; las demás siguen operando.
    - Si MongoDB no responde se devuelve el último catálogo conocido (o las base), nunca se lanza.
    """
    global _ULTIMAS_CONOCIDAS
    if db is None:
        return _ULTIMAS_CONOCIDAS
    try:
        col = db[COLECCION_VENTANILLAS]
        if col.find_one({}) is None:
            _ULTIMAS_CONOCIDAS = tuple(VENTANILLAS)
            return _ULTIMAS_CONOCIDAS
        codigos = {
            d["codigo"] for d in col.find({"estado": "activa"})
            if isinstance(d.get("codigo"), str) and re.fullmatch(PATRON_CODIGO_VENTANILLA, d["codigo"])
        }
        _ULTIMAS_CONOCIDAS = tuple(sorted(codigos, key=_orden_ventanilla))
        return _ULTIMAS_CONOCIDAS
    except Exception:  # noqa: BLE001 · la operación no debe caerse porque falle la consulta del catálogo
        return _ULTIMAS_CONOCIDAS


def codigos_para_consulta(db: Optional[Database] = None) -> tuple:
    """Todas las ventanillas conocidas (activas e inactivas) más las base: para filtros de historial."""
    try:
        registradas = obtener_codigos_ventanillas(db, solo_activas=False) if db is not None else []
    except Exception:  # noqa: BLE001
        registradas = []
    return tuple(sorted(set(VENTANILLAS) | set(registradas), key=_orden_ventanilla))
