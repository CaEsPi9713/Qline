"""
Datos de la vista de trabajo del operador (entrega a sucursal · Fase 5).

Una sola consulta entrega todo lo que la pantalla necesita para una ventanilla: el turno en curso con sus tiempos,
la cola de espera con cuánto lleva esperando cada turno, cuántos hay y cuántos son preferenciales, y lo que el propio
operador lleva atendido hoy. Todo son números y textos, listo para enviarse como JSON.

Reutiliza `estado_ventanillas` (turno actual según Redis y MongoDB) y `cola.ver_cola`: no decide nada nuevo sobre la
operación, solo la presenta. Una falla de Redis no tumba la vista: se muestra con un aviso.
"""
import time
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app import cola
from app.constantes import ESTADO_ATENDIDO
from app.formato import zona
from app.panel_atencion import estado_ventanillas

COLECCION = "turnos"
LIMITE_COLA_VISIBLE = 30
LIMITE_COLA_CONTADA = 500


def _ms(valor) -> Optional[int]:
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return int(valor.timestamp() * 1000)


def _inicio_del_dia_utc() -> datetime:
    """Medianoche de hoy en la zona horaria de la sucursal, expresada en UTC (así se guardan las fechas)."""
    ahora_local = datetime.now(zona())
    return ahora_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _cola(db, avisos: list) -> tuple:
    """(cola visible con tiempos de espera, total en espera, preferenciales en espera, Redis respondió)."""
    try:
        todos = cola.ver_cola(limite=LIMITE_COLA_CONTADA)
    except RedisError:
        avisos.append("Redis no responde: la cola de espera no se puede mostrar por ahora.")
        return [], 0, 0, False
    visibles = [dict(t) for t in todos[:LIMITE_COLA_VISIBLE]]
    if visibles:
        try:
            creados = {d["codigo"]: _ms((d.get("timestamps") or {}).get("creado"))
                       for d in db[COLECCION].find({"codigo": {"$in": [t["codigo"] for t in visibles]}},
                                                   {"codigo": 1, "timestamps.creado": 1})}
        except PyMongoError:
            creados = {}
            avisos.append("MongoDB no responde: no se pueden calcular los tiempos de espera.")
        for t in visibles:
            t["creado_ms"] = creados.get(t["codigo"])
    return visibles, len(todos), sum(1 for t in todos if t["prioridad"] == "preferencial"), True


def _turno_actual(db, ventanilla: str, usar_redis: bool, ahora_ms: int, avisos: list) -> Optional[dict]:
    try:
        ventanillas, avisos_panel = estado_ventanillas(db, usar_redis=usar_redis)
    except Exception:                                    # noqa: BLE001 · la vista no debe caerse por el panel
        avisos.append("MongoDB no responde: no se puede mostrar el turno en curso.")
        return None
    avisos.extend(a for a in avisos_panel if not a.startswith("Redis no disponible"))
    fila = next((v for v in ventanillas if v["id"] == ventanilla), None)
    if fila is None or fila["turno"] is None:
        return None
    turno = dict(fila["turno"])
    try:
        doc = db[COLECCION].find_one({"codigo": turno["codigo"]}, {"timestamps": 1}) or {}
    except PyMongoError:
        doc = {}
    ts = doc.get("timestamps") or {}
    turno.update(creado_ms=_ms(ts.get("creado")), llamado_ms=_ms(ts.get("llamado")), inicio_ms=_ms(ts.get("inicio_atencion")),
                 vence_ms=(ahora_ms + turno["segundos_restantes"] * 1000) if turno.get("segundos_restantes") is not None else None)
    turno.pop("llamado", None)                           # las fechas ISO sobran: el navegador usa los milisegundos
    turno.pop("inicio_atencion", None)
    if fila["extras"]:
        avisos.append(f"{ventanilla} tiene además: {', '.join(e['codigo'] for e in fila['extras'])}. Atiéndalos o finalícelos.")
    return turno


def _mis_numeros_de_hoy(db, operador: str) -> tuple:
    """(turnos que el operador atendió hoy, tiempo medio de atención en segundos o None)."""
    try:
        docs = list(db[COLECCION].find({"operador": operador, "estado": ESTADO_ATENDIDO,
                                        "timestamps.finalizado": {"$gte": _inicio_del_dia_utc()}},
                                       {"metricas.atencion_seg": 1}))
    except PyMongoError:
        return 0, None
    tiempos = [d["metricas"]["atencion_seg"] for d in docs
               if isinstance((d.get("metricas") or {}).get("atencion_seg"), (int, float))]
    return len(docs), (round(sum(tiempos) / len(tiempos)) if tiempos else None)


def estado_vacio(ventanilla: str, operador: str, aviso: str = "") -> dict:
    """Estado sin datos, para mostrar la pantalla aunque MongoDB no responda."""
    return {"ventanilla": ventanilla, "operador": operador, "servidor_ms": int(time.time() * 1000), "redis_ok": True,
            "turno": None, "cola": [], "en_espera": 0, "preferenciales": 0, "mis_atendidos_hoy": 0,
            "mi_atencion_media_seg": None, "avisos": [aviso] if aviso else []}


def estado_operador(db, ventanilla: str, operador: str, ahora_ms: Optional[int] = None) -> dict:
    ahora_ms = ahora_ms if ahora_ms is not None else int(time.time() * 1000)
    avisos: list = []
    visibles, en_espera, preferenciales, redis_ok = _cola(db, avisos)
    turno = _turno_actual(db, ventanilla, redis_ok, ahora_ms, avisos)
    atendidos, medio = _mis_numeros_de_hoy(db, operador)
    return {"ventanilla": ventanilla, "operador": operador, "servidor_ms": ahora_ms, "redis_ok": redis_ok,
            "turno": turno, "cola": visibles, "en_espera": en_espera, "preferenciales": preferenciales,
            "mis_atendidos_hoy": atendidos, "mi_atencion_media_seg": medio, "avisos": avisos}
