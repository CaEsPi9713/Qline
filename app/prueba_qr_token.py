"""TT-001 / TT-002 / HU-003 · Prueba en el servidor del campo `qr_token` y su índice parcial único.

Comprueba contra la colección real lo que el código solo puede afirmar:
  1. Un turno con un qr_token UUID v4 válido se acepta (validador del motor).
  2. Un segundo turno con el MISMO qr_token se rechaza (índice único).
  3. Varios turnos sin qr_token (campo ausente o null) conviven: el índice parcial no los indexa,
     que es lo que permite no migrar los turnos anteriores.
  4. La consulta que usa la aplicación (`filtro_por_token`) usa el índice (IXSCAN).
  5. Informativo: si el MOTOR valida el formato del token. El esquema del servidor se actualiza solo al
     recrear la colección, así que puede no hacerlo; el formato lo valida siempre el validador de Python.

Usa solo códigos Q-9901 a Q-9905 y los elimina al terminar (también si algo falla).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError, PyMongoError, WriteError

from app.consulta_qr import filtro_por_token
from app.datos_prueba import construir_turno
from app.informe import encabezado
from app.mediciones_indices import analizar_explain
from app.turnos_schema import TurnoValidationError, validar_documento_turno

CODIGOS = [f"Q-99{n:02d}" for n in range(1, 6)]


@dataclass
class Comprobacion:
    nombre: str
    ok: bool | None            # None = informativo (no cuenta para el resultado)
    detalle: str = ""


@dataclass
class ResultadoQr:
    comprobaciones: list[Comprobacion] = field(default_factory=list)

    def agregar(self, nombre: str, ok: bool | None, detalle: str = "") -> None:
        self.comprobaciones.append(Comprobacion(nombre, ok, detalle))

    @property
    def ok(self) -> bool:
        evaluables = [c for c in self.comprobaciones if c.ok is not None]
        return bool(evaluables) and all(c.ok for c in evaluables)


def _turno(codigo: str, **kw) -> dict:
    return construir_turno(codigo, "pendiente", "normal", datetime.now(timezone.utc), **kw)


def ejecutar(coleccion) -> ResultadoQr:
    res = ResultadoQr()
    token = str(uuid.uuid4())
    coleccion.delete_many({"codigo": {"$in": CODIGOS}})
    try:
        # 1. válido
        try:
            coleccion.insert_one(_turno(CODIGOS[0], qr_token=token))
            res.agregar("Un turno con qr_token UUID v4 se acepta", True)
        except PyMongoError as exc:
            res.agregar("Un turno con qr_token UUID v4 se acepta", False, f"{type(exc).__name__}: {exc}")
            return res

        # 2. duplicado
        try:
            coleccion.insert_one(_turno(CODIGOS[1], qr_token=token))
            res.agregar("Un segundo turno con el mismo qr_token se rechaza", False, "se insertó: el índice no es único")
        except DuplicateKeyError:
            res.agregar("Un segundo turno con el mismo qr_token se rechaza", True, "DuplicateKeyError")
        except PyMongoError as exc:
            res.agregar("Un segundo turno con el mismo qr_token se rechaza", False, f"{type(exc).__name__}: {exc}")

        # 3. sin token: coexisten
        try:
            coleccion.insert_one(_turno(CODIGOS[2]))
            coleccion.insert_one(_turno(CODIGOS[3]))
            coleccion.insert_one(_turno(CODIGOS[4], qr_token=None))
            res.agregar("Varios turnos sin qr_token (ausente o null) conviven", True,
                        "3 inserciones aceptadas: el índice parcial no los indexa")
        except PyMongoError as exc:
            res.agregar("Varios turnos sin qr_token (ausente o null) conviven", False, f"{type(exc).__name__}: {exc}")

        # 4. plan de la consulta de la aplicación
        try:
            plan = analizar_explain(coleccion.find(filtro_por_token(token)).explain())
            res.agregar("La consulta por token usa el índice (IXSCAN)", plan["usa_indice"],
                        f"plan {plan['plan']}, {plan['docs_examinados']} documento(s) examinado(s)")
        except Exception as exc:        # noqa: BLE001 · el simulado de pruebas no implementa explain
            res.agregar("La consulta por token usa el índice (IXSCAN)", None, f"no se pudo obtener el plan: {type(exc).__name__}")

        # 5. informativo: ¿el motor valida el formato?
        try:
            malo = _turno("Q-9905", qr_token="no-es-un-uuid")
            coleccion.insert_one(malo)
            coleccion.delete_one({"codigo": "Q-9905", "qr_token": "no-es-un-uuid"})
            res.agregar("Informativo · el motor valida el formato del token", None,
                        "NO: aceptó un token que no es UUID (el esquema del servidor es el anterior; se actualiza al recrear la colección)")
        except WriteError:
            res.agregar("Informativo · el motor valida el formato del token", None, "SÍ: rechazó un token que no es UUID")
        except PyMongoError as exc:
            res.agregar("Informativo · el motor valida el formato del token", None, f"{type(exc).__name__}")
        try:
            validar_documento_turno(_turno("Q-9905", qr_token="no-es-un-uuid"))
            res.agregar("El validador de Python rechaza un token que no es UUID v4", False, "lo aceptó")
        except TurnoValidationError as exc:
            res.agregar("El validador de Python rechaza un token que no es UUID v4", True, str(exc)[:80])
    finally:
        coleccion.delete_many({"codigo": {"$in": CODIGOS}})
    return res


def a_markdown(res: ResultadoQr) -> str:
    md = encabezado("Campo qr_token e índice parcial único (TT-001, TT-002, HU-003)")
    md += ("\nSe usan solo los códigos `Q-9901` a `Q-9905`, que se eliminan al terminar.\n\n"
           "| # | Comprobación | Resultado | Detalle |\n|---|---|---|---|\n")
    for i, c in enumerate(res.comprobaciones, start=1):
        estado = "informativo" if c.ok is None else ("✔ cumple" if c.ok else "✘ FALLA")
        md += f"| {i} | {c.nombre} | {estado} | {c.detalle} |\n"
    md += f"\n## Resultado global: {'**CORRECTO**' if res.ok else '**CON FALLAS**'}\n"
    return md
