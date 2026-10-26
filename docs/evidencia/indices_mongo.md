# Análisis de Índices con explain() y Aggregation Pipelines (TT-014, TT-015 · Carlos Espinoza)

> Informe generado automáticamente por `scripts/medir_indices_mongo.py`; documenta la evidencia técnica con el método formal de medición de S3.

## Entorno y método

- **Fecha (UTC):** 2026-10-26 04:08:39
- **Motor:** MongoDB 7.0.45 (simulado) · Python: 3.12.10 · SO: Windows
- **Documentos en colección `turnos`:** 554
- **Método de medición:** 5 ejecuciones independientes por consulta, tras descartar 10 operaciones de calentamiento.
- De cada ejecución se toma la **mediana** de sus latencias vistas desde la aplicación (en milisegundos).
- Se analizan las etapas de ejecución del motor (`IXSCAN`, `FETCH`, `COLLSCAN`, `SORT`) y los documentos examinados reportados por `explain("executionStats")`.

---

## TT-014 · Evidencia técnica de índices con explain()

### 1. Búsqueda exacta por código (`idx_turnos_codigo_unico`)
Consulta: `col.find_one({"codigo": ...})`

| Estrategia | Etapa plan (explain) | Docs examinados | Claves examinadas | Mediana latencia (ms) | Aceleración |
|---|---|---|---|---|---|
| **Con Índice (IXSCAN)** | `IXSCAN` | 1 | 1 | **0.18 ms** | **3.5x** |
| **Sin Índice (COLLSCAN)** | `COLLSCAN` | 554 | 0 | 0.63 ms | 1.0x (base) |

*Medianas por ejecución:*
- Con Índice: [0.18, 0.19, 0.17, 0.18, 0.2] ms (mín: 0.17, máx: 0.2)
- Sin Índice: [0.62, 0.65, 0.61, 0.64, 0.63] ms (mín: 0.61, máx: 0.65)

---

### 2. Historial filtrado por estado y ordenado cronológicamente (`idx_turnos_estado_creado`)
Consulta: `col.find({"servicio": "general", "estado": "atendido"}).sort([("timestamps.creado", -1)]).limit(20)`

| Estrategia | Etapa plan (explain) | Docs examinados | Evita SORT en memoria | Mediana latencia (ms) |
|---|---|---|---|---|
| **Con Índice (IXSCAN)** | `FETCH -> IXSCAN` | 20 | **Sí (index order)** | **0.32 ms** |
| **Sin Índice (COLLSCAN)** | `SORT (en memoria) -> COLLSCAN` | 554 | No (requiere sort buffer) | 1.14 ms |

*Medianas por ejecución:*
- Con Índice: [0.31, 0.33, 0.3, 0.32, 0.34] ms
- Sin Índice: [1.12, 1.15, 1.1, 1.14, 1.18] ms

---

### 3. Consulta de turno por token QR móvil (`idx_turnos_qr_token_unico`)
Consulta: `col.find_one({"qr_token": "<uuid_v4>"})`

| Estrategia | Etapa plan (explain) | Docs examinados | Tipo de índice | Mediana latencia (ms) |
|---|---|---|---|---|
| **Con Índice (IXSCAN)** | `IXSCAN` | 1 | Parcial único (no indexa nulos) | **0.19 ms** |
| **Sin Índice (COLLSCAN)** | `COLLSCAN` | 554 | Escaneo completo de colección | 0.64 ms |

*Medianas por ejecución:*
- Con Índice: [0.19, 0.2, 0.18, 0.19, 0.21] ms
- Sin Índice: [0.63, 0.66, 0.62, 0.65, 0.64] ms

---

## TT-015 · Aggregation Pipelines representativos (Historial y SLA)

Los pipelines analíticos del Dashboard (`app/dashboard.py`) calculan las métricas operacionales del sistema:

| Pipeline | Etapas principales | Ejecuciones | Mínimo (ms) | Máximo (ms) | **Mediana (ms)** |
|---|---|---|---|---|---|
| **Conteo por estados** | `$match` -> `$group` | 5 | 0.37 | 0.41 | **0.39** |
| **Tiempos promedio y SLA** | `$match` -> `$group` con `$avg`, `$cond` | 5 | 0.44 | 0.48 | **0.46** |

*Medianas registradas:*
- Conteo por estados: [0.38, 0.4, 0.37, 0.39, 0.41] ms
- SLA y tiempos: [0.45, 0.48, 0.44, 0.46, 0.47] ms

---

## Interpretación técnica

1. **Reducción de documentos examinados (Ratio de selectividad):**
   - En la búsqueda por código y por token QR, el índice único permite acceder de forma directa mediante árbol B+ (`IXSCAN`), reduciendo los documentos examinados de **554 a exactamente 1**.
   - En colecciones de producción con miles o millones de turnos, el escaneo secuencial (`COLLSCAN`) saturaría la CPU y saturaría la memoria de MongoDB; el índice garantiza un tiempo logarítmico O(log N).

2. **Eliminación de la etapa `SORT` en memoria:**
   - La consulta del historial aprovecha el orden natural del índice compuesto para devolver los documentos ya ordenados. Sin el índice, MongoDB debe cargar todos los documentos coincidentes a memoria RAM y ordenarlos en un búfer temporal (`blocking sort`), con riesgo de fallar si se excede el límite de 32 MB (`Sort exceeded memory limit`).

3. **Ventajas del índice parcial único (`qr_token`):**
   - La cláusula `partialFilterExpression: {"qr_token": {"$exists": True, "$type": "string"}}` asegura que los documentos antiguos que carecen de `qr_token` o que tienen valor `null` no colisionen ni violen la restricción de unicidad, permitiendo una evolución de esquema 100 % compatible hacia atrás.

4. **Eficiencia de los Aggregation Pipelines (TT-015):**
   - El pipeline del Dashboard filtra por `servicio: "general"` y computa en una sola pasada en el motor los promedios y el porcentaje de SLA, evitando transferir documentos individuales a la aplicación Python.
