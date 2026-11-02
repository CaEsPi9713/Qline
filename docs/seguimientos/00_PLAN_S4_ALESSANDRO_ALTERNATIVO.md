# Plan de implementación · Seguimiento 4 · Alessandro Cambronero Delgado

**Base:** [`PLAN_ALTERNATIVO_S4_QLINE.md`](../Plan%20de%20Desarrollo%20QLINE/PLAN_ALTERNATIVO_S4_QLINE.md) (v0.3), [`S4.md`](S4.md) y el código de `development` (rama de trabajo `acambronero`).
**Fecha:** 28/10/2026 · **Estado:** borrador para validar con el equipo. **Avance:** S4-M06 (`/salud`) implementado y verificado en el servidor; `/redis/estado` limitado a `{"ok": …}` y revisión parcial del mapa de claves (TT-027) con prueba automática; el resto sigue sin hacer. G0 no se ha iniciado.

> Convención de la bitácora: «verificado en el servidor» es lo ejecutado con MongoDB y Redis reales; «prueba automática» es la suite de `tests/` con simulados. Una tarea que toca Redis, Apache o WebSocket no se cierra solo con lo segundo.

> **Relación con `00_PLAN_S4_ALESSANDRO.md`:** ese borrador (sin seguimiento en git) parte de `propuestas_mejoras.md` e incluye sesiones y roles, cancelar desde el QR, pausar ventanilla y límite de peticiones. El plan alternativo **excluye** el login y los roles («no se crean… autenticación compleja») y no admite estados nuevos (A3 exigiría `cancelado`, que no existe: `ESTADOS` tiene cinco). Este documento lo sustituye; conviene borrar o archivar el anterior para que el equipo no trabaje con dos planes.

---

## 1. Qué me corresponde

| ID | Tarea | Complejidad | Previas | Cierre / integración |
|---|---|---|---|---|
| **S4-M06** | Endpoint `/salud` limitado (D1) | Media | — | UI-07 |
| **S4-M03** | Notas / motivo opcional de cierre (B3) | Media | G0 | UI-04, TT-028, TT-027 |
| **UI-04** | Cola, operación y pantalla pública | Alta | UI-01 | P09, S4-M03, UI-07 |
| **TT-027** | Revisión final del mapa de claves de Redis | Baja | P09, S4-M03 | TT-022 |
| **P07** | Demostración en vivo con datos sintéticos | Media | TT-028, UI-07 | TT-025 |
| **TT-029** | Tag y release final (incluye el arrastre de S3) | Media | TT-021, 023, 025, 026, UI-07 | P07, TT-022 |
| **S4-M01** | Estimación de espera (A1) | Alta | G0 | **Condicionada: no se programa sin autorización** |
| P08 | Evidencias y conclusiones de mis pruebas | Compartida | UI-07 | TT-022, TT-025 |

También participo en **G0** (aporte de Redis a las ventanillas dinámicas) y, en **UI-07**, verifico y corrijo mis propias pantallas.

Fuera de mi alcance, pero de las que dependo: **P09** (Carlos: catálogo de ventanillas), **UI-01** (Abigail: tokens y componentes CSS), **TT-028** (Carlos: carga de MongoDB), **TT-021/022/023/025/026** (Aaron y Abigail).

## 2. Lo que encontré en el código (condiciona el plan)

1. **`VENTANILLAS` es una tupla fija** (`("V-01","V-02","V-03")` en `app/constantes.py`) y se usa en 12 módulos: `atencion`, `cola`, `llamado`, `panel_atencion`, `dashboard`, `historial`, `datos_prueba`, `s3_comun`, `main`, `schemas`, `turnos_schema` y los scripts sintéticos. P09 (ventanillas dinámicas) toca todos; es el cambio con más riesgo del seguimiento y de él cuelgan UI-04, TT-027 y TT-028.
2. **El esquema de MongoDB limita `ventanilla` a esa lista** (`enum` en `turnos_schema.py`). Una ventanilla nueva sería **rechazada por el servidor** hasta actualizar el validador, y el servidor no lo actualiza solo en una colección existente (lección de S3 con `qr_token`). Es el punto que G0 debe resolver con Carlos.
3. **Las claves de Redis por ventanilla ya se construyen con el identificador** (`clave_ventanilla_actual(v)`), así que no cambian de forma con ventanillas nuevas; lo que cambia es **quién valida** que el identificador exista (`atencion.validar_ventanilla`, `cola.reservar_y_extraer`, `llamado`).
4. **Para S4-M03, el esquema ya lo permite sin migrar**: el documento raíz tiene `additionalProperties: True`, pero `timestamps` y `metricas` lo tienen en `False`. Un campo nuevo debe ir **en la raíz** (por ejemplo `cierre`), nunca dentro de `metricas`.
5. **No existe `/salud`**; solo `/redis/estado`. No hay tags en el repositorio (`git tag` vacío) y no hay versión declarada en la aplicación.
6. **`/pantalla`** ya fue rediseñada en S3 (233 líneas, con estilos `sala-*` en `style.css`); UI-04 la adapta a los tokens de UI-01, no la rehace.

## 3. Acuerdos previos (G0): mi parte

Antes de programar S4-M03 o tocar ventanillas hay que dejar escrito en `decisiones.md`:

| Tema | Mi propuesta |
|---|---|
| **Fuente del catálogo de ventanillas** | MongoDB (colección `ventanillas`, de Carlos). Una función `ventanillas_activas(db)` con caché corta (unos segundos) para no consultar en cada llamada; si MongoDB no responde se usa el último catálogo conocido. Redis no guarda el catálogo |
| **Formato del identificador** | `V-NN`, validado con expresión regular, sin espacios ni caracteres que rompan una clave de Redis |
| **Esquema** | Cambiar el `enum` de `ventanilla` por un patrón y aplicar `collMod` con un script de Carlos; verificar en el servidor antes de crear la primera ventanilla |
| **Motivo y nota de cierre** | Campo raíz `cierre: {motivo, nota}`, opcional; los turnos anteriores no lo tienen y deben seguir validando. Carlos aprueba |
| **Estimación (S4-M01)** | Se decide sí o no; sin acuerdo escrito no se programa |
| **Exposición de `/salud`** | Protegida por Apache como el resto (no se agrega al `.htaccess` público); respuesta mínima |

## 4. Fases y esfuerzo

| Fase | Contenido | Esfuerzo | Depende de |
|---|---|---|---|
| **0 · Decisiones y preparación** | Aporte a G0; medir la línea base de pruebas; empezar `/salud` | 1 día | — |
| **1 · Bases independientes** | S4-M06; S4-M03 (tras G0); aportes de Redis a P09; inicio de UI-04 con los tokens de UI-01 | 5 días | G0, UI-01 |
| **2 · Integración** | UI-04 con ventanillas (P09) y notas (S4-M03); TT-027; regresión | 2,5 días | P09, S4-M03 |
| **3 · Verificación** | UI-07 sobre mis pantallas; P08; regenerar evidencias en el servidor; preparar P07 | 3 días | UI-07, TT-028 |
| **4 · Entrega** | Validar P07; TT-029 con el arrastre de S3 | 1,5 días | TT-021, 023, 025, 026 |
| **Total** | | **≈ 12 días-persona** (+2 si se autoriza S4-M01) | |

**Corte mínimo si falta tiempo (≈ 8 días):** S4-M06, S4-M03, UI-04 con los tokens base, TT-027, P07 y TT-029. Lo que no entre se anota como pendiente, no como hecho.

## 5. Detalle por tarea

### S4-M06 · `/salud` (1 día, empieza ya)

- `GET /salud` responde `{"estado": "ok" | "degradado", "app": "ok", "redis": "ok" | "error", "mongo": "ok" | "error", "barrido": true | false}`. **200** si todo responde y **503** si falla Redis o MongoDB. Nunca 500.
- **No incluye** mensajes de excepción, nombres de servidor, puertos, usuarios ni versiones de software: los detalles van al registro del servidor, no al cuerpo.
- Comprobaciones con tiempo límite corto (un `PING` de Redis y un `ping` de MongoDB) para que una caída no cuelgue la respuesta. Revisar cómo configura `get_db()` el tiempo de selección del servidor.
- Revisar de paso **`/redis/estado`**: confirmar que no devuelve datos de infraestructura; si los devuelve, se limita (misma regla de «sin detalles»).
- Archivos: módulo nuevo `app/salud.py` y la ruta en `app/main.py`. Sin cambios en `.htaccess` (queda protegida) y una línea en `tests/test_htaccess.py` que lo confirme.
- **Pruebas automáticas:** todo sano; Redis caído; MongoDB caído; ambos caídos; el cuerpo no contiene texto de la excepción ni el valor de ninguna variable de entorno.
- **Servidor:** con Redis inalcanzable (se apunta a un puerto sin servicio, como en `probar_fallos_redis`; no se detiene el Redis compartido) y con el servicio sano. Informe: `docs/evidencia/salud.md`.

### S4-M03 · Notas y motivo opcional de cierre (2 días, tras G0)

- **Motivos:** lista cerrada y corta definida en `app/constantes.py` (por ejemplo: `resuelto`, `derivado`, `documentacion_incompleta`, `otro`). **Nota** libre opcional, recortada y con un máximo de 200 caracteres.
- Datos: `cierre: {"motivo": …, "nota": …}` en la raíz del documento; ausente si no se informa. Los cinco estados y `metricas`/`timestamps` no cambian.
- Cambios: parámetro opcional en `atencion.finalizar_atencion`, el mismo `update_one` condicionado (no se separa en dos escrituras); `app/schemas.py` (`TurnoFinalizado`); `POST /api/atencion/finalizar` y `POST /panel/finalizar` con campos opcionales; `turnos_schema.py` (validación del campo y del documento). Redis no cambia.
- Interfaz: selector y campo de texto junto al botón «Finalizar» de `panel.html`, plegados para no estorbar el flujo de ventanilla.
- Seguridad: la nota se escapa siempre al mostrarse (Jinja lo hace por defecto; se prueba con `<script>`), no se usa `innerHTML` ni `|safe`.
- Compatibilidad: historial, dashboard y descargas siguen funcionando con turnos sin `cierre`. Si Carlos lo aprueba, el historial muestra el motivo.
- **Pruebas:** finalizar sin motivo (igual que hoy); con motivo válido; motivo inválido (400 controlado); nota demasiado larga; nota con HTML; reintento de finalización que no sobrescribe el cierre; documento antiguo en historial y descargas.
- **Servidor:** finalizar un turno con nota desde el navegador y comprobar en MongoDB que el documento valida con el esquema real.

### UI-04 · Cola, operación y pantalla pública (3 días, tras UI-01)

- Archivos: `cola.html` (46 líneas), `panel.html` (74), `pantalla.html` (233) y los estilos `sala-*` de `style.css`. Los cambios al CSS compartido se acuerdan con Abigail antes de integrarlos; mis estilos van encapsulados por módulo.
- Estética fintech sólida con la paleta del plan (`#0B111C`, `#B8CBD8`, `#5BB6C5`, `#538573`, `#F7F7F7`), **sin vidrio** (el único vidrio del sistema es el de las tarjetas del quiosco).
- Estados y prioridades se distinguen **por texto e indicador, no solo por color**. Botones con tamaño táctil. Foco visible.
- Conservar sin cambios: los identificadores que usa el JavaScript de la sala (`#n-espera`, `#n-activos`, `#btn-sonido`), el WebSocket con *polling* de respaldo, `/api/llamados` y la semántica de la cola.
- Integrar cuando estén listas: la lista de ventanillas de P09 (el panel ya recorre `estado_ventanillas`, que dejará de leer la tupla fija) y el formulario de cierre de S4-M03.
- **Pruebas:** ajustar `tests/test_pantalla_sala.py` y las del panel; una prueba que compruebe que `cola`, `panel` y `pantalla` no usan `backdrop-filter`.
- **Servidor y UI-07:** panel en escritorio y móvil, sala en pantalla grande, con `POST /api/llamar` actualizando en tiempo real, y capturas antes y después.

### Aporte a P09 (1,5 días, tras el contrato de Carlos)

No soy responsable de P09, pero el comportamiento de Redis sí:
- Sustituir las comprobaciones `in VENTANILLAS` de `atencion`, `cola`, `llamado` y `panel_atencion` por `ventanillas_activas(db)`.
- **Ventanilla única:** una ventanilla nueva usa el mismo `SET NX` sobre `clave_ventanilla_actual`; prueba de concurrencia con cuatro ventanillas y turnos simultáneos, con 0 duplicados (hay que actualizar `scripts/prueba_concurrencia.py` y `scripts/probar_cola.py`, que tienen la lista fija).
- Recuperación y barrido de abandono: comprobar con una ventanilla nueva que `reconciliar_cola` y el barrido no dependen de la lista fija.
- Evidencia: regenerar `docs/evidencia/concurrencia.md` con la ventanilla nueva.

### TT-027 · Mapa de claves de Redis (0,5 día, tras P09 y S4-M03)

- Contrastar `docs/arquitectura/redis_claves.md` (107 líneas) con el código: listar todo lo que construye `REDIS_PREFIJO` (`constantes.py`, `cola.py`, `fallos_s3.py`, `recuperacion.py`, `tiempo_real.py`, las claves de prueba `grupo2:qline:prueba:*`) y cotejar clave, tipo, TTL de 180 s, canales y recuperación.
- Actualizar **solo diferencias verificadas**. S4-M06 y S4-M03 no agregan claves; P09 no cambia el patrón de la clave por ventanilla, pero hay que dejar escrito que el identificador sale del catálogo.
- Prueba nueva barata: que todo prefijo `grupo2:qline:` usado en `app/` aparezca en el documento, para detectar claves sin documentar.
- Enlazarlo desde el README (TT-022).

### P07 · Demostración en vivo (2 días, tras TT-028 y UI-07)

- Reutilizar lo existente: `scripts/init_mongo.py`, `scripts/generar_datos_sinteticos.py --cargar` (554 turnos `S-NNN`, con *upsert*), `scripts/precargar_cola.py` y `scripts/crear_turnos_qr_demo.py`.
- **Script `scripts/preparar_demo.py`**, idempotente, que verifica índices y datos, deja la cola lista y muestra un resumen. **No borra datos** que no sean de la demo, en línea con TT-028.
- Actualizar `/demo` (`demo.html`) al guion de S4: emitir con prioridad → llamar → atender y cerrar con motivo → QR en el celular → historial con fechas y paginación → dashboard con gráficos → ventanilla nueva → `/salud`.
- Los turnos sintéticos usan la serie `S-NNN` y la consulta por código solo admite `A-NNN` (deuda de `S4.md` §4.2): la demo de consulta y QR se hace con turnos emitidos en vivo.
- Ensayo completo con cronómetro, lista de comprobación previa (`/salud` en verde, datos cargados, celular con el QR abierto) y **plan B**: capturas y turnos precargados si falla la red.
- Sin promesas de resultados: las cifras que se muestren salen de `docs/evidencia/` regenerada.

### TT-029 · Tag y release (1 día, al final)

- **Antes:** PR de `acambronero` a `development` aprobado por otra persona; suite completa en verde; `docs/evidencia/` regenerada si cambió el código; sin credenciales en README, `portal.yml`, scripts ni capturas.
- **Arrastre de S3:** hoy no existe ningún tag. Hay que identificar el commit de cierre de S2 para `v0.2.0` y el de S3 para `v0.3.0` (`git log`), y ponerlos antes del tag final; actualizar `main`, que está atrasada respecto de `development`.
- **Tag final:** `v0.9.0` o `v1.0.0` según decida el equipo. Etiquetas anotadas, con publicación en GitHub y enlace a `CHANGELOG.md`.
- **Los tags y los empujes al repositorio remoto los ejecuto solo cuando el equipo lo confirme; los commits los hace cada integrante.**
- Evidencia: enlace de la publicación y resultado de la instalación limpia de TT-021.

### S4-M01 · Estimación de espera (condicionada)

**No se programa** sin autorización escrita (el Plan Maestro excluye la predicción). Lo único que hago ahora es dejar lista la propuesta para G0, de media página:
- Cálculo reproducible: mediana de `metricas.atencion_seg` de turnos `atendido` (global y por prioridad) × posiciones por delante ÷ ventanillas activas.
- Muestra mínima (por ejemplo 30 turnos atendidos) y *fallback* sin datos: «Estimación no disponible».
- Rótulo «orientativo» visible. Reutiliza las agregaciones de P02 (Carlos).
- Si se aprueba: unos 2 días, entre `consulta_qr.py` y `turno_qr.html` (UI-03, de Abigail). Si no, se registra en `decisiones.md` como **no ejecutada** y queda fuera del release.

## 6. Decisiones a registrar (`decisiones.md`)

| N.º previsto | Tema |
|---|---|
| D-24 | `/salud`: contenido mínimo, códigos de respuesta y exposición protegida |
| D-25 | Catálogo de ventanillas dinámicas: fuente, formato del identificador y validación en Redis (con Carlos) |
| D-26 | Cierre de turno: campo raíz `cierre`, motivos cerrados, nota limitada |
| D-27 | Estimación de espera: aprobada o no ejecutada (condicional) |

Los números pueden cambiar si otros integrantes registran decisiones antes (ya pasó en S3).

## 7. Verificación

- **Automática:** cada tarea trae sus pruebas; la suite completa (hoy 505, 1 omitida) debe seguir verde antes de cada PR.
- **Servidor** (lo que toque Redis, Apache o WebSocket): `/salud` con Redis inalcanzable, concurrencia con ventanillas nuevas, cierre con nota validando el esquema real, pantalla de sala en tiempo real, panel en celular.
- **Regresión:** recorrido de `GUION_VERIFICACION_S3.md` al terminar la Fase 2, porque P09 toca la cola y las ventanillas.
- **UI-07:** cada defecto de mis pantallas lo corrijo yo; mis capturas van a `docs/evidencia/capturas/`.

## 8. Ramas y control de cambios

- Ramas cortas desde `development`: `feat/salud`, `feat/cierre-nota`, `feat/ui-operacion`, `feat/ventanillas-redis`, `chore/mapa-claves`, `feat/preparar-demo`.
- Un PR por rama con revisión de otra persona; nadie aprueba el suyo.
- `feat/ventanillas-redis` se coordina con la rama de Carlos (P09) y se integra después de ella.
- Los commits los hace cada integrante; este plan no los ejecuta.

## 9. Riesgos

| Riesgo | Qué hago |
|---|---|
| P09 rompe una comprobación que dependía de la tupla fija | Búsqueda de todos los usos (§2), prueba de concurrencia con cuatro ventanillas y regresión con el guion de S3 |
| El esquema del servidor rechaza una ventanilla nueva | Decisión en G0 y `collMod` verificado en el servidor antes de crearla |
| UI-01 llega tarde y UI-04 espera | Empiezo por la estructura y las funciones (S4-M03, integración de P09) y aplico los tokens al final |
| `/salud` filtra datos de infraestructura | Respuesta mínima y prueba que busca texto de excepción y valores de entorno |
| Dos autores tocan el mismo CSS | Estilos por módulo y cambios compartidos solo vía Abigail |
| La nota de cierre abre un hueco de HTML inyectado | Escape por defecto y prueba con `<script>` |
| Falta de tiempo | Corte mínimo de la §4; lo descartado queda como pendiente documentado |
| S4-M01 se programa «por si acaso» | No se toca sin acuerdo escrito |

## 10. Seguimiento

Cada tarea se anota en `S4.md` §7 con el enlace al PR, a las pruebas y al informe del servidor. Una tarea sin esa evidencia se considera pendiente.
