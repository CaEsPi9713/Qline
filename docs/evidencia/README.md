# Evidencias del Seguimiento 3

Los informes de esta carpeta **los genera el script que los produce**, con los resultados de esa ejecución. No se editan a mano ni se escriben antes de correr la prueba: deben salir del servidor donde se demuestra el proyecto.

| Informe | Script | Tarea |
|---|---|---|
| `concurrencia.md` | `python scripts/prueba_concurrencia.py --http --informe docs/evidencia/concurrencia.md` | TT-016 · 10 solicitudes concurrentes, 0 duplicados |
| `rendimiento.md` | `python scripts/medir_rendimiento.py --informe docs/evidencia/rendimiento.md` | TT-018 · mediciones con mediana (parte de Redis) |
| `fallos.md` | `python scripts/probar_fallos_redis.py --informe docs/evidencia/fallos.md` | TT-019 · Redis caído y datos inválidos (módulos de Redis) |

## Cómo ejecutar TT-016 en el servidor

Con el entorno virtual activo y la app corriendo:

```bash
python scripts/prueba_concurrencia.py --http --informe docs/evidencia/concurrencia.md
```

- Sin `--http` solo corre los escenarios A y B sobre Redis, con claves de prueba que se eliminan al terminar.
- Con `--http` el escenario C usa el flujo real. Exige la cola vacía y las ventanillas libres, y elimina los turnos que crea. El contador de códigos queda avanzado: antes de la demostración se reinicia con `redis-cli del grupo2:qline:contador:atencion_general`.
- El código de salida es 0 si todo pasó y 1 si hubo cualquier fallo; en ese caso el informe lo dice, no lo oculta.
