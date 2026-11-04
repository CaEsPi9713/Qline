"""Ejecución periódica del barrido de abandono (HU-008 / TT-012).

Un hilo daemon por proceso (mismo patrón que el receptor de eventos de
app/tiempo_real.py). Con varios workers de Gunicorn habrá un barrido por
worker: es seguro, porque cada abandono es un update_one condicionado a
``estado = llamado`` (solo uno gana) y liberar/publicar son idempotentes.

Uso en FastAPI (ejemplo; adaptar al arranque real de la app):

    from app.barrido import BarridoPeriodico
    from app.abandono import barrer_abandonos

    barrido = BarridoPeriodico(lambda: barrer_abandonos(coleccion, **dependencias), intervalo_seg=10)

    @app.on_event("startup")
    def _iniciar(): barrido.iniciar()

    @app.on_event("shutdown")
    def _detener(): barrido.detener()
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

registro = logging.getLogger("qline.barrido")


class BarridoPeriodico:
    def __init__(self, ejecutar: Callable[[], object], intervalo_seg: float = 10.0):
        if intervalo_seg <= 0:
            raise ValueError("intervalo_seg debe ser > 0")
        self._ejecutar = ejecutar
        self.intervalo_seg = intervalo_seg
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.pasadas = 0
        self.errores = 0
        self.ultimo_resultado = None

    def ejecutar_una_vez(self):
        """Una pasada; nunca lanza (un fallo se cuenta y se registra)."""
        try:
            self.ultimo_resultado = self._ejecutar()
            self.pasadas += 1
        except Exception:                       # MongoDB caído u otro: reintentar en la siguiente pasada
            self.errores += 1
            registro.exception("Fallo en el barrido de abandono")
        return self.ultimo_resultado

    def _bucle(self):
        while not self._parar.is_set():
            self.ejecutar_una_vez()
            self._parar.wait(self.intervalo_seg)

    def iniciar(self):
        if self._hilo and self._hilo.is_alive():
            return
        self._parar.clear()
        self._hilo = threading.Thread(target=self._bucle, name="qline-barrido-abandono", daemon=True)
        self._hilo.start()

    def detener(self, esperar_seg: float = 2.0):
        self._parar.set()
        if self._hilo:
            self._hilo.join(timeout=esperar_seg)

    @property
    def activo(self) -> bool:
        return bool(self._hilo and self._hilo.is_alive())
