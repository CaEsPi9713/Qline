"""Colección MongoDB falsa en memoria para pruebas unitarias del ciclo de atención.

Implementa solo lo que usan app.atencion y el panel: find, find_one y update_one con filtro de igualdad (rutas con punto, y $in) y
$set con rutas con punto, find_one, y una bandera `falla` para simular una
caída de MongoDB. Las operaciones son atómicas (candado), como lo es
update_one sobre un documento en MongoDB.
"""

import copy
import threading
from datetime import datetime, timedelta, timezone

BASE = datetime(2026, 10, 18, 14, 0, 0, tzinfo=timezone.utc)


def utc(hora, minuto, segundo=0):
    return BASE.replace(hour=hora, minute=minuto, second=segundo)


def turno(codigo, estado, ventanilla, prioridad="normal", inicio=None):
    """Turno mínimo conforme a la sección 4.5; `inicio` fija timestamps.inicio_atencion."""
    creado = BASE
    llamado = creado + timedelta(minutes=5) if estado != "pendiente" else None
    return {
        "codigo": codigo,
        "servicio": "atencion_general",
        "prioridad": prioridad,
        "estado": estado,
        "ventanilla": ventanilla,
        "operador": None,
        "timestamps": {
            "creado": creado,
            "llamado": llamado,
            "inicio_atencion": inicio,
            "finalizado": None,
            "abandonado": creado + timedelta(minutes=8) if estado == "abandonado" else None,
        },
        "metricas": {"espera_seg": 300 if llamado else None, "atencion_seg": None},
    }


class _Resultado:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class ColeccionFalsa:
    def __init__(self, docs=()):
        self.docs = {d["codigo"]: copy.deepcopy(d) for d in docs}
        self.falla = False
        self._candado = threading.Lock()

    def _revisar(self):
        if self.falla:
            raise ConnectionError("MongoDB no disponible (simulado)")

    @staticmethod
    def _coincide(doc, filtro):
        def valor(ruta):
            actual = doc
            for parte in ruta.split("."):
                actual = actual.get(parte) if isinstance(actual, dict) else None
            return actual

        def cumple(k, esperado):
            if isinstance(esperado, dict) and "$in" in esperado:
                return valor(k) in esperado["$in"]
            return valor(k) == esperado

        return all(cumple(k, v) for k, v in filtro.items())

    def find(self, filtro):
        with self._candado:
            self._revisar()
            return [copy.deepcopy(d) for d in self.docs.values() if self._coincide(d, filtro)]

    def find_one(self, filtro):
        with self._candado:
            self._revisar()
            for doc in self.docs.values():
                if self._coincide(doc, filtro):
                    return copy.deepcopy(doc)
        return None

    def update_one(self, filtro, cambio):
        with self._candado:
            self._revisar()
            for doc in self.docs.values():
                if not self._coincide(doc, filtro):
                    continue
                for ruta, valor in cambio["$set"].items():
                    destino = doc
                    *padres, hoja = ruta.split(".")
                    for p in padres:
                        destino = destino[p]
                    destino[hoja] = valor
                return _Resultado(1)
        return _Resultado(0)
