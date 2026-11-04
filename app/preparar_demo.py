"""
P07 · Preparación de la demostración en vivo.

Comprueba que el entorno está listo (conexiones, índices, datos sintéticos, dirección de los QR, zona
horaria y estado de partida) y, si se pide, deja turnos en espera para empezar. Es idempotente y NO borra
nada: ni turnos, ni claves de Redis. Reiniciar la demo desde A-001 sigue siendo una decisión manual (ver la guía).

Estados de cada comprobación: ``ok``, ``aviso`` (conviene revisarlo; no impide la demo) o ``error``
(la demo no puede hacerse así).
"""
from __future__ import annotations

import os
from zoneinfo import ZoneInfo

from app import cola
from app.constantes import ESTADO_EN_ATENCION, ESTADO_LLAMADO, PRIORIDAD_NORMAL, PRIORIDAD_PREFERENCIAL
from app.emitir import emitir_turno
from app.turnos_schema import COLECCION_TURNOS, INDICES_TURNOS

SINTETICOS_MINIMOS = 500                       # el generador por defecto produce 554 turnos S-NNN
HOSTS_LOCALES = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def _c(nombre: str, estado: str, detalle: str) -> dict:
    return {"nombre": nombre, "estado": estado, "detalle": detalle}


def conexiones(db, redis) -> list:
    res = []
    for nombre, accion in (("MongoDB responde", lambda: db.command("ping")), ("Redis responde", redis.ping)):
        try:
            accion()
            res.append(_c(nombre, "ok", "responde"))
        except Exception as e:  # noqa: BLE001
            res.append(_c(nombre, "error", f"no responde ({type(e).__name__})"))
    return res


def indices(db) -> dict:
    esperados = [i["options"]["name"] for i in INDICES_TURNOS]
    try:
        presentes = set(db[COLECCION_TURNOS].index_information())
    except Exception as e:  # noqa: BLE001
        return _c("Índices de turnos", "error", f"no se pudieron leer ({type(e).__name__})")
    faltan = [n for n in esperados if n not in presentes]
    if faltan:
        return _c("Índices de turnos", "error", f"faltan: {', '.join(faltan)} (python scripts/init_mongo.py)")
    return _c("Índices de turnos", "ok", f"{len(esperados)} de {len(esperados)} presentes")


def sinteticos(db, cargar: bool = False) -> dict:
    """Cuenta los turnos S-NNN; con ``cargar`` hace el upsert idempotente del generador (no borra nada)."""
    filtro = {"codigo": {"$regex": r"^S-\d+$"}}
    cantidad = db[COLECCION_TURNOS].count_documents(filtro)
    if cantidad < SINTETICOS_MINIMOS and cargar:
        from scripts.sinteticos import cargador
        from scripts.sinteticos.generador import generar_turnos
        cargador.cargar(db[COLECCION_TURNOS], generar_turnos())
        cantidad = db[COLECCION_TURNOS].count_documents(filtro)
    if cantidad >= SINTETICOS_MINIMOS:
        return _c("Datos sintéticos (historial)", "ok", f"{cantidad} turnos S-NNN")
    return _c("Datos sintéticos (historial)", "aviso",
              f"{cantidad} turnos S-NNN; cárguelos con --cargar-sinteticos o scripts/generar_datos_sinteticos.py --cargar")


def direccion_qr(url_base: str | None = None) -> dict:
    url = (url_base if url_base is not None else os.getenv("PUBLIC_BASE_URL", "")).strip()
    if not url:
        return _c("Dirección de los QR", "aviso", "PUBLIC_BASE_URL no está definida")
    if any(h in url for h in HOSTS_LOCALES):
        return _c("Dirección de los QR", "aviso", f"{url} es local: un celular no podrá abrir los QR")
    return _c("Dirección de los QR", "ok", url)


def zona_horaria(nombre: str | None = None) -> dict:
    nombre = nombre or os.getenv("ZONA_HORARIA", "America/Costa_Rica")
    try:
        ZoneInfo(nombre)
        return _c("Zona horaria de las pantallas", "ok", nombre)
    except Exception:  # noqa: BLE001
        return _c("Zona horaria de las pantallas", "aviso", f"{nombre!r} no existe: se mostrará UTC")


def estado_de_partida(db) -> dict:
    """Informa de lo que ya hay en la operación; no lo modifica."""
    try:
        en_cola = cola.tamano_cola()
        activos = db[COLECCION_TURNOS].count_documents({"estado": {"$in": [ESTADO_LLAMADO, ESTADO_EN_ATENCION]}})
    except Exception as e:  # noqa: BLE001
        return _c("Estado de partida", "error", f"no se pudo leer ({type(e).__name__})")
    if en_cola == 0 and activos == 0:
        return _c("Estado de partida", "ok", "cola vacía y ninguna ventanilla ocupada")
    return _c("Estado de partida", "aviso",
              f"{en_cola} en la cola y {activos} turnos en curso: atiéndalos antes de empezar o continúe con ellos")


def asegurar_en_espera(db, cantidad: int) -> list:
    """Emite solo los turnos que faltan para que haya ``cantidad`` en la cola (idempotente). Devuelve los emitidos."""
    emitidos = []
    for i in range(max(0, cantidad - cola.tamano_cola())):
        prioridad = PRIORIDAD_PREFERENCIAL if i % 3 == 2 else PRIORIDAD_NORMAL
        emitidos.append(emitir_turno(db, prioridad))
    return emitidos


def preparar(db, redis, *, en_espera: int = 0, cargar_sinteticos: bool = False, url_base: str | None = None) -> list:
    """Corre todas las comprobaciones y devuelve la lista de resultados (nunca lanza por un servicio caído)."""
    res = conexiones(db, redis)
    if any(r["estado"] == "error" for r in res):
        return res                                    # sin conexiones no tiene sentido seguir
    res.append(indices(db))
    res.append(sinteticos(db, cargar_sinteticos))
    res.append(direccion_qr(url_base))
    res.append(zona_horaria())
    if en_espera:
        try:
            emitidos = asegurar_en_espera(db, en_espera)
            res.append(_c("Turnos en espera para la demo", "ok",
                          f"emitidos {len(emitidos)}: {', '.join(t['codigo'] for t in emitidos) or 'ya había suficientes'}"))
        except Exception as e:  # noqa: BLE001
            res.append(_c("Turnos en espera para la demo", "error", f"no se pudieron emitir ({type(e).__name__})"))
    res.append(estado_de_partida(db))
    return res


def hay_errores(resultados: list) -> bool:
    return any(r["estado"] == "error" for r in resultados)
