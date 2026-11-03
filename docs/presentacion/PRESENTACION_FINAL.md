# QLine · Presentación Final del Proyecto (TT-025)

**Documento oficial de apoyo a la exposición y defensa técnica · Seguimiento 4 (S4)**  
**Archivo editable complementario:** [`QLine_Presentacion_Final.pptx`](QLine_Presentacion_Final.pptx)  
**Curso:** Tópicos Avanzados de Bases de Datos · Universidad Nacional (UNA)  
**Equipo:** Query Logic (Grupo 2)  
**Integrantes:**
- Aaron Benavides Vega (`abenavides`)
- Abigail Urbina Gómez (`aurbina`)
- Alessandro Cambronero Delgado (`acambronero`)
- Carlos Espinoza Pérez (`cespinoza`)

---

## Diapositiva 1 · Portada e Identidad del Proyecto

### Contenido en Pantalla
- **Título:** QLine: Sistema Inteligente de Gestión de Filas y Turnos en Tiempo Real
- **Lema del Sistema:** *«MongoDB conserva lo que ocurrió. Redis controla lo que ocurre ahora.»*
- **Contexto:** Entrega Final · Seguimiento 4 (S4) · Release Candidate v0.9.0-rc
- **Stack Base:** Python 3.12 · FastAPI · Redis 7 (Sorted Sets, Hashes, Pub/Sub) · MongoDB 7 ($jsonSchema, Índices Parciales, Aggregations) · Jinja2 · Vanilla CSS

### Notas del Presentador (Guion de Exposición)
> *"Buenos días profesor y compañeros. Hoy les presentamos QLine, un sistema de gestión de colas y turnos diseñado bajo el principio fundamental de desacoplamiento operacional entre motores de bases de datos. En las instituciones y servicios con alta demanda de atención presencial, los sistemas convencionales colapsan por dos razones: o saturan la base de datos relacional con bloqueos y lecturas concurrentes para saber quién sigue, o carecen de trazabilidad histórica cuando el sistema falla. En QLine resolvemos este dilema separando responsabilidades: Redis es el árbitro estricto en memoria de lo que ocurre en este milisegundo, mientras que MongoDB es la fuente inmutable de auditoría histórica que preserva todo lo que ocurrió."*

---

## Diapositiva 2 · Introducción y Problema Abordado

### Contenido en Pantalla
- **El reto de las salas de espera tradicionales:**
  - Filas físicas densas, aglomeración en ventanillas e incertidumbre del usuario sobre su tiempo de atención.
  - Dependencia de pantallas fijas que obligan al cliente a permanecer inmóvil en la sala.
- **El desafío de la concurrencia en ventanillas:**
  - Rondas simultáneas donde múltiples operadores intentan extraer el siguiente turno a la vez.
  - Riesgo de turnos duplicados (dos ventanillas llamando a la misma persona).
- **El desafío de la resiliencia y el estado transitorio:**
  - Si un motor en memoria se reinicia o pierde energía, la cola no puede quedar vacía ni reiniciarse arbitrariamente repitiendo códigos.

### Notas del Presentador
> *"En los trámites de atención al público, un cliente insatisfecho suele ser producto de la falta de información. Tradicionalmente, la persona no sabe cuántos turnos tiene por delante ni cuándo debe levantarse. Desde la perspectiva de software, el reto es aún mayor: cuando diez operadores en ventanillas distintas hacen clic en 'Llamar siguiente' al mismo tiempo, una base de datos mal gestionada corre el riesgo de emitir turnos duplicados o bloquear la tabla completa. QLine aborda estos tres problemas de raíz: movilidad con seguimiento en tiempo real mediante QR, asignación atómica concurrente sin duplicados y un protocolo de reconciliación ante caídas."*

---

## Diapositiva 3 · Objetivos y Alcance Técnico

### Contenido en Pantalla
- **Objetivo General:** Desarrollar un sistema de turnos de alta velocidad, seguro y auditable mediante la integración complementaria de Redis y MongoDB.
- **Alcance Aprobado (Contratos Oficiales):**
  - **Servicio único:** `Atención General` (`servicio_id: atencion_general`).
  - **Dos prioridades oficiales:** `preferencial` (score de prioridad 0) y `normal` (score de prioridad 1).
  - **Tres ventanillas operativas base:** `V-01`, `V-02`, `V-03`.
  - **Cinco estados oficiales inmutables:** `pendiente` → `llamado` → `en_atencion` → `atendido` / `abandonado`.
  - **Ventana de llamado estricta:** 180 segundos de TTL para que el cliente se presente en ventanilla.
- **Exclusiones deliberadas del alcance:**
  - Sin predicción algorítmica de tiempo de espera (descartada en Plan Maestro por falta de muestra probabilística).
  - Sin exportación a CSV (se acordó entrega analítica exclusivamente en JSON estructurado).
  - Sin esquemas multisucursal ni autenticación compleja innecesaria para el cliente.

### Notas del Presentador
> *"Para garantizar el éxito de un proyecto de ingeniería es fundamental definir las fronteras. En QLine nos ceñimos rigurosamente a los contratos del Plan Maestro: tenemos un servicio único de Atención General, dos prioridades bien tipificadas, tres ventanillas y exactamente cinco estados de ciclo de vida. Excluimos deliberadamente promesas artificiales como algoritmos de predicción de tiempo de espera sin respaldo estadístico, y nos concentramos en lo que verdaderamente aporta valor: precisión, resiliencia y velocidad comprobable."*

---

## Diapositiva 4 · Arquitectura del Sistema

### Contenido en Pantalla
- **Capa Web y Presentación:**
  - FastAPI sobre Python 3.12 con soporte asíncrono para WebSockets y rutas HTTP REST.
  - Jinja2 para renderizado server-side rápido y seguro; Vanilla CSS con arquitectura Fintech sólida.
- **Capa en Memoria (Redis 7):**
  - Cola activa ordenada (Sorted Set), reservas de ventanilla (`SET NX`), ventana de espera (Hashes con TTL) y eventos (`Pub/Sub`).
- **Capa Persistente Documental (MongoDB 7):**
  - Colección `turnos` con validación `$jsonSchema`, índices compuestos y parciales, y aggregation pipelines.
- **Control Perimetral (Servidor Apache / .htaccess):**
  - Autenticación básica para módulos internos; paso libre exclusivo para las tres rutas del QR móvil (`/turno/qr/{uuid}`) y CSS estático.

### Notas del Presentador
> *"La arquitectura de QLine es asimétrica y desacoplada. Los navegadores de quiosco, pantalla pública, panel de operador y los teléfonos de los clientes se comunican con FastAPI. Cuando un evento ocurre, FastAPI no consulta a MongoDB para encolar o desencolar: delega esa tarea inmediata a Redis. Una vez que la operación atómica concluye en Redis, se persiste la verdad documental en MongoDB y se emite un mensaje Pub/Sub. Los WebSockets escuchan este canal y propagan la actualización al instante a las pantallas de sala y a los teléfonos celulares de los usuarios."*

---

## Diapositiva 5 · Responsabilidades de Redis

### Contenido en Pantalla
- **Cola atómica con prioridades:** Sorted Set `grupo2:qline:cola:atencion_general`.
- **Extracción atómica sin duplicados:** Comando nativo `ZPOPMIN`, garantizando *cero turnos duplicados*.
- **Ventanilla única concurrente:** Reserva temporal con `SET grupo2:qline:ventanilla:{id} "__asignando__" NX EX 10` que impide que dos solicitudes simultáneas atiendan en la misma ventanilla.
- **Estado de llamado temporal:** Hash `grupo2:qline:turno:{codigo}` con expiración a los 180 segundos (`MULTI/EXEC`), gobernando la cuenta regresiva del usuario.
- **Bus de eventos en tiempo real:** Canal Pub/Sub `grupo2:qline:eventos` para entrega instantánea a receptores WebSocket.

### Notas del Presentador
> *"Redis no es una base de datos secundaria en QLine: es el motor de concurrencia. Al utilizar un Sorted Set, la extracción del siguiente turno se hace con un único comando ZPOPMIN, que es atómico por naturaleza de hilo único en Redis. Además, resolvemos un problema clásico de concurrencia: el doble clic en la ventanilla. Antes de extraer un turno, reservamos la ventanilla mediante SET NX con un TTL de 10 segundos. Si otro hilo intenta llamar mientras la ventanilla está ocupada, se rechaza inmediatamente con código 409 Conflict sin alterar la cola."*

---

## Diapositiva 6 · Responsabilidades de MongoDB

### Contenido en Pantalla
- **Almacén documental inmutable:** Persistencia durable de los turnos en la colección `turnos` con marcas de tiempo en UTC e ISO 8601.
- **Integridad estructural ($jsonSchema):** Validación en motor (`turnos_schema.py`) en nivel estricto (`validationLevel: strict`, `validationAction: error`) que impide inserciones arbitrarias.
- **Evolución sin destrucción:** Índice parcial único `idx_turnos_qr_token_unico` sobre `qr_token` con filtro `{$exists: true, $type: "string"}`, permitiendo convivir con registros antiguos sin borrar la base de datos.
- **Optimización de consultas:**
  - `idx_turnos_codigo_unico` para búsquedas directas.
  - `idx_turnos_estado_creado` para consultas del historial sin ordenar en memoria RAM.
  - `idx_turnos_estado_llamado` para acelerar el barrido periódico de abandono.
- **Analítica en motor:** Aggregation Pipelines (`$match` → `$group`) para el cálculo de KPIs y SLA en menos de 2 ms.

### Notas del Presentador
> *"Mientras Redis vive en memoria volátil, MongoDB es el guardián de la historia. Diseñamos un esquema $jsonSchema estricto que protege la base de datos incluso ante scripts manuales de consola. Un logro clave de la ingeniería de S3 y S4 fue la incorporación del token QR: en lugar de borrar la base de datos con comandos destructivos para agregar un índice único, creamos un índice parcial único. Así, cientos de documentos antiguos sin QR coexisten pacíficamente con los nuevos turnos que sí lo tienen, garantizando búsquedas IXSCAN con 1 solo documento examinado."*

---

## Diapositiva 7 · Gestión de Cola y Prioridades

### Contenido en Pantalla
- **Fórmula de cálculo del Score en Redis:**
  $$\text{Score} = \text{Nivel Prioridad} \times 10^{13} + \text{Hora de Llegada (ms)}$$
- **Valores del nivel:**
  - `preferencial` $\rightarrow$ Nivel 0 ($\text{Score} \approx 0 + \text{ms} \approx 1.7 \times 10^{12}$)
  - `normal` $\rightarrow$ Nivel 1 ($\text{Score} \approx 10^{13} + \text{ms} \approx 1.17 \times 10^{13}$)
- **Propiedades del algoritmo:**
  - **Dominancia estricta:** Cualquier turno preferencial siempre tiene un score inferior al de un turno normal, sin importar a qué hora llegó.
  - **FIFO interno:** Entre dos turnos de igual prioridad, el desempate lo decide la marca de tiempo en milisegundos.
  - **Seguridad aritmética:** El valor máximo ($\approx 1.2 \times 10^{13}$) se encuentra muy por debajo del límite de precisión entera exacta de 64 bits y del límite IEEE 754 ($2^{53} \approx 9 \times 10^{15}$).

### Notas del Presentador
> *"Una pregunta frecuente es: ¿por qué no usar dos listas separadas en Redis, una para normales y otra para preferenciales? La respuesta es atomicidad. Con dos listas, un operador tendría que consultar si la preferencial tiene elementos, y si está vacía, consultar la normal. En ese lapso de dos comandos, otro operador podría interferir. Al unificar ambas en un solo Sorted Set mediante una fórmula aritmética ponderada por diez a la trece, un único comando ZPOPMIN extrae siempre al cliente preferencial más antiguo, o en su defecto, al normal más antiguo, de forma 100 % atómica."*

---

## Diapositiva 8 · Flujo de Quiosco, Ticket y QR Móvil

### Contenido en Pantalla
- **Quiosco de autoservicio (`/quiosco`):**
  - Interfaz táctil de autoservicio para emisión en dos toques (Atención Regular vs Atención Preferencial).
  - Cero fricción: no solicita identificación ni datos privados.
- **Ticket impreso y digital (`quiosco_confirmado.html`):**
  - Muestra código de turno en fuente grande, prioridad, fecha/hora local y código QR en SVG inline de alta definición.
  - **S4-M02:** Botón «Imprimir ticket» con estilos `@media print` y suspensión del temporizador de retorno de 25 s para no cerrar la pantalla durante la impresión.
- **Seguimiento móvil (`/turno/qr/{uuid}`):**
  - Visualización del estado en vivo, turnos por delante y cuenta regresiva si el turno fue llamado.
  - **P01 / P05:** Instrucciones claras que garantizan que el turno no se cancela al salir de la pantalla, y aviso explícito al finalizar: *«Su atención finalizó. Puede cerrar esta pestaña.»*

### Notas del Presentador
> *"En Seguimiento 4 perfeccionamos la experiencia del usuario. En el quiosco, tras emitir el turno, el usuario puede imprimir su ticket físico o escanear el código QR con su propio teléfono móvil. Gracias a la tarea S4-M02, el botón de imprimir no solo aplica un CSS de impresión limpio y de alto contraste, sino que además pausa el temporizador de retorno automático de 25 segundos del quiosco mediante los eventos beforeprint y afterprint. En su celular, el cliente ve cuántos turnos tiene por delante y recibe la instrucción clara de P05: puede guardar la página con tranquilidad, ya que cerrarla no cancela su turno."*

---

## Diapositiva 9 · Flujo del Operador y Ventanilla

### Contenido en Pantalla
- **Panel de operador (`/panel`):**
  - Control de ventanillas asignadas (`V-01`, `V-02`, `V-03`).
- **Ciclo de vida del llamado:**
  1. **Llamar siguiente:** `POST /api/llamar` $\rightarrow$ Valida ventanilla libre $\rightarrow$ `ZPOPMIN` $\rightarrow$ Reserva `SET NX` $\rightarrow$ Actualiza MongoDB a `llamado` $\rightarrow$ Crea Hash con TTL 180 s $\rightarrow$ Publica evento Pub/Sub.
  2. **Iniciar atención:** El usuario se presenta en ventanilla; el operador hace clic en «Iniciar atención» $\rightarrow$ Turno pasa a `en_atencion` $\rightarrow$ Se elimina el Hash con TTL de Redis.
  3. **Finalizar atención:** Se concluye el trámite; el turno pasa a `atendido` $\rightarrow$ Se libera la ventanilla $\rightarrow$ El cliente recibe aviso de fin de atención en su celular.

### Notas del Presentador
> *"El panel de operador es la estación de trabajo de los funcionarios. Cuando la ventanilla está libre, el botón de llamar permite extraer al cliente que encabeza la fila. El turno queda temporalmente en estado 'llamado' durante 180 segundos. Si el usuario se presenta a tiempo, el operador presiona 'Iniciar atención', lo que congela el cronómetro y destruye el Hash temporal en Redis. Al terminar el servicio, se registra la conclusión en MongoDB y la ventanilla vuelve a quedar libre inmediatamente."*

---

## Diapositiva 10 · Concurrencia, TTL, Abandono y Recuperación

### Contenido en Pantalla
- **Detección de abandono (HU-008):**
  - Hilo daemon de barrido que corre periódicamente en la aplicación.
  - **Condición dual estricta:** El turno debe tener más de 180 s en MongoDB **y** el Hash en Redis debe haber desaparecido.
  - **Idempotencia:** `update_one({"codigo": codigo, "estado": "llamado"}) → "abandonado"`.
  - **Marca de tiempo justa:** Se registra `timestamps.abandonado = timestamps.llamado + 180 s`, evitando castigar al usuario por el retraso del barrido.
- **Reconciliación y recuperación de cola (HU-012):**
  - Procedimiento no destructivo `scripts/recuperacion.py`.
  - Compara turnos `pendiente` de MongoDB contra el Sorted Set de Redis y reinserta únicamente los faltantes, calculando su puntaje original sin tocar el resto de la base de datos.

### Notas del Presentador
> *"Uno de los mayores desafíos técnicos fue el manejo del abandono sin notificaciones automáticas de Redis, ya que no contábamos con privilegios CONFIG SET en el servidor universitario. Diseñamos un barrido dual: un turno solo se abandona si han pasado 180 segundos Y su Hash ya expiró en Redis. Si Redis se cayera, el Hash desaparecería pero el barrido no abandonará porque comprueba ambas fuentes. Y si el servidor de Redis tuviera que reiniciarse de emergencia, el script de recuperación HU-012 rehidrata la cola desde MongoDB en milisegundos, recalculando los scores exactos sin duplicar registros."*

---

## Diapositiva 11 · Dashboard Analítico y Reportes

### Contenido en Pantalla
- **Visor operacional en tiempo real (`/dashboard`):**
  - Métricas de flujo: turnos en espera, llamados, en atención, atendidos y abandonados.
  - Tiempos promedio calculados: tiempo de espera en sala y tiempo de atención efectiva.
  - Cumplimiento de SLA operacional con umbral configurable (por defecto 300 s).
- **Historial paginado y auditoría (`/historial`):**
  - Filtros multicriterio por estado, ventanilla, prioridad y fechas.
- **Exportación analítica en formato abierto:**
  - Descargas completas en JSON estructurado con metadatos de auditoría (`/api/historial/descargar` y `/api/dashboard/descargar`).

### Notas del Presentador
> *"El supervisor del sistema cuenta con un panel analítico optimizado. Todos los indicadores de tiempos promedio y cumplimiento de acuerdos de nivel de servicio (SLA) se resuelven directamente en el motor de MongoDB mediante Aggregation Pipelines con $match y $group. Esto permite que el cálculo sobre cientos de turnos tome menos de 2 milisegundos, sin saturar la memoria RAM del servidor web. Además, respetando las decisiones del equipo, el historial completo se puede exportar en un archivo JSON estructurado con cabecera de descarga."*

---

## Diapositiva 12 · Pruebas y Mediciones Reales

### Contenido en Pantalla
- **Resultados de la Suite Automatizada:**
  - Total pruebas: **513 tests** · Aprobadas: **512** · Omitidas: **1** (decodificación con librería externa ausente) · Fallidas: **0**.
- **Pruebas de Concurrencia Formal en Servidor (`concurrencia.md`):**
  - **259 asignaciones comprobadas** con 10 consumidores concurrentes $\rightarrow$ **0 turnos duplicados**.
- **Mediciones Empíricas de Rendimiento (`rendimiento.md`):**
  - **INCR (código):** Redis 0.108 ms vs Mongo 0.376 ms (mejora: **71.3 %**).
  - **ZADD (encolar):** Redis 0.126 ms vs Mongo 0.347 ms (mejora: **63.7 %**).
  - **ZPOPMIN (desencolar):** Redis 0.135 ms vs Mongo 0.493 ms (mejora: **72.7 %**).
- **Contraste honesto con las hipótesis iniciales de S1:**
  - *Hipótesis 1 (Latencia Redis < 2 ms):* **CUMPLIDA** (mediana real < 0.14 ms).
  - *Hipótesis 2 (Mejora frente a Mongo > 85 %):* **NO CUMPLIDA** (la mejora real fue del 63.7 % al 72.7 %; Mongo con índices respondió más rápido de lo previsto).
- **Mediciones de Índices MongoDB (`indices_mongo.md`):**
  - Búsqueda por código: Con índice `IXSCAN` examina **1 documento** (0.42 ms) vs `COLLSCAN` con **554 documentos** (0.65 ms).
  - Aggregation Pipelines: Conteo de estados **0.96 ms**; tiempos y SLA **1.88 ms**.

### Notas del Presentador
> *"En QLine nos apegamos rigurosamente a la honestidad científica y técnica. En Seguimiento 1 formulamos dos hipótesis teóricas: que Redis tardaría menos de 2 milisegundos y que superaría a MongoDB en más de un 85 %. Al ejecutar las mediciones reales en el servidor universitario de producción, la primera hipótesis se confirmó sobradamente: Redis responde en apenas 0.13 milisegundos. Sin embargo, la segunda hipótesis NO se cumplió: la mejora fue del 63.7 % al 72.7 %. MongoDB, al estar correctamente indexado y optimizado con colecciones preparadas, rindió mucho mejor de lo esperado. Presentamos con orgullo los datos medidos y no las conjeturas iniciales."*

---

## Diapositiva 13 · Limitaciones Conocidas y Deuda Técnica

### Contenido en Pantalla
- **Autenticación perimetral Apache:**
  - Las rutas de QR móvil son públicas sin contraseña (D-22); sin embargo, el quiosco físico y la pantalla de sala actualmente dependen del login inicial de Apache en el servidor universitario.
- **Ausencia de Keyspace Notifications en Redis:**
  - Al no disponer de permisos administrativos `CONFIG SET` en el hosting del curso, el abandono depende de un barrido temporal en lugar de suscripción a eventos de expiración.
- **Vigencia del token QR:**
  - El `qr_token` UUID v4 no posee una expiración automática tras el estado atendido; el enlace sigue consultable como comprobante histórico.
- **Monoservicio:**
  - Arquitectura orientada y calibrada para una sola cola de atención general; escalabilidad a multiservicio requeriría parametrizar la clave del Sorted Set.
- **Validación en hardware físico:**
  - Las pruebas locales verifican el 100 % del código; la prueba física con televisor de sala y celulares reales en la red del campus requiere ejecución presencial del grupo.

### Notas del Presentador
> *"Un proyecto maduro reconoce con transparencia sus límites. El entorno compartido de la universidad nos impuso restricciones como la falta de permisos para notificaciones de expiración de llaves en Redis, lo que resolvimos con el barrido periódico dual. También identificamos que la pantalla de sala requerirá una exención en el .htaccess si se desea operar sin ingresar credenciales de Apache en el monitor del pasillo. Todas estas limitaciones están documentadas en nuestro registro de decisiones técnicas para futuras iteraciones."*

---

## Diapositiva 14 · Conclusiones y Demostración en Vivo

### Contenido en Pantalla
- **Aportes Integrados del Equipo:**
  - **Alessandro Cambronero:** Motor de Redis, concurrencia, ventanilla única, WebSockets y mediciones de rendimiento.
  - **Carlos Espinoza:** Esquema $jsonSchema, índices parciales, pipelines de analítica, historial y scripts de datos sintéticos; ventanillas dinámicas (P09) y, **como extra al trabajo**, el mantenimiento lógico de sucursales (RFC-004), que cataloga sedes y aprovisiona sus ventanillas sin volver multisucursal la operación.
  - **Abigail Urbina:** Sistema de diseño visual Fintech, arquitectura de plantillas Jinja2, experiencia de quiosco y accesibilidad.
  - **Aaron Benavides:** Interfaz de cliente, tickets imprimibles, códigos QR, instrucciones de espera, changelog, portal.yml y presentación de release.
  *(Nota: Cada integrante validará personalmente sus conclusiones individuales en la sustentación final).*
- **Guion de Demostración en Vivo (P07):**
  1. Abrir pantalla pública (`/pantalla`) en un monitor o ventana visible.
  2. En el quiosco (`/quiosco`), emitir un turno normal y un turno preferencial.
  3. Demostrar el ticket generado, la acción de impresión y el código QR móvil.
  4. Abrir la URL del QR en el celular y observar el estado en espera.
  5. En el panel de ventanilla (`/panel`), llamar turno: verificar que el preferencial sale de primero.
  6. Observar el cambio instantáneo en la pantalla de sala y en el celular vía WebSockets.
  7. Iniciar atención, finalizar turno y comprobar el aviso de cierre en el celular.
  8. Inspeccionar el dashboard (`/dashboard`) y descargar el historial JSON.

### Notas del Presentador
> *"Para cerrar, los invitamos a presenciar la demostración en vivo de QLine. Veremos en acción simultánea la emisión táctil en quiosco, la actualización en tiempo real en la pantalla de sala, el respeto incondicional de la prioridad preferencial, y el seguimiento en el teléfono móvil del cliente. Muchas gracias por su atención y quedamos a su entera disposición para la sesión de preguntas."*

---

## Anexo Técnico: Guion Detallado de Demostración en Vivo (P07)

A continuación se detalla la secuencia operativa exacta que el equipo debe ejecutar durante la defensa presencial ante el profesor:

| Paso | Actor | Pantalla / URL | Acción Concreta | Resultado Observable |
|:---:|---|---|---|---|
| **1** | Supervisor | `/pantalla` | Abrir la pantalla pública de sala en una pestaña o monitor secundario. | Se visualiza la interfaz de sala con reloj en hora local y mensaje de sala vacía o llamados previos. |
| **2** | Cliente 1 | `/quiosco` | Seleccionar «Atención Regular (Normal)» y presionar «Emitir mi turno». | Se genera el turno (ej. `A-001`). Se muestra el ticket con QR SVG y el botón «Imprimir ticket». |
| **3** | Cliente 1 | `/quiosco` | Presionar «Imprimir ticket». | Se abre el diálogo del navegador `window.print()`. Se observa que el contador de retorno (25 s) se detiene. Se cancela o imprime y el contador se restablece. |
| **4** | Cliente 2 | `/quiosco` | Emitir un turno seleccionando «Atención Preferencial». | Se genera el turno preferencial (ej. `P-002` o `A-002` con badge preferencial). |
| **5** | Cliente 1 | `/turno/qr/{uuid}` | Abrir el enlace del QR en el celular o en una pestaña del navegador. | Se observa el estado «En espera», turnos por delante y la instrucción clara de espera (P05). |
| **6** | Operador 1 | `/panel` | Seleccionar ventanilla `V-01` y hacer clic en «Llamar siguiente turno». | **Verificación de Prioridad:** El turno preferencial emitido en el paso 4 es extraído primero, antes que el normal emitido en el paso 2. |
| **7** | Sistema | `/pantalla` y `/turno/qr/{uuid}` | Observar ambas pantallas sin recargar manualmente. | La pantalla de sala emite el sonido chiptune, parpadea y muestra el turno en `V-01`. El celular cambia en vivo a «¡Es su turno! Diríjase a la ventanilla V-01» con cuenta regresiva de 180 s. |
| **8** | Operador 1 | `/panel` | Presionar «Iniciar atención». | El turno pasa a `en_atencion`. El Hash con TTL de 180 s se elimina en Redis. La pantalla de sala actualiza el badge a «En atención». |
| **9** | Operador 1 | `/panel` | Presionar «Finalizar atención». | El turno concluye exitosamente. La ventanilla `V-01` queda libre. En el celular del cliente aparece el aviso (P01): *«Su atención finalizó. Puede cerrar esta pestaña. ¡Gracias por su visita!»*. |
| **10** | Auditor | `/dashboard` e `/historial` | Ingresar a la analítica operacional y descargar reportes. | Se observan los tiempos de espera y atención actualizados en los KPIs, y se descarga el JSON completo con metadatos de auditoría. |
