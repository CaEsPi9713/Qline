"""TT-019 · Casos de fallo del abandono (HU-008) y la recuperación (HU-012).

Cada caso provoca una condición anormal y comprueba que el módulo responde de forma
CONTROLADA: sin excepciones sin explicar, sin dejar datos a medias y sin tocar lo que no debe.

Secciones: 1 caso normal · 2 Redis caído · 3 MongoDB caído · 4 datos inválidos · 5 carreras e idempotencia.

Reloj adelantado: la prueba usa un reloj ADELANTO_RELOJ_SEG por delante del real, así sus turnos
"vencidos" no lo están para el barrido automático de la aplicación, que no los toca durante la prueba.

Aislamiento: turnos de la serie "F" (F-001…), cola, canal de eventos y claves de ventanilla propios
(`grupo2:qline:prueba:*`). No se detiene ningún servicio: "caído" significa un cliente que apunta a un
puerto sin servidor (Redis) o una colección que lanza ConnectionError (MongoDB). Los datos
inválidos que el validador de MongoDB rechazaría se prueban sobre una colección en memoria.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from app import integracion_s3 as integ
from app.abandono import barrer_abandonos
from app.constantes import REDIS_PREFIJO, clave_turno
from app.datos_prueba import construir_turno
from app.informe import encabezado
from app.mediciones_s3 import ADELANTO_RELOJ_SEG, ColeccionAcotada
from app.recuperacion import reconciliar_cola
from app.s3_comun import ErrorS3, MongoNoDisponible, RedisNoDisponible, TTL_ABANDONO_SEG

SERIE = "F"
PREFIJO = f"{SERIE}-"
FILTRO_SERIE = {"codigo": {"$regex": rf"^{SERIE}-\d+$"}}
CLAVE_COLA = f"{REDIS_PREFIJO}prueba:cola:{SERIE}"
CLAVE_CONTADOR = f"{REDIS_PREFIJO}prueba:contador:{SERIE}"
CLAVE_EVENTOS = f"{REDIS_PREFIJO}prueba:eventos:{SERIE}"
PATRON_VENTANILLA = f"{REDIS_PREFIJO}prueba:ventanilla:{SERIE}:"


def clave_ventanilla(ventanilla: str) -> str:
    return f"{PATRON_VENTANILLA}{ventanilla}"


# --------------------------------------------------------------------------------------
# Colecciones y clientes que fallan
# --------------------------------------------------------------------------------------
class ColeccionCaida:
    """MongoDB inalcanzable: toda operación lanza ConnectionError."""

    def __getattr__(self, nombre):
        def _falla(*a, **kw):
            raise ConnectionError("MongoDB no disponible (simulado)")
        return _falla


class ColeccionEnMemoria:
    """Colección mínima en memoria para datos que el validador real rechazaría o para carreras.

    `vista_find`: si se indica, `find` devuelve siempre esa instantánea (un dato que ya cambió).
    `falla_al_actualizar`: update_one lanza ConnectionError (MongoDB cae a mitad del barrido).
    """

    class _Res:
        def __init__(self, n):
            self.modified_count = n

    def __init__(self, docs, vista_find=None, falla_al_actualizar=False):
        self.docs = [json.loads(json.dumps(d, default=lambda x: x.isoformat())) for d in docs]
        self._fechas(self.docs)
        self.vista_find = vista_find
        self.falla_al_actualizar = falla_al_actualizar

    @staticmethod
    def _fechas(docs):
        for d in docs:
            for k, v in (d.get("timestamps") or {}).items():
                if isinstance(v, str):
                    d["timestamps"][k] = datetime.fromisoformat(v)

    @staticmethod
    def _valor(doc, ruta):
        for parte in ruta.split("."):
            doc = doc.get(parte) if isinstance(doc, dict) else None
        return doc

    def _cumple(self, doc, filtro):
        for clave, esperado in filtro.items():
            if clave == "$and":
                if not all(self._cumple(doc, f) for f in esperado):
                    return False
                continue
            v = self._valor(doc, clave)
            if isinstance(esperado, dict):
                if "$in" in esperado and v not in esperado["$in"]:
                    return False
                if "$lte" in esperado and (v is None or v > esperado["$lte"]):
                    return False
                if "$regex" in esperado and not (isinstance(v, str) and re.search(esperado["$regex"], v)):
                    return False
            elif v != esperado:
                return False
        return True

    def find(self, filtro=None, proyeccion=None, *a, **kw):
        fuente = self.vista_find if self.vista_find is not None else self.docs
        return [dict(d) for d in fuente if self._cumple(d, filtro or {})]

    def update_one(self, filtro, cambio, *a, **kw):
        if self.falla_al_actualizar:
            raise ConnectionError("MongoDB se cayó a mitad del barrido (simulado)")
        for d in self.docs:
            if self._cumple(d, filtro):
                for ruta, valor in cambio["$set"].items():
                    if "." in ruta:
                        a1, b1 = ruta.split(".")
                        d.setdefault(a1, {})[b1] = valor
                    else:
                        d[ruta] = valor
                return self._Res(1)
        return self._Res(0)


class RedisCaido:
    """Redis inalcanzable (para pruebas automáticas, sin esperar tiempos de conexión)."""

    def __getattr__(self, nombre):
        from redis.exceptions import ConnectionError as RedisConnError

        def _falla(*a, **kw):
            raise RedisConnError("Redis no disponible (simulado)")
        return _falla


def cliente_redis_caido(puerto: int = 6390):
    """Cliente real hacia un puerto sin Redis, con falla rápida (sin reintentos)."""
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    return redis.Redis(host="127.0.0.1", port=puerto, decode_responses=True, socket_connect_timeout=1,
                       retry=Retry(NoBackoff(), 0))


# --------------------------------------------------------------------------------------
# Contexto y casos
# --------------------------------------------------------------------------------------
@dataclass
class Caso:
    seccion: str
    nombre: str
    provoca: str
    esperado: str
    observado: str = ""
    ok: bool = False
    ms: float = 0.0


class Contexto:
    def __init__(self, coleccion, r, r_caido, ahora: datetime):
        self.col, self.r, self.r_caido, self.ahora = coleccion, r, r_caido, ahora
        self.acotada = ColeccionAcotada(coleccion, FILTRO_SERIE)

    def limpiar(self):
        self.col.delete_many(FILTRO_SERIE)
        for patron in (f"{PATRON_VENTANILLA}*", clave_turno(PREFIJO) + "*"):
            for clave in list(self.r.scan_iter(match=patron)):
                self.r.delete(clave)
        self.r.delete(CLAVE_COLA, CLAVE_CONTADOR)

    def llamado(self, codigo, seg=200, ventanilla="V-01", reservar=True):
        llamado = self.ahora - timedelta(seconds=seg)
        self.col.insert_one(construir_turno(codigo, "llamado", "normal", llamado - timedelta(seconds=60),
                                            ventanilla, llamado))
        if reservar:
            self.r.set(clave_ventanilla(ventanilla), codigo)

    def pendiente(self, codigo, prioridad="normal", minutos=10):
        self.col.insert_one(construir_turno(codigo, "pendiente", prioridad, self.ahora - timedelta(minutes=minutos)))

    def estado(self, codigo):
        d = self.col.find_one({"codigo": codigo})
        return d["estado"] if d else None

    def dep_aband(self, r=None):
        return integ.dependencias_abandono(r or self.r, clave_eventos=CLAVE_EVENTOS, clave_ventanilla=clave_ventanilla)

    def dep_cola(self, r=None):
        return integ.dependencias_cola(r or self.r, clave_cola=CLAVE_COLA, clave_contador=CLAVE_CONTADOR)

    def barrer(self, col=None, deps=None, **kw):
        return barrer_abandonos(col if col is not None else self.acotada, ahora=self.ahora,
                                **(deps or self.dep_aband()), **kw)

    def reconciliar(self, col=None, deps=None, **kw):
        kw.setdefault("restaurar_contador", False)
        return reconciliar_cola(col if col is not None else self.col, deps or self.dep_cola(),
                                aplicar=True, serie=SERIE, solo_serie=True, **kw)

    def suscribir(self):
        ps = self.r.pubsub()
        ps.subscribe(CLAVE_EVENTOS)
        ps.get_message(timeout=1)
        return ps

    @staticmethod
    def eventos(ps, esperados=1, espera=1.0) -> list[dict]:
        out, fin = [], time.time() + espera
        while len(out) < esperados and time.time() < fin:
            m = ps.get_message(timeout=0.1)
            if m and m.get("type") == "message":
                out.append(json.loads(m["data"]))
        return out


CASOS: list[tuple[str, str, str, str, Callable]] = []


def caso(seccion, nombre, provoca, esperado):
    def deco(fn):
        CASOS.append((seccion, nombre, provoca, esperado, fn))
        return fn
    return deco


S1, S2, S3, S4, S5 = ("1. Caso normal", "2. Redis caído", "3. MongoDB caído", "4. Datos inválidos",
                      "5. Carreras e idempotencia")


# 1 · normal ----------------------------------------------------------------------------
@caso(S1, "Abandono de un turno que no se presentó", "Turno llamado hace 200 s, sin Hash en Redis",
      "Pasa a abandonado, la ventanilla se libera y se publica el evento")
def _(c: Contexto):
    c.llamado("F-001")
    ps = c.suscribir()
    res = c.barrer()
    ev = c.eventos(ps)
    ok = (res.ok and res.abandonados == ["F-001"] and c.estado("F-001") == "abandonado"
          and c.r.get(clave_ventanilla("V-01")) is None and len(ev) == 1 and ev[0]["tipo"] == "turno_abandonado")
    return ok, f"estado={c.estado('F-001')}, ventanilla libre={c.r.get(clave_ventanilla('V-01')) is None}, eventos={len(ev)}"


@caso(S1, "Rehidratación de una cola perdida", "5 pendientes en MongoDB y la cola vacía",
      "Los 5 vuelven a la cola, en orden, sin errores")
def _(c: Contexto):
    for i in range(1, 6):
        c.pendiente(f"F-{i:03d}", "preferencial" if i == 4 else "normal", minutos=20 - i)
    rep = c.reconciliar()
    cola = c.r.zrange(CLAVE_COLA, 0, -1)
    return (rep.ok is True and cola == ["F-004", "F-001", "F-002", "F-003", "F-005"],
            f"cola={cola}")


# 2 · Redis caído -----------------------------------------------------------------------
@caso(S2, "Barrido con Redis caído", "No se puede consultar si el Hash existe",
      "No se abandona nada (no se sabe si el plazo venció de verdad); el turno sigue llamado")
def _(c: Contexto):
    c.llamado("F-001")
    res = c.barrer(deps=c.dep_aband(c.r_caido))
    return (res.omitidos_redis == ["F-001"] and not res.abandonados and c.estado("F-001") == "llamado",
            f"omitidos_redis={res.omitidos_redis}, estado={c.estado('F-001')}")


@caso(S2, "Redis cae después de abandonar (no libera la ventanilla)", "Mongo ya marcó el abandono; liberar falla",
      "El abandono queda en MongoDB, se informa errores_liberar y no hay excepción")
def _(c: Contexto):
    c.llamado("F-001")
    deps = c.dep_aband()
    deps["liberar_ventanilla"] = c.dep_aband(c.r_caido)["liberar_ventanilla"]
    res = c.barrer(deps=deps)
    return (res.abandonados == ["F-001"] and res.errores_liberar == ["F-001"] and res.ok is False
            and c.estado("F-001") == "abandonado",
            f"errores_liberar={res.errores_liberar}, estado={c.estado('F-001')}")


@caso(S2, "Redis cae al publicar el evento", "El abandono ya está guardado; publicar falla",
      "El abandono se conserva, se informa errores_evento y la ventanilla se liberó")
def _(c: Contexto):
    c.llamado("F-001")
    deps = c.dep_aband()
    deps["publicar_evento"] = c.dep_aband(c.r_caido)["publicar_evento"]
    res = c.barrer(deps=deps)
    return (res.abandonados == ["F-001"] and res.errores_evento == ["F-001"]
            and c.estado("F-001") == "abandonado" and c.r.get(clave_ventanilla("V-01")) is None,
            f"errores_evento={res.errores_evento}")


@caso(S2, "Rehidratación con Redis caído", "No se puede leer la cola",
      "Error controlado «Redis no disponible» y MongoDB intacto")
def _(c: Contexto):
    c.pendiente("F-001")
    try:
        c.reconciliar(deps=c.dep_cola(c.r_caido))
    except RedisNoDisponible as e:
        return c.estado("F-001") == "pendiente", f"RedisNoDisponible: {e.mensaje}"
    return False, "no lanzó el error controlado"


# 3 · MongoDB caído ---------------------------------------------------------------------
@caso(S3, "Barrido con MongoDB caído", "No se pueden leer los candidatos",
      "Error controlado «MongoDB no disponible»; la ventanilla en Redis no se toca")
def _(c: Contexto):
    c.r.set(clave_ventanilla("V-01"), "F-001")
    try:
        c.barrer(col=ColeccionCaida())
    except MongoNoDisponible as e:
        return c.r.get(clave_ventanilla("V-01")) == "F-001", f"MongoNoDisponible: {e.mensaje}"
    return False, "no lanzó el error controlado"


@caso(S3, "Rehidratación con MongoDB caído", "No se pueden leer los pendientes",
      "Error controlado «MongoDB no disponible»; la cola de Redis no cambia")
def _(c: Contexto):
    try:
        c.reconciliar(col=ColeccionCaida())
    except MongoNoDisponible as e:
        return c.r.zcard(CLAVE_COLA) == 0, f"MongoNoDisponible: {e.mensaje}"
    return False, "no lanzó el error controlado"


@caso(S3, "MongoDB cae a mitad del barrido", "La lectura funciona, la actualización falla",
      "Se informa errores_mongo, no se libera la ventanilla ni se publica nada, sin excepción")
def _(c: Contexto):
    doc = construir_turno("F-001", "llamado", "normal", c.ahora - timedelta(seconds=300), "V-01",
                          c.ahora - timedelta(seconds=240))
    col = ColeccionEnMemoria([doc], falla_al_actualizar=True)
    c.r.set(clave_ventanilla("V-01"), "F-001")
    res = c.barrer(col=col)
    return (res.errores_mongo == ["F-001"] and not res.abandonados and col.docs[0]["estado"] == "llamado"
            and c.r.get(clave_ventanilla("V-01")) == "F-001",
            f"errores_mongo={res.errores_mongo}")


# 4 · datos inválidos -------------------------------------------------------------------
def _ts(c, seg_llamado=240):
    return c.ahora - timedelta(seconds=seg_llamado)


@caso(S4, "Turno llamado sin fecha de llamado", "Documento en estado llamado sin timestamps.llamado",
      "Se ignora (no es candidato), no hay excepción y el estado no cambia")
def _(c: Contexto):
    doc = construir_turno("F-001", "llamado", "normal", _ts(c, 300), "V-01", _ts(c))
    doc["timestamps"]["llamado"] = None
    col = ColeccionEnMemoria([doc])
    res = c.barrer(col=col)
    return not res.abandonados and col.docs[0]["estado"] == "llamado", f"abandonados={res.abandonados}"


@caso(S4, "Pendientes con prioridad o fecha inválida", "Un pendiente con prioridad «urgente» y otro sin fecha de creación",
      "Se informan como inválidos, no se encolan y los pendientes válidos sí se recuperan")
def _(c: Contexto):
    bueno = construir_turno("F-001", "pendiente", "normal", _ts(c, 600))
    malo1 = construir_turno("F-002", "pendiente", "normal", _ts(c, 500)); malo1["prioridad"] = "urgente"
    malo2 = construir_turno("F-003", "pendiente", "normal", _ts(c, 400)); malo2["timestamps"]["creado"] = None
    rep = c.reconciliar(col=ColeccionEnMemoria([bueno, malo1, malo2]))
    cola = c.r.zrange(CLAVE_COLA, 0, -1)
    return (rep.invalidos == ["F-002", "F-003"] and cola == ["F-001"] and not rep.errores,
            f"inválidos={rep.invalidos}, cola={cola}")


@caso(S4, "Código en la cola que no existe en MongoDB", "La cola tiene F-900 y MongoDB no",
      "Se advierte y NO se quita (sin la opción explícita)")
def _(c: Contexto):
    c.pendiente("F-001")
    c.r.zadd(CLAVE_COLA, {"F-900": 1})
    rep = c.reconciliar()
    cola = c.r.zrange(CLAVE_COLA, 0, -1)
    return ("F-900" in cola and any("no existen en MongoDB" in a for a in rep.advertencias),
            f"advertencias={rep.advertencias}")


@caso(S4, "Turno ya atendido dentro de la cola", "F-050 está atendido pero sigue en la cola",
      "Por defecto solo se informa; con quitar_sobrantes se retira")
def _(c: Contexto):
    c.col.insert_one(construir_turno("F-050", "atendido", "normal", _ts(c, 900), "V-01", _ts(c, 800)))
    c.r.zadd(CLAVE_COLA, {"F-050": 1})
    sin = c.reconciliar()
    sigue = "F-050" in c.r.zrange(CLAVE_COLA, 0, -1)
    con = c.reconciliar(quitar_sobrantes=True)
    se_fue = "F-050" not in c.r.zrange(CLAVE_COLA, 0, -1)
    return (sigue and se_fue and sin.sobrantes_restantes == ["F-050"] and con.quitados == ["F-050"],
            f"sin opción: sigue={sigue}; con opción: retirado={se_fue}")


@caso(S4, "Turno que cambió de estado justo antes del abandono", "El barrido leyó «llamado» pero ya estaba en atención",
      "No se abandona (ya_cambiados) y el turno sigue en atención")
def _(c: Contexto):
    viejo = construir_turno("F-001", "llamado", "normal", _ts(c, 300), "V-01", _ts(c))
    actual = construir_turno("F-001", "en_atencion", "normal", _ts(c, 300), "V-01", _ts(c))
    col = ColeccionEnMemoria([actual], vista_find=[viejo])
    res = c.barrer(col=col)
    return res.ya_cambiados == ["F-001"] and col.docs[0]["estado"] == "en_atencion", f"ya_cambiados={res.ya_cambiados}"


# 5 · carreras e idempotencia -----------------------------------------------------------
@caso(S5, "El cliente confirmó presencia (Hash vigente)", "Plazo vencido por reloj pero el Hash de Redis aún existe",
      "No se abandona: Redis manda mientras el Hash viva")
def _(c: Contexto):
    c.llamado("F-001")
    c.r.hset(clave_turno("F-001"), mapping={"estado": "llamado"})
    res = c.barrer()
    return (res.omitidos_vigentes == ["F-001"] and c.estado("F-001") == "llamado"
            and c.r.get(clave_ventanilla("V-01")) == "F-001"), f"omitidos_vigentes={res.omitidos_vigentes}"


@caso(S5, "La ventanilla ya atiende a otro turno", "Al abandonar F-001 la ventanilla apunta a F-002",
      "F-001 se abandona pero la ventanilla de F-002 no se libera")
def _(c: Contexto):
    c.llamado("F-001")
    c.r.set(clave_ventanilla("V-01"), "F-002")
    res = c.barrer()
    return (res.abandonados == ["F-001"] and c.r.get(clave_ventanilla("V-01")) == "F-002",
            f"ventanilla={c.r.get(clave_ventanilla('V-01'))}")


@caso(S5, "Barrido repetido", "Dos barridos seguidos sobre el mismo turno",
      "El segundo no cambia nada y el evento se publica una sola vez")
def _(c: Contexto):
    c.llamado("F-001")
    ps = c.suscribir()
    r1, r2 = c.barrer(), c.barrer()
    ev = c.eventos(ps, esperados=2, espera=0.5)
    return r1.abandonados == ["F-001"] and r2.abandonados == [] and len(ev) == 1, f"eventos={len(ev)}"


@caso(S5, "Cuatro barridos simultáneos", "20 turnos vencidos y 4 hilos barriendo a la vez",
      "Cada turno se abandona exactamente una vez y cada evento se publica una vez")
def _(c: Contexto):
    for i in range(1, 21):
        c.llamado(f"F-{i:03d}", ventanilla=f"V-0{i % 3 + 1}", reservar=False)
    ps = c.suscribir()
    resultados, errores = [], []

    def hilo():
        try:
            resultados.append(c.barrer())
        except Exception as e:      # noqa: BLE001
            errores.append(repr(e))

    hilos = [threading.Thread(target=hilo) for _ in range(4)]
    for h in hilos: h.start()
    for h in hilos: h.join()
    abandonados = [x for r in resultados for x in r.abandonados]
    ev = c.eventos(ps, esperados=25, espera=1.0)
    ok = (not errores and len(abandonados) == 20 and len(set(abandonados)) == 20 and len(ev) == 20
          and c.col.count_documents({"codigo": {"$regex": "^F-"}, "estado": "abandonado"}) == 20)
    return ok, f"abandonados={len(abandonados)} (únicos {len(set(abandonados))}), eventos={len(ev)}, errores={errores}"


# --------------------------------------------------------------------------------------
def ejecutar_casos(coleccion, r, r_caido, ahora: datetime | None = None) -> list[Caso]:
    from app.s3_comun import ahora_utc
    ctx = Contexto(coleccion, r, r_caido, ahora or ahora_utc() + timedelta(seconds=ADELANTO_RELOJ_SEG))
    resultados = []
    try:
        for seccion, nombre, provoca, esperado, fn in CASOS:
            c = Caso(seccion, nombre, provoca, esperado)
            ctx.limpiar()
            t0 = time.perf_counter()
            try:
                c.ok, c.observado = fn(ctx)
                c.ok = bool(c.ok)
            except ErrorS3 as e:
                c.ok, c.observado = False, f"error controlado inesperado: {e.mensaje}"
            except Exception as e:      # noqa: BLE001 · una excepción sin controlar es justo lo que se busca
                c.ok, c.observado = False, f"EXCEPCIÓN NO CONTROLADA {type(e).__name__}: {e}"
            c.ms = (time.perf_counter() - t0) * 1000
            resultados.append(c)
    finally:
        ctx.limpiar()
    return resultados


def informe(casos: list[Caso]) -> str:
    fuera = [c for c in casos if not c.ok]
    md = encabezado("Casos de fallo · abandono y recuperación (TT-019, parte de Abigail)")
    md += ("\nCada caso provoca una condición anormal y comprueba que el módulo responde de forma **controlada**. "
           f"Datos de la serie `{SERIE}-*`, con cola, eventos y ventanillas propios (`grupo2:qline:prueba:*`); "
           "no se detiene ningún servicio ni se toca la operación real. «Caído» significa un cliente apuntando a un "
           "puerto sin servidor (Redis) o una colección que lanza ConnectionError (MongoDB).\n")
    md += (f"\n## Resultado global\n\n**{'OK' if not fuera else 'CON FALLAS'}** · {len(casos)} casos ejecutados · "
           f"{len(fuera)} fuera de lo esperado.\n")
    seccion = None
    for c in casos:
        if c.seccion != seccion:
            seccion = c.seccion
            md += f"\n## {seccion}\n\n| Caso | Condición provocada | Esperado | Observado | Tiempo (ms) | Resultado |\n|---|---|---|---|---|---|\n"
        md += f"| {c.nombre} | {c.provoca} | {c.esperado} | {c.observado} | {c.ms:.0f} | {'OK' if c.ok else '**FALLA**'} |\n"
    return md
