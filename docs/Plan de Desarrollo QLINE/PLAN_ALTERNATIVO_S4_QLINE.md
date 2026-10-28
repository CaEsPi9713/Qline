# QLine | Plan alternativo de desarrollo S4
**Versión 0.3 · Matriz de tareas, dependencias e integración visual · Propuesta para validación del equipo**

**Documento independiente. No modifica ni reemplaza el Plan Maestro ni el enunciado del curso.**

**Base:** `development`, `docs/seguimientos/S4.md`, Plan Maestro `docs/Plan de Desarrollo QLINE/PLAN_DESARROLLO_QLINE.md`, feedback del profesor, y propuestas preseleccionadas de `docs/propuestas_mejoras.md`.

**Estado:** planificación. La asignación propuesta no prueba implementación ni representa aceptación formal del equipo.

---

## 1. Alcance, prioridad y reglas de control
El Plan Maestro y las normas oficiales mantienen prioridad. El presente documento es **una matriz de ejecución alterna** para ordenar las 29 tareas operativas seleccionadas, distribuir responsables y establecer condiciones de integración. No se crean servicios, sucursales, roles, autenticación compleja, nuevos estados o prioridades por consecuencia de los mockups. Se preservan Redis, MongoDB, QR, actualización en vivo y TTL de 180 s.

- **TT-024 (video):** permanece en el Plan Maestro, pero se excluye **del alcance operativo de este plan** según la decisión de realizar demo en vivo. Conservar el acta/aclaración docente que sustenta la excepción; no afirmar que el enunciado fue cambiado sin evidencia.
- **S4-M01 (A1, estimación):** es una mejora preseleccionada **condicionada**, porque el Plan Maestro excluye predicción de espera. Sin acuerdo formal queda en espera y **no bloquea** el release.
- **S4-M04:** conservar descarga JSON existente; **CSV fuera**. Las propuestas B1, C1, D5, F3 y F4 se integran en otras tareas, no se cuentan dos veces.
- **G0 (punto de decisión, no tarea adicional):** aprobación grupal de los contratos de ventanillas dinámicas, cambios opcionales al esquema Mongo, exposición segura de landing/CRUD y resolución de la contradicción de S4-M01. No autoriza borrado de datos ni cambio de semántica Redis. Se documenta antes de aplicar cambios de esas áreas.

## 2. Responsabilidades consolidadas
La distribución se hace por **complejidad técnica, continuidad de los módulos y capacidad de ejecución paralela**, no únicamente por cantidad de filas. La asignación no es definitiva hasta que el equipo la valide. Cada tarea tiene un responsable primario; las tareas transversales requieren aportes verificables de los cuatro integrantes.

| Integrante | Área de responsabilidad | Tareas lideradas |
|---|---|---|
| **Aaron** | Mensajes al cliente, identificación, ticket imprimible, documentación de release, presentación y checklist de aceptación | TT-021, TT-023, TT-025, TT-026, P01, P04, P05, S4-M02, UI-07 |
| **Abigail** | Arquitectura visual, plantillas compartidas, portada, experiencia de quiosco, accesibilidad y README | TT-022, P06, UI-01, UI-02, UI-03, UI-06 |
| **Alessandro** | Operación, consulta/estimación condicionada, persistencia de notas, salud, Redis, demo y publicación | TT-027, TT-029, P07, S4-M01, S4-M03, S4-M06, UI-04 |
| **Carlos** | Ventanillas, contrato/carga Mongo, métricas, historia, reportes y visualización analítica | TT-028, P02, P09, S4-M04, S4-M05, UI-05 |

**P08 es de los cuatro:** cada integrante redacta conclusiones basadas en sus pruebas. Abigail consolida las secciones documentales y Aaron las refleja en la presentación. Los responsables técnicos validan el funcionamiento de sus módulos durante UI-07 y apoyan la demo P07.

## 3. Matriz completa: actividades, responsables y dependencias
**Cómo leerla:** **«Previas»** = requisitos para empezar la actividad correspondiente, no solo para cerrarla; **«Integración / cierre»** = tareas que pueden avanzar en paralelo, pero deben estar coordinadas o completadas antes de aceptar el resultado. El símbolo «—» significa que no hay dependencia formal. **G0** es un acuerdo previo y no suma al total. Las tareas de complejidad Baja/Media/Alta son estimaciones de planificación, no horas comprometidas.

### A. Entregables oficiales de S4 (8)

| ID | Tarea | Responsable | Complejidad | Previas | Integración / cierre |
|---|---|---|---|---|---|
| **TT-021** | Prueba de instalación limpia usando solamente el README | **Aaron** | Media | TT-022, TT-028 | TT-027 |
| **TT-022** | README final y guía reproducible | **Abigail** | Media | UI-07, TT-027, TT-028 | TT-021 |
| **TT-023** | CHANGELOG.md basado en cambios reales | **Aaron** | Baja | UI-07 | TT-029 |
| **TT-025** | Presentación final y guion de exposición | **Aaron** | Media | P07, P08, UI-07 | TT-023 |
| **TT-026** | Ficha portal.yml para publicación | **Aaron** | Baja | TT-022 | TT-029 |
| **TT-027** | Revisión final del mapa de claves Redis (ya avanzado) | **Alessandro** | Baja | P09, S4-M03 | TT-022 |
| **TT-028** | Script reproducible de inicialización y carga MongoDB | **Carlos** | Media | P09, S4-M03 | P07, TT-021 |
| **TT-029** | Tag y release final | **Alessandro** | Media | TT-021, TT-023, TT-025, TT-026, UI-07 | P07, TT-022 |

**Criterios de aceptación específicos:**

- **TT-021:** En un entorno nuevo se reproduce instalación, configuración, carga de datos y arranque; documentar errores y resultado. **Condición:** el verificador no debe ser quien preparó ese entorno. Si Aaron lo preparó, sustituir por otro integrante que no lo haya hecho.
- **TT-022:** README con arquitectura, prerrequisitos, variables de entorno sin secretos, instalación, carga sintética, operaciones, seguridad, capturas y enlaces; primero preparar borrador y cerrar al final. Cada responsable aporta instrucciones de su módulo.
- **TT-023:** Historial coherente con cambios integrados y versión acordada; no declarar funcionalidades pendientes como realizadas.
- **TT-025:** Diapositivas sobre problema, arquitectura, tecnologías, flujo, métricas reales, pruebas, conclusiones y demo; recibir material de cada dueño de módulo. No introducir resultados ficticios.
- **TT-026:** Archivo válido para el formato exigido por el curso, con metadatos, descripción y enlaces reales; verificar sintaxis y rutas.
- **TT-027:** Contrastar docs/arquitectura/redis_claves.md con el código integrado: claves, tipos, TTL de 180 s, canales, uso y recuperación; actualizar solo diferencias verificadas.
- **TT-028:** Revisar scripts ya existentes y comprobar carga sintética sin borrar datos reales; índices/contrato compatibles; documentar comando, salida y precauciones.
- **TT-029:** Revisar rama integrada, pruebas, versión y entregables; emitir tag v0.9.0 o v1.0.0 según decisión del equipo y conservar evidencia de publicación.

### B. Retroalimentación del profesor y ajuste P09 (8)

| ID | Tarea | Responsable | Complejidad | Previas | Integración / cierre |
|---|---|---|---|---|---|
| **P01** | Aviso al finalizar atención en QR | **Aaron** | Baja | — | UI-03 |
| **P02** | Estadísticas de atención y gráficos (incluye C1) | **Carlos** | Alta | — | P09, UI-05, S4-M05 |
| **P04** | Nombre institucional visible; logo opcional | **Aaron** | Baja | UI-01 | UI-02, UI-03 |
| **P05** | Indicaciones claras sobre la página de consulta QR | **Aaron** | Baja | — | UI-03 |
| **P06** | Página Acerca de: equipo y repositorio | **Abigail** | Baja | UI-01 | UI-02 |
| **P07** | Preparación de demostración en vivo con datos sintéticos | **Alessandro** | Media | TT-028, UI-07 | TT-025 |
| **P08** | Evidencias y conclusiones redactadas por el equipo | **Todos** | Compartida | UI-07 | TT-022, TT-025 |
| **P09** | Alta de ventanillas desde administración (incluye B1) | **Carlos** | Alta | G0 | UI-04, P02, S4-M04, TT-028 |

**Criterios de aceptación específicos:**

- **P01:** Cuando el turno pase a atendido, indicar explícitamente que la atención terminó y el cliente puede cerrar la pestaña; mantener actualización del estado existente, sin nuevos estados.
- **P02:** KPIs comprobables de cantidad, atención, abandono y tiempos con desgloses por fecha y ventanilla; gráficos por hora/periodo cuando haya datos y sin inventar un segundo servicio.
- **P04:** Nombre identificable y consistente en pantallas pertinentes; logo solamente si existe recurso aprobado. No equivale a multisucursal.
- **P05:** Texto corto sobre conservar enlace/página y recibir actualizaciones; evitar afirmar que cerrar o recargar cancela el turno.
- **P06:** Mostrar propósito, nombres del equipo y URL verificada del repositorio; no fabricar perfiles o datos institucionales.
- **P07:** Guion y entorno reproducibles: emitir, prioridad, llamar, atender, QR, historial, dashboard; datos precargados verificables, sin promesas de resultados.
- **P08:** Cada integrante documenta sus pruebas y conclusiones propias; Abigail consolida apartado de documentación, Aaron compila en presentación. No presentar texto artificial como experiencia del equipo.
- **P09:** Permitir crear ventanilla válida y utilizarla en llamadas/panel/historial/reportes; respetar exclusión de doble atención; no añadir edición/eliminación, login ni cambios de prioridades; validar catálogo, Mongo y Redis antes de migrar.

### C. Mejoras seleccionadas de Alessandro, sin duplicaciones (6)

| ID | Tarea | Responsable | Complejidad | Previas | Integración / cierre |
|---|---|---|---|---|---|
| **S4-M01** | A1: estimación histórica orientativa en consulta QR | **Alessandro** | Alta | G0 | UI-03 |
| **S4-M02** | A5: ticket imprimible por el navegador | **Aaron** | Media | UI-01 | UI-03 |
| **S4-M03** | B3: notas/motivo opcional de cierre | **Alessandro** | Media | G0 | UI-04, TT-028, TT-027 |
| **S4-M04** | C2: fechas y paginación de historial | **Carlos** | Media | — | P09, UI-05 |
| **S4-M05** | C3: reporte diario reproducible | **Carlos** | Media | P02 | TT-022 |
| **S4-M06** | D1: endpoint de salud limitado | **Alessandro** | Media | — | UI-07 |

**Criterios de aceptación específicos:**

- **S4-M01:** **Condicionada a autorización expresa del equipo**: el Plan Maestro excluye predicción de espera. Si se autoriza, usar datos reales, muestra suficiente, rótulo orientativo, cálculo reproducible y fallback sin datos; no implementar ni bloquear el release mientras siga sin aprobación.
- **S4-M02:** Vista CSS @media print con código, QR, prioridad y fecha/hora disponibles; impresión desde navegador, sin asumir impresora especial ni nuevas integraciones.
- **S4-M03:** Añadir controles y persistencia opcionales en cierre, compatibles con documentos anteriores. Carlos valida esquema Mongo; cinco estados existentes intactos; no modificar flujo Redis sin acuerdo.
- **S4-M04:** Controles de fecha y paginación sobre filtros existentes, orden y conteo coherentes, exportación JSON funcional. No implementar CSV por exclusión previa.
- **S4-M05:** Script invocable que genera Markdown o JSON con fechas y cifras verificables; documentar ejecución. No programar envío automático ni tareas recurrentes.
- **S4-M06:** Endpoint /salud con estado controlado de app/Redis/Mongo y códigos adecuados, sin exponer secretos, stack traces ni detalles de infraestructura.

### D. EP-09 — Diseño e integración visual (7)

| ID | Tarea | Responsable | Complejidad | Previas | Integración / cierre |
|---|---|---|---|---|---|
| **UI-01** | Design system / componentes CSS y especificación visual | **Abigail** | Media | — | P04, P06, UI-02, UI-03, UI-04, UI-05, UI-06 |
| **UI-02** | Página de inicio (F3), navegación y Acerca de | **Abigail** | Alta | UI-01 | P04, P06, UI-07 |
| **UI-03** | Quiosco, emisión, ticket y consulta QR: integración estética | **Abigail** | Alta | UI-01 | P01, P04, P05, S4-M01, S4-M02, UI-07 |
| **UI-04** | Cola, operación y pantalla pública | **Alessandro** | Alta | UI-01 | P09, S4-M03, UI-07 |
| **UI-05** | Dashboard e historial: interfaz de datos | **Carlos** | Media | UI-01 | P02, S4-M04, UI-07 |
| **UI-06** | Accesibilidad, responsive y páginas 403/404/500 (D5/F4) | **Abigail** | Media | UI-01, UI-02, UI-03, UI-04, UI-05 | UI-07 |
| **UI-07** | Pruebas de integración visual, regresión y capturas | **Aaron** | Media | UI-02, UI-03, UI-04, UI-05, UI-06, P09, S4-M04, S4-M06 | TT-022, P07, P08 |

**Criterios de aceptación específicos:**

- **UI-01:** Documentar tokens azul marino, azul grisáceo, turquesa, verde, blanco; tipografía, espaciado, botones, tarjetas, tablas, estados y contraste. Centralizar CSS y reutilizar plantillas sin cambiar contratos.
- **UI-02:** Portada limpia y navegación consistente; incorpora identidad institucional y Acerca de. Revisar ruta / y .htaccess para no exponer CRUD/administración públicamente; sin agregar autenticación nueva.
- **UI-03:** Retocar interfaz cliente y adaptar componentes de las aportaciones. Quiosco: panel Bienvenido **sólido**, vidrio discreto solo en opciones (15 % orientativo), fondo sobrio y sin decoración excesiva. Demás pantallas sin glassmorphism; código/QR siempre legibles.
- **UI-04:** Panel de operador, turnos y pantalla de sala con estética fintech sólida, estados distinguibles y controles claros; integrar nuevas ventanillas y notas si fueron aprobadas; no cambiar semántica de cola.
- **UI-05:** Tarjetas KPI, gráficos, tablas, filtros y paginación con paleta fintech, sin vidrio; preservar métricas reales, JSON y controles existentes.
- **UI-06:** Comprobar contraste, tamaños táctiles, foco y teclado, mensajes, móvil/desktop y pantalla de sala; páginas de error con códigos HTTP verdaderos y sin exponer trazas.
- **UI-07:** Ejecutar checklist guiada en pantallas principales y móvil, documentar evidencias/capturas y abrir defectos al dueño del módulo. Cada responsable verifica y corrige su propia funcionalidad; no sustituye pruebas técnicas de Redis/Mongo.

## 4. Dependencias reales y trabajo en paralelo
**Fase 0 — decisiones y preparación.** Resolver G0 para cambios de ventanillas/esquema; documentar responsable y compatibilidad. En paralelo iniciar UI-01, P01, P05, P02 (consultas de métricas), S4-M04, S4-M06 y borradores de README/presentación. **La parte no autorizada de S4-M01 no se programa.**

**Fase 1 — bases y trabajo independiente.** Tras UI-01, Abigail inicia UI-02/UI-03 y P06; Aaron realiza P04/S4-M02; Alessandro trabaja UI-04 y S4-M03 (tras G0); Carlos trabaja P09 (tras G0), P02, S4-M04 y TT-028 cuando corresponda. Las pantallas pueden desarrollarse en paralelo mediante interfaces existentes; su aceptación final depende de integrar datos/componentes correspondientes.

**Fase 2 — integración funcional y visual.** Cerrar enlaces P01/P05/S4-M02 con UI-03; P09/S4-M03 con UI-04; P02/S4-M04 con UI-05. Consolidar TT-027 y TT-028 después de estabilizar Redis/contrato Mongo. S4-M05 puede reutilizar métricas P02. Aplicar UI-06 sobre las pantallas ya integradas.

**Fase 3 — verificación.** UI-07 con el equipo corrigiendo sus propios módulos; evidencias y capturas; actualizar README final TT-022 y comprobar scripts. Aaron hace TT-021 **solo si no preparó el entorno probado**. P08 recoge conclusiones basadas en esas pruebas.

**Fase 4 — entrega.** Aaron finaliza TT-023, TT-025 y TT-026; Alessandro valida P07 y ejecuta TT-029 **después** de instalación reproducible y documentación. La demo es en vivo y el video permanece sujeto a la excepción documentada.

### Cadena de entrega (dependencias de cierre)
```text
 G0 ──> P09 ───────────> UI-04 ──┐
   └─> S4-M03 ─────────> UI-04   │
 UI-01 ──> UI-02, UI-03, UI-04, UI-05 ──> UI-06 ──> UI-07
 P02 + S4-M04 ─────────> UI-05   │               │
 P01/P04/P05/S4-M02 ──> UI-03   │               v
                                        TT-022 (README final)
 TT-028 (Mongo/datos sintéticos) ─────> TT-021 (instalación limpia)
 TT-022 (README final) ──────────────> TT-021
 UI-07 + P08 + P07 ──────────────────> TT-025 (presentación)
 TT-021 + TT-023 + TT-025 + TT-026 + UI-07 ──> TT-029 (release/tag)
```
El diagrama es un mapa de **cierre/integración**. El detalle preciso de qué bloquea el inicio de cada tarea está en la columna «Previas»; evita convertir una coordinación de integración en una espera innecesaria.

## 5. Plan de integración del diseño en el código (EP-09)
El rediseño **se implementa en los archivos reales de la aplicación**. Los mockups sirven de guía; la entrega debe reflejarse en las plantillas Jinja y el CSS de `development`. No se introduce un framework nuevo ni se alteran los contratos funcionales solamente por razones estéticas.

### 5.1 Mapa de intervención por tarea y archivo
| Tarea | Responsable | Archivos actuales de integración | Entrega visual comprobable |
|---|---|---|---|
| **UI-01** | **Abigail** | `static/style.css`; `app/templates/base.html`; `app/templates/base_publico.html` | Variables/tokens de colores, tipografía, espaciados, botones, tarjetas, tablas, navegación y estados; componentes reutilizables; guía visual breve. |
| **UI-02** | **Abigail** | `app/templates/base.html`; `app/templates/index.html`; `app/templates/demo.html` y plantilla nueva solo si la portada lo requiere | Inicio y navegación coherentes con la referencia Fintech; Acerca de (P06) e identidad (P04); protección de las rutas administrativas conservada. |
| **UI-03** | **Abigail** | `app/templates/quiosco.html`; `quiosco_confirmado.html`; `emitir.html`; `turno_confirmado.html`; `consultar.html`; `turno_qr.html`; `base_publico.html` | Quiosco con panel Bienvenido sólido y **15 % de glassmorphism discreto solo en tarjetas de elección**; emisión, ticket y consulta QR con superficies sólidas. |
| **UI-04** | **Alessandro** | `app/templates/cola.html`; `panel.html`; `pantalla.html`; componentes CSS compartidos | Cola, controles del operador y pantalla de sala consistentes; presentación de ventanillas (P09, de Carlos) y notas (S4-M03) cuando estén integradas. |
| **UI-05** | **Carlos** | `app/templates/dashboard.html`; `historial.html`; componentes CSS compartidos | KPIs, gráficos, filtros, tabla y paginación en estilo Fintech sólido; datos reales procedentes de P02 y S4-M04. |
| **UI-06** | **Abigail** | `static/style.css`; todas las plantillas afectadas; páginas de error nuevas **solo si se requieren** | Vista adaptable, contraste, foco teclado, tamaño táctil y páginas 403/404/500 sin fugas de información. |
| **UI-07** | **Aaron** | Sin archivo funcional propio; evidencia de pantallas y reporte de verificación | Lista de comprobación, capturas antes/después y defectos asignados a quien implementó cada pantalla. |

**Nota de precisión:** las rutas del repositorio se verificaron sobre la rama `development` al elaborar esta versión. Los nombres de archivos nuevos (p. ej., portada o páginas de error) solo se definen durante su implementación; no se presentan como archivos ya existentes.

### 5.2 Regla única de Glassmorphism
- El estilo general toma la paleta del referente **Fintech Dashboard UI — Md Iqbal Hasan**, con fondo limpio y paneles sólidos.
- En la pantalla **`/quiosco`**, el panel grande **«Bienvenido» es completamente sólido**. Solo las tarjetas de selección (Regular y Preferencial) podrán usar una leve transparencia, difuminado discreto, bordes suaves y sombra tenue: **15 % glassmorphism, como criterio visual orientativo, no fórmula de opacidad CSS**.
- No aplicar vidrio en el ticket, QR, consulta, operador, pantalla pública, inicio, dashboard ni historial. Evitar esferas, ondas, brillos y degradados agresivos en el fondo.
- Los estados de turno y las prioridades se distinguen por texto e indicadores, no solo por colores.

### 5.3 Cómo colaborarán sin pisarse el CSS
1. **Abigail (UI-01)** establece variables de tema y componentes en `static/style.css`, entrega una guía de uso breve y conserva las clases existentes cuando sea viable.
2. **Alessandro y Carlos (UI-04/UI-05)** trabajan sus propias plantillas y proponen estilos encapsulados por módulo. Los cambios al CSS compartido se coordinan con Abigail antes de integrarlos.
3. **Aaron (P01/P04/P05 y S4-M02)** se ocupa de contenidos y ticket imprimible. Coordina los textos/estados con UI-03 para que el rediseño no sobrescriba su trabajo.
4. **Abigail (UI-03)** elimina progresivamente estilos en línea del quiosco a favor de clases reutilizables, sin cambiar los valores de formulario, rutas o generación de turnos.
5. **UI-06/UI-07** verifican todas las pantallas al final; cada dueño corrige los defectos de su módulo. Ninguna tarea visual habilita cambios a Redis/Mongo por sí sola.

### 5.4 Orden de entrega visual y criterios de integración
| Orden | Trabajo | Condición de integración |
|---|---|---|
| **V1** | UI-01: base de colores y componentes | Variables y clases listas; demostración en quiosco y panel sin modificar lógica. |
| **V2 — paralelo** | UI-02, UI-03, UI-04 y UI-05 | Las cuatro vistas pueden avanzar simultáneamente, cada una en sus plantillas; dependen de V1. |
| **V3** | Contenidos y mejoras conectadas: P01, P04, P05, P06, P09, S4-M02, S4-M03, P02 y S4-M04 | Cada módulo muestra su funcionalidad real; lo condicionado no bloquea las pantallas básicas. |
| **V4** | UI-06: responsive, teclado y errores | Se revisan las pantallas ya integradas; las correcciones se devuelven a su dueño. |
| **V5** | UI-07: regresión y capturas | Se verifica escritorio, móvil y quiosco táctil; screenshots consistentes con aplicación real. |

**Aceptación del diseño:** se observa la paleta en todas las vistas; el quiosco conserva el panel Bienvenido sólido y el único vidrio ligero del sistema; las funciones anteriores siguen operativas; no aparecen accesos públicos nuevos al CRUD; los responsables dejan evidencia y capturas.

## 6. Interfaz y diseño aprobados: criterios de aceptación
La identidad de todas las pantallas usa como referencia **Fintech Dashboard UI — Md Iqbal Hasan**: azul marino `#0B111C`, azul grisáceo `#B8CBD8`, turquesa `#5BB6C5`, verde `#538573`, blanco suave `#F7F7F7`, como valores base referenciales ajustables si el contraste lo requiere.

- **Solo quiosco:** aproximadamente **15 % de Glassmorphism discreto** localizado en tarjetas de opciones; **85 % superficies sólidas**. Panel principal «Bienvenido» sólido. Fondo muy sobrio, sin burbujas, ondas grandes, halos intensos ni contraste agresivo.
- **Todas las demás pantallas:** estilo fintech limpio y sólido, **sin glassmorphism**: QR/consulta, ticket, operador, sala, dashboard, historial, portada, errores.
- Botones táctiles legibles, iconografía coherente, tipografía de alto contraste, foco visible, estados claros y jerarquía consistente. Ningún mockup autoriza funcionalidades que el sistema no tenga.

## 7. Riesgos, compatibilidad y verificación
| Control | Criterio para autorizar integración |
|---|---|
| Ventanillas (P09) | Revisar constantes, validación Mongo, selección en panel, claves Redis, exclusión concurrente, historial y métricas. **Solo crear** nuevas ventanillas; no asumir CRUD completo. |
| Notas/motivos (S4-M03) | Contrato opcional compatible con documentos anteriores; aprobación de Carlos y pruebas; sin cambiar los cinco estados. |
| Estimación (S4-M01) | La aprobación previa se registra explícitamente; si no se obtiene, queda como **no ejecutable** y fuera del release. |
| Página de inicio (UI-02) | Verificar la ruta raíz y protección Apache: mostrar landing no puede exponer el CRUD al público. No agregar login ficticio ni eliminar controles actuales. |
| Publicación | Sin credenciales en README, portal.yml, scripts ni capturas; datos sintéticos; versiones, evidencias y conclusiones reales. |
| Compatibilidad | Mantener estados `pendiente`, `llamado`, `en_atencion`, `atendido`, `abandonado`, prioridad vigente y TTL Redis de 180 s; no introducir servicios/sucursales extras. |
| Arrastres documentales de S3 | Revisar capturas, estado de `main` y tags anteriores indicados en S4.md; documentar qué corresponde cerrar antes del release. No crear tareas S4 ficticias por duplicado. |

## 8. Control final de cobertura
| Origen | Cantidad |
|---|---:|
| Tareas oficiales S4 ejecutables (TT-021–023 y TT-025–029) | 8 |
| Retroalimentación del profesor / P09 | 8 |
| Mejoras funcionales adicionales sin duplicación | 6 |
| Sistema visual e integración (EP-09) | 7 |
| **Total** | **29** |

**No contabilizados como tareas adicionales:** TT-024 (video excluido condicional a respaldo), B1 (integrado P09), C1 (P02/UI-05), D5 (UI-06), F3 (UI-02), F4 (UI-06), P03 (no seleccionado), G0 (decisión técnica).

**Siguiente control de gobernanza:** el equipo valida responsables y G0 antes de crear issues/branches. Este documento por sí mismo no modifica el repositorio ni concede aprobación para implementar la estimación de espera.
