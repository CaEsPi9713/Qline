"""
Precarga turnos SINTÉTICOS en la cola Redis real para demos y pruebas de la
vista de cola (HU-004), sin depender de la emisión web.

    python -m scripts.precargar_cola          # 5 turnos mixtos
    python -m scripts.precargar_cola --n 8

Solo agrega a la cola; no escribe en MongoDB. Usa el contador real, así que
los códigos continúan la secuencia.
"""
import argparse
import random

from app import cola
from app.constantes import PRIORIDAD_NORMAL, PRIORIDAD_PREFERENCIAL


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=5)
    n = ap.parse_args().n
    random.seed(7)
    for _ in range(n):
        prioridad = random.choice([PRIORIDAD_NORMAL, PRIORIDAD_NORMAL, PRIORIDAD_PREFERENCIAL])
        codigo = cola.siguiente_codigo()
        cola.encolar(codigo, prioridad)
        print(f"{codigo} {prioridad}")


if __name__ == "__main__":
    main()
