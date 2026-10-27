# Decisiones técnicas y alternativas (TT-020)

Registro de las decisiones tomadas durante el desarrollo, con las alternativas que se consideraron y por qué se descartaron. Cada integrante documenta las de su área. Este archivo no sustituye al Plan de Desarrollo: lo complementa con el *por qué*.

**Estado:** secciones de Redis, tiempo real y consulta por QR (Alessandro), MongoDB e historial (Carlos) y ciclo de atención y recuperación (Abigail) completas. Queda por añadir la sección de cliente (Aaron).

---

## Redis, concurrencia y tiempo real (Alessandro)

### D-01 · Una sola cola con prioridad en un Sorted Set

| | |
|---|---|
| **Decisión** | La cola es un Sorted Set `grupo2:qline:cola:atencion_general`. El puntaje es `nivel × 10¹³ + hora de llegada (ms)`, con nivel 0 para preferencial y 1 para normal. |
| **Por qué** | `ZPOPMIN` entrega el primero con prioridad y orden de llegada en un solo comando. La prioridad siempre domina a la hora (10¹³ es mayor que cualquier marca de tiempo en ms) y, dentro de una prioridad, se conserva FIFO. El valor máximo (~1,2·10¹³) es exacto como número de doble precisión (límite 2⁵³ ≈ 9·10¹⁵). |
| **Alternativas** | *Dos listas* (una por prioridad): obliga a vaciar una antes de la otra y a coordinar dos extracciones, que ya no serían atómicas. *Ordenar en MongoDB* en cada llamada: más lento y no atómico respecto de la asignación. |

### D-02 · Asignación atómica con `ZPOPMIN`

| | |
|---|---|
| **Decisión** | El siguiente turno se obtiene con `ZPOPMIN`, que quita y devuelve el primero en un solo paso. |
| **Por qué** | Redis ejecuta los comandos uno por uno: dos ventanillas que llamen casi a la vez nunca reciben el mismo turno. Es el núcleo del criterio «turnos duplicados = 0». |
| **Evidencia** | `docs/evidencia/concurrencia.md`: 259 asignaciones, 0 duplicados. |
| **Alternativa** | *Leer el primero y luego quitarlo* (`ZRANGE` + `ZREM`): entre ambos pasos otra ventanilla puede leer el mismo turno. La prueba formal incluye una versión así para comprobar que se detectaría. |

### D-03 · Una ventanilla atiende un turno a la vez, con reserva `SET NX`

| | |
|---|---|
| **Contexto** | Una prueba con dos clics simultáneos en V-01 asignó dos turnos distintos a la misma ventanilla y el panel solo veía uno: no era un duplicado, sino una regla de negocio ausente. |
| **Decisión** | Antes de extraer un turno se reserva la ventanilla con `SET clave "__asignando__" NX EX 10`. Si ya está ocupada, la llamada se rechaza con 409 y no se extrae nada. La reserva se reemplaza por el código del turno solo cuando MongoDB confirma el cambio de estado, y expira sola a los 10 s si el proceso muere. Además se consulta MongoDB: un turno `llamado` o `en_atencion` ocupa la ventanilla aunque Redis haya perdido la clave. |
| **Alternativas** | *Script Lua* que haga «si está libre, sacar y asignar» en un paso: más compacto, pero requiere permiso para `EVAL` en un Redis compartido que no administramos (un bloqueo rompería la demostración) y librerías extra para probarlo. *Solo la comprobación en MongoDB*: no cubre dos clics simultáneos. |
| **Consecuencia** | Si el proceso muere justo después de extraer el turno y antes de que MongoDB lo confirme, el turno queda fuera de la cola con el documento aún `pendiente`; la rehidratación (HU-012) lo recupera. |

### D-04 · Estado temporal del turno llamado: Hash con TTL, sin notificaciones de expiración

| | |
|---|---|
| **Decisión** | Al llamar a un turno se crea `grupo2:qline:turno:{codigo}` (Hash) con TTL de 180 s, junto con la clave de la ventanilla, en una transacción `MULTI/EXEC`. Se elimina cuando el cliente se presenta (inicia la atención) o el turno termina. |
| **Por qué** | Da la tercera estructura de Redis (TT-011) y un estado que caduca solo. |
| **Cómo se detecta el abandono** | Redis no avisa cuando una clave expira salvo que se active `notify-keyspace-events`, lo que exige `CONFIG SET`, que la cuenta del curso no tiene. Un turno `llamado` es candidato a abandono cuando `timestamps.llamado + 180 s` ya pasó **y** el Hash ya no existe; la decisión se apoya en MongoDB, porque el Hash también desaparecería si se perdiera Redis. La transición debe ser idempotente (`update_one` con filtro de estado) para que varios procesos no choquen. |
| **Alternativas** | *Notificaciones de expiración*: no disponibles. *Solo el tiempo en MongoDB* sin Hash: no usaría la tercera estructura ni daría la cuenta regresiva al cliente. *Sorted Set de vencimientos*: introduce una clave nueva fuera del contrato (sección 26 del plan). |

### D-05 · Eventos con Redis Pub/Sub y WebSocket, con consulta periódica de respaldo

| | |
|---|---|
| **Decisión** | Cada transición publica un evento JSON en `grupo2:qline:eventos` después de que MongoDB confirma. Un hilo por proceso se suscribe y reparte los mensajes por WebSocket. Si el WebSocket no abre o se corta, la página consulta su API JSON cada 3 s; además hay una consulta de seguridad cada 30 s. |
| **Por qué** | Pub/Sub ya está en el contrato de Redis y funciona con varios procesos de la app (cada uno tiene su suscriptor). El respaldo garantiza «actualización automática sin recargar» aunque falle el WebSocket (por ejemplo, un servidor sin el módulo de proxy). |
| **La publicación es de mejor esfuerzo** | Si Redis no puede publicar, la operación de negocio ya hecha no se rompe ni se deshace: MongoDB es la fuente de verdad. |
| **Alternativas** | *Server-Sent Events*: más simple, pero con proxies que almacenan la respuesta en búfer es poco fiable. *Solo consulta periódica*: no es instantánea y multiplica las consultas. |

### D-06 · El WebSocket por Apache necesita una regla explícita

| | |
|---|---|
| **Hallazgo** | `scripts/probar_websocket.py` (directo a la app) daba `Todo OK`, pero `/ws-prueba` (por Apache) fallaba desde el primer paso: el `.htaccess` reenviaba solo por `http://`. |
| **Decisión** | Agregar, antes de las reglas HTTP: `RewriteCond %{HTTP:Upgrade} =websocket [NC]` y `RewriteRule ^(.*)$ ws://127.0.0.1:18002/$1 [P,L]`. Funcionó sin permisos de administrador y sin tocar el resto del sitio. |
| **Cómo se diagnosticó** | Dos comprobaciones separadas (la app sin proxy y la página a través del proxy) permiten saber de quién es el problema. Se conservan como `scripts/probar_websocket.py` y `/ws-prueba`. |

### D-07 · La consulta por QR recibe señales anónimas, no eventos

| | |
|---|---|
| **Decisión** | El WebSocket de la consulta por QR (`/ws/turno/qr/{uuid}`) envía solo `{"tipo": "actualizar"}` ante **cualquier** evento, sin código ni datos de otros turnos; la página vuelve a consultar su propio estado. |
| **Por qué** | La posición en la fila de un cliente cambia cuando se llama a **otros** turnos, así que debe enterarse de cualquier cambio, pero no debe conocer los códigos ajenos. |
| **Alternativa** | Reenviar los eventos filtrados por código: el cliente no se enteraría de que su posición mejoró. Reenviar todos los eventos: filtra códigos ajenos. |

### D-08 · Consulta por QR de solo lectura, que reutiliza HU-002

| | |
|---|---|
| **Decisión** | `consultar_por_token` valida un UUID v4, busca el turno por `qr_token` y delega el estado y la posición en `consultar_turno` (HU-002). Distingue UUID inválido (400), inexistente (404) y MongoDB caído (503); una falla de Redis no es un error: se muestra el estado de MongoDB con un aviso. No devuelve el token ni el `_id`. |
| **Por qué** | Una sola semántica de consulta (lo pide el plan) y ninguna filtración del identificador. |
| **Alternativa** | Una consulta propia para el QR: duplicaría la lógica y podría diverger de HU-002. |

### D-09 · Sin cambios de esquema por `qr_token`

| | |
|---|---|
| **Decisión** | La consulta por QR no modifica el esquema ni los índices. El esquema de `turnos` admite campos adicionales, por lo que `qr_token` pasa sin tocarlo; la búsqueda funciona sin índice. El índice único parcial y la validación del formato son de Carlos y exigen acuerdo del equipo (sección 26). *Actualización de S3: ese acuerdo se dio; Carlos añadió el campo, su validación y el índice parcial único (D-13).* |
| **Por qué** | El usuario del curso no puede ejecutar `collMod`, y recrear la colección (`--recrear`) borra datos: el plan no autoriza usarlo para esto. |

### D-10 · Redis falla rápido

| | |
|---|---|
| **Decisión** | El cliente de Redis se configura sin reintentos (`Retry(NoBackoff(), 0)`) y, en una petición, tras el primer fallo no se vuelve a consultar Redis. |
| **Por qué** | Redis corre en la misma máquina: reintentar no aporta nada y retrasa la respuesta. Medido en un entorno donde la conexión rechazada tarda unos 2 s, los reintentos por defecto llevaban una petición a unos 26 s. Sin reintentos, cada ruta responde «Redis no disponible» enseguida. |
| **Alternativa** | Mantener los reintentos del cliente: útiles contra una red inestable, que aquí no existe. |

### D-11 · Pruebas de concurrencia y de rendimiento que no se pueden «aprobar» sin ejecutarse

| | |
|---|---|
| **Decisión** | `scripts/prueba_concurrencia.py`, `scripts/medir_rendimiento.py` y `scripts/probar_fallos_redis.py` generan sus propios informes en `docs/evidencia/` con los resultados de **esa ejecución**; si no corren, no hay informe. Incluyen pruebas de que detectan fallos (por ejemplo, una extracción no atómica produce duplicados). |
| **Por qué** | El plan prohíbe declarar pruebas aprobadas o rendimientos sin ejecutarlos. Las cifras de S1 (Redis < 2 ms, más de 85 % de mejora) son hipótesis: el informe de rendimiento las contrasta y dice si se cumplen o no. |
| **Resultado** | Medido en el servidor: Redis 0,108 a 0,135 ms (la primera hipótesis se cumple) y mejora del 63,7 % al 72,7 % frente a MongoDB (**la segunda no se cumple**, quedó por debajo del 85 %). El proyecto reporta los valores medidos y no los de S1. Ver `docs/evidencia/rendimiento.md`. |

---

## MongoDB e historial (Carlos)

### D-12 · Validación con $jsonSchema a nivel de motor y espejo en Python

| | |
|---|---|
| **Decisión** | Se definió un esquema `$jsonSchema` estricto en MongoDB (`turnos_schema.py`) con `validationLevel: strict` y `validationAction: error`, respaldado por un validador en memoria en Python (`validar_documento_turno`) para validación previa en tests y scripts. |
| **Por qué** | Garantiza la integridad del modelo de datos como fuente de verdad duradera: ningún script, inserción directa o error de aplicación puede guardar estados desconocidos, ventanillas inexistentes o timestamps con tipos incompatibles. |
| **Alternativas** | *Validar únicamente en la aplicación*: deja el motor desprotegido ante scripts de migración, consola `mongosh` o accesos concurrentes. *Dejar MongoDB totalmente schemaless*: facilita corrupción de datos a largo plazo. |

### D-13 · Índice parcial único para `qr_token` sin migración destructiva

| | |
|---|---|
| **Contexto** | S3 introduce la consulta por QR móvil (HU-003 / HU-013) con un token UUID v4 en MongoDB. Existen más de 500 registros previos en la base de datos sin este campo. Un índice único estándar fallaría por claves duplicadas (nulas). |
| **Decisión** | Definir `idx_turnos_qr_token_unico` con `unique: True` y `partialFilterExpression: {"qr_token": {"$exists": True, "$type": "string"}}`. |
| **Por qué** | Garantiza unicidad estricta para todos los turnos que poseen QR, mientras que los turnos antiguos o sin token no son indexados ni colisionan. Permite una evolución de esquema 100 % no destructiva, sin requerir `--recrear` ni borrar datos del servidor compartido (respetando la regla de la sección 26 del plan). |
| **Alternativas** | *Índice sparse simple*: en MongoDB un índice `sparse` con campos nulos explícitos puede generar colisiones en unicidad. *Poblar UUIDs ficticios en documentos viejos*: alteraría la auditoría histórica de S2 sin necesidad. |
| **Resultado de la integración** | Al medirlo en el servidor, `find({"qr_token": t})` hacía `COLLSCAN`: MongoDB solo usa un índice parcial si la consulta repite su condición. La aplicación (`consulta_qr.filtro_por_token`) y la medición usan ahora `{"qr_token": {"$eq": t, "$type": "string"}}`, y la repetición en el servidor dio `IXSCAN` con 1 documento examinado de 555. |

### D-14 · Cálculo de KPIs y SLA en el motor mediante Aggregation Pipelines

| | |
|---|---|
| **Decisión** | Los indicadores operacionales del Dashboard (conteo por estados, tiempos promedio de espera y porcentaje de cumplimiento SLA) se calculan en MongoDB mediante Aggregation Pipelines (`$match -> $group` con `$avg`, `$cond`), no en bucles Python. |
| **Por qué** | Evita transferir miles de documentos por la red hacia el proceso web. El motor ejecuta los cálculos en C++ optimizado y devuelve únicamente el resumen agregado, logrando respuestas en menos de 0.5 ms. |
| **Alternativas** | *Calcular en Python en cada petición*: descargar todos los registros genera saturación de memoria RAM y latencia proporcional al volumen histórico (O(N) en red). |

### D-15 · Exportación completa de historial filtrado en JSON

| | |
|---|---|
| **Decisión** | `/api/historial/descargar` exporta todos los documentos que cumplen los filtros seleccionados (`limite=0`), entregando un archivo descargable con cabecera `Content-Disposition: attachment; filename="historial_turnos_<timestamp>.json"`. |
| **Por qué** | El visor web pagina a 100 registros para ergonomía visual, pero una auditoría analítica requiere descargar la totalidad de los datos filtrados en un solo archivo estructurado con metadatos de auditoría (`fecha_exportacion`, `total_exportados`, `filtros_aplicados`). |
| **Alternativas** | *Descargar solo la página visible (100 registros)*: incompleto para supervisores que auditan días completos. *Exportar a CSV*: el alcance acordado en el plan especificó JSON sin introducir dependencias de formateo CSV. |


## Ciclo de atención y recuperación (Abigail)

> Diseño de los módulos de Abigail; la integración y los módulos de soporte los implementó Alessandro con asistencia de Claude Code (ver la nota de autoría en `docs/seguimientos/S3.md`, sección 5).

### D-16 · El abandono lo decide un barrido sobre MongoDB y el Hash, no un aviso de Redis

| | |
|---|---|
| **Decisión** | Un barrido periódico busca los turnos `llamado` con `timestamps.llamado ≤ ahora − 180 s` y abandona los que ya no tienen su Hash `grupo2:qline:turno:{codigo}`. `timestamps.abandonado` se registra como `llamado + 180 s` (el instante en que venció el plazo), no como la hora en que corrió el barrido. |
| **Por qué** | Redis no avisa cuando una clave expira (D-04). Pedir las dos condiciones evita abandonar por error: el plazo vencido por reloj no basta si el Hash sigue vivo (el cliente confirmó presencia), y la ausencia del Hash no basta si el plazo no venció (Redis pudo perder datos). Si Redis no responde, no se abandona: no se sabe si venció de verdad. |
| **Alternativas** | *Notificaciones de expiración de Redis*: requieren `CONFIG SET`, no disponible. *Índice TTL de MongoDB*: borra documentos, y aquí el turno debe conservarse para el historial. *Un temporizador por turno en memoria*: se pierde al reiniciar la aplicación y no funciona con varios procesos. |
| **Resultado** | Verificado en el servidor: `A-001` llamado a las 23:31:23,881 y abandonado con `abandonado = 23:34:23,881`. |

### D-17 · El abandono es idempotente por una condición en el `update_one`

| | |
|---|---|
| **Decisión** | La transición es `update_one({codigo, estado: "llamado"}) → abandonado`. Si el turno ya cambió (inició atención, otro proceso lo abandonó), no se modifica nada y se informa como `ya_cambiados`. Liberar la ventanilla solo ocurre si la clave sigue apuntando a ese turno; publicar el evento ocurre después de confirmar MongoDB y es de mejor esfuerzo. |
| **Por qué** | Permite repetir el barrido, ejecutarlo en varios procesos a la vez y reintentar tras un fallo sin duplicar ni deshacer nada. Se probó con 4 barridos simultáneos sobre 20 turnos: 20 abandonados, 20 únicos, 20 eventos. |
| **Alternativas** | *Lua o transacción entre MongoDB y Redis*: no existen transacciones entre ambos y no se verificó `EVAL` en el Redis compartido. *Revertir MongoDB si Redis falla*: dejaría un turno llamado sin Hash que el siguiente barrido volvería a procesar. |

### D-18 · Un barrido por proceso de la aplicación, sin candado distribuido

| | |
|---|---|
| **Decisión** | El barrido corre en un hilo daemon que se inicia y detiene con la aplicación (`_lifespan`), cada 10 s (`BARRIDO_INTERVALO_SEG`) y se apaga con `BARRIDO_ABANDONO=0`. Con varios *workers* de Gunicorn habrá uno por worker. Las pruebas lo apagan por defecto. |
| **Por qué** | Es seguro gracias a D-17 y evita depender de un candado en Redis o de un proceso aparte. Un fallo de una pasada (MongoDB caído) se cuenta y la siguiente reintenta. La ventanilla única bloquea una ventanilla hasta que su turno se resuelve, por lo que el barrido es crítico para que no queden ventanillas retenidas. |
| **Alternativas** | *Cron que ejecute el script*: no corre a menos de 1 minuto y se desacopla de la aplicación. *Candado `SET NX` para un solo barrido*: más piezas para ahorrar trabajo que ya es barato (consulta indexada). |
| **Índice** | `idx_turnos_estado_llamado` `{estado, timestamps.llamado}` para la consulta del barrido. |

### D-19 · La recuperación es una reconciliación, no un vaciado

| | |
|---|---|
| **Decisión** | `reconciliar_cola` compara los pendientes de MongoDB con la cola de Redis y agrega solo los que faltan, con el mismo puntaje que la emisión (calculado con enteros, sin errores de coma flotante). Solo se recuperan `pendiente`. Lo que sobra se informa y solo se quita con `--quitar-sobrantes`. El contador de códigos solo sube. Sin `--aplicar` muestra el plan. Los pendientes con datos inválidos se informan y no se encolan. |
| **Por qué** | Sirve igual para una pérdida total, una parcial y el caso abierto de S2 (turno extraído cuyo cambio no llegó a MongoDB). Repetirla no cambia nada. Bajar el contador repetiría códigos ya emitidos. |
| **Alternativas** | *Vaciar y reconstruir toda la cola*: dejaría la cola vacía unos instantes y está prohibido `FLUSHALL`/`FLUSHDB`. *Reencolar también los llamados vencidos*: los cubre el barrido. |
| **Resultado** | Verificado en el servidor: 12 pendientes recuperados en 0,0028 s, mismo orden, sin duplicados; contador restaurado de 0 a 20 (clave aislada). |

### D-20 · La rehidratación no es atómica con las llamadas

| | |
|---|---|
| **Decisión** | No se usa Lua ni bloqueo entre `rehidratar_cola` y `/api/llamar`. Se documenta que conviene ejecutarla con la atención detenida. |
| **Por qué** | Si un turno se llama justo mientras se reencola, queda un código obsoleto en la cola; el siguiente llamado lo rechaza con el aviso de inconsistencia que ya existe y no se duplica ni se pierde ninguna atención. La rehidratación es un procedimiento de recuperación, poco frecuente. |
| **Alternativas** | *Script Lua atómico*: `EVAL` no verificado en el Redis compartido. *Bloquear las llamadas durante la recuperación*: añadiría estado compartido nuevo. |

### D-21 · Las pruebas usan datos y claves propios, y un reloj adelantado

| | |
|---|---|
| **Decisión** | Las pruebas de recuperación, mediciones y fallos usan series propias (`R-*`, `M-*`, `F-*`), cola, contador, eventos y ventanillas aislados (`grupo2:qline:prueba:*`) y un reloj de prueba adelantado 6 minutos. «Caído» significa un cliente a un puerto sin servidor o una colección que lanza error; no se detiene ningún servicio. |
| **Por qué** | Corren en el servidor compartido sin tocar turnos reales ni mostrar eventos de prueba al público. El reloj adelantado se agregó tras un incidente: el barrido automático de la aplicación abandonó, muy probablemente, parte de los turnos de prueba (vencidos a propósito) y una medición salió 4/5. Con el reloj adelantado esos turnos no vencen para el reloj real. |
| **Alternativas** | *Datos simulados en memoria para la evidencia*: no probarían el servidor real (por eso se eliminó el modo `--simulado` de los scripts). *Apagar el barrido de la aplicación durante la medición*: requeriría reiniciar el servicio compartido. |
| **Resultado** | Tras el cambio, 45 de 45 ejecuciones de medición correctas y 18 de 18 casos de fallo, en el servidor. |

---

## Cliente (Aaron)

*Pendiente de completar por el integrante.*

---

## Despliegue e integración (equipo)

### D-22 · El seguimiento del turno por QR no pide contraseña de Apache; el resto sí

| | |
|---|---|
| **Hallazgo** | En la demo, al abrir el enlace del QR en un celular, el navegador pedía usuario y contraseña una y otra vez. El `.htaccess` ponía `AuthType Basic` (`Require valid-user`) a **toda** la aplicación, también a la página del turno y a lo que ella consulta sola (consulta cada 3 s y WebSocket). Los navegadores del celular, y el visor de la cámara, no siempre reenvían las credenciales guardadas. |
| **Decisión** | `.htaccess` deja pasar sin contraseña solo tres rutas, siempre con un UUID de 36 caracteres al final: `/turno/qr/{uuid}` (página), `/api/turnos/qr/{uuid}` (consulta) y `/ws/turno/qr/{uuid}` (WebSocket), además de `/static/` (CSS). Se hace con `SetEnvIf Request_URI ... ACCESO_PUBLICO` y `<RequireAny> Require valid-user / Require env ACCESO_PUBLICO`. Todo lo demás sigue exigiendo usuario y contraseña. |
| **Por qué** | El contrato de HU-003 y HU-013 exige que el enlace del QR se abra desde cualquier celular; un cliente real no puede tener una cuenta de Apache. El UUID v4 es imposible de adivinar y esas rutas son de solo lectura y no exponen datos personales. |
| **Qué sigue protegido** | Quiosco, panel, cola, historial, dashboard, descargas JSON, `/api/llamados`, `/ws/eventos`, la pantalla de sala y el administrador de MongoDB (`/insertar`, `/eliminar`, `/crear_coleccion`). `tests/test_htaccess.py` lo comprueba con más de 20 direcciones. |
| **Alternativas** | *Dejar la protección en todo*: el cliente necesitaría credenciales. *Quitarla en todo*: expondría el administrador de MongoDB, que puede crear y borrar colecciones. *Reintentar menos el WebSocket desde la página*: reduce los avisos pero la página seguiría pidiendo contraseña. *Dejar pública la pantalla de sala y el quiosco*: son dispositivos fijos que se identifican una sola vez; el quiosco, además, emite turnos. |
| **Riesgo** | La cuenta del curso protege el sitio con ese `.htpasswd`; esta decisión relaja esa protección solo para las rutas del cliente y debe estar acordada con el equipo (y, si aplica, con el profesor). La regla `/static/` es pública en cualquier lugar de la ruta. Requiere Apache 2.4 y que el hosting permita `AllowOverride` de autenticación y `FileInfo`; si no, el sitio puede responder 500 y se restaura el `.htaccess` anterior. |
| **Estado** | Aplicado y **verificado en el servidor con un celular el 27/10/2026**: el enlace del QR abre sin usuario ni contraseña y el resto del sitio sigue protegido. |

### D-23 · Las fechas se guardan y se entregan en UTC; las pantallas las muestran en hora local

| | |
|---|---|
| **Hallazgo** | Varias pantallas mostraban la fecha tal como sale de la base de datos (`2026-10-27T01:12:49.757000`): sin zona horaria, con microsegundos y en UTC, lo que además se leía seis horas adelantado frente a la hora real de la sala. |
| **Decisión** | MongoDB, las APIs y las descargas JSON conservan ISO 8601 en UTC y ahora con la zona explícita y milisegundos (`2026-10-27T01:12:49.757Z`). `app/formato.py` ofrece los filtros `fecha`, `hora`, `fecha_hora` e `iso_utc` para las plantillas: las pantallas muestran `26/10/2026` y `19:12:49` en la zona de la variable `ZONA_HORARIA` (por defecto `America/Costa_Rica`). El valor exacto en UTC queda en el detalle (`title`) y en `<time datetime>`. |
| **Por qué** | Los datos deben ser inequívocos para otras máquinas (UTC con zona), y las personas deben leer la hora de su reloj. Separar ambos evita errores de conversión y deja la zona como un ajuste de despliegue. |
| **Alternativas** | *Guardar la hora local en MongoDB*: ambigua en los cambios de horario y entre zonas. *Convertir en el navegador*: la hora dependería del dispositivo (cada celular vería la suya) y las tablas no se podrían probar. *Dejar el ISO en pantalla*: lo que se corrigió. |
| **Alcance** | Historial, ticket y confirmación del quiosco; los relojes de la pantalla de sala y de la página del QR usan 24 horas. No cambian las descargas, las APIs ni los informes de `docs/evidencia/` (que indican UTC). El editor JSON del administrador de MongoDB mantiene el formato extendido, que debe poder editarse y guardarse. Si el servidor no tiene la base de zonas horarias, se muestra UTC (`tzdata` está en `requirements.txt`). |
