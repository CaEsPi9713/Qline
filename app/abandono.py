"""HU-008 · Abandono de turno llamado (TTL de 180 s) — lado MongoDB del barrido.

Contrato acordado con Alessandro (docs/arquitectura/redis_claves.md):
  Un turno llamado es candidato a abandono cuando
      timestamps.llamado + 180 s  ya pasó   Y   el Hash grupo2:qline:turno:{codigo} ya no existe.
Redis no avisa cuando una clave expira (no se puede usar CONFIG SET), por eso
un *barrido* revisa periódicamente los turnos llamados.

Qué hace, por cada candidato (en este orden):
  1. Comprueba que el Hash ya no exista (si existe, aún no venció: se omite).
  2. MongoDB (atómico):  llamado -> abandonado, solo si SIGUE en "llamado".
     Si el cliente se presentó entre medias (HU-006 lo pasó a en_atencion), el
     filtro no coincide y NO se abandona: nunca se pisa una atención iniciada.
  3. Libera la ventanilla en Redis (si todavía apunta a ese turno).
  4. Publica el evento "turno_abandonado" (un fallo aquí no revierte MongoDB).

Decisiones (ver docs/s3_abigail/04_DECISIONES_ABIGAIL.md):
  * timestamps.abandonado = llamado + 180 s (instante en que venció el TTL),
    no la hora del barrido, para que la métrica no dependa de la latencia del barrido.
  * La ventanilla se conserva en el documento (historial).
  * Un turno abandonado no vuelve a ser llamado ni atendido (HU-006 solo acepta "llamado").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from .s3_comun import (
    ESTADO_ABANDONADO,
    ESTADO_LLAMADO,
    TTL_ABANDONO_SEG,
    MongoNoDisponible,
    a_utc,
    ahora_utc,
)

EVENTO_ABANDONO = "turno_abandonado"


@dataclass
class ResultadoBarrido:
    ahora: datetime
    revisados: int = 0
    abandonados: list[str] = field(default_factory=list)
    omitidos_vigentes: list[str] = field(default_factory=list)   # el Hash aún existe
    omitidos_redis: list[str] = field(default_factory=list)      # no se pudo consultar Redis
    ya_cambiados: list[str] = field(default_factory=list)        # otro proceso los cambió (p. ej. iniciaron atención)
    inconsistentes: list[str] = field(default_factory=list)      # llamado sin timestamps.llamado
    errores_liberar: list[str] = field(default_factory=list)
    errores_evento: list[str] = field(default_factory=list)
    errores_mongo: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True si no quedó nada a medias (omitir un turno aún vigente no es error)."""
        return not (self.omitidos_redis or self.errores_liberar or self.errores_evento
                    or self.errores_mongo or self.inconsistentes)

    def resumen(self) -> dict:
        return {
            "ahora": self.ahora.isoformat(),
            "revisados": self.revisados,
            "abandonados": self.abandonados,
            "omitidos_vigentes": self.omitidos_vigentes,
            "omitidos_redis": self.omitidos_redis,
            "ya_cambiados": self.ya_cambiados,
            "inconsistentes": self.inconsistentes,
            "errores_liberar": self.errores_liberar,
            "errores_evento": self.errores_evento,
            "errores_mongo": self.errores_mongo,
            "ok": self.ok,
        }


def barrer_abandonos(
    coleccion,
    *,
    hash_existe: Callable[[str], bool],
    liberar_ventanilla: Callable[[str, str], None],
    publicar_evento: Callable[[str, dict], None] | None = None,
    ahora: datetime | None = None,
    ttl_seg: int = TTL_ABANDONO_SEG,
    reintentos_liberar: int = 2,
) -> ResultadoBarrido:
    """Una pasada del barrido de abandono. Es idempotente y segura de repetir.

    Args:
        coleccion: colección ``turnos`` (PyMongo o equivalente).
        hash_existe: ``codigo -> bool``; True si el Hash ``grupo2:qline:turno:{codigo}`` existe.
        liberar_ventanilla: ``(ventanilla, codigo) -> None``; debe liberar la clave
            ``grupo2:qline:ventanilla:{id}:actual`` SOLO si aún apunta a ese turno.
        publicar_evento: ``(tipo, datos) -> None``; opcional.
        ahora: solo para pruebas.
        ttl_seg: TTL oficial (180).

    Raises:
        MongoNoDisponible: si no se pueden leer los candidatos (no se toca nada).
    """
    ahora = a_utc(ahora or ahora_utc())
    limite = ahora - timedelta(seconds=ttl_seg)
    resultado = ResultadoBarrido(ahora=ahora)

    try:
        candidatos = list(coleccion.find(
            {"estado": ESTADO_LLAMADO, "timestamps.llamado": {"$lte": limite}},
            {"codigo": 1, "ventanilla": 1, "timestamps.llamado": 1},
        ))
    except Exception as exc:
        raise MongoNoDisponible() from exc

    resultado.revisados = len(candidatos)
    for doc in candidatos:
        codigo = doc["codigo"]
        ventanilla = doc.get("ventanilla")
        llamado = (doc.get("timestamps") or {}).get("llamado")
        if llamado is None:
            resultado.inconsistentes.append(codigo)
            continue

        # 1. ¿El Hash de Redis ya expiró? Si no se puede saber, no se abandona.
        try:
            if hash_existe(codigo):
                resultado.omitidos_vigentes.append(codigo)
                continue
        except Exception:
            resultado.omitidos_redis.append(codigo)
            continue

        # 2. Cambio atómico en MongoDB: solo si el turno SIGUE llamado.
        vence = a_utc(llamado) + timedelta(seconds=ttl_seg)
        try:
            r = coleccion.update_one(
                {"codigo": codigo, "estado": ESTADO_LLAMADO},
                {"$set": {"estado": ESTADO_ABANDONADO, "timestamps.abandonado": vence}},
            )
        except Exception:
            resultado.errores_mongo.append(codigo)
            break                      # sin MongoDB no tiene sentido seguir; lo hecho queda registrado
        if r.modified_count != 1:
            resultado.ya_cambiados.append(codigo)
            continue
        resultado.abandonados.append(codigo)

        # 3. Liberar la ventanilla en Redis (con reintento corto).
        if ventanilla:
            for intento in range(max(1, reintentos_liberar)):
                try:
                    liberar_ventanilla(ventanilla, codigo)
                    break
                except Exception:
                    if intento == max(1, reintentos_liberar) - 1:
                        resultado.errores_liberar.append(codigo)

        # 4. Evento en vivo; un fallo no revierte MongoDB.
        if publicar_evento is not None:
            try:
                publicar_evento(EVENTO_ABANDONO, {"codigo": codigo, "ventanilla": ventanilla})
            except Exception:
                resultado.errores_evento.append(codigo)

    return resultado
