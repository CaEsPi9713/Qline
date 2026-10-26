# tests package
import os

# Las pruebas no deben arrancar el barrido de abandono en segundo plano (HU-008): lo prueban de forma explícita.
os.environ.setdefault("BARRIDO_ABANDONO", "0")
