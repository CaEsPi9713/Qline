"""HU-008 · Barrido de abandono de turnos llamados (TTL 180 s).

    python -m scripts.barrer_abandonos                 # una pasada (servidor: MongoDB y Redis reales)
    python -m scripts.barrer_abandonos --continuo --intervalo 10
    python -m scripts.barrer_abandonos --simulado      # demostración con simulados (NO es evidencia)

En producción el barrido corre dentro de la app (app/barrido.py); este script
sirve para ejecutarlo a mano, desde cron o para la evidencia.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta

from app.abandono import barrer_abandonos
from app.datos_prueba import construir_turno
from app.s3_comun import ErrorS3
from app.simulacion import EntornoSimulado


def _escenario_simulado() -> EntornoSimulado:
    env = EntornoSimulado()
    ahora = env.reloj.ahora
    casos = [  # (codigo, segundos desde el llamado, estado, ¿Hash vigente?)
        ("R-001", 200, "llamado", False),      # vencido, sin Hash  -> abandonado
        ("R-002", 100, "llamado", True),       # dentro de los 180 s -> no es candidato
        ("R-003", 300, "en_atencion", False),  # ya iniciado         -> no es candidato
        ("R-004", 181, "llamado", True),       # vencido por reloj, Hash aún vigente -> se omite
        ("R-005", 400, "llamado", False),      # vencido, sin Hash  -> abandonado
    ]
    for codigo, seg, estado, hash_vigente in casos:
        llamado = ahora - timedelta(seconds=seg)
        env.coleccion.insert_one(construir_turno(codigo, estado, "normal", llamado - timedelta(seconds=60),
                                                 "V-01", llamado))
        if estado == "llamado":
            env.redis.reservar_ventanilla("V-01", codigo)
            if hash_vigente:
                env.redis.crear_hash(codigo, ahora + timedelta(seconds=30))
    return env


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--simulado", action="store_true", help="usa MongoDB y Redis simulados (no es evidencia)")
    p.add_argument("--continuo", action="store_true", help="repite el barrido hasta Ctrl+C")
    p.add_argument("--intervalo", type=float, default=10.0, help="segundos entre pasadas con --continuo")
    args = p.parse_args(argv)

    try:
        if args.simulado:
            env = _escenario_simulado()
            coleccion, deps, reloj = env.coleccion, env.dependencias_abandono(), env.reloj
            print("SIMULADO — esto no es evidencia del servidor", file=sys.stderr)
        else:
            from app import integracion_s3 as real
            coleccion, reloj = real.conectar_mongo(), None
            deps = real.dependencias_abandono(real.conectar_redis())

        while True:
            resultado = barrer_abandonos(coleccion, ahora=reloj() if reloj else None, **deps)
            print(json.dumps(resultado.resumen(), ensure_ascii=False, indent=2))
            if not args.continuo:
                return 0 if resultado.ok else 1
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        return 0
    except ErrorS3 as err:
        print(f"Error controlado: {err.mensaje}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
