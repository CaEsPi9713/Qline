"""TT-018 · Mediciones de la recuperación y del abandono (parte de Abigail).

Tres operaciones, cada una con varias ejecuciones y reportada con su mediana:
  1. Rehidratar la cola después de perderla (reconstruir N pendientes desde MongoDB).
  2. Barrido de abandono (marcar N llamados vencidos como abandonados).
  3. Reconciliar cuando la cola ya está completa (no hay nada que corregir: el costo de verificar).

Reloj adelantado: los turnos "vencidos" lo están respecto de un reloj de prueba adelantado
ADELANTO_RELOJ_SEG; para el reloj real todavía no lo están. Así el barrido automático de la aplicación
(que corre cada pocos segundos en el servidor) no los abandona antes que la medición.

Aislamiento: se usa la serie "M" (M-001…), una cola y un canal de eventos propios de la medición
(las dependencias que se reciben ya vienen con claves de prueba) y el barrido solo ve turnos M-*.
No se toca ningún turno ni la cola de la operación real, ni se publican eventos que vea el público.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.abandono import barrer_abandonos
from app.datos_prueba import construir_turno
from app.informe import encabezado
from app.recuperacion import DependenciasCola, reconciliar_cola
from app.s3_comun import ESTADO_LLAMADO, ESTADO_PENDIENTE, TTL_ABANDONO_SEG

SERIE = "M"
PREFIJO = f"{SERIE}-"
FILTRO_SERIE = {"codigo": {"$regex": rf"^{SERIE}-\d+$"}}
MINIMO_EJECUCIONES = 3
ADELANTO_RELOJ_SEG = 2 * TTL_ABANDONO_SEG


@dataclass
class Medicion:
    nombre: str
    n: int
    segundos: list[float] = field(default_factory=list)
    correctas: int = 0

    @property
    def ejecuciones(self) -> int:
        return len(self.segundos)

    @property
    def mediana(self) -> float:
        return statistics.median(self.segundos)

    @property
    def correcta(self) -> bool:
        return self.ejecuciones > 0 and self.correctas == self.ejecuciones


class ColeccionAcotada:
    """Colección que solo muestra los turnos de la serie de medición: el barrido no ve los de otros."""

    def __init__(self, coleccion, filtro: dict = FILTRO_SERIE):
        self._c, self._filtro = coleccion, filtro

    def find(self, filtro=None, *args, **kw):
        return self._c.find({"$and": [filtro or {}, self._filtro]}, *args, **kw)

    def update_one(self, filtro, *args, **kw):
        return self._c.update_one({"$and": [filtro, self._filtro]}, *args, **kw)


def _docs_pendientes(ahora: datetime, n: int) -> list[dict]:
    return [construir_turno(f"{PREFIJO}{i:04d}", ESTADO_PENDIENTE, "preferencial" if i % 4 == 0 else "normal",
                            ahora - timedelta(seconds=(n - i) * 5 + 600))
            for i in range(1, n + 1)]


def _docs_llamados_vencidos(ahora: datetime, n: int) -> list[dict]:
    docs = []
    for i in range(1, n + 1):
        llamado = ahora - timedelta(seconds=TTL_ABANDONO_SEG + 1 + i % 50)
        docs.append(construir_turno(f"{PREFIJO}{i:04d}", ESTADO_LLAMADO, "normal", llamado - timedelta(seconds=90),
                                    f"V-0{i % 3 + 1}", llamado))
    return docs


def _limpiar(coleccion, deps: DependenciasCola) -> None:
    coleccion.delete_many(FILTRO_SERIE)
    for codigo in [c for c in deps.leer_cola() if c.startswith(PREFIJO)]:
        deps.quitar(codigo)


def _verificar_ejecuciones(ejecuciones: int) -> None:
    if ejecuciones < MINIMO_EJECUCIONES:
        raise ValueError(f"Se necesitan al menos {MINIMO_EJECUCIONES} ejecuciones por medición")


def medir_rehidratacion(coleccion, deps: DependenciasCola, ahora: datetime, n: int, ejecuciones: int) -> Medicion:
    _verificar_ejecuciones(ejecuciones)
    med = Medicion(f"Rehidratar la cola ({n} pendientes)", n)
    _limpiar(coleccion, deps)
    try:
        coleccion.insert_many(_docs_pendientes(ahora, n))
        for _ in range(ejecuciones):
            for codigo in [c for c in deps.leer_cola() if c.startswith(PREFIJO)]:
                deps.quitar(codigo)                                  # la cola se "pierde"
            t0 = time.perf_counter()
            rep = reconciliar_cola(coleccion, deps, aplicar=True, restaurar_contador=False,
                                   serie=SERIE, solo_serie=True)
            med.segundos.append(time.perf_counter() - t0)
            med.correctas += int(rep.ok is True and len(rep.encolados) == n)
    finally:
        _limpiar(coleccion, deps)
    return med


def medir_reconciliacion_sin_cambios(coleccion, deps: DependenciasCola, ahora: datetime, n: int,
                                     ejecuciones: int) -> Medicion:
    _verificar_ejecuciones(ejecuciones)
    med = Medicion(f"Reconciliar con la cola completa ({n} pendientes)", n)
    _limpiar(coleccion, deps)
    try:
        docs = _docs_pendientes(ahora, n)
        coleccion.insert_many(docs)
        for d in docs:
            deps.encolar(d)
        for _ in range(ejecuciones):
            t0 = time.perf_counter()
            rep = reconciliar_cola(coleccion, deps, aplicar=True, restaurar_contador=False,
                                   serie=SERIE, solo_serie=True)
            med.segundos.append(time.perf_counter() - t0)
            med.correctas += int(rep.ok is True and not rep.encolados)
    finally:
        _limpiar(coleccion, deps)
    return med


def medir_barrido(coleccion, deps: DependenciasCola, dep_abandono: dict, ahora: datetime, n: int,
                  ejecuciones: int) -> Medicion:
    _verificar_ejecuciones(ejecuciones)
    med = Medicion(f"Barrido de abandono ({n} llamados vencidos)", n)
    acotada = ColeccionAcotada(coleccion)
    reloj = ahora + timedelta(seconds=ADELANTO_RELOJ_SEG)       # reloj de prueba: solo para él vencen los llamados
    try:
        for _ in range(ejecuciones):
            coleccion.delete_many(FILTRO_SERIE)
            coleccion.insert_many(_docs_llamados_vencidos(reloj, n))
            t0 = time.perf_counter()
            res = barrer_abandonos(acotada, ahora=reloj, **dep_abandono)
            med.segundos.append(time.perf_counter() - t0)
            med.correctas += int(res.ok and len(res.abandonados) == n)
    finally:
        _limpiar(coleccion, deps)
    return med


def informe(resultados: list[Medicion], tamanos: list[int], ejecuciones: int) -> str:
    md = encabezado("Mediciones de recuperación y abandono (TT-018, parte de Abigail)")
    md += (f"\n## Método\n\n"
           f"- Tamaños medidos: {', '.join(map(str, tamanos))} turnos. **{ejecuciones} ejecuciones** por medición "
           f"(mínimo exigido: {MINIMO_EJECUCIONES}); se reportan mínimo, máximo y **mediana**.\n"
           f"- Datos de la serie `{SERIE}-*`, con cola y canal de eventos propios de la medición: no se tocan los turnos "
           f"ni la cola de la operación real y el público no recibe eventos de la prueba.\n"
           f"- Cada ejecución mide solo la operación; la preparación de datos y su limpieza quedan fuera del tiempo.\n"
           f"- Tiempo visto desde la aplicación (incluye red y biblioteca cliente).\n"
           f"\n## Resultados\n\n"
           f"| Operación | Turnos | Ejecuciones | Mínimo (ms) | Máximo (ms) | **Mediana (ms)** | Mediana por turno (µs) | Resultado correcto |\n"
           f"|---|---|---|---|---|---|---|---|\n")
    for m in resultados:
        ms = [s * 1000 for s in m.segundos]
        md += (f"| {m.nombre} | {m.n} | {m.ejecuciones} | {min(ms):.2f} | {max(ms):.2f} | **{m.mediana * 1000:.2f}** | "
               f"{m.mediana * 1e6 / m.n:.1f} | {'sí' if m.correcta else 'NO'} ({m.correctas}/{m.ejecuciones}) |\n")
    md += "\n## Tiempos de cada ejecución (ms)\n\n"
    for m in resultados:
        md += f"- {m.nombre}: {[round(s * 1000, 2) for s in m.segundos]}\n"
    if not all(m.correcta for m in resultados):
        md += "\n> **Atención:** alguna ejecución no produjo el resultado esperado; sus tiempos no son comparables.\n"
    return md
