"""Generador determinista de turnos sintéticos para QLine.

Idea: en lugar de inventar fechas al azar, se SIMULA la operación de la fila
(llegadas, prioridad antes que llegada, FIFO dentro de cada prioridad, 3
ventanillas, abandono a los 180 s). Así los datos son coherentes entre sí:
ninguna ventanilla atiende dos turnos a la vez, los tiempos de espera salen de
la cola real y los estados respetan el flujo oficial.

Reproducibilidad: toda la aleatoriedad sale de ``random.Random(semilla)``.
Con los mismos parámetros se obtienen exactamente los mismos documentos
(verificado con Python 3.12). No se usa la hora actual: la fecha de la
simulación es un parámetro.

Los datos NO contienen personas: solo códigos, prioridad, ventanilla y tiempos.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.constantes import (
    ESTADO_ABANDONADO,
    ESTADO_ATENDIDO,
    ESTADO_EN_ATENCION,
    ESTADO_LLAMADO,
    ESTADO_PENDIENTE,
    PRIORIDAD_NORMAL,
    PRIORIDAD_PREFERENCIAL,
    SERVICIO_ID,
    TTL_ABANDONO_SEG,
    VENTANILLAS,
)

# Fecha por defecto fija (NO la de hoy) para que el resultado sea reproducible.
FECHA_FIN_POR_DEFECTO = date(2026, 10, 16)
SEMILLA_POR_DEFECTO = 20261018
PREFIJO_POR_DEFECTO = "S"


@dataclass(frozen=True)
class Parametros:
    semilla: int = SEMILLA_POR_DEFECTO
    dias: int = 3
    fecha_fin: date = FECHA_FIN_POR_DEFECTO
    llegadas_por_hora: float = 30.0
    prob_preferencial: float = 0.20
    prob_abandono: float = 0.07
    mediana_atencion_seg: float = 240.0
    # Jornada en UTC (14:00-22:00 UTC equivale a 08:00-16:00 en UTC-6).
    hora_apertura_utc: int = 14
    hora_cierre_utc: int = 22
    # Instante "ahora" simulado dentro del último día (hora UTC, decimal: 18.5 = 18:30).
    hora_corte_utc: float = 18.5
    prefijo_codigo: str = PREFIJO_POR_DEFECTO
    # False (por defecto): los turnos que al corte estarían 'llamado' o 'en_atencion'
    # se cierran (atendido/abandonado). Así los datos sintéticos no dejan turnos
    # "activos" que se confundan con la operación real (p. ej. en el panel de
    # atención). Los 'pendiente' sí se conservan. True: instantánea fiel del corte.
    dejar_turnos_activos: bool = False

    def validar(self) -> None:
        if self.dias < 1:
            raise ValueError("dias debe ser >= 1")
        if self.llegadas_por_hora <= 0:
            raise ValueError("llegadas_por_hora debe ser > 0")
        for nombre in ("prob_preferencial", "prob_abandono"):
            if not 0 <= getattr(self, nombre) <= 1:
                raise ValueError(f"{nombre} debe estar entre 0 y 1")
        if not 0 <= self.hora_apertura_utc < self.hora_cierre_utc <= 24:
            raise ValueError("jornada inválida")
        if not self.hora_apertura_utc <= self.hora_corte_utc <= self.hora_cierre_utc + 2:
            raise ValueError("hora_corte_utc fuera de la jornada")
        if len(self.prefijo_codigo) != 1 or not self.prefijo_codigo.isalpha() or not self.prefijo_codigo.isupper():
            raise ValueError("prefijo_codigo debe ser una letra mayúscula (formato X-001)")


def _dt(segundos: int) -> datetime:
    return datetime.fromtimestamp(segundos, tz=timezone.utc)


def _simular_dia(rng: random.Random, dia: date, p: Parametros) -> list[dict]:
    """Simula un día completo. Devuelve turnos con tiempos en segundos (epoch)."""
    apertura = int(datetime(dia.year, dia.month, dia.day, p.hora_apertura_utc, tzinfo=timezone.utc).timestamp())
    cierre = int(datetime(dia.year, dia.month, dia.day, p.hora_cierre_utc, tzinfo=timezone.utc).timestamp()) \
        if p.hora_cierre_utc < 24 else apertura + (p.hora_cierre_utc - p.hora_apertura_utc) * 3600
    # Se dejan de aceptar llegadas 30 min antes del cierre.
    limite_llegadas = cierre - 1800

    llegadas = []
    t = float(apertura)
    tasa = p.llegadas_por_hora / 3600.0
    while True:
        t += rng.expovariate(tasa)
        if t >= limite_llegadas:
            break
        pref = rng.random() < p.prob_preferencial
        llegadas.append({"creado": int(t), "prioridad": PRIORIDAD_PREFERENCIAL if pref else PRIORIDAD_NORMAL})

    # Atributos aleatorios fijados por turno ANTES de simular (el orden de
    # consumo del generador no depende de las decisiones de la cola).
    for ll in llegadas:
        ll["abandona"] = rng.random() < p.prob_abandono
        ll["acercarse_seg"] = 10 + int(rng.random() * 111)                    # 10-120 s hasta iniciar
        dur = rng.lognormvariate(0, 0.5) * p.mediana_atencion_seg              # mediana configurable
        ll["atencion_seg"] = int(min(max(dur, 45), 1200))

    libre_en = {v: apertura for v in VENTANILLAS}
    pendientes: list[int] = []
    i = 0
    n = len(llegadas)
    resultado = []
    while i < n or pendientes:
        ventanilla = min(VENTANILLAS, key=lambda v: (libre_en[v], v))
        t_ahora = libre_en[ventanilla]
        if not pendientes:
            t_ahora = max(t_ahora, llegadas[i]["creado"])
        while i < n and llegadas[i]["creado"] <= t_ahora:
            pendientes.append(i)
            i += 1
        # Prioridad antes que llegada; FIFO dentro de la misma prioridad.
        elegido = min(
            pendientes,
            key=lambda k: (0 if llegadas[k]["prioridad"] == PRIORIDAD_PREFERENCIAL else 1,
                           llegadas[k]["creado"], k),
        )
        pendientes.remove(elegido)
        ll = llegadas[elegido]
        llamado = t_ahora
        turno = {"creado": ll["creado"], "prioridad": ll["prioridad"], "ventanilla": ventanilla,
                 "llamado": llamado, "inicio": None, "final": None, "abandonado": None}
        if ll["abandona"]:
            turno["abandonado"] = llamado + TTL_ABANDONO_SEG
            libre_en[ventanilla] = turno["abandonado"]
        else:
            turno["inicio"] = llamado + ll["acercarse_seg"]
            turno["final"] = turno["inicio"] + ll["atencion_seg"]
            libre_en[ventanilla] = turno["final"]
        resultado.append(turno)
    return resultado


def _a_documento(sim: dict, codigo: str, ahora: int | None) -> dict | None:
    """Convierte un turno simulado en documento del contrato, aplicando el corte
    de 'ahora' (None = día completo). Devuelve None si aún no existe."""
    if ahora is not None and sim["creado"] > ahora:
        return None

    def visible(valor):
        return valor if (valor is not None and (ahora is None or valor <= ahora)) else None

    llamado = visible(sim["llamado"])
    inicio = visible(sim["inicio"])
    final = visible(sim["final"])
    abandonado = visible(sim["abandonado"])

    if llamado is None:
        estado = ESTADO_PENDIENTE
    elif abandonado is not None:
        estado = ESTADO_ABANDONADO
    elif final is not None:
        estado = ESTADO_ATENDIDO
    elif inicio is not None:
        estado = ESTADO_EN_ATENCION
    else:
        estado = ESTADO_LLAMADO

    return {
        "codigo": codigo,
        "servicio": SERVICIO_ID,
        "prioridad": sim["prioridad"],
        "estado": estado,
        "ventanilla": None if estado == ESTADO_PENDIENTE else sim["ventanilla"],
        "operador": None,
        "timestamps": {
            "creado": _dt(sim["creado"]),
            "llamado": _dt(llamado) if llamado is not None else None,
            "inicio_atencion": _dt(inicio) if inicio is not None else None,
            "finalizado": _dt(final) if final is not None else None,
            "abandonado": _dt(abandonado) if abandonado is not None else None,
        },
        "metricas": {
            "espera_seg": (llamado - sim["creado"]) if llamado is not None else None,
            "atencion_seg": (final - inicio) if final is not None else None,
        },
    }


def generar_turnos(parametros: Parametros | None = None) -> list[dict]:
    """Genera la lista completa de turnos sintéticos, ordenados por creación.

    Los códigos son consecutivos globales (como el contador INCR real):
    ``S-001``, ``S-002``... El prefijo (por defecto ``S``) se separa a propósito
    de la serie ``A-`` que usa la operación real/demo para no colisionar con el
    contador de Redis ni con los turnos emitidos en vivo.
    """
    p = parametros or Parametros()
    p.validar()
    rng = random.Random(p.semilla)

    simulados: list[tuple[dict, int | None]] = []
    for desplazamiento in range(p.dias - 1, -1, -1):
        dia = p.fecha_fin - timedelta(days=desplazamiento)
        ultimo = desplazamiento == 0
        corte = None
        if ultimo:
            corte = int(datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc).timestamp()
                        + p.hora_corte_utc * 3600)
        for sim in _simular_dia(rng, dia, p):
            simulados.append((sim, corte))

    # El corte solo descarta llegadas posteriores al instante simulado (las últimas
    # en el tiempo), así que el consecutivo de códigos queda sin huecos.
    simulados = [(sim, corte) for sim, corte in simulados if corte is None or sim["creado"] <= corte]
    simulados.sort(key=lambda par: par[0]["creado"])
    ancho = max(3, len(str(len(simulados))))
    documentos = []
    for numero, (sim, corte) in enumerate(simulados, start=1):
        if corte is not None and not p.dejar_turnos_activos and sim["llamado"] <= corte:
            corte = None  # ya estaba en curso al corte: se muestra terminado
        documentos.append(_a_documento(sim, f"{p.prefijo_codigo}-{numero:0{ancho}d}", corte))
    return documentos
