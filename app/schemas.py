"""Modelos de entrada/salida del ciclo de atención (Pydantic, incluido con FastAPI)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.constantes import PATRON_VENTANILLA


class IniciarAtencionEntrada(BaseModel):
    # Formato V-NN (catálogo dinámico, P09). Se valida además en el servicio.
    ventanilla: str = Field(pattern=PATRON_VENTANILLA)


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
    # Motivo y nota opcionales del cierre (S4-M03); None si no se informaron.
    cierre: dict | None = None
