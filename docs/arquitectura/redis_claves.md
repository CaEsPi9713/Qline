# Mapa de claves Redis de QLine

Documento vivo del contrato de Redis (TT-011, TT-012, TT-013 y TT-027). **Revisado contra el código integrado el 02/11/2026** (TT-027): las diferencias verificadas están incorporadas y `tests/test_redis_claves_doc.py` vigila que el documento y el código no se separen.
Todas las claves y canales empiezan con `grupo2:qline:`. Está prohibido `FLUSHALL` y `FLUSHDB`.
Las constantes viven en [`app/constantes.py`](../../app/constantes.py); las operaciones, en [`app/cola.py`](../../app/cola.py).

## Estructuras

| Clave / canal | Tipo | Vida | Quién la escribe | Estado |
|---|---|---|---|---|
| `grupo2:qline:contador:atencion_general` | String | Permanente | Emisión (`INCR`) | Implementada |
| `grupo2:qline:cola:atencion_general` | Sorted Set | Mientras el turno espera | Emisión (`ZADD NX`) · llamada (`ZPOPMIN`) · compensaciones (`devolver_a_cola`, `reencolar`) · recuperación (`rehidratar_cola`) | Implementada |
| `grupo2:qline:ventanilla:{id}:actual` | String | Reserva `__asignando__` de 10 s; después, el código del turno **sin TTL** hasta que se libera | Llamada (`SET NX`, luego `MULTI/EXEC`) · finalización · abandono (`liberar_ventanilla_si`) · compensación | Implementada |
| `grupo2:qline:turno:{codigo}` | **Hash + TTL 180 s** | Hasta que el cliente se presenta o vence | Llamada · inicio/fin de atención | **Implementada (Fase 1)** |
| `grupo2:qline:eventos` | Pub/Sub | — | Todas las transiciones | Publicador y receptor implementados; emitir, llamar, iniciar, finalizar y abandonar ya publican (el abandono lo publica el barrido, HU-008). Ver [tiempo_real.md](tiempo_real.md) |

Con esto el flujo ya usa **tres estructuras distintas** de Redis (Sorted Set, String y Hash), requisito de TT-011.

**Qué NO agrega claves:** el cierre con motivo y nota (S4-M03) vive solo en MongoDB (`cierre`); `/salud` solo hace `PING`; las ventanillas nuevas (P09) usan la misma clave `ventanilla:{id}:actual`; la pantalla de sala y el QR se alimentan de los eventos de `grupo2:qline:eventos` y de MongoDB. No se usan `EVAL`, `CONFIG SET`, `FLUSHALL` ni `FLUSHDB`.

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
| `cola.liberar_ventanilla_si(ventanilla, codigo)` | Libera la clave de la ventanilla solo si aún apunta a ese turno |
| `cola.devolver_a_cola(codigo, score, ventanilla)` / `cola.reencolar(...)` | Compensaciones: el turno vuelve a la cola con su posición original |

## Contrato para el abandono (HU-008 / TT-012, de Abigail) · implementado

Implementado en [`app/abandono.py`](../../app/abandono.py) y [`app/integracion_s3.py`](../../app/integracion_s3.py); decisiones D-16 a D-18 en [`decisiones.md`](../decisiones.md).

Redis **no avisa** cuando una clave expira: las notificaciones de expiración exigen `CONFIG SET`, que no está disponible con la cuenta del curso. Por eso:

1. Un turno `llamado` en MongoDB es **candidato a abandono** cuando `timestamps.llamado + 180 s` ya pasó **y** `cola.turno_llamado(codigo)` devuelve `None`.
2. La decisión se apoya en `timestamps.llamado` de MongoDB; la ausencia del Hash por sí sola no basta (también desaparecería si se perdiera Redis).
3. La transición `llamado → abandonado` debe ser idempotente: `update_one` con filtro `estado == "llamado"`, de modo que varias ejecuciones simultáneas (varios procesos de la app) no choquen.
4. Al abandonar: registrar `timestamps.abandonado`, liberar la ventanilla (`cola.liberar_ventanilla_si(ventanilla, codigo)`) y no devolver el turno a la cola.
5. Un turno `abandonado` no se vuelve a asignar (transición prohibida por el plan).

## Recuperación de la cola (HU-012, de Abigail)

[`app/recuperacion.py`](../../app/recuperacion.py) reconstruye la cola desde MongoDB (`python -m scripts.rehidratar_cola`, plan sin `--aplicar`). Escribe solo en dos claves del contrato, con las mismas reglas que la emisión:

| Clave | Qué hace la recuperación |
|---|---|
| `grupo2:qline:cola:atencion_general` | `ZADD NX` de los pendientes que faltan, con `score = nivel × 10¹³ + creado_ms`. Nunca reordena ni duplica; no quita nada salvo con `--quitar-sobrantes` |
| `grupo2:qline:contador:atencion_general` | Lo sube al mayor consecutivo de MongoDB si Redis lo perdió; nunca lo baja (se aplica con `WATCH/MULTI`) |

Conviene ejecutarla con la atención detenida (decisión D-20).

## Claves de prueba (se eliminan al terminar)

Las pruebas de TT-017, TT-018 y TT-019 usan claves aparte para no tocar la operación real. Solo existen mientras corre el script.

| Clave | Uso |
|---|---|
| `grupo2:qline:prueba:contador:R`, `...:M`, `...:F` | Contador aislado de la prueba de recuperación, de las mediciones y de los casos de fallo |
| `grupo2:qline:prueba:cola:M`, `...:F` | Cola aislada de las mediciones y de los casos de fallo |
| `grupo2:qline:prueba:eventos`, `...:eventos:F` | Canal de eventos aislado (el público no recibe nada) |
| `grupo2:qline:prueba:ventanilla:F:{id}` | Claves de ventanilla de los casos de fallo |

La prueba de recuperación (`R-*`) sí usa la cola real, pero solo con códigos `R-*`.

Las pruebas de la cola, de rendimiento y de concurrencia usan la familia `grupo2:qline:test:*`, que cada script elimina al terminar:

| Clave | Script | Uso |
|---|---|---|
| `grupo2:qline:test:contador`, `grupo2:qline:test:cola`, `grupo2:qline:test:ventanilla:{id}:actual` | `scripts/probar_cola.py` | Contador, cola y ventanillas de la prueba de la cola |
| `grupo2:qline:test:bench:*` (`contador`, `cola_enc`, `cola_sig`…) | `scripts/medir_rendimiento.py` | Mediciones de Redis contra MongoDB |
| `grupo2:qline:test:conc:cola`, `...:conc:actual:{consumidor}` | `scripts/prueba_concurrencia.py` | Consumidores simultáneos sobre una cola aislada |

El escenario C de `prueba_concurrencia.py` (opcional, con `--http`) sí usa la cola real y exige que esté vacía y sin ventanillas ocupadas; solo toca los turnos que él mismo emite.

## Identificador de ventanilla

`{id}` en `ventanilla:{id}:actual` es el código de una ventanilla con el formato `V-NN` (`PATRON_VENTANILLA` en `app/constantes.py`): `V-01` a `V-03` (las base, `VENTANILLAS`) y las que se den de alta en el catálogo de MongoDB (colección `ventanillas`, P09). La forma de la clave no depende del número de ventanillas y la reserva `SET NX` es la misma para cualquiera; quien valida que la ventanilla exista y esté activa es `app/ventanillas.ventanillas_activas(db)`, que `llamado.py` consulta **antes** de reservar. Si MongoDB no responde se usa el último catálogo conocido. No se agregan claves nuevas.

## Reglas de consistencia (sección 17 del plan)

- Un turno `atendido` o `abandonado` no puede estar en la cola ni como actual de una ventanilla.
- Un mismo turno no puede ser el actual de dos ventanillas.
- Todas las operaciones de Redis posteriores a un cambio en MongoDB son de mejor esfuerzo: si Redis falla, MongoDB queda correcto y la respuesta lo indica (`aviso` o `redis_liberado: false`).
