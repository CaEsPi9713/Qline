"""
Pantalla pública de llamados (HU-009).

Mantiene en memoria una lista de los llamados más recientes para mostrar en la
pantalla de sala. La lista se actualiza cuando llega un evento `turno_llamado`
del canal Redis Pub/Sub (a través del Hub de TT-013).

La lista solo expone: código de turno y ventanilla. No contiene datos
personales ni credenciales.

Reglas:
- Máximo MAX_LLAMADOS entradas simultáneas.
- Un turno ya atendido (atencion_finalizada) o abandonado se retira de la lista.
- Si no hay llamados activos, la lista se devuelve vacía.
- La lista persiste en memoria; si el proceso reinicia se pierde (aceptable para
  una pantalla de sala cuyo objetivo es mostrar el llamado actual, no un historial).
"""
import threading
from datetime import datetime, timezone
from typing import List, Optional

from app.constantes import (
    ESTADO_LLAMADO,
    ESTADO_EN_ATENCION,
)
from app.eventos import TURNO_LLAMADO, ATENCION_FINALIZADA, TURNO_ABANDONADO, ATENCION_INICIADA

MAX_LLAMADOS = 10          # entradas visibles en la pantalla de sala
TTL_LLAMADO_SEG = 300      # 5 min: tiempo máximo que un llamado permanece en pantalla sin confirmación


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _Llamado:
    __slots__ = ("codigo", "ventanilla", "estado", "ts")

    def __init__(self, codigo: str, ventanilla: str, estado: str = ESTADO_LLAMADO):
        self.codigo = codigo
        self.ventanilla = ventanilla
        self.estado = estado
        self.ts = datetime.now(timezone.utc).timestamp()

    def esta_vigente(self) -> bool:
        """True si el llamado sigue activo (no expiró y el estado lo permite)."""
        if self.estado not in (ESTADO_LLAMADO, ESTADO_EN_ATENCION):
            return False
        edad = datetime.now(timezone.utc).timestamp() - self.ts
        return edad < TTL_LLAMADO_SEG

    def a_dict(self) -> dict:
        return {"codigo": self.codigo, "ventanilla": self.ventanilla, "estado": self.estado}


class PantallaPública:
    """
    Registro en memoria de los llamados activos para la pantalla de sala.

    Thread-safe: usa un Lock interno porque el Hub de eventos corre en un hilo
    separado y las rutas FastAPI en el hilo principal / workers asíncronos.
    """

    def __init__(self, max_llamados: int = MAX_LLAMADOS):
        self._max = max_llamados
        self._llamados: List[_Llamado] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def registrar_llamado(self, codigo: str, ventanilla: str) -> None:
        """Añade o actualiza el llamado de un turno en la pantalla."""
        with self._lock:
            # Si ya existe, actualiza y mueve al frente
            for entry in self._llamados:
                if entry.codigo == codigo:
                    entry.ventanilla = ventanilla
                    entry.estado = ESTADO_LLAMADO
                    entry.ts = datetime.now(timezone.utc).timestamp()
                    self._llamados.remove(entry)
                    self._llamados.insert(0, entry)
                    return
            nuevo = _Llamado(codigo, ventanilla)
            self._llamados.insert(0, nuevo)
            # Mantener solo los últimos N
            if len(self._llamados) > self._max:
                self._llamados = self._llamados[: self._max]

    def marcar_en_atencion(self, codigo: str) -> None:
        """Actualiza el estado del turno a en_atencion; sigue visible en pantalla."""
        with self._lock:
            for entry in self._llamados:
                if entry.codigo == codigo:
                    entry.estado = ESTADO_EN_ATENCION
                    return

    def retirar(self, codigo: str) -> None:
        """Elimina el turno de la pantalla (atendido o abandonado)."""
        with self._lock:
            self._llamados = [e for e in self._llamados if e.codigo != codigo]

    def llamados_vigentes(self) -> List[dict]:
        """Lista de llamados activos, del más reciente al más antiguo."""
        with self._lock:
            vigentes = [e for e in self._llamados if e.esta_vigente()]
            # Compactar si expirados
            if len(vigentes) != len(self._llamados):
                self._llamados = vigentes
            return [e.a_dict() for e in vigentes]

    def procesar_evento(self, evento: dict) -> None:
        """
        Procesa un evento recibido del canal Redis Pub/Sub.
        Llamado desde el hilo del Hub (thread-safe).
        """
        tipo = evento.get("tipo")
        codigo = evento.get("codigo")
        if not codigo:
            return
        if tipo == TURNO_LLAMADO:
            ventanilla = evento.get("ventanilla", "")
            self.registrar_llamado(codigo, ventanilla)
        elif tipo == ATENCION_INICIADA:
            self.marcar_en_atencion(codigo)
        elif tipo in (ATENCION_FINALIZADA, TURNO_ABANDONADO):
            self.retirar(codigo)

    def consultar_desde_mongo(self, db, limite: int = MAX_LLAMADOS) -> Optional[List[dict]]:
        """
        Fallback: consulta MongoDB para obtener turnos con estado llamado/en_atencion
        cuando la lista en memoria está vacía (p. ej. tras reinicio del proceso).
        Devuelve None si MongoDB no está disponible.
        """
        try:
            cursor = db["turnos"].find(
                {"estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]},
                 "ventanilla": {"$exists": True, "$ne": None}},
                {"_id": 0, "codigo": 1, "ventanilla": 1, "estado": 1},
            ).sort("timestamps.llamado", -1).limit(limite)
            return [
                {"codigo": d["codigo"], "ventanilla": d.get("ventanilla", ""), "estado": d.get("estado", "")}
                for d in cursor
            ]
        except Exception:
            return None


# Instancia global (una por proceso)
pantalla = PantallaPública()
