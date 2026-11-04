"""HU-012 · Recuperar la cola después de una pérdida de Redis (rehidratación).

Principio: MongoDB conserva lo que ocurrió; Redis controla lo que ocurre ahora.
Si Redis pierde la cola, MongoDB tiene lo necesario para reconstruirla.

La función es una *reconciliación* idempotente: compara MongoDB con Redis y
corrige solo la diferencia. Sirve igual para:
  * pérdida total de Redis (la cola está vacía),
  * pérdida parcial,
  * el caso abierto de S3: el proceso murió tras sacar un turno de la cola y
    antes de que MongoDB confirmara el llamado (turno "pendiente" fuera de cola).

Reglas (criterios de HU-012):
  * Solo vuelven a la cola los turnos en estado "pendiente".
  * NUNCA se rehidratan atendidos, abandonados, llamados ni en atención.
  * Orden: prioridad primero (preferencial antes que normal), luego llegada (creado), luego código.
  * Sin duplicados: lo que ya está en la cola no se vuelve a insertar.
  * El resultado se puede comparar antes/después (ReporteRecuperacion).

Además restaura el contador de códigos (grupo2:qline:contador:atencion_general):
si Redis lo perdió, INCR empezaría en 1 y se repetirían códigos ya existentes en
MongoDB. Solo se sube, nunca se baja.

La cola y el contador de Redis son de Alessandro: este módulo NO define el
formato del miembro ni la fórmula del score; recibe esas operaciones como
funciones (DependenciasCola) para usar exactamente las de app/cola.py.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Callable

from .s3_comun import (
    ESTADO_PENDIENTE,
    RANGO_PRIORIDAD,
    SERVICIO_INICIAL,
    MongoNoDisponible,
    RedisNoDisponible,
    a_utc,
)


@dataclass
class DependenciasCola:
    """Operaciones de Redis necesarias (las implementa/enlaza app/integracion_s3.py).

    leer_cola:      () -> list[str]   códigos en la cola, en orden de atención. NO debe remover nada.
    encolar:        (turno: dict) -> None   mete UN turno con la misma función que usa la emisión
                    (misma fórmula de score y formato de miembro de app/cola.py).
    quitar:         (codigo: str) -> None   saca un código de la cola (solo con quitar_sobrantes).
    leer_contador:  () -> int   valor actual del contador (0 si no existe).
    fijar_contador: (valor: int) -> None   debe fijar SOLO SI el valor es mayor al actual (atómico).
    """

    leer_cola: Callable[[], list[str]]
    encolar: Callable[[dict], None]
    quitar: Callable[[str], None] | None = None
    leer_contador: Callable[[], int] | None = None
    fijar_contador: Callable[[int], None] | None = None


@dataclass
class ReporteRecuperacion:
    aplicado: bool
    antes_cola: list[str] = field(default_factory=list)
    esperados: list[str] = field(default_factory=list)       # pendientes en MongoDB, en el orden correcto
    faltantes: list[str] = field(default_factory=list)       # pendientes que no estaban en la cola
    sobrantes: list[str] = field(default_factory=list)       # en la cola pero MongoDB dice que no son pendientes
    encolados: list[str] = field(default_factory=list)
    quitados: list[str] = field(default_factory=list)
    invalidos: list[str] = field(default_factory=list)       # pendientes con datos inválidos (no se encolan)
    despues_cola: list[str] | None = None
    duplicados: list[str] = field(default_factory=list)
    orden_correcto: bool | None = None
    contador_antes: int | None = None
    contador_maximo_mongo: int | None = None
    contador_despues: int | None = None
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    duracion_seg: float = 0.0

    @property
    def recuperados_pct(self) -> float | None:
        """% de turnos pendientes válidos presentes en la cola después de recuperar."""
        if self.despues_cola is None:
            return None
        if not self.esperados:
            return 100.0
        presentes = set(self.despues_cola)
        return 100.0 * sum(1 for c in self.esperados if c in presentes) / len(self.esperados)

    @property
    def ok(self) -> bool | None:
        """None en simulación (aplicar=False). True solo si todo quedó consistente."""
        if not self.aplicado:
            return None
        return (self.recuperados_pct == 100.0 and not self.duplicados and self.orden_correcto is True
                and not self.sobrantes_restantes and not self.errores)

    @property
    def sobrantes_restantes(self) -> list[str]:
        return [c for c in self.sobrantes if c not in self.quitados]

    def resumen(self) -> dict:
        return {
            "aplicado": self.aplicado,
            "pendientes_esperados": len(self.esperados),
            "en_cola_antes": len(self.antes_cola),
            "faltantes": len(self.faltantes),
            "sobrantes": len(self.sobrantes),
            "encolados": len(self.encolados),
            "quitados": len(self.quitados),
            "invalidos": len(self.invalidos),
            "en_cola_despues": None if self.despues_cola is None else len(self.despues_cola),
            "recuperados_pct": self.recuperados_pct,
            "duplicados": len(self.duplicados),
            "orden_correcto": self.orden_correcto,
            "contador": {"antes": self.contador_antes, "maximo_mongo": self.contador_maximo_mongo,
                         "despues": self.contador_despues},
            "errores": self.errores,
            "advertencias": self.advertencias,
            "duracion_seg": round(self.duracion_seg, 4),
            "ok": self.ok,
        }


def _orden(doc: dict):
    return (RANGO_PRIORIDAD[doc["prioridad"]], a_utc(doc["timestamps"]["creado"]), doc["codigo"])


def _es_valido(doc: dict) -> bool:
    ts = doc.get("timestamps") or {}
    return doc.get("prioridad") in RANGO_PRIORIDAD and ts.get("creado") is not None and bool(doc.get("codigo"))


def consecutivo_maximo(coleccion, serie: str = "A") -> int:
    """Mayor consecutivo numérico de los códigos ``{serie}-NNN`` existentes en MongoDB (0 si no hay)."""
    patron = re.compile(rf"^{re.escape(serie)}-(\d+)$")
    maximo = 0
    for doc in coleccion.find({"codigo": {"$regex": f"^{re.escape(serie)}-\\d+$"}}, {"codigo": 1}):
        m = patron.match(doc["codigo"])
        if m:
            maximo = max(maximo, int(m.group(1)))
    return maximo


def reconciliar_cola(
    coleccion,
    deps: DependenciasCola,
    *,
    aplicar: bool = True,
    quitar_sobrantes: bool = False,
    restaurar_contador: bool = True,
    serie: str = "A",
    solo_serie: bool = False,
) -> ReporteRecuperacion:
    """Reconstruye/reconcilia la cola de Redis desde MongoDB.

    Args:
        aplicar: False = solo calcula el plan (no escribe en Redis).
        quitar_sobrantes: si True, saca de la cola los códigos que MongoDB no
            considera pendientes (estado inválido según §17). Por defecto solo los informa.
        restaurar_contador: sube el contador al mayor consecutivo de MongoDB si Redis lo perdió.
        serie: letra de la serie operativa de códigos (por defecto "A", como A-015).
        solo_serie: limita la reconciliación a los códigos de esa serie (en MongoDB y en la cola).
            Las pruebas la usan con la serie "R" para no tocar los turnos de la operación real.

    Raises:
        MongoNoDisponible / RedisNoDisponible: si falla la lectura inicial (no se modifica nada).
    """
    inicio = time.perf_counter()
    rep = ReporteRecuperacion(aplicado=aplicar)
    filtro = {"servicio": SERVICIO_INICIAL, "estado": ESTADO_PENDIENTE}
    leer_original = deps.leer_cola
    if solo_serie:
        prefijo = f"{serie}-"
        filtro["codigo"] = {"$regex": f"^{re.escape(prefijo)}"}
        deps = replace(deps, leer_cola=lambda: [c for c in leer_original() if c.startswith(prefijo)])

    # --- Lecturas (si fallan, no se ha tocado nada) ---------------------------------
    try:
        pendientes = list(coleccion.find(filtro))
    except Exception as exc:
        raise MongoNoDisponible() from exc
    try:
        rep.antes_cola = list(deps.leer_cola())
    except Exception as exc:
        raise RedisNoDisponible() from exc

    validos = [d for d in pendientes if _es_valido(d)]
    rep.invalidos = sorted(d.get("codigo", "?") for d in pendientes if not _es_valido(d))
    if rep.invalidos:
        rep.advertencias.append(f"{len(rep.invalidos)} turno(s) pendiente(s) con datos inválidos no se encolan")
    validos.sort(key=_orden)
    rep.esperados = [d["codigo"] for d in validos]
    por_codigo = {d["codigo"]: d for d in validos}

    en_cola = set(rep.antes_cola)
    rep.faltantes = [c for c in rep.esperados if c not in en_cola]

    # Sobrantes: están en la cola, pero MongoDB no los tiene como pendientes válidos.
    # (Un pendiente con datos inválidos sigue siendo pendiente: no se cuenta como sobrante.)
    invalidos_set = set(rep.invalidos)
    rep.sobrantes = list(dict.fromkeys(c for c in rep.antes_cola if c not in por_codigo and c not in invalidos_set))
    if rep.sobrantes:
        try:
            existentes = {d["codigo"] for d in coleccion.find({"codigo": {"$in": rep.sobrantes}}, {"codigo": 1})}
        except Exception as exc:
            raise MongoNoDisponible() from exc
        huerfanos = [c for c in rep.sobrantes if c not in existentes]
        if huerfanos:
            rep.advertencias.append(f"{len(huerfanos)} código(s) en la cola no existen en MongoDB")

    # --- Contador ------------------------------------------------------------------
    manejar_contador = restaurar_contador and deps.leer_contador is not None
    if manejar_contador:
        try:
            rep.contador_maximo_mongo = consecutivo_maximo(coleccion, serie)
        except Exception as exc:
            raise MongoNoDisponible() from exc
        try:
            rep.contador_antes = int(deps.leer_contador())
        except Exception as exc:
            raise RedisNoDisponible() from exc
    elif restaurar_contador:
        rep.advertencias.append("No se restauró el contador: no hay funciones de contador enlazadas")

    if not aplicar:
        rep.duracion_seg = time.perf_counter() - inicio
        return rep

    # --- Escrituras (idempotentes: repetir la ejecución completa el trabajo) ---------
    for codigo in rep.faltantes:
        try:
            deps.encolar(por_codigo[codigo])
            rep.encolados.append(codigo)
        except Exception as exc:
            rep.errores.append(f"No se pudo encolar {codigo}: {type(exc).__name__}")

    if rep.sobrantes and quitar_sobrantes:
        if deps.quitar is None:
            rep.errores.append("quitar_sobrantes=True pero no hay función 'quitar' enlazada")
        else:
            for codigo in rep.sobrantes:
                try:
                    deps.quitar(codigo)
                    rep.quitados.append(codigo)
                except Exception as exc:
                    rep.errores.append(f"No se pudo quitar {codigo}: {type(exc).__name__}")
    elif rep.sobrantes:
        rep.advertencias.append(
            f"{len(rep.sobrantes)} código(s) en la cola no son pendientes en MongoDB (use quitar_sobrantes)")

    if manejar_contador:
        try:
            if rep.contador_antes < rep.contador_maximo_mongo:
                deps.fijar_contador(rep.contador_maximo_mongo)
            rep.contador_despues = int(deps.leer_contador())
        except Exception as exc:
            rep.errores.append(f"No se pudo restaurar el contador: {type(exc).__name__}")

    # --- Verificación antes/después -----------------------------------------------
    try:
        rep.despues_cola = list(deps.leer_cola())
    except Exception as exc:
        rep.errores.append(f"No se pudo leer la cola para verificar: {type(exc).__name__}")
        rep.duracion_seg = time.perf_counter() - inicio
        return rep

    rep.duplicados = sorted(c for c, n in Counter(rep.despues_cola).items() if n > 1)
    esperados = set(rep.esperados)
    vistos = [c for c in rep.despues_cola if c in esperados]
    # orden correcto = los pendientes esperados aparecen en la cola en el orden prioridad+llegada
    rep.orden_correcto = list(dict.fromkeys(vistos)) == [c for c in rep.esperados if c in set(vistos)]
    rep.duracion_seg = time.perf_counter() - inicio
    return rep
