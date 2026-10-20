
# QLine

**Sistema inteligente de gestión de filas y turnos en tiempo real**

> *"MongoDB conserva lo que ocurrió. Redis controla lo que ocurre ahora."*

Proyecto final de **Tópicos Avanzados de Bases de Datos** · Universidad Nacional · Equipo **Query Logic**

![Estado](https://img.shields.io/badge/estado-Seguimiento%201-blue)
![Python](https://img.shields.io/badge/python-3.12-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-009688)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248)
![Redis](https://img.shields.io/badge/Redis-DC382D)
![Licencia](https://img.shields.io/badge/licencia-MIT-green)

## Estructura de ramas

Repositorio principal para el proyecto QLine.

- `main`: Rama de producción / código estable.
- `development`: Rama principal de desarrollo e integración.

### Ramas de trabajo (derivadas de `development`):

- `cespinoza`
- `abenavides`
- `acambronero`
- `aurbina`

## 1. Licencia

Distribuido bajo licencia **MIT**. Ver [`LICENSE`](LICENSE).

## 2. Datos sintéticos (TT-005)

QLine incluye un generador de turnos **100 % sintéticos**: solo códigos, prioridad, ventanilla y tiempos, sin datos personales. Simula la operación de la fila (prioridad antes que llegada, FIFO dentro de cada prioridad, 3 ventanillas, abandono a los 180 s), de modo que los estados y las marcas de tiempo son coherentes entre sí.

### Qué genera

- Documentos con el contrato de `turnos` (servicio `atencion_general`, prioridades `normal`/`preferencial`, ventanillas `V-01`/`V-02`/`V-03`, estados oficiales). Los campos que aún no aplican quedan en `null`.
- Códigos `S-001`, `S-002`, ... La serie `S-` está separada a propósito de la serie `A-` de la operación real, para no colisionar con el contador de Redis ni con los turnos emitidos en vivo.
- Con los parámetros por defecto: 3 días simulados y unos 550 turnos, todos terminados (`atendido` o `abandonado`). Son **historial**: no dejan turnos `pendiente`, `llamado` ni `en_atencion`, para que no se confundan con la operación real (panel de atención, dashboard) ni los reencole una rehidratación de Redis. Con `--con-activos` se obtiene la instantánea del corte, con turnos en espera y en curso (solo existen en MongoDB; no se encolan en Redis).

### Cómo ejecutarlo

Desde la raíz del proyecto, con el entorno virtual activo:

```bash
python scripts/generar_datos_sinteticos.py                          # vista previa: genera, valida y resume; no escribe nada
python scripts/generar_datos_sinteticos.py --salida datos.jsonl     # escribe un archivo JSON Lines (Extended JSON)
python scripts/generar_datos_sinteticos.py --cargar                 # upsert en MongoDB (no duplica)
python scripts/generar_datos_sinteticos.py --reiniciar --confirmar  # borra los sintéticos y vuelve a cargar
python scripts/generar_datos_sinteticos.py --limpiar --confirmar    # borra solo los códigos S-NNN
```

Opciones útiles: `--semilla`, `--dias`, `--fecha-fin`, `--llegadas-por-hora`, `--prefijo`, `--con-activos` y `--json` (resumen en JSON).

- **Reproducible:** la semilla por defecto es fija y la fecha de simulación no depende de la fecha actual. Los mismos parámetros producen exactamente los mismos documentos.
- **Sin duplicados:** `--cargar` hace upsert por `codigo`, así que ejecutarlo varias veces deja los mismos documentos.
- **Seguro:** `--limpiar` y `--reiniciar` exigen `--confirmar` y solo afectan a los códigos con el prefijo sintético, nunca a la serie `A-`.
- **Validado:** antes de escribir, el generador comprueba el contrato (valores oficiales, `null` donde corresponde, marcas de tiempo en orden, métricas consistentes, ninguna ventanilla con dos turnos a la vez).
- La carga lee `MONGO_USER`, `MONGO_PASS`, `MONGO_DB`, `MONGO_HOST` y `MONGO_PORT` del archivo `.env` (ver `.env.example`).

### Turnos de prueba para el ciclo de atención

`python scripts/sembrar_turnos_hu006.py` inserta (o restaura) seis turnos `A-015` a `A-020` en distintos estados, para probar iniciar y finalizar atención. `--limpiar` elimina solo esos seis. Usan la serie `A-`, así que no los ejecute si ya existen turnos reales con esos códigos.

### Pruebas

```bash
python -m unittest discover -s tests -t . -v
```

Las pruebas de rutas HTTP y de Redis requieren `httpx`/`httpx2` y `fakeredis`; si no están instalados, se omiten. Para ejecutarlas todas: `pip install -r requirements-dev.txt`.
