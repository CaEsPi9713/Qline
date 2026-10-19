#!/usr/bin/env python3
"""TT-005 · Datos sintéticos reproducibles de QLine.

Por defecto SOLO genera, valida y muestra un resumen: no escribe nada.

Ejemplos:
    python scripts/generar_datos_sinteticos.py                       # vista previa
    python scripts/generar_datos_sinteticos.py --salida datos.jsonl  # archivo
    python scripts/generar_datos_sinteticos.py --cargar              # upsert en MongoDB
    python scripts/generar_datos_sinteticos.py --reiniciar --confirmar
    python scripts/generar_datos_sinteticos.py --limpiar --confirmar

Variables de entorno (ver .env.example): MONGO_USER, MONGO_PASS, MONGO_HOST,
MONGO_PORT, MONGO_DB. No contiene secretos.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sinteticos import cargador  # noqa: E402
from scripts.sinteticos.generador import (  # noqa: E402
    FECHA_FIN_POR_DEFECTO,
    PREFIJO_POR_DEFECTO,
    SEMILLA_POR_DEFECTO,
    Parametros,
    generar_turnos,
)
from scripts.sinteticos.serializacion import a_jsonl  # noqa: E402
from scripts.sinteticos.validador import resumen, validar_conjunto  # noqa: E402


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = p.add_argument_group("generación")
    g.add_argument("--semilla", type=int, default=SEMILLA_POR_DEFECTO, help="semilla aleatoria (default: %(default)s)")
    g.add_argument("--dias", type=int, default=3, help="días simulados (default: %(default)s)")
    g.add_argument("--fecha-fin", type=date.fromisoformat, default=FECHA_FIN_POR_DEFECTO,
                   help="último día simulado, AAAA-MM-DD (default: %(default)s; fija, no es la fecha de hoy)")
    g.add_argument("--llegadas-por-hora", type=float, default=30.0, help="llegadas por hora (default: %(default)s)")
    g.add_argument("--prefijo", default=PREFIJO_POR_DEFECTO,
                   help="letra del código sintético (default: %(default)s da S-001). Distinto de 'A' para no "
                        "colisionar con los turnos de la operación real")
    g.add_argument("--con-activos", action="store_true",
                   help="deja turnos 'llamado'/'en_atencion' al corte (por defecto se cierran para no "
                        "confundirse con la operación real)")
    a = p.add_argument_group("acciones (sin ninguna, solo vista previa)")
    a.add_argument("--salida", type=Path, help="escribe los turnos en JSON Lines (Extended JSON)")
    a.add_argument("--cargar", action="store_true", help="upsert en MongoDB (no duplica)")
    a.add_argument("--reiniciar", action="store_true", help="limpiar turnos sintéticos y volver a cargar")
    a.add_argument("--limpiar", action="store_true", help="elimina SOLO los turnos con el prefijo sintético")
    a.add_argument("--confirmar", action="store_true", help="requerido para --limpiar y --reiniciar")
    a.add_argument("--json", action="store_true", help="imprime el resumen en JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)

    if (args.limpiar or args.reiniciar) and not args.confirmar:
        print("Operación destructiva sobre turnos sintéticos: agregue --confirmar.", file=sys.stderr)
        return 2
    if args.prefijo == "A":
        print("Aviso: el prefijo 'A' coincide con la serie de la operación real/demo (A-001...).", file=sys.stderr)

    try:
        parametros = Parametros(semilla=args.semilla, dias=args.dias, fecha_fin=args.fecha_fin,
                                llegadas_por_hora=args.llegadas_por_hora, prefijo_codigo=args.prefijo,
                                dejar_turnos_activos=args.con_activos)
        if args.limpiar and (args.cargar or args.reiniciar or args.salida):
            print("--limpiar se usa solo; para limpiar y volver a cargar use --reiniciar.", file=sys.stderr)
            return 2
        if args.limpiar:
            coleccion = cargador.conectar()
            print(f"Eliminados {cargador.limpiar(coleccion, args.prefijo)} turnos sintéticos ({args.prefijo}-*)")
            return 0

        docs = generar_turnos(parametros)
    except ValueError as err:
        print(f"Parámetros inválidos: {err}", file=sys.stderr)
        return 2
    except cargador.ErrorCarga as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1

    errores = validar_conjunto(docs)
    if errores:
        print(f"Los datos generados NO cumplen el contrato ({len(errores)} errores):", file=sys.stderr)
        for e in errores[:10]:
            print(f"  - {e}", file=sys.stderr)
        return 1

    # Con --json, stdout queda reservado para el JSON; los demás mensajes van a stderr.
    def info(mensaje: str) -> None:
        print(mensaje, file=sys.stderr if args.json else sys.stdout)

    res = resumen(docs)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"Turnos generados: {res['total']} ({res['primer_codigo']} ... {res['ultimo_codigo']})")
        print(f"  por estado:     {res['por_estado']}")
        print(f"  por prioridad:  {res['por_prioridad']}")
        print(f"  por ventanilla: {res['por_ventanilla']}")
        print(f"  mediana espera: {res['mediana_espera_seg']} s · mediana atención: {res['mediana_atencion_seg']} s")
        print("Validación contra el contrato de turnos: OK")

    if args.salida:
        args.salida.write_text(a_jsonl(docs), encoding="utf-8")
        info(f"Archivo escrito: {args.salida}")

    if args.cargar or args.reiniciar:
        try:
            coleccion = cargador.conectar()
            if args.reiniciar:
                info(f"Eliminados {cargador.limpiar(coleccion, args.prefijo)} turnos sintéticos previos")
            info(f"Cargados (upsert) {cargador.cargar(coleccion, docs)} turnos en MongoDB")
        except cargador.ErrorCarga as err:
            print(f"Error: {err}", file=sys.stderr)
            return 1
    elif not args.salida:
        info("(vista previa: no se escribió nada; use --salida o --cargar)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
