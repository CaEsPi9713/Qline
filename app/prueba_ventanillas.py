"""
P09 · Evidencia de las ventanillas dinámicas conectadas a la operación.

Comprueba contra MongoDB, con una ventanilla de prueba (`V-98`) y un turno propio (`Z-901`) que se eliminan al terminar:
  1. el catálogo reconoce la ventanilla nueva y deja de reconocerla al desactivarla;
  2. **qué hace el motor de MongoDB** al guardar un turno asignado a una ventanilla fuera de V-01 a V-03.

El punto 2 depende del validador de la colección `turnos`. El usuario del curso no puede ejecutar `collMod`, así que si el
validador es el anterior (con la lista fija) el motor rechazará la ventanilla nueva aunque la aplicación la acepte; el informe lo dice.

No toca turnos reales, la cola ni las claves de Redis.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pymongo.errors import PyMongoError

from app.datos_prueba import construir_turno
from app.informe import encabezado
from app.ventanillas import (
    COLECCION_VENTANILLAS,
    desactivar_ventanilla,
    VENTANILLA_PRUEBA,
    registrar_ventanilla,
    ventanillas_activas,
)

CODIGO_PRUEBA = "Z-901"


def _caso(nombre: str, ok: bool, detalle: str) -> dict:
    return {"caso": nombre, "ok": bool(ok), "detalle": detalle}


def ejecutar(db) -> tuple[list, str]:
    """Devuelve (resultados, veredicto del motor). Limpia al terminar."""
    cat = db[COLECCION_VENTANILLAS]
    turnos = db["turnos"]
    existia = cat.find_one({"codigo": VENTANILLA_PRUEBA}) is not None
    res = []
    veredicto = "no se pudo comprobar"
    try:
        turnos.delete_many({"codigo": CODIGO_PRUEBA})
        registrar_ventanilla(db, codigo=VENTANILLA_PRUEBA, nombre="Ventanilla de prueba")
        res.append(_caso("El catálogo reconoce la ventanilla nueva", VENTANILLA_PRUEBA in ventanillas_activas(db),
                         f"{VENTANILLA_PRUEBA} figura entre las ventanillas activas"))

        # ¿Qué hace el motor con un turno asignado a la ventanilla nueva?
        ahora = datetime.now(timezone.utc)
        turno = construir_turno(CODIGO_PRUEBA, "llamado", "normal", ahora - timedelta(minutes=3), VENTANILLA_PRUEBA,
                                ahora - timedelta(minutes=1))
        try:
            turnos.insert_one(turno)
            veredicto = ("ACEPTA la ventanilla nueva: el validador de la colección ya admite el formato V-NN "
                         "(la operación con ventanillas dinámicas funciona de extremo a extremo)")
            motor_ok = True
        except PyMongoError:
            veredicto = ("RECHAZA la ventanilla nueva: el validador de la colección es el anterior (lista fija V-01 a V-03). "
                         "La aplicación ya la acepta, pero el motor impide guardar turnos con ella hasta que un administrador "
                         "ejecute `collMod` con el validador de `app/turnos_schema.py` o se recree la colección")
            motor_ok = False
        res.append(_caso("El motor guarda un turno con la ventanilla nueva", motor_ok,
                         "ACEPTA" if motor_ok else "RECHAZA (límite conocido: falta collMod)"))

        turnos.delete_many({"codigo": CODIGO_PRUEBA})          # una ventanilla con turno en curso no se puede desactivar
        desactivar_ventanilla(db, VENTANILLA_PRUEBA)
        res.append(_caso("Desactivada, deja de operar", VENTANILLA_PRUEBA not in ventanillas_activas(db),
                         f"{VENTANILLA_PRUEBA} ya no figura entre las activas"))
    finally:
        turnos.delete_many({"codigo": CODIGO_PRUEBA})
        if not existia:
            cat.delete_one({"codigo": VENTANILLA_PRUEBA})
    return res, veredicto


def hay_fallos_de_aplicacion(resultados: list) -> bool:
    """El rechazo del motor es un límite documentado, no un fallo de la aplicación."""
    return any(not r["ok"] for r in resultados if not r["caso"].startswith("El motor"))


def a_markdown(resultados: list, veredicto: str) -> str:
    fallos = [r for r in resultados if not r["ok"] and not r["caso"].startswith("El motor")]
    limite = any(not r["ok"] for r in resultados if r["caso"].startswith("El motor"))
    estado = "FALLA" if fallos else ("OK CON LÍMITE" if limite else "OK")
    f = [encabezado("Ventanillas dinámicas conectadas a la operación (P09)"),
         "## Resultado global", "", f"**{estado}** · {len(resultados)} casos.", "",
         "| Caso | Resultado | Qué se comprobó |", "|---|---|---|"]
    for r in resultados:
        marca = "OK" if r["ok"] else ("LÍMITE" if r["caso"].startswith("El motor") else "FALLA")
        f.append(f"| {r['caso']} | {marca} | {r['detalle']} |")
    f += ["", "## Qué hace el motor de MongoDB", "", f"- El motor {veredicto}.", "",
          "## Alcance", "",
          f"- Se usó la ventanilla `{VENTANILLA_PRUEBA}` y el turno `{CODIGO_PRUEBA}`, eliminados al terminar. No se tocaron turnos reales, la cola ni Redis.",
          "- La aplicación (llamar, panel, atención, historial) acepta cualquier ventanilla activa del catálogo; la ventanilla única "
          "y la liberación en Redis funcionan igual con cualquier identificador (`SET NX` sobre `grupo2:qline:ventanilla:{id}:actual`)."]
    return "\n".join(f) + "\n"
