# Plan de implementación de lo faltante · S4 · Alessandro Cambronero Delgado

**Base:** [`PLAN_ALTERNATIVO_S4_QLINE.md`](../Plan%20de%20Desarrollo%20QLINE/PLAN_ALTERNATIVO_S4_QLINE.md) (v0.3), [`00_PLAN_S4_ALESSANDRO_ALTERNATIVO.md`](00_PLAN_S4_ALESSANDRO_ALTERNATIVO.md) y el estado de la rama `acambronero` tras integrar `aurbina` (Abigail) y `abenavides` (Aaron).
**Fecha:** 01/11/2026 · **Estado:** borrador para validar. **Avance:** Fase 0 (H1–H4) implementada con 12 pruebas automáticas; falta comprobarla en el servidor bajo Apache. P07 (script, guía y documento) y README final redactados, con prueba automática; falta ensayo y servidor. G0 aprobada y registrada como D-29 a D-33. S4-M03 implementada con 22 pruebas (falta servidor y validación de Carlos). UI-04 aplicada a cola, panel y sala (8 pruebas, sin revisión visual en navegador todavía); S4-M03, aporte a P09 y cierre de TT-027 esperan G0. Se corrigió además una llave sin cerrar en `style.css` del merge. El CRUD quedó en `/administracion` (plantilla `administracion.html`); `index.html` no se rehízo. Este documento complementa al plan anterior con lo que se encontró **después** de integrar; no lo reemplaza.

> Convención: «verificado en el servidor» = MongoDB y Redis reales; «prueba automática» = `tests/` con simulados. Los commits los hace cada integrante; los tags y empujes, solo con confirmación del equipo.

---

## 1. Qué hay y qué falta tras la integración

**Hecho y verificado por mí (suite: 537 pruebas, 1 omitida):** S4-M06 `/salud` (servidor, 5 casos OK), `/redis/estado` limitado, revisión parcial de TT-027.

**Aportes de Aaron presentes:** P01, P04, P05, S4-M02, `CHANGELOG.md`, `portal.yml`, presentación (`.pptx` + guion), `verificar_ui07.py`, decisiones D-24 a D-28. Pendientes suyos: contra-firma de TT-021 por otra persona y verificación física de la sala.

**Aportes de Carlos: no están.** `origin/cespinoza` sigue en el cierre de S3. Faltan P09, TT-028, P02, S4-M04, S4-M05 y UI-05.

**Aportes de Abigail: marcados «realizado» en su tabla, pero la integración muestra huecos** (hallazgos verificados en el código):

| # | Hallazgo | Evidencia | Gravedad |
|---|---|---|---|
| H1 | **Se perdió la pantalla del CRUD de MongoDB.** `index.html` (131 líneas, con colecciones, formularios de alta, edición y borrado) fue reemplazado por la portada. La ruta `/` sigue pasando los datos del CRUD a una plantilla que ya no los usa, y `/crear_coleccion`, `/insertar`, `/actualizar` y `/eliminar` redirigen a `/` | `app/main.py` (`inicio`, `render`); `git show 6b6c7ae:app/templates/index.html` | **Alta** |
| H2 | Los manejadores de error de UI-06 **no están registrados**: `app/errores.py` existe, pero `main.py` no llama a `registrar_errores`. Una ruta inexistente devuelve el JSON por defecto, no la página 404, y un error interno no usa `500.html` | `grep errores app/main.py`; `GET /no-existe` devuelve 22 bytes | Media |
| H3 | **`/acerca` responde 404**: la plantilla existe, la ruta no. La URL del repositorio dentro de la plantilla termina en un punto (`…/Qline.`) | `acerca.html` | Media |
| H4 | Los enlaces nuevos (`/quiosco`, `/consultar`, `/acerca`, `/`) son **absolutos y no usan `{{ base }}`**: bajo Apache (`/proyecto/qline`) llevarían fuera de la aplicación | `index.html`, `error_base.html`, `acerca.html` | Alta en el servidor |
| H5 | **UI-03 no está aplicada.** Sus versiones de `quiosco`, `quiosco_confirmado`, `turno_confirmado`, `turno_qr` y `base*` eran borradores («ADAPTAR») que rompían el QR en SVG, las fechas y `BASE_PATH`; al integrar conservé las funcionales. El rediseño visual de esas pantallas queda sin hacer, y `style.css` arrastra ambos juegos de reglas | Resolución del merge | Media |
| H6 | `README.md` sigue siendo el de S1–S3 (75 líneas, insignia «Seguimiento 1», sin variables de entorno ni enlace al mapa de claves) | `README.md` | Alta para TT-021/TT-029 |
| H7 | La portada y el resto de plantillas públicas usan una `base_publico.html` sin navegación; no hay menú de operación visible para el equipo | revisión | Baja |

Aaron ya inspeccionó «13 pantallas» con `verificar_ui07.py` antes de este merge: hay que **repetirlo** después de corregir H1–H5.

## 2. Reglas para tocar el trabajo de otros

- Solo corrijo lo que rompe el sistema o impide una entrega (H1–H4, H6). El rediseño de UI-03 (H5) se hace con Abigail o con su aprobación, sin cambiar rutas, valores de formulario ni generación de turnos.
- Cada corrección va con su prueba automática y se anota en `S4.md` con el autor original y quién la corrigió.
- Lo de Carlos no lo programo yo salvo acuerdo explícito (ver §4, bloque C).

## 3. Decisiones previas (G0): hay que cerrarlas antes de S4-M03 y P09

**Requiere tu visto bueno para empezar** (indicaste antes no iniciar G0). Contenido, en `docs/decisiones.md`, con los números que siguen a los de Aaron:

| N.º | Tema | Propuesta |
|---|---|---|
| D-29 | `/salud` y `/redis/estado`: respuesta mínima y exposición protegida | Ya implementado; solo registrarlo |
| D-30 | Catálogo de ventanillas dinámicas | Colección `ventanillas` en MongoDB, `ventanillas_activas(db)` con caché corta y último catálogo conocido si Mongo falla; identificador `V-NN` validado; `collMod` del esquema verificado en el servidor antes de crear la primera |
| D-31 | Cierre con motivo y nota | Campo raíz `cierre: {motivo, nota}`, opcional; nota ≤ 200 caracteres; Carlos valida el esquema |
| D-32 | Estimación de espera (S4-M01) | Aprobada o **no ejecutada**; sin acuerdo escrito no se programa |
| D-33 | Ubicación del CRUD tras la portada (H1) | `/` = portada; CRUD en `/administracion` (protegido por Apache como hoy) |

## 4. Fases

### Fase 0 · Recuperar lo que se rompió (1 día) — empieza ya, no depende de G0
1. **H1 CRUD:** restaurar la plantilla desde `6b6c7ae` como `administracion.html`, mover la vista a `/administracion` y actualizar las redirecciones de `/crear_coleccion`, `/insertar`, `/actualizar`, `/eliminar` (D-33). `/` renderiza la portada. Pruebas: el CRUD sigue creando, editando y borrando con validación del esquema; `/crud` y las rutas de escritura siguen fuera de las rutas públicas (`tests/test_htaccess.py`).
2. **H2 errores:** llamar a `registrar_errores(app, templates)`; pruebas: 404 de página en HTML, 404 de `/api/…` en JSON, 500 sin traza ni texto de la excepción, 403.
3. **H3 y H4:** ruta `GET /acerca`; corregir la URL del repositorio; sustituir enlaces absolutos por `{{ base }}…` en `index`, `acerca`, `error_base`, `quiosco`; prueba que recorra las plantillas y falle ante `href="/…"` sin `base`.
4. Regresión: suite completa y `GUION_VERIFICACION_S3.md` abreviado en el servidor (cola, panel, QR bajo Apache).

### Fase 1 · Mis tareas independientes (3 días)
| Tarea | Trabajo | Salida |
|---|---|---|
| **S4-M03** (tras D-31) | Constantes de motivos; parámetro opcional en `finalizar_atencion` (mismo `update_one`); `TurnoFinalizado`; `/api/atencion/finalizar` y `/panel/finalizar`; esquema; formulario plegado en `panel.html`; escape de la nota; historial y descargas con turnos sin `cierre` | Pruebas (sin motivo, válido, inválido → 400, nota larga, `<script>`, reintento sin sobrescribir, documento antiguo) + verificación en el servidor contra el esquema real |
| **UI-04** | Aplicar los tokens de Abigail (ya integrados) a `cola.html`, `panel.html`, `pantalla.html` con estilos propios por módulo; sin vidrio; estados por texto e indicador; mantener `#n-espera`, `#n-activos`, `#btn-sonido`, WebSocket y *polling* | Pruebas de `pantalla_sala` y panel ajustadas; prueba de ausencia de `backdrop-filter`; capturas |
| **Aporte a P09** | `ventanillas_activas(db)` en lugar de `in VENTANILLAS` (`atencion`, `cola`, `llamado`, `panel_atencion`); `SET NX` igual; concurrencia con 4 ventanillas (0 duplicados); `reconciliar_cola` y barrido sin la lista fija | Evidencia regenerada en el servidor: `concurrencia.md` |
| **TT-027** (cierre) | Contrastar de nuevo el mapa con el código ya integrado; el catálogo de ventanillas queda descrito | `test_redis_claves_doc.py` en verde |

### Fase 2 · Lo que depende de Carlos y de UI-03 (2 días, riesgo alto)
- **Bloque C (Carlos):** P09, TT-028, P02, S4-M04, S4-M05, UI-05 no han llegado. **Hay que preguntarle hoy su estado y fecha.** Si no entrega, el plan de contingencia (con aprobación del equipo) es: yo hago el alta de ventanillas mínima (sin edición ni borrado) y documento TT-028 con los scripts existentes (`init_mongo.py`, `generar_datos_sinteticos.py --cargar`), sin prometer lo que no exista.
- **H5 (UI-03):** acordar con Abigail quién adapta las 6 plantillas. Propuesta: ella adapta y yo reviso; si no puede, lo hago yo partiendo de la versión funcional y sus clases, y limpio los estilos duplicados de `style.css`.
- **H6 (README):** redactar el README final (arquitectura, prerrequisitos, variables de entorno sin secretos, instalación, datos sintéticos, operación, `/salud`, seguridad, capturas, enlace al mapa de claves) si Abigail no lo entrega. Es lo que usa TT-021.

### Fase 3 · Verificación y demo (3 días)
- **UI-07 repetida** sobre las pantallas integradas; defectos de mis pantallas, corregidos por mí.
- **P07:** `scripts/preparar_demo.py` idempotente (índices, datos, cola, resumen; sin borrar datos ajenos); `/demo` actualizado al guion de `PRESENTACION_FINAL.md`; lista de comprobación previa (`/salud` en verde); plan B con capturas. La demo de consulta y QR usa turnos emitidos en vivo (la consulta por código solo admite `A-NNN`).
- **P08:** mis conclusiones, solo de pruebas que ejecuté (`/salud`, concurrencia, regresión, UI-04).
- **Regenerar** `docs/evidencia/` en el servidor si cambió el código; traer `salud.md` al repositorio.

### Fase 4 · Entrega (1,5 días)
- Contra-firma de TT-021 por alguien que no sea Aaron.
- **TT-029:** PR aprobado por otra persona; suite verde; sin credenciales en README, `portal.yml`, scripts ni capturas; coherencia entre `CHANGELOG.md` (hoy `v0.9.0-rc`), `portal.yml` y el tag que decida el equipo. Primero `v0.2.0` y `v0.3.0` (hoy no existe ningún tag), luego `main`, luego el tag final. Tags anotados solo cuando el equipo lo confirme.

### S4-M01 (condicionada)
No se programa. Solo la propuesta de media página para D-32. Si no hay autorización escrita, queda registrada como **no ejecutada**.

## 5. Esfuerzo y corte mínimo

| Fase | Días-persona |
|---|---|
| 0 · Recuperar | 1 |
| 1 · Independientes | 3 |
| 2 · Dependientes | 2 (+2 si Carlos no entrega P09/TT-028) |
| 3 · Verificación y demo | 3 |
| 4 · Entrega | 1,5 |
| **Total** | **≈ 10,5** (≈ 12,5 con contingencia; +2 si se autoriza S4-M01) |

**Corte mínimo (≈ 7 días):** Fase 0 completa, S4-M03, UI-04 con tokens, TT-027, README mínimo reproducible, P07 y TT-029. Lo que no entre se anota como pendiente.

## 6. Orden recomendado

1. Fase 0 (H1–H4): es lo único que rompe el sistema hoy.
2. Mensaje a Carlos y a Abigail con los hallazgos H1–H6.
3. G0 (con tu visto bueno) y registrar D-29 a D-33.
4. S4-M03 y UI-04 en paralelo con el aporte a P09.
5. README, UI-07, P07, P08.
6. TT-029.

## 7. Riesgos

| Riesgo | Qué hago |
|---|---|
| Restaurar el CRUD rompe una ruta o prueba | Pruebas del CRUD antes y después; rutas de escritura siguen protegidas |
| Carlos no entrega P09/TT-028 | Contingencia de §4 y aviso temprano; nada se declara hecho sin evidencia |
| Abigail y yo editamos el mismo CSS | Estilos por módulo; cambios al CSS compartido, avisados |
| `style.css` con reglas duplicadas altera pantallas | Revisión visual de las 13 pantallas tras cada cambio; limpieza al integrar UI-03 |
| El README o `portal.yml` exponen datos | Revisión de secretos antes del tag |
