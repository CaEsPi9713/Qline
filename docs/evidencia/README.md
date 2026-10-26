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
