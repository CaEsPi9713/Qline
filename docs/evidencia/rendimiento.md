# Mediciones de rendimiento · Redis frente a MongoDB (TT-018, parte de Alessandro)

> Informe generado por `scripts/medir_rendimiento.py` con los resultados de **esa ejecución**; no se escribe a mano.

## Entorno y método

- Fecha (UTC): 2026-10-24 17:46:33
- Redis: 7.0.15 · MongoDB: 7.0.45
- Python: 3.12.3 · Linux
- **5 ejecuciones** por operación y motor; cada ejecución son **200 operaciones** seguidas, tras 20 de calentamiento que se descartan.
- De cada ejecución se toma la **mediana** de sus latencias; las tablas muestran el mínimo, el máximo y la mediana de esas medianas.
- Latencia vista desde la aplicación (incluye la red local y la biblioteca cliente), en milisegundos.

## Generar el código del turno

| Motor | Operación | Ejecuciones | Mínimo (ms) | Máximo (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|
| Redis | INCR | 5 | 0.103 | 0.111 | **0.108** |
| MongoDB | find_one_and_update ($inc) | 5 | 0.367 | 0.382 | **0.376** |

Medianas de cada ejecución — Redis: [0.103, 0.1044, 0.1104, 0.1081, 0.1115] · MongoDB: [0.3673, 0.3819, 0.3762, 0.3779, 0.3752]

## Poner el turno en la cola

| Motor | Operación | Ejecuciones | Mínimo (ms) | Máximo (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|
| Redis | ZADD | 5 | 0.118 | 0.128 | **0.126** |
| MongoDB | insert_one | 5 | 0.344 | 0.355 | **0.347** |

Medianas de cada ejecución — Redis: [0.1261, 0.128, 0.1275, 0.1253, 0.1178] · MongoDB: [0.3554, 0.3444, 0.347, 0.3538, 0.3441]

## Sacar el siguiente turno

| Motor | Operación | Ejecuciones | Mínimo (ms) | Máximo (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|
| Redis | ZPOPMIN | 5 | 0.131 | 0.139 | **0.135** |
| MongoDB | find_one_and_update (mayor prioridad) | 5 | 0.482 | 0.519 | **0.493** |

Medianas de cada ejecución — Redis: [0.1336, 0.1364, 0.1314, 0.1345, 0.1386] · MongoDB: [0.4956, 0.4825, 0.4825, 0.519, 0.4925]

## Interpretación

- **Generar el código del turno** (INCR): Redis tardó 0.108 ms de mediana; MongoDB (find_one_and_update ($inc)) 0.376 ms. Redis fue 3.5 veces más rápido (71.3 % menos latencia).
- **Poner el turno en la cola** (ZADD): Redis tardó 0.126 ms de mediana; MongoDB (insert_one) 0.347 ms. Redis fue 2.8 veces más rápido (63.7 % menos latencia).
- **Sacar el siguiente turno** (ZPOPMIN): Redis tardó 0.135 ms de mediana; MongoDB (find_one_and_update (mayor prioridad)) 0.493 ms. Redis fue 3.7 veces más rápido (72.7 % menos latencia).

## Contraste con las hipótesis de S1

S1 planteó como **hipótesis inicial** una latencia de Redis menor de 2 ms y una mejora de más del 85 % frente a MongoDB. Con lo medido:

| Operación | Redis < 2 ms | Mejora frente a MongoDB | ¿Más del 85 %? |
|---|---|---|---|
| Generar el código del turno | sí | 71.3 % | no |
| Poner el turno en la cola | sí | 63.7 % | no |
| Sacar el siguiente turno | sí | 72.7 % | no |

## Límites de esta medición

- Es una medición desde la aplicación hacia un servidor **compartido**: la carga de otros grupos puede variar los números entre ejecuciones; por eso se reportan el mínimo, el máximo y la mediana.
- Compara operaciones equivalentes para QLine, no el rendimiento interno de cada motor.
- Las operaciones de MongoDB usan colecciones de prueba con el índice que tendría la consulta real; sin ese índice la diferencia sería mayor.
- Las mediciones de las otras partes del equipo (índices con `explain()`, agregaciones y recuperación) las consolidan sus responsables.
