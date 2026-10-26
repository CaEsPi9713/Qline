"""
Módulo de Historial y Auditoría de Turnos (HU-010 / HU-014).

Responsable: Carlos Espinoza (cespinoza)
Permite auditar turnos procesados y activos, trazabilidad cronológica
y cálculo derivado de tiempos de espera y atención.
"""
from datetime import datetime, timezone
from typing import Optional

from pymongo.database import Database

from app.constantes import ESTADOS, PRIORIDADES, SERVICIO_ID, VENTANILLAS

COLECCION_TURNOS = "turnos"


def _formatear_fecha(dt) -> Optional[str]:
    """Formatea un objeto datetime a string ISO legible."""
    if isinstance(dt, datetime):
        return dt.isoformat()
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


def obtener_historial_turnos(
    db: Database,
    estado: Optional[str] = None,
    ventanilla: Optional[str] = None,
    prioridad: Optional[str] = None,
    codigo: Optional[str] = None,
    limite: int = 100,
    salto: int = 0,
) -> dict:
    """
    Consulta turnos en MongoDB con filtros controlados y cálculo de métricas derivadas.
    Permite auditar el historial incluso si los turnos ya no están en Redis.
    """
    filtro = {"servicio": SERVICIO_ID}

    if estado and estado in ESTADOS:
        filtro["estado"] = estado
    if ventanilla and ventanilla in VENTANILLAS:
        filtro["ventanilla"] = ventanilla
    if prioridad and prioridad in PRIORIDADES:
        filtro["prioridad"] = prioridad
    if codigo and codigo.strip():
        filtro["codigo"] = codigo.strip().upper()

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

    return {
        "ok": True,
        "total": total,
        "limite": limite,
        "salto": salto,
        "filtros": {
            "estado": estado,
            "ventanilla": ventanilla,
            "prioridad": prioridad,
            "codigo": codigo,
        },
        "turnos": turnos_procesados,
    }


def exportar_historial_turnos(
    db: Database,
    estado: Optional[str] = None,
    ventanilla: Optional[str] = None,
    prioridad: Optional[str] = None,
    codigo: Optional[str] = None,
) -> dict:
    """
    Exporta la totalidad de turnos en MongoDB que cumplan con los filtros indicados (HU-010).
    Sin límite de paginación para auditoría completa y descarga en formato JSON.
    """
    res = obtener_historial_turnos(
        db=db,
        estado=estado,
        ventanilla=ventanilla,
        prioridad=prioridad,
        codigo=codigo,
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

