"""
Verificación de la cola Redis (TT-007) contra el Redis real.

Usa claves temporales grupo2:qline:test:* (contador, cola y ventanillas) y las
elimina al terminar. No toca el contador, la cola ni las ventanillas reales.
Ejecutar desde la raíz del proyecto:

    python -m scripts.probar_cola
"""
import time
from concurrent.futures import ThreadPoolExecutor

from app import cola
from app.constantes import clave_turno
from app.redis_client import get_redis, verificar_conexion

CONTADOR = "grupo2:qline:test:contador"
COLA = "grupo2:qline:test:cola"
ACTUAL = "grupo2:qline:test:ventanilla:{}:actual"
VENTANILLAS = ("V-01", "V-02", "V-03")
CODIGO_HASH = "TEST-HASH-001"   # código de prueba: su clave no choca con turnos reales


def check(nombre, condicion):
    print(("OK   " if condicion else "FALLA"), nombre)
    if not condicion:
        raise SystemExit(1)


def main():
    estado = verificar_conexion()
    check(f"conexión Redis {estado}", estado["ok"])
    r = get_redis()
    r.delete(CONTADOR, COLA, clave_turno(CODIGO_HASH), *[ACTUAL.format(v) for v in VENTANILLAS])
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

        def llamar(v):
            return cola.llamar_siguiente(v, COLA, ACTUAL.format(v))

        check("llamar V-01 -> A-002", llamar("V-01") == "A-002")
        check("V-01 actual registrado", r.get(ACTUAL.format("V-01")) == "A-002")
        check("A-002 ya no está en cola", cola.posicion_en_cola("A-002", COLA) is None)

        try:
            llamar("V-01")
            check("V-01 ocupada rechaza un segundo turno", False)
        except cola.VentanillaOcupada as e:
            check("V-01 ocupada rechaza un segundo turno", e.codigo == "A-002")
        check("el rechazo no extrajo ningún turno", cola.tamano_cola(COLA) == 3)

        for malo in ("V-99", ""):
            try:
                llamar(malo)
                check(f"ventanilla inválida {malo!r} rechazada", False)
            except cola.ColaError:
                check(f"ventanilla inválida {malo!r} rechazada", True)
        try:
            cola.encolar("A-009", "urgente", clave_cola=COLA)
            check("prioridad inválida rechazada", False)
        except cola.ColaError:
            check("prioridad inválida rechazada", True)

        # concurrencia ligera: 3 turnos restantes, 10 consumidores sobre 3 ventanillas libres
        r.delete(ACTUAL.format("V-01"))

        def consumir(v):
            try:
                return llamar(v)
            except cola.VentanillaOcupada:
                return "ocupada"

        with ThreadPoolExecutor(10) as ex:
            res = list(ex.map(consumir, list(VENTANILLAS) * 3 + ["V-01"]))
        asignados = [x for x in res if x != "ocupada"]
        check(f"concurrencia: {len(asignados)} asignados, {res.count('ocupada')} rechazados, sin duplicados",
              len(asignados) == 3 and len(set(asignados)) == 3 and res.count("ocupada") == 7)
        r.delete(ACTUAL.format("V-01"))
        check("cola vacía -> None", llamar("V-01") is None)
        check("cola vacía no deja la ventanilla reservada", r.get(ACTUAL.format("V-01")) is None)

        # TT-011/TT-012: Hash temporal con TTL (tercera estructura de Redis)
        clave = clave_turno(CODIGO_HASH)
        cola.registrar_llamado(CODIGO_HASH, "V-01", "preferencial", ttl=2)
        check("el estado temporal es un Hash", r.type(clave) == "hash")
        datos = r.hgetall(clave)
        check(f"Hash con sus campos {sorted(datos)}",
              sorted(datos) == ["codigo", "llamado_ms", "prioridad", "vence_ms", "ventanilla"])
        check("el Hash tiene TTL", 0 < r.ttl(clave) <= 2)
        check("segundos_restantes disponible", cola.segundos_restantes(CODIGO_HASH) in (1, 2))
        time.sleep(3)
        check("el Hash expira solo tras el TTL", cola.turno_llamado(CODIGO_HASH) is None and not r.exists(clave))
        cola.registrar_llamado(CODIGO_HASH, "V-01", "normal", ttl=60)
        check("confirmar_presencia elimina el Hash", cola.confirmar_presencia(CODIGO_HASH)
              and cola.turno_llamado(CODIGO_HASH) is None)
    finally:
        r.delete(CONTADOR, COLA, clave_turno(CODIGO_HASH), *[ACTUAL.format(v) for v in VENTANILLAS])
    print("Todo OK")


if __name__ == "__main__":
    main()
