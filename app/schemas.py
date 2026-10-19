"""Modelos de entrada/salida del ciclo de atención (Pydantic, incluido con FastAPI)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IniciarAtencionEntrada(BaseModel):
    # Debe coincidir con app.constantes.VENTANILLAS. Se valida además en el servicio.
    ventanilla: Literal["V-01", "V-02", "V-03"]


class TurnoEnAtencion(BaseModel):
    codigo: str
    estado: str
    ventanilla: str | None
    inicio_atencion: str | None


class TurnoFinalizado(BaseModel):
    codigo: str
    estado: str
    ventanilla: str
    inicio_atencion: str | None
    finalizado: str
    atencion_seg: int
    # None: sin gancho; False: MongoDB quedó correcto pero no se pudo limpiar Redis.
    redis_liberado: bool | None = None
