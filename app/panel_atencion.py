"""Datos del panel de atención: qué turno tiene cada ventanilla ahora.

El turno actual se toma de Redis (ventanilla:{id}:actual). Si Redis no lo tiene
o no responde, se busca en MongoDB un turno de esa ventanilla en estado
'en_atencion' o 'llamado', para que el operador pueda terminar su trabajo
aunque el estado temporal se haya perdido. MongoDB decide siempre el estado.
"""

from app.atencion import _iso
from app.constantes import (
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    VENTANILLAS,
    clave_ventanilla_actual,
)
from app import cola
from app.redis_client import get_redis

COLECCION = "turnos"


class _AccesoRedis:
    """
    Lecturas de Redis de UNA petición. Tras el primer fallo no se vuelve a intentar
    en esa petición: con Redis caído cada intento esperaría el tiempo de espera y la
    página tardaría varias veces más; con MongoDB como respaldo basta un aviso.
    """

    def __init__(self, activo: bool = True):
        self.activo = activo
        self.error = ""

    def _fallo(self, e: Exception) -> None:
        self.activo = False
        self.error = f"Redis no disponible: {e}"

    def actual(self, ventanilla: str):
        if not self.activo:
            return None
        try:
            return get_redis().get(clave_ventanilla_actual(ventanilla))
        except Exception as e:
            self._fallo(e)
            return None

    def restantes(self, turno: dict):
        """Segundos que le quedan a un turno llamado antes de considerarse abandonado (Hash con TTL)."""
        if not self.activo or turno["estado"] != ESTADO_LLAMADO:
            return None
        try:
            return cola.segundos_restantes(turno["codigo"])
        except Exception as e:
            self._fallo(e)
            return None


def _fila(turno: dict, acceso: _AccesoRedis) -> dict:
    ts = turno.get("timestamps") or {}
    return {
        "codigo": turno["codigo"],
        "estado": turno["estado"],
        "prioridad": turno.get("prioridad"),
        "llamado": _iso(ts.get("llamado")),
        "inicio_atencion": _iso(ts.get("inicio_atencion")),
        "segundos_restantes": acceso.restantes(turno),
        "puede_iniciar": turno["estado"] == ESTADO_LLAMADO,
        "puede_finalizar": turno["estado"] == ESTADO_EN_ATENCION,
    }


def _orden(doc: dict):
    """En atención primero, luego llamado; dentro de cada grupo, el más antiguo."""
    ts = doc.get("timestamps") or {}
    antiguedad = ts.get("llamado")
    return (0 if doc.get("estado") == ESTADO_EN_ATENCION else 1,
            antiguedad.isoformat() if hasattr(antiguedad, "isoformat") else "")


def estado_ventanillas(db, usar_redis: bool = True) -> tuple[list[dict], list[str]]:
    """
    Devuelve (ventanillas con su turno actual, avisos). Nunca lanza por Redis.

    Cada ventanilla trae `turno` (el que se atiende) y `extras`: otros turnos
    `llamado`/`en_atencion` que MongoDB tiene asignados a la misma ventanilla.
    Una ventanilla debería atender un turno a la vez; si hay más, se muestran
    y se avisa, para que ninguno quede invisible. Con `usar_redis=False` (la
    página ya sabe que Redis no responde) no se consulta Redis.
    """
    col = db[COLECCION]
    avisos: list[str] = []
    ventanillas = []
    acceso = _AccesoRedis(usar_redis)
    for v in VENTANILLAS:
        codigo = acceso.actual(v)
        activos = sorted(
            col.find({"ventanilla": v, "estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]}}),
            key=_orden,
        )
        turno = col.find_one({"codigo": codigo}) if codigo else None
        # Redis apunta a un turno que ya terminó (o no existe): no es un turno activo.
        if turno is not None and turno.get("estado") not in (ESTADO_LLAMADO, ESTADO_EN_ATENCION):
            avisos.append(f"{v}: Redis apunta a {codigo}, que en MongoDB está '{turno.get('estado')}'.")
            turno = None
        if turno is None and activos:
            turno = activos[0]
        extras = [d for d in activos if turno is None or d["codigo"] != turno["codigo"]]
        if extras:
            avisos.append(
                f"{v} tiene {len(extras) + 1} turnos activos en MongoDB "
                f"({', '.join([turno['codigo']] + [d['codigo'] for d in extras])}); "
                "atienda o finalice los demás.")
        ventanillas.append({"id": v, "turno": _fila(turno, acceso) if turno else None,
                            "extras": [_fila(d, acceso) for d in extras]})
    if acceso.error:
        avisos.insert(0, acceso.error)
    return ventanillas, avisos
