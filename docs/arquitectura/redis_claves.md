# Mapa de claves Redis de QLine

Documento vivo del contrato de Redis (TT-011, TT-012, TT-013 y, al cierre, TT-027).
Todas las claves y canales empiezan con `grupo2:qline:`. Está prohibido `FLUSHALL` y `FLUSHDB`.
Las constantes viven en [`app/constantes.py`](../../app/constantes.py); las operaciones, en [`app/cola.py`](../../app/cola.py).

## Estructuras

| Clave / canal | Tipo | Vida | Quién la escribe | Estado |
|---|---|---|---|---|
| `grupo2:qline:contador:atencion_general` | String | Permanente | Emisión (`INCR`) | Implementada |
| `grupo2:qline:cola:atencion_general` | Sorted Set | Mientras el turno espera | Emisión (`ZADD NX`) · llamada (`ZPOPMIN`) | Implementada |
| `grupo2:qline:ventanilla:{id}:actual` | String | Mientras la ventanilla atiende el turno | Llamada · finalización | Implementada |
| `grupo2:qline:turno:{codigo}` | **Hash + TTL 180 s** | Hasta que el cliente se presenta o vence | Llamada · inicio/fin de atención | **Implementada (Fase 1)** |
| `grupo2:qline:eventos` | Pub/Sub | — | Todas las transiciones | Publicador y receptor implementados; emitir, llamar, iniciar y finalizar ya publican (falta el abandono, HU-008). Ver [tiempo_real.md](tiempo_real.md) |

Con esto el flujo ya usa **tres estructuras distintas** de Redis (Sorted Set, String y Hash), requisito de TT-011.

## Cola (Sorted Set)

`score = nivel × 10¹³ + hora_de_llegada_ms`, con nivel 0 = preferencial y 1 = normal. La prioridad domina a la llegada y, a igual prioridad, se conserva FIFO. El miembro es el código del turno.

## Ventanilla actual (String): una ventanilla, un turno

- `SET NX` con vida de 10 s **reserva** la ventanilla antes de extraer el turno (valor `__asignando__`). Si ya tiene un turno, la llamada se rechaza con 409 y no se extrae nada.
- La reserva se reemplaza por el código del turno **solo cuando MongoDB ya lo marcó `llamado`**. Si el proceso muere antes, la reserva expira sola.
- MongoDB también cuenta: un turno `llamado` o `en_atencion` ocupa la ventanilla aunque Redis haya perdido la clave, y una clave que apunta a un turno terminado se repara.

## Estado temporal del turno llamado (Hash + TTL)

`grupo2:qline:turno:{codigo}` — se crea **junto con** `ventanilla:{id}:actual` en una misma transacción (`MULTI/EXEC`) cuando el turno pasa a `llamado`.

| Campo | Contenido |
|---|---|
| `codigo` | Código del turno |
| `ventanilla` | Ventanilla que lo llamó |
| `prioridad` | `normal` o `preferencial` |
| `llamado_ms` | Instante de la llamada (epoch, ms) |
| `vence_ms` | `llamado_ms + 180 000`: instante en que se considera abandonado |

TTL: **180 s** (`TTL_ABANDONO_SEG`). Sin datos personales.

### Ciclo de vida

```text
pendiente ──llamar──▶ llamado ──iniciar atención──▶ en_atencion ──finalizar──▶ atendido
                      │ Hash creado (TTL 180 s)      │ Hash eliminado             │ Hash eliminado
                      └──── 180 s sin presentarse ──▶ abandonado (HU-008)
```

| Evento | Qué hace con el Hash | Función |
|---|---|---|
| Llamar siguiente | Lo crea con TTL 180 s | `cola.confirmar_asignacion` |
| Iniciar atención (`/api/atencion/iniciar`, `/panel/iniciar`) | Lo elimina: el cliente se presentó | `cola.confirmar_presencia` |
| Finalizar atención | Lo elimina por seguridad | `redis_atencion.liberar_turno` |
| Pasan 180 s | Redis lo elimina solo | TTL |

### Funciones disponibles

| Función | Devuelve |
|---|---|
| `cola.registrar_llamado(codigo, ventanilla, prioridad, ttl=180)` | Crea o reinicia el Hash |
| `cola.turno_llamado(codigo)` | Datos del Hash, o `None` si no existe o expiró |
| `cola.segundos_restantes(codigo)` | Segundos que faltan, o `None` |
| `cola.confirmar_presencia(codigo)` | `True` si existía y se eliminó |

## Contrato para el abandono (HU-008 / TT-012, de Abigail)

Redis **no avisa** cuando una clave expira: las notificaciones de expiración exigen `CONFIG SET`, que no está disponible con la cuenta del curso. Por eso:

1. Un turno `llamado` en MongoDB es **candidato a abandono** cuando `timestamps.llamado + 180 s` ya pasó **y** `cola.turno_llamado(codigo)` devuelve `None`.
2. La decisión se apoya en `timestamps.llamado` de MongoDB; la ausencia del Hash por sí sola no basta (también desaparecería si se perdiera Redis).
3. La transición `llamado → abandonado` debe ser idempotente: `update_one` con filtro `estado == "llamado"`, de modo que varias ejecuciones simultáneas (varios procesos de la app) no choquen.
4. Al abandonar: registrar `timestamps.abandonado`, liberar la ventanilla (`cola.liberar_ventanilla_si(ventanilla, codigo)`) y no devolver el turno a la cola.
5. Un turno `abandonado` no se vuelve a asignar (transición prohibida por el plan).

## Reglas de consistencia (sección 17 del plan)

- Un turno `atendido` o `abandonado` no puede estar en la cola ni como actual de una ventanilla.
- Un mismo turno no puede ser el actual de dos ventanillas.
- Todas las operaciones de Redis posteriores a un cambio en MongoDB son de mejor esfuerzo: si Redis falla, MongoDB queda correcto y la respuesta lo indica (`aviso` o `redis_liberado: false`).
