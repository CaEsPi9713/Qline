# Evidencias del Seguimiento 3

Los informes de esta carpeta **los genera el script que los produce**, con los resultados de esa ejecución. No se editan a mano ni se escriben antes de correr la prueba: deben salir del servidor donde se demuestra el proyecto.

| Informe | Script | Tarea |
|---|---|---|
| `concurrencia.md` | `python scripts/prueba_concurrencia.py --http --informe docs/evidencia/concurrencia.md` | TT-016 · 10 solicitudes concurrentes, 0 duplicados |
| `rendimiento.md` | `python scripts/medir_rendimiento.py --informe docs/evidencia/rendimiento.md` | TT-018 · mediciones con mediana (parte de Redis) |
| `fallos.md` | `python scripts/probar_fallos_redis.py --informe docs/evidencia/fallos.md` | TT-019 · Redis caído y datos inválidos (módulos de Redis) |
| `recuperacion.md` | `python -m scripts.probar_recuperacion --informe docs/evidencia/recuperacion.md` | TT-017 · caída y rehidratación de la cola (HU-012) |
| `rendimiento_recuperacion.md` | `python -m scripts.medir_recuperacion --informe docs/evidencia/rendimiento_recuperacion.md` | TT-018 · rehidratación, reconciliación y barrido de abandono, con mediana |
| `fallos_recuperacion.md` | `python -m scripts.probar_fallos_recuperacion --informe docs/evidencia/fallos_recuperacion.md` | TT-019 · Redis y MongoDB caídos, datos inválidos y carreras (HU-008 y HU-012) |
| `indices_mongo.md` | `python scripts/medir_indices_mongo.py --informe docs/evidencia/indices_mongo.md` | TT-014 y TT-015 · índices con `explain()` y aggregation pipelines del dashboard (Carlos). **Se genera en el servidor** |
| `qr_token.md` | `python -m scripts.probar_qr_token --informe docs/evidencia/qr_token.md` | TT-001, TT-002 y HU-003 · `qr_token` aceptado, repetido rechazado, turnos sin token conviven y la consulta usa el índice (Carlos y Aaron). **Se genera en el servidor** |

## Cómo ejecutar TT-016 en el servidor

Con el entorno virtual activo y la app corriendo:

```bash
python scripts/prueba_concurrencia.py --http --informe docs/evidencia/concurrencia.md
```

- Sin `--http` solo corre los escenarios A y B sobre Redis, con claves de prueba que se eliminan al terminar.
- Con `--http` el escenario C usa el flujo real. Exige la cola vacía y las ventanillas libres, y elimina los turnos que crea. El contador de códigos queda avanzado: antes de la demostración se reinicia con `redis-cli del grupo2:qline:contador:atencion_general`.
- El código de salida es 0 si todo pasó y 1 si hubo cualquier fallo; en ese caso el informe lo dice, no lo oculta.

## Cómo ejecutar las pruebas de abandono y recuperación (Abigail)

Con el entorno virtual activo y la aplicación corriendo, desde la raíz del proyecto. Las tres usan datos de prueba propios (series `R-`, `M-` y `F-`, claves `grupo2:qline:prueba:*`) y los eliminan al terminar; no tocan los turnos reales.

```bash
python -m scripts.probar_recuperacion --informe docs/evidencia/recuperacion.md
python -m scripts.medir_recuperacion --informe docs/evidencia/rendimiento_recuperacion.md
python -m scripts.probar_fallos_recuperacion --informe docs/evidencia/fallos_recuperacion.md
```

- Se pueden ejecutar con la aplicación (y su barrido de abandono) en marcha: sus turnos «vencidos» usan un reloj adelantado y el barrido real no los toca.
- Cada una termina con código 0 si todo salió como se esperaba y 1 si no; el informe lo dice, no lo oculta.
- `medir_recuperacion` exige al menos 3 ejecuciones por medición (`--ejecuciones`, 5 por defecto).

## Cómo ejecutar la medición de índices (Carlos)

Con el entorno virtual activo, desde la raíz del proyecto y con los índices de `app/turnos_schema.py` creados:

```bash
python scripts/medir_indices_mongo.py --informe docs/evidencia/indices_mongo.md
```

- Mide contra el MongoDB real; no existe modo simulado. Si faltan índices o hay menos de 50 turnos, termina con un error que indica cómo resolverlo.
- Solo lee la colección `turnos`. Si ningún turno tiene `qr_token`, crea uno temporal (`Q-9901`) y lo elimina al terminar.
- Código de salida: 0 si midió, 1 si no pudo, 2 si los argumentos no son válidos.

## Cómo ejecutar la prueba de `qr_token` (Carlos y Aaron)

```bash
python -m scripts.probar_qr_token --informe docs/evidencia/qr_token.md
```

- Inserta y elimina solo los turnos `Q-9901` a `Q-9905`; no toca turnos reales.
- Una línea es **informativa**: indica si el motor valida el formato del token (depende del esquema con el que se creó la colección); el formato lo valida siempre el validador de Python.
- Código de salida: 0 si todo cumple, 1 si algo falla.
