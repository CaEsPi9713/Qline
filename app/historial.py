"""
Módulo de Historial y Auditoría de Turnos (HU-010 / HU-014).

Responsable: Carlos Espinoza (cespinoza)
Permite auditar turnos procesados y activos, trazabilidad cronológica
y cálculo derivado de tiempos de espera y atención.
"""
from datetime import datetime, timezone
from typing import Any, Optional, Union

from pymongo.database import Database

import re

from app.constantes import ESTADOS, PATRON_VENTANILLA, PRIORIDADES, SERVICIO_ID

COLECCION_TURNOS = "turnos"


def _formatear_fecha(dt) -> Optional[str]:
    """Fecha en ISO 8601 y UTC, con milisegundos y la zona explícita (`2026-10-27T01:12:49.757Z`).

    MongoDB entrega las fechas sin zona (en UTC); las pantallas las convierten a hora local con app/formato.py.
    """
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return None


def _calcular_duracion_seg(inicio, fin) -> Optional[int]:
    """Calcula la diferencia en segundos entre dos timestamps datetime."""
    if isinstance(inicio, datetime) and isinstance(fin, datetime):
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=timezone.utc)
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        return max(0, int((fin - inicio).total_seconds()))
    return None


def parsear_fecha_filtro(valor: Any, fin_de_dia: bool = False) -> Optional[datetime]:
    """
    Parsea una fecha de filtro (string YYYY-MM-DD, ISO o datetime) a datetime UTC para consultas en MongoDB.
    Si solo se indica la fecha (YYYY-MM-DD):
      - Si fin_de_dia es False, toma el inicio del día local (00:00:00) y lo convierte a UTC.
      - Si fin_de_dia es True, toma el final del día local (23:59:59.999999) y lo convierte a UTC.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        dt = valor
        if dt.tzinfo is None:
            from app.formato import zona
            dt = dt.replace(tzinfo=zona())
        return dt.astimezone(timezone.utc)
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        from app.formato import zona
        # Formato YYYY-MM-DD típico de <input type="date">
        if len(texto) == 10 and texto.count("-") == 2:
            try:
                partes = [int(p) for p in texto.split("-")]
                tz = zona()
                if fin_de_dia:
                    dt = datetime(partes[0], partes[1], partes[2], 23, 59, 59, 999999, tzinfo=tz)
                else:
                    dt = datetime(partes[0], partes[1], partes[2], 0, 0, 0, 0, tzinfo=tz)
                return dt.astimezone(timezone.utc)
            except ValueError:
                return None
        # Formato ISO con posible hora o zona
        if texto.endswith(("Z", "z")):
            texto = texto[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(texto)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zona())
            return dt.astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def obtener_historial_turnos(
    db: Database,
    estado: Optional[str] = None,
    ventanilla: Optional[str] = None,
    prioridad: Optional[str] = None,
    codigo: Optional[str] = None,
    fecha_desde: Optional[Union[str, datetime]] = None,
    fecha_hasta: Optional[Union[str, datetime]] = None,
    limite: int = 100,
    salto: int = 0,
) -> dict:
    """
    Consulta turnos en MongoDB con filtros controlados, rango de fechas y cálculo de métricas derivadas (HU-010 / S4-M04).
    Permite auditar el historial incluso si los turnos ya no están en Redis.
    """
    filtro = {"servicio": SERVICIO_ID}

    if estado and estado in ESTADOS:
        filtro["estado"] = estado
    if ventanilla and re.fullmatch(PATRON_VENTANILLA, ventanilla):
        filtro["ventanilla"] = ventanilla
    if prioridad and prioridad in PRIORIDADES:
        filtro["prioridad"] = prioridad
    if codigo and codigo.strip():
        filtro["codigo"] = codigo.strip().upper()

    dt_desde = parsear_fecha_filtro(fecha_desde, fin_de_dia=False)
    dt_hasta = parsear_fecha_filtro(fecha_hasta, fin_de_dia=True)
    if dt_desde or dt_hasta:
        filtro_fecha = {}
        if dt_desde:
            filtro_fecha["$gte"] = dt_desde
        if dt_hasta:
            filtro_fecha["$lte"] = dt_hasta
        filtro["timestamps.creado"] = filtro_fecha

    col = db[COLECCION_TURNOS]
    total = col.count_documents(filtro)

    # Ordenar por creado descendente (más recientes primero)
    cursor = col.find(filtro).sort("timestamps.creado", -1).skip(salto)
    if limite and limite > 0:
        cursor = cursor.limit(limite)

    turnos_procesados = []
    for doc in cursor:
        ts = doc.get("timestamps") or {}
        met = doc.get("metricas") or {}

        creado = ts.get("creado")
        llamado = ts.get("llamado")
        inicio_atencion = ts.get("inicio_atencion")
        finalizado = ts.get("finalizado")
        abandonado = ts.get("abandonado")

        # Tiempos calculados o derivados
        espera_seg = met.get("espera_seg")
        if espera_seg is None and creado and llamado:
            espera_seg = _calcular_duracion_seg(creado, llamado)

        atencion_seg = met.get("atencion_seg")
        if atencion_seg is None and inicio_atencion and finalizado:
            atencion_seg = _calcular_duracion_seg(inicio_atencion, finalizado)

        turnos_procesados.append({
            "id": str(doc.get("_id", "")),
            "codigo": doc.get("codigo"),
            "servicio": doc.get("servicio", SERVICIO_ID),
            "prioridad": doc.get("prioridad"),
            "estado": doc.get("estado"),
            "ventanilla": doc.get("ventanilla"),
            "operador": doc.get("operador"),
            "timestamps": {
                "creado": _formatear_fecha(creado),
                "llamado": _formatear_fecha(llamado),
                "inicio_atencion": _formatear_fecha(inicio_atencion),
                "finalizado": _formatear_fecha(finalizado),
                "abandonado": _formatear_fecha(abandonado),
            },
            "metricas": {
                "espera_seg": espera_seg,
                "atencion_seg": atencion_seg,
            },
        })

    pagina_actual = (salto // limite) + 1 if limite and limite > 0 else 1
    total_paginas = ((total + limite - 1) // limite) if limite and limite > 0 else 1

    f_desde_str = fecha_desde if isinstance(fecha_desde, str) else (fecha_desde.isoformat() if fecha_desde else None)
    f_hasta_str = fecha_hasta if isinstance(fecha_hasta, str) else (fecha_hasta.isoformat() if fecha_hasta else None)

    return {
        "ok": True,
        "total": total,
        "limite": limite,
        "salto": salto,
        "pagina_actual": pagina_actual,
        "total_paginas": total_paginas,
        "filtros": {
            "estado": estado,
            "ventanilla": ventanilla,
            "prioridad": prioridad,
            "codigo": codigo,
            "fecha_desde": f_desde_str,
            "fecha_hasta": f_hasta_str,
        },
        "turnos": turnos_procesados,
    }


def exportar_historial_turnos(
    db: Database,
    estado: Optional[str] = None,
    ventanilla: Optional[str] = None,
    prioridad: Optional[str] = None,
    codigo: Optional[str] = None,
    fecha_desde: Optional[Union[str, datetime]] = None,
    fecha_hasta: Optional[Union[str, datetime]] = None,
) -> dict:
    """
    Exporta la totalidad de turnos en MongoDB que cumplan con los filtros indicados (HU-010 / S4-M04).
    Sin límite de paginación para auditoría completa y descarga en formato JSON.
    """
    res = obtener_historial_turnos(
        db=db,
        estado=estado,
        ventanilla=ventanilla,
        prioridad=prioridad,
        codigo=codigo,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limite=0,
        salto=0,
    )
    return {
        "ok": True,
        "servicio": SERVICIO_ID,
        "fecha_exportacion": datetime.now(timezone.utc).isoformat(),
        "total_exportados": len(res["turnos"]),
        "total_registros_coincidentes": res["total"],
        "filtros_aplicados": res["filtros"],
        "turnos": res["turnos"],
    }

