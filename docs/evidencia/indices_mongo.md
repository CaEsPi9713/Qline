# Índices con explain() y aggregation pipelines (TT-014, TT-015 · Carlos Espinoza)

> Informe generado por un script con los resultados de **esa ejecución**; no se escribe a mano.

- Fecha (UTC): 2026-10-27 00:11:26
- Python: 3.12.3 · Linux

## Entorno y método

- Motor: MongoDB 7.0.45 · Documentos en `turnos`: **554**
- Sistema: Linux · Python 3.12.3
- **5 ejecuciones** independientes por consulta (mínimo exigido: 3), de 50 operaciones cada una tras 10 de calentamiento que se descartan. De cada ejecución se toma la **mediana**; las tablas muestran el mínimo, el máximo y la mediana de esas medianas.
- «Con índice» deja que MongoDB elija su plan. «Recorrido completo» fuerza `hint $natural` (lectura de toda la colección).
- Latencia vista desde la aplicación, en milisegundos. Las etapas y los documentos examinados salen de `explain("executionStats")`.
- Medición hecha con **554 documentos**: con tan pocos datos las diferencias de tiempo son pequeñas; los documentos examinados muestran mejor el efecto del índice.

## TT-014 · Índices con explain()

### 1. Búsqueda por código (`idx_turnos_codigo_unico`)

Consulta: `find({"codigo": "S-001"})`

| Estrategia | Plan (explain) | Docs examinados | Claves examinadas | Devueltos | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|---|---|
| Con índice | `FETCH -> IXSCAN` | 1 | 1 | 1 | 0.4238 | 0.4319 | **0.4257** |
| Recorrido completo | `COLLSCAN` | 554 | 0 | 1 | 0.6516 | 0.6658 | **0.6567** |

Medianas de cada ejecución — con índice: [0.4294, 0.4319, 0.4257, 0.4246, 0.4238] · recorrido completo: [0.6658, 0.6585, 0.6567, 0.6561, 0.6516]

**Resultado:** con índice examina 1 documento(s) (1 clave(s)) y sin índice 554; mediana 0.4257 ms frente a 0.6567 ms (1.5 veces).

### 2. Historial por estado, ordenado por creación (los 20 más recientes) (`idx_turnos_estado_creado`)

Consulta: `find({"servicio": "atencion_general", "estado": "atendido"}).sort("timestamps.creado", -1).limit(20)`

| Estrategia | Plan (explain) | Docs examinados | Claves examinadas | Devueltos | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|---|---|
| Con índice | `LIMIT -> FETCH -> IXSCAN` | 20 | 20 | 20 | 0.5745 | 0.5812 | **0.5765** |
| Recorrido completo | `SORT -> COLLSCAN` | 554 | 0 | 20 | 1.0477 | 1.0562 | **1.0513** |

Medianas de cada ejecución — con índice: [0.5812, 0.5765, 0.5753, 0.5745, 0.5776] · recorrido completo: [1.0477, 1.0524, 1.0513, 1.0497, 1.0562]

**Resultado:** con índice examina 20 documento(s) (20 clave(s)) y sin índice 554; el plan con índice no ordena en memoria (usa el orden del índice); el recorrido completo ordena en memoria; mediana 0.5765 ms frente a 1.0513 ms (1.8 veces).

### 3. Consulta por token QR (el mismo filtro que usa la aplicación) (`idx_turnos_qr_token_unico`)

Consulta: `find(filtro_por_token("<uuid v4>"))  # {"qr_token": {"$eq": t, "$type": "string"}}`

| Estrategia | Plan (explain) | Docs examinados | Claves examinadas | Devueltos | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|---|---|
| Con índice | `FETCH -> IXSCAN` | 1 | 1 | 1 | 0.4311 | 0.4369 | **0.4319** |
| Recorrido completo | `COLLSCAN` | 555 | 0 | 1 | 0.7108 | 0.7217 | **0.7144** |

Medianas de cada ejecución — con índice: [0.4369, 0.4319, 0.4343, 0.4311, 0.4319] · recorrido completo: [0.7134, 0.7144, 0.7108, 0.7217, 0.7189]

**Resultado:** con índice examina 1 documento(s) (1 clave(s)) y sin índice 555; mediana 0.4319 ms frente a 0.7144 ms (1.7 veces).

> No había turnos con qr_token: se creó un turno temporal durante esta consulta (un documento más que en las demás) y se eliminó al terminar.

### 4. Candidatos del barrido de abandono (HU-008) (`idx_turnos_estado_llamado`)

Consulta: `find({"estado": "llamado", "timestamps.llamado": {"$lte": ahora - 180 s}})`

| Estrategia | Plan (explain) | Docs examinados | Claves examinadas | Devueltos | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|---|---|
| Con índice | `FETCH -> IXSCAN` | 0 | 0 | 0 | 0.4138 | 0.4159 | **0.4141** |
| Recorrido completo | `COLLSCAN` | 554 | 0 | 0 | 0.6639 | 0.6753 | **0.6721** |

Medianas de cada ejecución — con índice: [0.4138, 0.4159, 0.4141, 0.4149, 0.4139] · recorrido completo: [0.6736, 0.6639, 0.6674, 0.6721, 0.6753]

**Resultado:** con índice examina 0 documento(s) (0 clave(s)) y sin índice 554; mediana 0.4141 ms frente a 0.6721 ms (1.6 veces).

## TT-015 · Aggregation pipelines del dashboard

Son los mismos pipelines que usa la aplicación (`pipeline_conteo_estados` y `pipeline_tiempos_sla` de `app/dashboard.py`).

| Pipeline | Etapas | Ejecuciones | Mín. (ms) | Máx. (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|
| Conteo por estados | `$match -> $group` | 5 | 0.9636 | 0.9795 | **0.9679** |
| Tiempos promedio y cumplimiento de SLA | `$match -> $group (con $avg y $cond)` | 5 | 1.884 | 1.966 | **1.8896** |

Medianas de cada ejecución:
- Conteo por estados: [0.9795, 0.9731, 0.9657, 0.9636, 0.9679] ms
- Tiempos promedio y cumplimiento de SLA: [1.9067, 1.884, 1.8896, 1.8869, 1.966] ms

## Lectura de los resultados

- Todas las consultas medidas usaron su índice.
- Los pipelines agregan en el motor y devuelven solo el resumen, no los documentos; no se comparó contra un cálculo en Python, así que esta medición no cuantifica esa ventaja.
