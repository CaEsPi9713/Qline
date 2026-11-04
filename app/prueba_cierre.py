"""
S4-M03 · Evidencia del cierre con motivo y nota, sin depender de `collMod`.

El usuario de MongoDB del curso no puede ejecutar `collMod`, así que el validador del servidor no se
actualiza para el campo `cierre`. Como la raíz del documento admite campos extra, el servidor lo acepta
igual y la validación la hace la aplicación. Esta prueba lo demuestra con turnos propios (serie `Z-9NN`,
que se eliminan al terminar) y dice con honestidad qué valida el servidor y qué valida la aplicación.

No toca turnos reales ni Redis.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pymongo.errors import PyMongoError

from app.atencion import finalizar_atencion
from app.constantes import NOTA_CIERRE_MAX
from app.datos_prueba import construir_turno
from app.excepciones import DatosInvalidos, TransicionNoPermitida
from app.historial import obtener_historial_turnos
from app.informe import encabezado
from app.turnos_schema import validar_documento_turno

CODIGOS = tuple(f"Z-9{n:02d}" for n in range(1, 8))
SCRIPT = "<script>alert(1)</script>"


def _turno_en_atencion(db, codigo: str) -> datetime:
    inicio = datetime.now(timezone.utc) - timedelta(minutes=2)
    doc = construir_turno(codigo, "en_atencion", "normal", inicio - timedelta(minutes=8), "V-01",
                          inicio - timedelta(minutes=3), inicio=inicio)
    db["turnos"].insert_one(doc)
    return inicio


def _doc(db, codigo: str) -> dict:
    return db["turnos"].find_one({"codigo": codigo}) or {}


def _caso(nombre: str, ok: bool, detalle: str) -> dict:
    return {"caso": nombre, "ok": bool(ok), "detalle": detalle}


def ejecutar(db) -> tuple[list, str]:
    """Corre los casos contra `db` y devuelve (resultados, qué validó el servidor). Limpia al terminar."""
    col = db["turnos"]
    col.delete_many({"codigo": {"$in": list(CODIGOS)}})
    res = []
    try:
        # 1. Sin motivo ni nota: igual que antes de S4-M03.
        _turno_en_atencion(db, CODIGOS[0])
        r = finalizar_atencion(col, CODIGOS[0], "V-01")
        d = _doc(db, CODIGOS[0])
        res.append(_caso("Finalizar sin motivo ni nota", d.get("estado") == "atendido" and "cierre" not in d
                         and r["cierre"] is None, "estado atendido y sin campo `cierre`"))

        # 2. Con motivo y nota: el servidor acepta el documento y valida contra el contrato.
        _turno_en_atencion(db, CODIGOS[1])
        finalizar_atencion(col, CODIGOS[1], "V-01", motivo="derivado", nota="Pasa a cajas")
        d = _doc(db, CODIGOS[1])
        try:
            validar_documento_turno(d)
            valido = True
        except ValueError:
            valido = False
        res.append(_caso("Finalizar con motivo y nota", d.get("cierre") == {"motivo": "derivado", "nota": "Pasa a cajas"}
                         and valido, "MongoDB guarda `cierre` y el documento cumple el contrato"))

        # 3. Motivo inválido: la aplicación lo rechaza y no escribe nada.
        _turno_en_atencion(db, CODIGOS[2])
        try:
            finalizar_atencion(col, CODIGOS[2], "V-01", motivo="inventado")
            rechazado = False
        except DatosInvalidos:
            rechazado = True
        d = _doc(db, CODIGOS[2])
        res.append(_caso("Motivo inválido", rechazado and d.get("estado") == "en_atencion" and "cierre" not in d,
                         "rechazado por la aplicación; el turno sigue en atención"))

        # 4. Nota demasiado larga.
        try:
            finalizar_atencion(col, CODIGOS[2], "V-01", nota="x" * (NOTA_CIERRE_MAX + 1))
            rechazado = False
        except DatosInvalidos:
            rechazado = True
        res.append(_caso(f"Nota de {NOTA_CIERRE_MAX + 1} caracteres", rechazado and _doc(db, CODIGOS[2]).get("estado") == "en_atencion",
                         "rechazada por la aplicación"))

        # 5. Reintento: no sobrescribe el cierre.
        try:
            finalizar_atencion(col, CODIGOS[1], "V-01", motivo="otro", nota="segunda")
            reintento = False
        except TransicionNoPermitida:
            reintento = True
        res.append(_caso("Reintento de finalización", reintento and _doc(db, CODIGOS[1])["cierre"]["nota"] == "Pasa a cajas",
                         "409 y el cierre original se conserva"))

        # 6. Nota con HTML: se guarda como texto, sin modificarla.
        _turno_en_atencion(db, CODIGOS[3])
        finalizar_atencion(col, CODIGOS[3], "V-01", nota=SCRIPT)
        res.append(_caso("Nota con HTML", _doc(db, CODIGOS[3])["cierre"]["nota"] == SCRIPT,
                         "se guarda tal cual; las pantallas la escapan al mostrarla"))

        # 7. Turnos con y sin cierre conviven en el historial.
        try:
            h = obtener_historial_turnos(db, codigo=CODIGOS[0])["turnos"] + obtener_historial_turnos(db, codigo=CODIGOS[1])["turnos"]
            conviven = len(h) == 2
        except Exception:  # noqa: BLE001
            conviven = False
        res.append(_caso("Historial con y sin cierre", conviven, "el historial lee ambos turnos"))

        # 8. ¿Qué valida el servidor? Se intenta escribir un cierre inválido directamente, sin la aplicación.
        servidor = "no valida `cierre`"
        try:
            col.update_one({"codigo": CODIGOS[1]}, {"$set": {"cierre": {"motivo": "zzz", "nota": 5}}})
            servidor = "NO valida `cierre`: el validador del servidor es el anterior (sin `collMod`); lo valida la aplicación"
        except PyMongoError:
            servidor = "valida `cierre`: el validador del servidor ya incluye el campo"
    finally:
        col.delete_many({"codigo": {"$in": list(CODIGOS)}})
    return res, servidor


def a_markdown(resultados: list, servidor: str) -> str:
    fallos = sum(1 for r in resultados if not r["ok"])
    f = [encabezado("Cierre de turno con motivo y nota (S4-M03)"),
         "## Resultado global", "",
         f"**{'OK' if fallos == 0 else 'FALLA'}** · {len(resultados)} casos · {fallos} fuera de lo esperado.", "",
         "| Caso | Resultado | Qué se comprobó |", "|---|---|---|"]
    for r in resultados:
        f.append(f"| {r['caso']} | {'OK' if r['ok'] else 'FALLA'} | {r['detalle']} |")
    f += ["", "## Qué valida el servidor", "",
          f"- El validador de MongoDB {servidor}.",
          "- El usuario del curso no puede ejecutar `collMod` (`init_mongo` lo informa como «Unauthorized»), por lo que el "
          "esquema con `cierre` solo se aplica al crear la colección. La raíz del documento admite campos extra, así que "
          "MongoDB acepta `cierre` igualmente; el motivo (lista cerrada) y el largo de la nota los valida la aplicación "
          "(`app/atencion.py`) **antes** de escribir y `validar_documento_turno` en memoria.",
          "- Para que el servidor también lo valide haría falta que un administrador ejecute `collMod` con el validador de "
          "`app/turnos_schema.py`; no es necesario para el funcionamiento.", "",
          "## Alcance", "",
          "- Se usaron turnos propios de la serie `Z-9NN`, eliminados al terminar. No se tocaron turnos reales ni Redis."]
    return "\n".join(f) + "\n"
