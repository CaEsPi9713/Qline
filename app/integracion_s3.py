"""
Adaptadores entre los módulos de abandono/recuperación y la infraestructura real.

`abandono.py` y `recuperacion.py` no conocen Redis ni MongoDB: reciben funciones. Aquí se
construyen esas funciones con las mismas claves y reglas que usa app/cola.py, para que el
barrido y la recuperación actúen sobre la cola, las ventanillas y el canal de eventos reales.

Las claves se pueden reemplazar (`clave_cola`, `clave_contador`, `clave_eventos`) para que las
pruebas y las mediciones trabajen en un espacio aislado sin tocar la cola de operación.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from redis.exceptions import RedisError, WatchError

from app import cola, eventos
from app.constantes import CLAVE_COLA, CLAVE_CONTADOR, CLAVE_EVENTOS, clave_turno, clave_ventanilla_actual
from app.s3_comun import MongoNoDisponible, RedisNoDisponible, a_utc, EPOCH_UTC

REINTENTOS_CONTADOR = 20
INTERVALO_BARRIDO_POR_DEFECTO_SEG = 10.0
_MS = timedelta(milliseconds=1)


def conectar_mongo():
    """Colección `turnos` de la aplicación."""
    from app.main import get_db   # import diferido: evita cargar toda la aplicación al importar este módulo
    try:
        return get_db()["turnos"]
    except Exception as exc:
        raise MongoNoDisponible() from exc


def conectar_redis():
    """Cliente Redis de la aplicación (falla rápido si el servidor no responde)."""
    from app.redis_client import get_redis
    r = get_redis()
    try:
        r.ping()
    except RedisError as exc:
        raise RedisNoDisponible() from exc
    return r


def milisegundos(fecha: datetime) -> int:
    """Milisegundos desde la época con aritmética entera (sin errores de coma flotante)."""
    return (a_utc(fecha) - EPOCH_UTC) // _MS


def dependencias_abandono(r=None, *, clave_eventos: str = CLAVE_EVENTOS,
                          clave_ventanilla=clave_ventanilla_actual) -> dict:
    """Funciones para `barrer_abandonos`. Se usan como `barrer_abandonos(col, **dependencias_abandono(r))`.

    `clave_eventos` y `clave_ventanilla` se pueden reemplazar para pruebas aisladas de la operación real."""
    r = r or conectar_redis()

    def hash_existe(codigo: str) -> bool:
        try:
            return bool(r.exists(clave_turno(codigo)))
        except RedisError as exc:
            raise RedisNoDisponible() from exc

    def liberar_ventanilla(ventanilla: str, codigo: str) -> None:
        # Igual que cola.liberar_ventanilla_si: solo se libera si la ventanilla aún apunta a este turno.
        clave = clave_ventanilla(ventanilla)
        try:
            if r.get(clave) == codigo:
                r.delete(clave)
        except RedisError as exc:
            raise RedisNoDisponible() from exc

    def publicar_evento(tipo: str, datos: dict) -> None:
        evento = eventos.construir_evento(tipo, datos.get("codigo"), "abandonado", datos.get("ventanilla"))
        try:
            r.publish(clave_eventos, json.dumps(evento, ensure_ascii=False))
        except RedisError as exc:   # a diferencia de eventos.publicar, aquí el fallo se informa al barrido
            raise RedisNoDisponible() from exc

    return {"hash_existe": hash_existe, "liberar_ventanilla": liberar_ventanilla,
            "publicar_evento": publicar_evento}


def dependencias_cola(r=None, *, clave_cola: str = CLAVE_COLA, clave_contador: str = CLAVE_CONTADOR):
    """`DependenciasCola` para `reconciliar_cola`, sobre la cola y el contador reales (o aislados)."""
    from app.recuperacion import DependenciasCola
    r = r or conectar_redis()

    def leer_cola() -> list[str]:
        return list(r.zrange(clave_cola, 0, -1))

    def encolar(turno: dict) -> None:
        # Mismo puntaje que cola.encolar; NX para no reordenar ni duplicar lo que ya está.
        score = cola.calcular_score(turno["prioridad"], milisegundos(turno["timestamps"]["creado"]))
        r.zadd(clave_cola, {turno["codigo"]: score}, nx=True)

    def quitar(codigo: str) -> None:
        r.zrem(clave_cola, codigo)

    def leer_contador() -> int:
        return int(r.get(clave_contador) or 0)

    def fijar_contador(valor: int) -> None:
        """Sube el contador a `valor`; nunca lo baja (otro proceso pudo emitir turnos entretanto)."""
        for _ in range(REINTENTOS_CONTADOR):
            with r.pipeline() as pipe:
                try:
                    pipe.watch(clave_contador)
                    actual = int(pipe.get(clave_contador) or 0)
                    if actual >= valor:
                        return
                    pipe.multi()
                    pipe.set(clave_contador, valor)
                    pipe.execute()
                    return
                except WatchError:
                    continue
        raise RedisNoDisponible("No se pudo fijar el contador: demasiada concurrencia.")

    return DependenciasCola(leer_cola=leer_cola, encolar=encolar, quitar=quitar,
                            leer_contador=leer_contador, fijar_contador=fijar_contador)


def barrido_habilitado() -> bool:
    """BARRIDO_ABANDONO=0 (o false/no/off) apaga el barrido automático; por defecto está encendido."""
    return os.environ.get("BARRIDO_ABANDONO", "1").strip().lower() not in ("0", "false", "no", "off", "")


def intervalo_barrido() -> float:
    try:
        valor = float(os.environ.get("BARRIDO_INTERVALO_SEG", INTERVALO_BARRIDO_POR_DEFECTO_SEG))
    except ValueError:
        return INTERVALO_BARRIDO_POR_DEFECTO_SEG
    return valor if valor > 0 else INTERVALO_BARRIDO_POR_DEFECTO_SEG


def crear_barrido_abandono():
    """
    Barrido periódico de abandono listo para iniciar, o None si está deshabilitado.

    Cada pasada obtiene la colección y el cliente Redis en ese momento, así una caída de
    MongoDB o Redis solo hace fallar esa pasada (BarridoPeriodico la cuenta y sigue).
    """
    if not barrido_habilitado():
        return None
    from app.abandono import barrer_abandonos
    from app.barrido import BarridoPeriodico
    from app.redis_client import get_redis

    def pasada():
        return barrer_abandonos(conectar_mongo(), **dependencias_abandono(get_redis()))

    return BarridoPeriodico(pasada, intervalo_seg=intervalo_barrido())
