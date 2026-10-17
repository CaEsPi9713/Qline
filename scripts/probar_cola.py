"""
Verificación de la cola Redis (TT-007) contra el Redis real.

Usa claves temporales grupo2:qline:test:* y las elimina al terminar.
No toca el contador ni la cola reales. Ejecutar desde la raíz del proyecto:

    python -m scripts.probar_cola
"""
from concurrent.futures import ThreadPoolExecutor

from app import cola
from app.redis_client import get_redis, verificar_conexion

CONTADOR = "grupo2:qline:test:contador"
COLA = "grupo2:qline:test:cola"
ACTUAL = "grupo2:qline:ventanilla:{}:actual"


def check(nombre, condicion):
    print(("OK   " if condicion else "FALLA"), nombre)
    if not condicion:
        raise SystemExit(1)


def main():
    estado = verificar_conexion()
    check(f"conexión Redis {estado}", estado["ok"])
    r = get_redis()
    r.delete(CONTADOR, COLA)
    try:
        c1 = cola.siguiente_codigo(CONTADOR)
        c2 = cola.siguiente_codigo(CONTADOR)
        check("códigos consecutivos", (c1, c2) == ("A-001", "A-002"))

        # normal llega antes que preferencial
        cola.encolar("A-001", "normal", 1_000, COLA)
        cola.encolar("A-002", "preferencial", 2_000, COLA)
        cola.encolar("A-003", "normal", 3_000, COLA)
        cola.encolar("A-004", "preferencial", 4_000, COLA)
        check("reencolar mismo código no duplica", not cola.encolar("A-001", "normal", 9, COLA))
        orden = [t["codigo"] for t in cola.ver_cola(clave_cola=COLA)]
        check(f"orden prioridad+FIFO {orden}", orden == ["A-002", "A-004", "A-001", "A-003"])
        check("ver_cola no remueve", cola.tamano_cola(COLA) == 4)
        check("posición de A-001 = 2", cola.posicion_en_cola("A-001", COLA) == 2)

        check("llamar V-01 -> A-002", cola.llamar_siguiente("V-01", COLA) == "A-002")
        check("V-01 actual registrado", r.get(ACTUAL.format("V-01")) == "A-002")
        check("A-002 ya no está en cola", cola.posicion_en_cola("A-002", COLA) is None)

        for malo in ("V-99", ""):
            try:
                cola.llamar_siguiente(malo, COLA)
                check(f"ventanilla inválida {malo!r} rechazada", False)
            except cola.ColaError:
                check(f"ventanilla inválida {malo!r} rechazada", True)
        try:
            cola.encolar("A-009", "urgente", clave_cola=COLA)
            check("prioridad inválida rechazada", False)
        except cola.ColaError:
            check("prioridad inválida rechazada", True)

        # concurrencia ligera: 3 restantes, 10 consumidores -> sin duplicados
        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(lambda v: cola.llamar_siguiente(v, COLA),
                              ["V-01", "V-02", "V-03"] * 3 + ["V-01"]))
        asignados = [x for x in res if x]
        check(f"concurrencia: {len(asignados)} asignados, sin duplicados",
              len(asignados) == 3 and len(set(asignados)) == 3)
        check("cola vacía -> None", cola.llamar_siguiente("V-01", COLA) is None)
    finally:
        r.delete(CONTADOR, COLA)
    print("Todo OK")


if __name__ == "__main__":
    main()
