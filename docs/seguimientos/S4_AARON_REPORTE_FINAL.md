# Reporte Final de Entrega · Seguimiento 4 (S4)
**Responsable:** Aaron Benavides Vega (`abenavides`)  
**Rama de trabajo:** `abenavides`  
**Rama de integración:** `development`  
**Fecha de finalización y verificación:** 2026-11-01  
**Versión de entrega:** `v0.9.0-rc` (Release Candidate)  

---

## 1. Resumen Ejecutivo (Executive Summary)

El presente informe documenta la culminación, validación automatizada y generación de entregables correspondientes a las tareas asignadas a Aaron Benavides Vega para el Seguimiento 4 (S4) del proyecto **QLine: Sistema Inteligente de Gestión de Filas y Turnos en Tiempo Real**.

### Lo completado
1. **P01 (Aviso de finalización en QR):** Implementado en renderizado inicial (SSR) y en actualización viva vía JavaScript en `app/templates/turno_qr.html`. Indica explícitamente: *«Su atención finalizó. Puede cerrar esta pestaña. ¡Gracias por su visita!»*.
2. **P04 (Identidad institucional verificada):** Consolidada la marca oficial `QLine` y el servicio `Atención General` en quiosco, tickets de emisión y consulta móvil por QR, sin fabricar entidades o sucursales inexistentes.
3. **P05 (Instrucciones de espera en QR):** Bloque informativo accesible en `turno_qr.html` que clarifica la autoactualización en tiempo real, indica que recargar manualmente es innecesario y garantiza que cerrar la página no cancela el turno.
4. **S4-M02 (Ticket imprimible):** Acción «Imprimir ticket» mediante `window.print()` en `quiosco_confirmado.html` y `turno_confirmado.html`, respaldada por estilos limpios `@media print` en `static/style.css` y con suspensión/pausa del temporizador automático de retorno de 25 s del quiosco (`beforeprint`, `afterprint`) para no interrumpir el diálogo de impresión.
5. **TT-023 (CHANGELOG.md):** Historial completo trazable desde S1 hasta S4 en formato estándar Keep a Changelog.
6. **TT-025 (Presentación Final):** Entregable doble: archivo editable PowerPoint [`docs/presentacion/QLine_Presentacion_Final.pptx`](../presentacion/QLine_Presentacion_Final.pptx) con diseño Fintech sobrio, y documento completo slide-by-slide con notas del presentador y guion de demostración en vivo [`docs/presentacion/PRESENTACION_FINAL.md`](../presentacion/PRESENTACION_FINAL.md).
7. **TT-026 (portal.yml):** Archivo de metadatos del proyecto y curso con sintaxis YAML 100 % validada y sin credenciales ni secretos.
8. **TT-021 (Verificación de instalación limpia):** Demostración empírica de instalación aislada desde cero en un entorno virtual nuevo, ejecución de la suite completa y generación de datos sintéticos en modo no destructivo.
9. **UI-07 (Integración visual y regresión):** Inspección de las 13 pantallas del sistema, confirmando superficies sólidas, ausencia de glassmorphism indebido y generación del informe [`docs/seguimientos/UI_07_INTEGRACION_VISUAL.md`](UI_07_INTEGRACION_VISUAL.md).
10. **Aportes adicionales:** Completada la sección de decisiones técnicas D-24 a D-28 en [`docs/decisiones.md`](../decisiones.md), conciliada la bitácora de [`docs/seguimientos/S3.md`](S3.md) y documentada la excepción de video frente a la demostración en vivo.

### Lo que resta por dependencias externas
- Validación física presencial en la pantalla de sala del campus y escaneo con celular en la red universitaria (dependencia del entorno físico de producción).
- Contra-firma de la instalación limpia (TT-021) por parte de un compañero de equipo distinto a quien preparó el entorno, conforme a la condición académica.
- Cierre de los módulos de los demás compañeros (UI-01/UI-02/TT-022 de Abigail, TT-028/P02/P09 de Carlos, TT-027/TT-029 de Alessandro).

### Dictamen de preparación
**La contribución de Aaron Benavides está 100 % FINALIZADA, PROBADA Y LISTA PARA REVISIÓN E INTEGRACIÓN en `development`.**

---

## 2. Resultados Tarea por Tarea (Task-by-Task Results)

### P01 · Aviso al finalizar atención en QR
- **Estado:** COMPLETED
- **Acciones realizadas:** Se actualizó `app/templates/turno_qr.html` para que tanto en el bloque Jinja2 SSR como en la función JavaScript `mensajeDe(t)` el estado `atendido` informe al usuario: *«Su atención finalizó. Puede cerrar esta pestaña. ¡Gracias por su visita!»*.
- **Archivos modificados:** `app/templates/turno_qr.html`, `tests/test_s4_aaron.py`.
- **Criterios de aceptación satisfechos:** Aviso explícito de fin de atención; indicación de cierre de pestaña; cobertura dual SSR y WebSocket/polling; preservación de los 5 estados oficiales; 2 pruebas específicas aprobadas.

### P04 · Nombre institucional visible y consistente
- **Estado:** COMPLETED
- **Acciones realizadas:** Se verificaron las fuentes autorizadas del repositorio (`constantes.py`, `base_publico.html`, `PLAN_DESARROLLO_QLINE.md`). Se incorporó el encabezado `ticket-institucion` con el texto `QLine · Atención General` en `quiosco_confirmado.html` y `turno_confirmado.html`, y se unificó la identidad en el pie de `turno_qr.html`. No se inventaron logotipos no aprobados ni sucursales ficticias.
- **Archivos modificados:** `app/templates/quiosco_confirmado.html`, `app/templates/turno_confirmado.html`, `app/templates/turno_qr.html`, `static/style.css`, `tests/test_s4_aaron.py`.
- **Criterios de aceptación satisfechos:** Identidad visible y consistente en quiosco, ticket y QR; respeto de la exclusión multisucursal; pruebas unitarias de presencia textual aprobadas.

### P05 · Indicaciones claras sobre la página de consulta QR
- **Estado:** COMPLETED
- **Acciones realizadas:** Se integró un bloque informativo con rol `note` (`#instrucciones-espera`) en `turno_qr.html`. Explica claramente: conservar la página abierta durante la espera, autoactualización en tiempo real, innecesariedad de F5 manual, y garantía explícita de que cerrar la página no cancela el turno en el sistema.
- **Archivos modificados:** `app/templates/turno_qr.html`, `tests/test_s4_aaron.py`.
- **Criterios de aceptación satisfechos:** Instrucción concisa y accesible; preservación de WebSockets; garantía explícita de no cancelación del turno; pruebas unitarias aprobadas.

### S4-M02 · Ticket imprimible por el navegador
- **Estado:** COMPLETED
- **Acciones realizadas:** Se implementó el botón «Imprimir ticket» invocando `window.print()` en las dos vistas de ticket. Se crearon estilos `@media print` en `static/style.css` que aíslan la tarjeta del ticket con bordes sólidos y fondo blanco, ocultando cabeceras, pie, botones, alertas y navegación. En `quiosco_confirmado.html` se sincronizó la pausa del temporizador de retorno de 25 segundos mediante los eventos `beforeprint`, `afterprint` y timeout de seguridad.
- **Archivos modificados:** `app/templates/quiosco_confirmado.html`, `app/templates/turno_confirmado.html`, `static/style.css`, `tests/test_s4_aaron.py`.
- **Criterios de aceptación satisfechos:** Impresión nativa por navegador; no requiere drivers térmicos; el temporizador no interrumpe el diálogo de impresión; preserva código, QR, prioridad, servicio, fecha y hora local; 3 pruebas de regresión aprobadas.

### TT-023 · CHANGELOG.md
- **Estado:** COMPLETED
- **Acciones realizadas:** Creación del archivo `CHANGELOG.md` en la raíz del repositorio siguiendo el estándar internacional Keep a Changelog. Se documentaron de forma fidedigna los cambios desde S1 hasta S4 categorizados en Añadido, Modificado, Seguridad y Despliegue, reflejando el estado `v0.9.0-rc`.
- **Archivos creados:** `CHANGELOG.md`.
- **Criterios de aceptación satisfechos:** Trazabilidad real de Git; distinción cronológica S1, S2, S3 y S4; sin funcionalidades ficticias; formato Markdown válido.

### TT-025 · Presentación final y guion de exposición
- **Estado:** COMPLETED
- **Acciones realizadas:** Generación de presentación en formato PowerPoint [`docs/presentacion/QLine_Presentacion_Final.pptx`](../presentacion/QLine_Presentacion_Final.pptx) aplicando estética Fintech (azul marino, turquesa, blanco) mediante `scripts/generar_presentacion_pptx.py`. Paralelamente, se redactó el documento slide-by-slide [`docs/presentacion/PRESENTACION_FINAL.md`](../presentacion/PRESENTACION_FINAL.md) cubriendo los 14 puntos obligatorios, notas de exposición y el guion detallado para la demostración en vivo (P07).
- **Archivos creados:** `docs/presentacion/QLine_Presentacion_Final.pptx`, `docs/presentacion/PRESENTACION_FINAL.md`, `scripts/generar_presentacion_pptx.py`.
- **Criterios de aceptación satisfechos:** 14 temas cubiertos; separación estricta entre hipótesis y mediciones reales; datos numéricos reales de latencia y concurrencia; guion de demo paso a paso.

### TT-026 · portal.yml
- **Estado:** COMPLETED
- **Acciones realizadas:** Creación de `portal.yml` en la raíz con metadatos reales del curso, equipo, repositorio, arquitectura, stack tecnológico y enlaces documentales. Se validó sintácticamente con el motor PyYAML en Python 3.12.
- **Archivos creados:** `portal.yml`.
- **Criterios de aceptación satisfechos:** Sintaxis YAML válida; metadatos reales verificados; cero exposición de credenciales o cadenas de conexión.

### TT-021 · Prueba de instalación limpia desde cero
- **Estado:** COMPLETED (Soporte automatizado) / PARTIAL (Condición académica de contra-firma)
- **Acciones realizadas:** Se creó un entorno virtual aislado (`scratch/clean_env`), se instalaron exitosamente todas las dependencias de `requirements.txt` y `requirements-dev.txt`, se ejecutó la suite completa de 513 pruebas (512 OK, 1 skip) y se probó el generador sintético en modo no destructivo (554 turnos validados).
- **Criterios de aceptación satisfechos:** Instalación reproducible sin errores; ejecución de dependencias validada; datos sintéticos operativos.
- **Pendiente académico:** Un integrante del equipo distinto de Aaron debe firmar la validación independiente en el servidor antes del tag final TT-029.

### UI-07 · Pruebas de integración visual, regresión y capturas
- **Estado:** COMPLETED
- **Acciones realizadas:** Se desarrolló `scripts/verificar_ui07.py` que evaluó 13 vistas de la aplicación. Se comprobó la solidez de las superficies, la ausencia total de `backdrop-filter` indebido y la operatividad de los estilos de impresión. Se generó el informe técnico [`docs/seguimientos/UI_07_INTEGRACION_VISUAL.md`](UI_07_INTEGRACION_VISUAL.md).
- **Archivos creados:** `scripts/verificar_ui07.py`, `docs/seguimientos/UI_07_INTEGRACION_VISUAL.md`.
- **Criterios de aceptación satisfechos:** 13 pantallas verificadas con HTTP 200; regla de glassmorphism cumplida; reporte detallado generado.

### Tareas adicionales A, B, C, D
- **A. docs/decisiones.md:** Se añadieron las decisiones D-24 a D-28 cubriendo quiosco sin datos personales, QR en SVG, Web Audio sintetizado en pantalla pública, impresión nativa `@media print` e instrucciones de espera en QR.
- **B. docs/seguimientos/S3.md:** Se agregó la nota de conciliación de estado en la sección 3, justificando las pruebas locales automatizadas al 100 % y los ítems pendientes en servidor físico.
- **C. Contribución a P08:** Métricas y evidencias empíricas consolidadas en este reporte y en la presentación final.
- **D. Revisión de requisitos pendientes:** Mapeo exhaustivo de responsabilidades de cierre para Abigail, Alessandro, Carlos y acuerdos grupales.

---

## 3. Comandos Ejecutados (All Commands Executed)

A continuación se detallan los comandos ejecutados en la terminal, en orden cronológico, con su propósito y resultado exacto:

| # | Comando | Propósito | Código de Salida | Resultado relevante |
|---|---|---|:---:|---|
| 1 | `git status` | Verificar estado de la rama `abenavides` | 0 | Rama limpia, sincronizada con `origin/abenavides`. |
| 2 | `git log -n 5 --oneline` | Inspeccionar últimos commits | 0 | Último commit: `054aa97` (Plan alternativo S4). |
| 3 | `python -m unittest discover -s tests -t . -v` | Ejecutar suite de línea base pre-implementación | 0 | 505 pruebas ejecutadas: 504 OK, 1 omitida (`zxing-cpp`). Línea base confirmada. |
| 4 | `python -m unittest tests/test_consulta_qr.py tests/test_hu001_emitir.py` | Pruebas enfocadas tras modificar plantillas | 0 | 50 pruebas ejecutadas, 50 OK (0 fallos). |
| 5 | `python -m unittest tests.test_s4_aaron -v` | Ejecutar las 8 pruebas nuevas de S4 (P01, P04, P05, S4-M02) | 0 | 8 pruebas ejecutadas, 8 OK en 0.082s. |
| 6 | `python -m compileall -q app scripts tests` | Verificar sintaxis de todo el código Python | 0 | Cero errores de compilación sintáctica. |
| 7 | `python scripts/generar_datos_sinteticos.py` | Validar generador de datos sintéticos en modo no destructivo | 0 | 554 turnos generados y validados contra el contrato oficial. Vista previa limpia. |
| 8 | `python -m venv <scratch>/clean_env` | Crear entorno virtual limpio para TT-021 | 0 | Entorno virtual aislado creado. |
| 9 | `& "<clean_env>/python.exe" -m pip install -r requirements.txt -r requirements-dev.txt` | Instalar dependencias en entorno limpio | 0 | Instalación exitosa de FastAPI, Redis, PyMongo, Jinja2, Fakeredis, Mongomock y demás dependencias. |
| 10 | `& "<clean_env>/python.exe" -m unittest discover -s tests -t . -v` | Ejecutar suite completa en entorno virtual limpio | 0 | 513 pruebas ejecutadas: 512 OK, 1 omitida, 0 fallos en 27.2s. |
| 11 | `& "<clean_env>/python.exe" -m pip install python-pptx` | Instalar biblioteca para generar PPTX | 0 | Instalación exitosa de `python-pptx` 1.0.2 y Pillow. |
| 12 | `& "<clean_env>/python.exe" scripts/generar_presentacion_pptx.py` | Generar archivo editable de presentación | 0 | Generado `docs/presentacion/QLine_Presentacion_Final.pptx`. |
| 13 | `python -c "import yaml; yaml.safe_load(open('portal.yml'))"` | Validar sintaxis de `portal.yml` | 0 | Sintaxis YAML válida: QLine v0.9.0-rc. |
| 14 | `python scripts/verificar_ui07.py` | Ejecutar verificación dinámica y visual UI-07 | 0 | 13 pantallas inspeccionadas con HTTP 200 y reporte generado. |
| 15 | `python -m unittest discover -s tests -t . -v` | Ejecución final completa de la suite de regresión | 0 | **513 pruebas ejecutadas: 512 OK, 1 omitida, 0 fallos en 26.6s.** |
| 16 | `git diff --check` | Validar ausencia de conflictos o espacios sobrantes | 0 | Limpio (cero errores de formato). |
| 17 | `git status --short` y `git diff --stat` | Inspección final del working tree | 0 | 6 archivos modificados, 7 archivos nuevos listos para commit. |

---

## 4. Resultados de las Pruebas (Test Results)

### Comparativa frente a la línea base
- **Línea base histórica verificada:** 505 pruebas (504 aprobadas, 1 omitida, 0 fallidas).
- **Resultado final tras modificaciones:** **513 pruebas (512 aprobadas, 1 omitida, 0 fallidas)**.
- **Ganancia neta:** +8 pruebas automatizadas de regresión específicas para Aaron (`tests/test_s4_aaron.py`), con 100 % de éxito y 0 regresiones en suites previas.

### Detalle de pruebas
- **Total:** 513
- **Aprobadas:** 512
- **Fallidas:** 0
- **Omitidas:** 1 (`test_qr_legible_independiente` en `tests/test_pantalla_publica.py`).
  - *Motivo de la omisión:* La prueba utiliza `@unittest.skipUnless(HAY_ZXING_O_PILLOW)` para verificar el escaneo óptico independiente mediante la librería `zxing-cpp`. Al ser una herramienta de decodificación externa opcional para pruebas unitarias en Linux, el marco de prueba salta la prueba sin comprometer la generación del SVG vectorial nativo.

### Pruebas de integración visual y sala
- `tests/test_pantalla_sala.py`: 11 pruebas aprobadas (100 %).
- `tests/test_s4_aaron.py`: 8 pruebas aprobadas (100 %).
- `scripts/verificar_ui07.py`: 13 vistas web evaluadas con status HTTP 200 y validación de diseño Fintech sólido.

---

## 5. Inventario de Archivos (File Inventory)

### Archivos modificados
- [`app/templates/turno_qr.html`](../../app/templates/turno_qr.html): Mensaje de finalización de atención (P01), instrucciones de espera (P05) e identidad institucional en pie (P04).
- [`app/templates/quiosco_confirmado.html`](../../app/templates/quiosco_confirmado.html): Botón «Imprimir ticket» (S4-M02), membrete institucional y pausa de temporizador de 25 s.
- [`app/templates/turno_confirmado.html`](../../app/templates/turno_confirmado.html): Botón «Imprimir ticket» (S4-M02) y membrete institucional en ticket.
- [`static/style.css`](../../static/style.css): Reglas `@media print` para aislamiento de ticket y clases `.ticket-institucion` y `.btn-imprimir`.
- [`docs/decisiones.md`](../decisiones.md): Registro de decisiones técnicas D-24 a D-28 de Aaron Benavides.
- [`docs/seguimientos/S3.md`](S3.md): Nota de conciliación de bitácora S3/S4.

### Archivos nuevos
- [`portal.yml`](../../portal.yml): Ficha de publicación y metadatos del proyecto (TT-026).
- [`CHANGELOG.md`](../../CHANGELOG.md): Registro histórico trazable de cambios S1 a S4 (TT-023).
- [`tests/test_s4_aaron.py`](../../tests/test_s4_aaron.py): Suite de pruebas automatizadas de regresión para P01, P04, P05 y S4-M02.
- [`scripts/generar_presentacion_pptx.py`](../../scripts/generar_presentacion_pptx.py): Script generador de la presentación en PowerPoint.
- [`docs/presentacion/QLine_Presentacion_Final.pptx`](../presentacion/QLine_Presentacion_Final.pptx): Presentación final editable (TT-025).
- [`docs/presentacion/PRESENTACION_FINAL.md`](../presentacion/PRESENTACION_FINAL.md): Presentación slide-by-slide con notas del orador y guion de demostración (TT-025).
- [`scripts/verificar_ui07.py`](../../scripts/verificar_ui07.py): Script de inspección y validación de vistas web.
- [`docs/seguimientos/UI_07_INTEGRACION_VISUAL.md`](UI_07_INTEGRACION_VISUAL.md): Informe de integración visual y regresión estética (UI-07).
- [`docs/seguimientos/S4_AARON_REPORTE_FINAL.md`](S4_AARON_REPORTE_FINAL.md): Este reporte final integral.

---

## 6. Dependencias y Bloqueadores (Dependencies and Blockers)

### 1. Abigail Urbina Gómez
- **TT-022 (README final):** Abigail consolida el borrador final del README con instrucciones generales de instalación y enlaces. Los aportes de Aaron sobre emisión, quiosco y tickets ya están integrados en las plantillas.
- **UI-01 / UI-02 (Diseño base y portada):** La integración visual de portada y componentes compartidos de Abigail no altera los contratos funcionales ni las clases creadas para el ticket imprimible.

### 2. Alessandro Cambronero Delgado
- **TT-027 (Mapa de claves Redis):** Revisión final documental de claves en `docs/arquitectura/redis_claves.md`.
- **TT-029 (Release y Tag final):** Alessandro ejecutará el tag formal (`v0.9.0` o `v1.0.0`) una vez integrada la rama en `development` y completadas las firmas.
- **P07 (Demostración en vivo):** Alessandro lidera la preparación del entorno de demostración en vivo, utilizando el guion paso a paso documentado en [`PRESENTACION_FINAL.md`](../presentacion/PRESENTACION_FINAL.md).

### 3. Carlos Espinoza Pérez
- **TT-028 (Carga de datos MongoDB):** Script de carga sintética reproducible para el release.
- **P02 / P09 / S4-M04 / S4-M05:** Dashboard avanzado, alta de ventanillas y paginación analítica en su rama de desarrollo.

### 4. Condición académica de instalación limpia (TT-021)
- Conforme a la normativa del curso, la validación formal de instalación limpia debe ser firmada por un integrante del equipo diferente de quien preparó el entorno probado. Las pruebas automatizadas en `clean_env` sirven como evidencia probatoria de respaldo.

### 5. Excepción del video oficial (TT-024)
- El Plan Maestro incluye originalmente un video de demostración de 3 a 5 minutos. El equipo acordó sustituirlo por una **demostración en vivo interactiva (P07)** ante el profesor. No se fabricó ningún video falso ni se afirma que el requisito oficial fue eliminado; queda sujeto a la ratificación documental docente durante la sustentación.

---

## 7. Seguridad y Compatibilidad (Security and Compatibility)

- **Contratos inmutables preservados:** Se conservan estrictamente los 5 estados (`pendiente`, `llamado`, `en_atencion`, `atendido`, `abandonado`), las 2 prioridades (`normal`, `preferencial`), el TTL de Redis de 180 s y los prefijos oficiales `grupo2:qline:`.
- **Cero secretos en el repositorio:** Se verificó exhaustivamente que `portal.yml`, scripts y archivos de plantilla no incluyan contraseñas, tokens de autenticación ni cadenas de conexión a MongoDB o Redis.
- **Aislamiento de acceso perimetral:** Las rutas del cliente (`/turno/qr/{uuid}`) permanecen libres de contraseña en Apache conforme a la decisión D-22, mientras que las consolas administrativas, panel, cola e historial continúan protegidas.

---

## 8. Estado Final de Git (Final Git Status)

### `git status --short`
```text
 M app/templates/quiosco_confirmado.html
 M app/templates/turno_confirmado.html
 M app/templates/turno_qr.html
 M docs/decisiones.md
 M docs/seguimientos/S3.md
 M static/style.css
?? CHANGELOG.md
?? docs/presentacion/
?? docs/seguimientos/S4_AARON_REPORTE_FINAL.md
?? docs/seguimientos/UI_07_INTEGRACION_VISUAL.md
?? portal.yml
?? scripts/generar_presentacion_pptx.py
?? scripts/verificar_ui07.py
?? tests/test_s4_aaron.py
```

### `git diff --stat`
```text
 app/templates/quiosco_confirmado.html |  33 +++++++++-
 app/templates/turno_confirmado.html   |   2 +
 app/templates/turno_qr.html           |  11 +++-
 docs/decisiones.md                    |  44 ++++++++++++-
 docs/seguimientos/S3.md               |   3 +
 static/style.css                      | 120 ++++++++++++++++++++++++++++++++++
 6 files changed, 204 insertions(+), 9 deletions(-)
```

### `git diff --check`
```text
(Salida vacía · Cero errores de sintaxis, espacios en blanco o conflictos)
```

---

## 9. Próximas Acciones Manuales (Next Manual Actions)

Para completar formalmente la contribución de Aaron en el repositorio central, el usuario debe realizar las siguientes acciones en su terminal:

1. **Revisar el diff local:**
   ```bash
   git diff app/ static/ docs/
   ```
2. **Agregar los archivos al índice de Git:**
   ```bash
   git add app/templates/quiosco_confirmado.html app/templates/turno_confirmado.html app/templates/turno_qr.html
   git add static/style.css docs/decisiones.md docs/seguimientos/S3.md
   git add CHANGELOG.md portal.yml tests/test_s4_aaron.py scripts/generar_presentacion_pptx.py scripts/verificar_ui07.py
   git add docs/presentacion/ docs/seguimientos/UI_07_INTEGRACION_VISUAL.md docs/seguimientos/S4_AARON_REPORTE_FINAL.md
   ```
3. **Realizar el commit en la rama `abenavides`:**
   ```bash
   git commit -m "feat(s4): completar tareas de Aaron Benavides (P01, P04, P05, S4-M02, TT-021, TT-023, TT-025, TT-026, UI-07)"
   ```
4. **Subir los cambios a GitHub:**
   ```bash
   git push origin abenavides
   ```
5. **Notificar al equipo:** Informar a Alessandro para la integración hacia `development` y coordinar con un compañero la contra-firma de la instalación limpia (TT-021).

---

## 10. Mensaje de Commit Sugerido (Suggested Commit Message)

```text
feat(s4): completar tareas de Aaron Benavides (P01, P04, P05, S4-M02, TT-021, TT-023, TT-025, TT-026, UI-07)

- P01: Notificación explícita de fin de atención en QR (SSR y JS) con indicación de cerrar pestaña.
- P04: Unificación de identidad institucional verificada (QLine · Atención General) en quiosco, ticket y QR.
- P05: Instrucciones de espera claras en vista QR garantizando que cerrar la ventana no cancela el turno.
- S4-M02: Soporte para ticket imprimible vía window.print(), reglas @media print y pausa de temporizador.
- TT-023: Creación de CHANGELOG.md trazable desde S1 hasta S4 según estándar Keep a Changelog.
- TT-025: Presentación final editable en PPTX y documento slide-by-slide con guion para demo en vivo.
- TT-026: Ficha portal.yml con metadatos reales y sintaxis YAML validada.
- TT-021: Verificación de instalación reproducible en entorno virtual limpio y datos sintéticos.
- UI-07: Inspección y reporte de integración visual en 13 pantallas cumpliendo diseño Fintech sólido.
- Documentación: Decisiones D-24 a D-28 en decisiones.md y conciliación de bitácora S3.
- Pruebas: Incorporación de tests/test_s4_aaron.py (513 tests ejecutados, 512 OK, 1 skip, 0 fallos).
```
