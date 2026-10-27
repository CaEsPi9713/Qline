"""TT-017 · Prueba de caída y rehidratación de la cola (evidencia de HU-012).

Se trabaja solo con turnos de la serie "R" (R-001, R-002…): nunca se toca un turno de la
operación real (serie "A") ni se reinicia o vacía Redis. La "pérdida" la provoca quien llama
(`perder`), por ejemplo sacando de la cola solo los códigos R-*.

Qué se comprueba:
  1. Antes de la caída, la cola emitida por la ruta normal tiene el mismo orden que el que
     calcularía la recuperación desde MongoDB (prioridad, luego llegada).
  2. El plan (aplicar=False) detecta todos los faltantes y no escribe nada.
  3. Tras recuperar: 100 % de los pendientes, mismo orden que antes de la caída, sin duplicados.
  4. Ningún turno atendido, abandonado, llamado o en atención vuelve a la cola.
  5. Repetir la recuperación no cambia nada (idempotencia).
  6. Una pérdida parcial (se pierden solo algunos códigos) también se corrige.
  7. Opcional: el contador de códigos de la serie se restaura al mayor consecutivo de MongoDB.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from app.datos_prueba import construir_mezcla_estados
from app.informe import encabezado
from app.recuperacion import DependenciasCola, consecutivo_maximo, reconciliar_cola
from app.s3_comun import ESTADO_PENDIENTE, MongoNoDisponible

SERIE = "R"
PREFIJO = f"{SERIE}-"
FILTRO_SERIE = {"codigo": {"$regex": rf"^{SERIE}-\d+$"}}


@dataclass
class Verificacion:
    nombre: str
    ok: bool
    detalle: str = ""


@dataclass
class ResultadoPrueba:
    pendientes: int = 0
    otros_estados: dict = field(default_factory=dict)
    cola_inicial: list[str] = field(default_factory=list)
    tras_perdida: list[str] = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    reporte: dict = field(default_factory=dict)
    repeticion: dict = field(default_factory=dict)
    parcial: dict = field(default_factory=dict)
    contador: dict | None = None
    cola_final: list[str] = field(default_factory=list)
    verificaciones: list[Verificacion] = field(default_factory=list)
    duracion_seg: float = 0.0

    def verificar(self, nombre: str, condicion: bool, detalle: str = "") -> bool:
        self.verificaciones.append(Verificacion(nombre, bool(condicion), detalle))
        return bool(condicion)

    @property
    def ok(self) -> bool:
        return bool(self.verificaciones) and all(v.ok for v in self.verificaciones)


def _cola_serie(deps: DependenciasCola) -> list[str]:
    return [c for c in deps.leer_cola() if c.startswith(PREFIJO)]


def _limpiar(coleccion, deps: DependenciasCola) -> None:
    if deps.quitar is not None:
        for codigo in _cola_serie(deps):
            deps.quitar(codigo)
    coleccion.delete_many(FILTRO_SERIE)


def ejecutar_prueba(
    coleccion,
    deps: DependenciasCola,
    *,
    base: datetime,
    perder: Callable[[], None],
    pendientes: int = 12,
    limpiar: bool = True,
    deps_contador: DependenciasCola | None = None,
    perder_contador: Callable[[], None] | None = None,
) -> ResultadoPrueba:
    """Ejecuta la prueba completa. Siempre devuelve el resultado; las fallas quedan en `verificaciones`."""
    inicio = time.perf_counter()
    res = ResultadoPrueba(pendientes=pendientes)
    _limpiar(coleccion, deps)                                   # restos de una ejecución anterior
    try:
        docs = construir_mezcla_estados(base, serie=SERIE, pendientes=pendientes)
        coleccion.insert_many(docs)
        pend = [d for d in docs if d["estado"] == ESTADO_PENDIENTE]
        res.otros_estados = {e: sum(1 for d in docs if d["estado"] == e)
                             for e in sorted({d["estado"] for d in docs}) if e != ESTADO_PENDIENTE}
        codigos_pend = {d["codigo"] for d in pend}

        # 1. Emisión normal: encolar con la misma función que usa la operación.
        for d in pend:
            deps.encolar(d)
        res.cola_inicial = _cola_serie(deps)
        plan_inicial = reconciliar_cola(coleccion, deps, aplicar=False, restaurar_contador=False,
                                        serie=SERIE, solo_serie=True)
        res.verificar("La cola emitida tiene el mismo orden que el calculado desde MongoDB",
                      res.cola_inicial == plan_inicial.esperados and len(res.cola_inicial) == pendientes,
                      f"{len(res.cola_inicial)} en cola, {len(plan_inicial.esperados)} esperados")

        # 2. Pérdida total y plan sin escribir.
        perder()
        res.tras_perdida = _cola_serie(deps)
        res.verificar("La pérdida dejó la cola de la prueba vacía", not res.tras_perdida,
                      f"{len(res.tras_perdida)} turno(s) quedaron")
        plan = reconciliar_cola(coleccion, deps, aplicar=False, restaurar_contador=False,
                                serie=SERIE, solo_serie=True)
        res.plan = plan.resumen()
        res.verificar("El plan detecta todos los pendientes como faltantes", set(plan.faltantes) == codigos_pend)
        res.verificar("El plan no escribe nada en Redis", not _cola_serie(deps))

        # 3. Recuperación.
        rep = reconciliar_cola(coleccion, deps, aplicar=True, restaurar_contador=False,
                               serie=SERIE, solo_serie=True)
        res.reporte = rep.resumen()
        res.cola_final = _cola_serie(deps)
        res.verificar("Se recuperó el 100 % de los pendientes", rep.recuperados_pct == 100.0,
                      f"{rep.recuperados_pct}%")
        res.verificar("La cola recuperada tiene el mismo orden que antes de la caída",
                      res.cola_final == res.cola_inicial)
        res.verificar("Sin duplicados", not rep.duplicados and len(res.cola_final) == len(set(res.cola_final)))
        res.verificar("La recuperación se reporta como correcta", rep.ok is True, str(rep.errores or ""))

        # 4. Solo vuelven los pendientes.
        intrusos = sorted(set(res.cola_final) - codigos_pend)
        res.verificar("No volvió a la cola ningún turno atendido, abandonado, llamado ni en atención",
                      not intrusos, ", ".join(intrusos))

        # 5. Idempotencia.
        rep2 = reconciliar_cola(coleccion, deps, aplicar=True, restaurar_contador=False,
                                serie=SERIE, solo_serie=True)
        res.repeticion = rep2.resumen()
        res.verificar("Repetir la recuperación no cambia nada",
                      not rep2.encolados and _cola_serie(deps) == res.cola_inicial)

        # 6. Pérdida parcial: el primero, uno del medio y el último.
        perdidos = [res.cola_inicial[0], res.cola_inicial[len(res.cola_inicial) // 2], res.cola_inicial[-1]]
        if deps.quitar is not None:
            for c in dict.fromkeys(perdidos):
                deps.quitar(c)
        rep3 = reconciliar_cola(coleccion, deps, aplicar=True, restaurar_contador=False,
                                serie=SERIE, solo_serie=True)
        res.parcial = rep3.resumen()
        res.verificar("Una pérdida parcial se corrige y respeta el orden",
                      set(rep3.encolados) == set(perdidos) and _cola_serie(deps) == res.cola_inicial,
                      f"se perdieron {len(set(perdidos))}, se reencolaron {len(rep3.encolados)}")

        # 7. Contador de la serie (con claves aisladas, nunca el contador real).
        if deps_contador is not None and perder_contador is not None:
            maximo = consecutivo_maximo(coleccion, SERIE)
            perder_contador()
            antes = deps_contador.leer_contador()
            rep4 = reconciliar_cola(coleccion, deps_contador, aplicar=True, restaurar_contador=True,
                                    serie=SERIE, solo_serie=True)
            despues = deps_contador.leer_contador()
            res.contador = {"maximo_mongo": maximo, "tras_perdida": antes, "restaurado": despues}
            res.verificar("El contador se restauró al mayor consecutivo de MongoDB",
                          despues == maximo and antes < maximo and rep4.errores == [],
                          f"perdido={antes}, restaurado={despues}, máximo en MongoDB={maximo}")
    except MongoNoDisponible:
        raise
    finally:
        if limpiar:
            _limpiar(coleccion, deps)
        res.duracion_seg = time.perf_counter() - inicio
    return res


def a_markdown(res: ResultadoPrueba) -> str:
    md = encabezado("Evidencia · Prueba de caída y rehidratación de la cola (TT-017 / HU-012)")
    md += ("\nSe usan solo turnos de la serie `R-*`; no se reinicia Redis ni se tocan turnos de la operación real.\n\n"
           f"- Pendientes de la prueba: **{res.pendientes}**\n"
           f"- Otros turnos que **no** deben volver a la cola: {res.otros_estados}\n"
           f"- Cola antes de la caída ({len(res.cola_inicial)}): `{', '.join(res.cola_inicial)}`\n"
           f"- Cola tras la pérdida ({len(res.tras_perdida)}): `{', '.join(res.tras_perdida) or '(vacía)'}`\n"
           f"- Cola tras recuperar ({len(res.cola_final)}): `{', '.join(res.cola_final)}`\n"
           f"- Duración total de la prueba: {res.duracion_seg:.2f} s\n")
    md += "\n## Verificaciones\n\n| # | Verificación | Resultado | Detalle |\n|---|---|---|---|\n"
    for i, v in enumerate(res.verificaciones, start=1):
        md += f"| {i} | {v.nombre} | {'✔ cumple' if v.ok else '✘ FALLA'} | {v.detalle} |\n"
    if res.contador:
        md += f"\n## Contador de códigos (clave aislada de la prueba)\n\n{res.contador}\n"
    md += f"\n## Resultado global: {'**CORRECTO**' if res.ok else '**CON FALLAS**'}\n"
    if res.reporte:
        md += (f"\nTiempo de la recuperación completa: {res.reporte.get('duracion_seg')} s "
               f"({res.reporte.get('encolados')} turnos reencolados).\n")
    return md
