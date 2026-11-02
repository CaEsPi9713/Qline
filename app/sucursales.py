"""
Módulo de Mantenimiento Lógico de Sucursales y Onboarding de Ventanillas (RFC-004).

Responsable: Carlos Espinoza (cespinoza)
Permite la administración de sucursales institucionales y el aprovisionamiento
automático de capacidad (ventanillas), gobernanza de esquemas e índices en MongoDB,
y preservación del principio de compatibilidad hacia atrás mediante 'central'.
"""
from datetime import datetime, timezone
import re
from typing import Any, Optional

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.constantes import (
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    SERVICIO_ID,
    VENTANILLAS,
)

COLECCION_SUCURSALES = "sucursales"
COLECCION_VENTANILLAS = "ventanillas"
COLECCION_TURNOS = "turnos"

SUCURSAL_DEFECTO = "central"
NOMBRE_SUCURSAL_DEFECTO = "Sede Central - San José"

ESTADOS_SUCURSAL = ("activa", "inactiva", "mantenimiento")
PATRON_CODIGO_SUCURSAL = r"^[a-z0-9_-]{3,20}$"


class SucursalError(Exception):
    """Excepción para errores de validación o lógica de negocio en sucursales."""
    pass


def validar_codigo_sucursal(codigo: str) -> str:
    """Valida y normaliza el identificador canónico de una sucursal."""
    if not codigo or not isinstance(codigo, str):
        raise SucursalError("El código de sucursal es obligatorio y debe ser una cadena de texto.")
    codigo_norm = codigo.strip().lower()
    if not re.fullmatch(PATRON_CODIGO_SUCURSAL, codigo_norm):
        raise SucursalError(
            f"Código de sucursal inválido: {codigo!r}. Debe tener entre 3 y 20 caracteres "
            f"alfanuméricos en minúsculas (guiones y guiones bajos permitidos)."
        )
    return codigo_norm


def configurar_indices_sucursales(db: Database) -> list[str]:
    """
    Garantiza la creación idempotente de los índices requeridos para
    la arquitectura multi-sucursal en MongoDB.
    """
    col_sucursales = db[COLECCION_SUCURSALES]
    col_ventanillas = db[COLECCION_VENTANILLAS]
    col_turnos = db[COLECCION_TURNOS]

    indices_creados = []

    try:
        col_sucursales.create_index(
            [("codigo", 1)],
            unique=True,
            name="idx_sucursales_codigo_unico",
        )
        indices_creados.append("idx_sucursales_codigo_unico")

        col_sucursales.create_index(
            [("estado", 1), ("nombre", 1)],
            name="idx_sucursales_estado_nombre",
        )
        indices_creados.append("idx_sucursales_estado_nombre")
    except Exception:
        pass

    try:
        col_ventanillas.create_index(
            [("sucursal", 1), ("codigo", 1)],
            unique=True,
            name="idx_ventanillas_sucursal_codigo_unico",
        )
        indices_creados.append("idx_ventanillas_sucursal_codigo_unico")
    except Exception:
        pass

    try:
        col_turnos.create_index(
            [("sucursal", 1), ("estado", 1), ("timestamps.creado", 1)],
            name="idx_turnos_sucursal_estado_creado",
        )
        indices_creados.append("idx_turnos_sucursal_estado_creado")
    except Exception:
        pass

    return indices_creados


def inicializar_sucursal_base(db: Database) -> dict:
    """
    Garantiza que la sucursal canónica predeterminada ('central')
    exista en MongoDB con sus ventanillas iniciales aprovisionadas.
    """
    configurar_indices_sucursales(db)
    col = db[COLECCION_SUCURSALES]
    ahora = datetime.now(timezone.utc)

    doc_central = col.find_one({"codigo": SUCURSAL_DEFECTO})
    if not doc_central:
        doc_central = {
            "codigo": SUCURSAL_DEFECTO,
            "nombre": NOMBRE_SUCURSAL_DEFECTO,
            "direccion": "Avenida Segunda, Edificio Principal",
            "telefono": "+506 2222-0000",
            "estado": "activa",
            "servicios_habilitados": [SERVICIO_ID],
            "configuracion_ventanillas": {
                "cantidad_total": len(VENTANILLAS),
                "prefijo": "V",
                "numeracion_inicio": 1,
            },
            "configuracion_sla": {
                "objetivo_max_espera_seg": 300,
                "tasa_minima_cumplimiento": 80.0,
            },
            "timestamps": {
                "creado": ahora,
                "actualizado": ahora,
            },
            "metadatos": {
                "creado_por": "sistema",
                "notas": "Sede central de atención institucional",
            },
        }
        col.insert_one(doc_central)

    # Asegurar que las ventanillas base pertenezcan a la sucursal central
    col_v = db[COLECCION_VENTANILLAS]
    for v in VENTANILLAS:
        doc_v = col_v.find_one({"codigo": v})
        if not doc_v:
            num = v.split("-")[-1]
            col_v.insert_one({
                "sucursal": SUCURSAL_DEFECTO,
                "codigo": v,
                "nombre": f"Ventanilla {num}",
                "tipo": "general",
                "estado": "activa",
                "creado_en": ahora,
                "actualizado_en": ahora,
            })
        elif "sucursal" not in doc_v:
            col_v.update_one({"_id": doc_v["_id"]}, {"$set": {"sucursal": SUCURSAL_DEFECTO}})

    return doc_central


def crear_sucursal_con_ventanillas(
    db: Database,
    codigo: str,
    nombre: str,
    direccion: str = "",
    telefono: str = "",
    cantidad_ventanillas: int = 3,
    prefijo_ventanilla: str = "V",
    objetivo_max_espera_seg: int = 300,
    tasa_minima_cumplimiento: float = 80.0,
    creado_por: str = "admin",
) -> dict:
    """
    Crea una nueva sucursal y aprovisiona atómicamente sus N ventanillas en MongoDB (RFC-004).
    Valida identificadores, reglas SLA y evita colisiones por clave única.
    """
    codigo_norm = validar_codigo_sucursal(codigo)
    nombre_limpio = (nombre or "").strip()
    if not nombre_limpio or len(nombre_limpio) < 3:
        raise SucursalError("El nombre de la sucursal es obligatorio y debe tener al menos 3 caracteres.")

    if not isinstance(cantidad_ventanillas, int) or cantidad_ventanillas < 1 or cantidad_ventanillas > 50:
        raise SucursalError("La cantidad de ventanillas a aprovisionar debe ser un entero entre 1 y 50.")

    if objetivo_max_espera_seg < 60 or objetivo_max_espera_seg > 3600:
        raise SucursalError("El objetivo de espera SLA debe situarse entre 60 y 3600 segundos.")

    col_sucursales = db[COLECCION_SUCURSALES]
    if col_sucursales.find_one({"codigo": codigo_norm}):
        raise SucursalError(f"La sucursal con código '{codigo_norm}' ya se encuentra registrada.")

    ahora = datetime.now(timezone.utc)
    prefijo_norm = (prefijo_ventanilla or "V").strip().upper()

    doc_sucursal = {
        "codigo": codigo_norm,
        "nombre": nombre_limpio,
        "direccion": (direccion or "").strip(),
        "telefono": (telefono or "").strip(),
        "estado": "activa",
        "servicios_habilitados": [SERVICIO_ID],
        "configuracion_ventanillas": {
            "cantidad_total": cantidad_ventanillas,
            "prefijo": prefijo_norm,
            "numeracion_inicio": 1,
        },
        "configuracion_sla": {
            "objetivo_max_espera_seg": int(objetivo_max_espera_seg),
            "tasa_minima_cumplimiento": float(tasa_minima_cumplimiento),
        },
        "timestamps": {
            "creado": ahora,
            "actualizado": ahora,
        },
        "metadatos": {
            "creado_por": creado_por,
            "notas": f"Sucursal creada con aprovisionamiento inicial de {cantidad_ventanillas} ventanillas",
        },
    }

    try:
        col_sucursales.insert_one(doc_sucursal)
    except DuplicateKeyError:
        raise SucursalError(f"La sucursal con código '{codigo_norm}' ya existe.")

    # Aprovisionar automáticamente las N ventanillas
    col_ventanillas = db[COLECCION_VENTANILLAS]
    ventanillas_creadas = []
    for i in range(1, cantidad_ventanillas + 1):
        cod_v = f"{prefijo_norm}-{i:02d}"
        doc_v = {
            "sucursal": codigo_norm,
            "codigo": cod_v,
            "nombre": f"Ventanilla {i}",
            "tipo": "general" if i > 1 else "preferencial",
            "estado": "activa",
            "creado_en": ahora,
            "actualizado_en": ahora,
        }
        col_ventanillas.update_one(
            {"sucursal": codigo_norm, "codigo": cod_v},
            {"$set": doc_v},
            upsert=True,
        )
        ventanillas_creadas.append(cod_v)

    return {
        "ok": True,
        "accion": "creada",
        "codigo": codigo_norm,
        "nombre": nombre_limpio,
        "cantidad_ventanillas": cantidad_ventanillas,
        "ventanillas": ventanillas_creadas,
        "estado": "activa",
    }


def actualizar_sucursal(
    db: Database,
    codigo: str,
    nombre: Optional[str] = None,
    direccion: Optional[str] = None,
    telefono: Optional[str] = None,
    cantidad_ventanillas: Optional[int] = None,
    estado: Optional[str] = None,
    objetivo_max_espera_seg: Optional[int] = None,
    tasa_minima_cumplimiento: Optional[float] = None,
) -> dict:
    """
    Modifica parámetros de la sucursal y ajusta dinámicamente la capacidad de ventanillas.
    Si se reduce la cantidad de ventanillas, valida que los módulos a deshabilitar
    no tengan turnos activos en atención.
    """
    codigo_norm = validar_codigo_sucursal(codigo)
    col_sucursales = db[COLECCION_SUCURSALES]
    sucursal = col_sucursales.find_one({"codigo": codigo_norm})
    if not sucursal:
        raise SucursalError(f"No existe la sucursal con código '{codigo_norm}'.")

    update_fields = {}
    ahora = datetime.now(timezone.utc)
    update_fields["timestamps.actualizado"] = ahora

    if nombre is not None:
        nombre_limpio = nombre.strip()
        if len(nombre_limpio) < 3:
            raise SucursalError("El nombre de la sucursal debe tener al menos 3 caracteres.")
        update_fields["nombre"] = nombre_limpio

    if direccion is not None:
        update_fields["direccion"] = direccion.strip()

    if telefono is not None:
        update_fields["telefono"] = telefono.strip()

    if estado is not None:
        estado_norm = estado.strip().lower()
        if estado_norm not in ESTADOS_SUCURSAL:
            raise SucursalError(f"Estado de sucursal inválido: {estado!r}. Opciones: {ESTADOS_SUCURSAL}")
        update_fields["estado"] = estado_norm

    if objetivo_max_espera_seg is not None:
        if objetivo_max_espera_seg < 60 or objetivo_max_espera_seg > 3600:
            raise SucursalError("El objetivo SLA debe situarse entre 60 y 3600 segundos.")
        update_fields["configuracion_sla.objetivo_max_espera_seg"] = int(objetivo_max_espera_seg)

    if tasa_minima_cumplimiento is not None:
        update_fields["configuracion_sla.tasa_minima_cumplimiento"] = float(tasa_minima_cumplimiento)

    # Ajuste de capacidad de ventanillas
    col_ventanillas = db[COLECCION_VENTANILLAS]
    col_turnos = db[COLECCION_TURNOS]
    prefijo = sucursal.get("configuracion_ventanillas", {}).get("prefijo", "V")
    cant_actual = sucursal.get("configuracion_ventanillas", {}).get("cantidad_total", 3)

    if cantidad_ventanillas is not None and cantidad_ventanillas != cant_actual:
        if not isinstance(cantidad_ventanillas, int) or cantidad_ventanillas < 1 or cantidad_ventanillas > 50:
            raise SucursalError("La cantidad de ventanillas debe ser un entero entre 1 y 50.")

        if cantidad_ventanillas > cant_actual:
            # Incrementar ventanillas
            for i in range(cant_actual + 1, cantidad_ventanillas + 1):
                cod_v = f"{prefijo}-{i:02d}"
                col_ventanillas.update_one(
                    {"sucursal": codigo_norm, "codigo": cod_v},
                    {
                        "$set": {
                            "sucursal": codigo_norm,
                            "codigo": cod_v,
                            "nombre": f"Ventanilla {i}",
                            "tipo": "general",
                            "estado": "activa",
                            "actualizado_en": ahora,
                        },
                        "$setOnInsert": {"creado_en": ahora},
                    },
                    upsert=True,
                )
        else:
            # Reducir ventanillas: validar que los módulos a deshabilitar no tengan turnos en curso
            ventanillas_a_remover = [f"{prefijo}-{i:02d}" for i in range(cantidad_ventanillas + 1, cant_actual + 1)]
            turno_activo = col_turnos.find_one({
                "sucursal": codigo_norm,
                "ventanilla": {"$in": ventanillas_a_remover},
                "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
            })
            if turno_activo:
                raise SucursalError(
                    f"No se puede reducir la capacidad: la ventanilla {turno_activo.get('ventanilla')} "
                    f"tiene activo el turno '{turno_activo.get('codigo')}' en estado '{turno_activo.get('estado')}'."
                )

            for cod_rem in ventanillas_a_remover:
                col_ventanillas.update_one(
                    {"sucursal": codigo_norm, "codigo": cod_rem},
                    {"$set": {"estado": "inactiva", "actualizado_en": ahora}},
                )

        update_fields["configuracion_ventanillas.cantidad_total"] = cantidad_ventanillas

    col_sucursales.update_one({"codigo": codigo_norm}, {"$set": update_fields})
    return {
        "ok": True,
        "accion": "actualizada",
        "codigo": codigo_norm,
    }


def desactivar_sucursal_segura(db: Database, codigo: str) -> dict:
    """
    Desactiva una sucursal verificando previamente que no existan turnos
    en curso en sus módulos de atención (guardián de consistencia).
    """
    codigo_norm = validar_codigo_sucursal(codigo)
    col_turnos = db[COLECCION_TURNOS]

    turnos_activos = col_turnos.count_documents({
        "sucursal": codigo_norm,
        "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
    })
    if turnos_activos > 0:
        raise SucursalError(
            f"No se puede desactivar la sucursal '{codigo_norm}' porque "
            f"tiene {turnos_activos} turno(s) en atención activa en ventanilla."
        )

    col_sucursales = db[COLECCION_SUCURSALES]
    ahora = datetime.now(timezone.utc)
    res = col_sucursales.update_one(
        {"codigo": codigo_norm},
        {"$set": {"estado": "inactiva", "timestamps.actualizado": ahora}},
    )
    if res.matched_count == 0:
        raise SucursalError(f"No existe la sucursal con código '{codigo_norm}'.")

    return {
        "ok": True,
        "accion": "desactivada",
        "codigo": codigo_norm,
        "estado": "inactiva",
    }


def reactivar_sucursal(db: Database, codigo: str) -> dict:
    """Reactiva una sucursal que se encontraba inactiva o en mantenimiento."""
    codigo_norm = validar_codigo_sucursal(codigo)
    col_sucursales = db[COLECCION_SUCURSALES]
    ahora = datetime.now(timezone.utc)
    res = col_sucursales.update_one(
        {"codigo": codigo_norm},
        {"$set": {"estado": "activa", "timestamps.actualizado": ahora}},
    )
    if res.matched_count == 0:
        raise SucursalError(f"No existe la sucursal con código '{codigo_norm}'.")

    return {
        "ok": True,
        "accion": "reactivada",
        "codigo": codigo_norm,
        "estado": "activa",
    }


def obtener_sucursal(db: Database, codigo: str) -> Optional[dict]:
    """Retorna los datos de la sucursal junto con el detalle de sus ventanillas."""
    codigo_norm = validar_codigo_sucursal(codigo)
    col_sucursales = db[COLECCION_SUCURSALES]
    sucursal = col_sucursales.find_one({"codigo": codigo_norm})
    if not sucursal:
        return None

    col_ventanillas = db[COLECCION_VENTANILLAS]
    # Buscar ventanillas asociadas explícitamente a la sucursal o fallback canónico a 'central'
    query_v = {"sucursal": codigo_norm} if codigo_norm != SUCURSAL_DEFECTO else {"$or": [{"sucursal": SUCURSAL_DEFECTO}, {"sucursal": {"$exists": False}}]}
    docs_v = list(col_ventanillas.find(query_v).sort("codigo", 1))

    ventanillas_detalle = []
    for d in docs_v:
        ventanillas_detalle.append({
            "codigo": d.get("codigo"),
            "nombre": d.get("nombre", f"Ventanilla {d.get('codigo')}"),
            "tipo": d.get("tipo", "general"),
            "estado": d.get("estado", "activa"),
        })

    return {
        "codigo": sucursal.get("codigo"),
        "nombre": sucursal.get("nombre"),
        "direccion": sucursal.get("direccion", ""),
        "telefono": sucursal.get("telefono", ""),
        "estado": sucursal.get("estado", "activa"),
        "configuracion_ventanillas": sucursal.get("configuracion_ventanillas", {}),
        "configuracion_sla": sucursal.get("configuracion_sla", {}),
        "ventanillas": ventanillas_detalle,
    }


def listar_sucursales(db: Database, solo_activas: bool = False) -> list[dict]:
    """
    Retorna la lista de todas las sucursales con su conteo de ventanillas y turnos activos.
    Si la base de datos aún no tiene la colección inicializada, aprovisiona la sede 'central'.
    """
    col_sucursales = db[COLECCION_SUCURSALES]
    filtro = {"estado": "activa"} if solo_activas else {}
    docs = list(col_sucursales.find(filtro).sort("nombre", 1))

    if not docs:
        inicializar_sucursal_base(db)
        docs = list(col_sucursales.find(filtro).sort("nombre", 1))

    col_ventanillas = db[COLECCION_VENTANILLAS]
    col_turnos = db[COLECCION_TURNOS]

    resultado = []
    for d in docs:
        c_cod = d.get("codigo")
        query_v = {"sucursal": c_cod} if c_cod != SUCURSAL_DEFECTO else {"$or": [{"sucursal": SUCURSAL_DEFECTO}, {"sucursal": {"$exists": False}}]}
        total_v = col_ventanillas.count_documents(query_v)
        activas_v = col_ventanillas.count_documents({**query_v, "estado": "activa"})

        # Turnos en espera o atención en esa sucursal
        turnos_activos = col_turnos.count_documents({
            "sucursal": c_cod,
            "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
        })

        resultado.append({
            "codigo": c_cod,
            "nombre": d.get("nombre"),
            "direccion": d.get("direccion", ""),
            "telefono": d.get("telefono", ""),
            "estado": d.get("estado", "activa"),
            "cantidad_ventanillas": d.get("configuracion_ventanillas", {}).get("cantidad_total", total_v),
            "ventanillas_totales": total_v,
            "ventanillas_activas": activas_v,
            "turnos_activos": turnos_activos,
            "sla_espera_max_seg": d.get("configuracion_sla", {}).get("objetivo_max_espera_seg", 300),
            "sla_tasa_minima": d.get("configuracion_sla", {}).get("tasa_minima_cumplimiento", 80.0),
        })

    return resultado
