# Prueba formal de concurrencia (TT-016)

> Informe generado por `scripts/prueba_concurrencia.py` con los resultados de **esa ejecución**; no se escribe a mano.

## Entorno

- Fecha (UTC): 2026-10-24 17:35:09
- Redis: 7.0.15 (127.0.0.1:6379)
- Python: 3.12.3 · Linux
- Consumidores simultáneos por ronda: 10 (meta del plan: 10)

## Resultado global

**OK** · 259 asignaciones comprobadas · **0 turnos duplicados**.

## Escenario A · rondas de consumidores simultáneos

Cada ronda arranca todos los consumidores a la vez con una barrera; se comprueba que cada uno recibe un turno distinto, que el conjunto asignado es el de los primeros de la cola (prioridad respetada) y que la cola baja en la cantidad exacta.

| Ronda | Consumidores | Turnos en cola | Asignados | Duplicados | Errores | Prioridad respetada | Cola restante | Tiempo (ms) | Resultado |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 25 | 10 | 0 | 0 | sí | 15 (esperada 15) | 15.1 | OK |
| 2 | 10 | 25 | 10 | 0 | 0 | sí | 15 (esperada 15) | 7.5 | OK |
| 3 | 10 | 25 | 10 | 0 | 0 | sí | 15 (esperada 15) | 7.4 | OK |
| 4 | 10 | 25 | 10 | 0 | 0 | sí | 15 (esperada 15) | 7.6 | OK |
| 5 | 10 | 25 | 10 | 0 | 0 | sí | 15 (esperada 15) | 7.8 | OK |

## Escenario B · vaciado competitivo

10 consumidores se disputan 200 turnos hasta vaciar la cola.

| Turnos en cola | Asignados | Únicos | Duplicados | Errores | Cola restante | Tiempo (ms) | Resultado |
|---|---|---|---|---|---|---|---|
| 200 | 200 | 200 | 0 | 0 | 0 | 151.4 | OK |

Reparto entre consumidores (turnos por consumidor): [22, 22, 21, 21, 20, 20, 20, 19, 18, 17]

## Escenario C · flujo real de extremo a extremo

12 turnos emitidos por la API (primero normales, luego 4 preferenciales). En cada ronda, 10 solicitudes simultáneas a `POST /api/llamar` sobre las 3 ventanillas reales; se verifica MongoDB y Redis y se cierra el ciclo (iniciar y finalizar).

| Ronda | Solicitudes | Asignados | Rechazados (409) | Duplicados | Prioridad | MongoDB | Redis | Ciclo completo | Resultado |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 10 | 3 (A-010, A-009, A-011) | 7 | 0 | respetada | OK | OK | sí | OK |
| 2 | 10 | 3 (A-001, A-012, A-002) | 7 | 0 | respetada | OK | OK | sí | OK |
| 3 | 10 | 3 (A-004, A-005, A-003) | 7 | 0 | respetada | OK | OK | sí | OK |

## Qué demuestra

- `ZPOPMIN` es atómico: dos consumidores nunca reciben el mismo turno, ni siquiera con todos arrancando a la vez.
- La reserva `SET NX` de la ventanilla impide asignar dos turnos a la misma ventanilla.
- La prioridad se respeta bajo concurrencia.

## Alcance y límites

- Los escenarios A y B ejercitan Redis directamente (la parte que decide la asignación). El escenario C ejercita además MongoDB y la API.
- Los consumidores son hilos de un mismo proceso: demuestran la atomicidad de Redis, no el rendimiento (eso es TT-018).
- No sustituye la medición de latencias ni la prueba de recuperación (TT-017).
