"""Modelos de entrada/salida de HU-006 (Pydantic, incluido con FastAPI)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IniciarAtencionEntrada(BaseModel):
    # Debe coincidir con constantes.VENTANILLAS. Se valida además en el servicio.
    ventanilla: Literal["V-01", "V-02", "V-03"]


class TurnoEnAtencion(BaseModel):
    codigo: str
    estado: str
    ventanilla: str | None
    inicio_atencion: str | None
