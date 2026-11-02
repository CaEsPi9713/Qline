# Registro de Cambios (CHANGELOG) - QLine

Todos los cambios notables en este proyecto están documentados en este archivo.
El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

Estado de versión actual: **v0.9.0-rc** (Candidato a release de Seguimiento 4, pendiente de acuerdo final de release del equipo TT-029).

---

## [0.9.0-rc] - 2026-11-01 (Seguimiento 4 · Release Candidate)

### Añadido
- **P01 · Aviso de finalización en QR:** Notificación explícita al cliente cuando el turno pasa a estado `atendido` indicando que la atención ha finalizado y que puede cerrar la pestaña del navegador (`app/templates/turno_qr.html`). Soportado en renderizado inicial (SSR) y en actualización dinámica vía JavaScript.
- **P04 · Identidad institucional verificada:** Integración consistente de la marca oficial `QLine` y del servicio único `Atención General` en todas las vistas de cara al cliente (quiosco táctil, ticket y consulta por QR), sin inventar organizaciones o sucursales externas.
- **P05 · Instrucciones de espera en consulta QR:** Sección informativa accesible que explica la actualización automática en tiempo real, indica que no se requiere recarga manual y aclara expresamente que cerrar la pestaña no cancela el turno en cola.
- **S4-M02 · Ticket imprimible por navegador:** Acción funcional «Imprimir ticket» mediante `window.print()` en las vistas de confirmación de quiosco (`quiosco_confirmado.html`) y emisión (`turno_confirmado.html`), acompañada de reglas `@media print` en `static/style.css` que aíslan el ticket y ocultan cabeceras, botones, temporizadores y elementos decorativos.
- **S4-M02 · Control de temporizador de quiosco:** Pausa automática del temporizador de retorno a pantalla inicial durante el diálogo de impresión mediante los eventos `beforeprint`, `afterprint` y timeout de seguridad.
- **TT-026 · Ficha portal.yml:** Archivo estructurado con metadatos del proyecto, equipo, stack tecnológico, arquitectura y enlaces de documentación, validado sintácticamente y libre de credenciales o secretos.
- **TT-023 · CHANGELOG.md:** Registro histórico trazable de cambios desde Seguimiento 1 hasta Seguimiento 4.
- **TT-025 · Presentación final y guion:** Material de exposición y demostración en vivo con separación estricta entre hipótesis teóricas iniciales y mediciones reales documentadas.
- **Tests S4 Aaron:** Suite de pruebas automatizadas específicas (`tests/test_s4_aaron.py`) para validar P01, P04, P05 y S4-M02.

### Modificado
- `app/templates/turno_qr.html`: Actualización de mensajes para estado atendido, bloque de instrucciones de espera e integración de identidad institucional.
- `app/templates/quiosco_confirmado.html`: Incorporación de botón de impresión, marca institucional en ticket y suspensión del temporizador durante impresión.
- `app/templates/turno_confirmado.html`: Incorporación de botón de impresión y marca institucional en ticket.
- `static/style.css`: Inclusión de clases `.ticket-institucion`, `.btn-imprimir` y bloque `@media print` con diseño sobrio y de alto contraste.

---

## [0.3.0] - 2026-10-27 (Seguimiento 3 · Concurrencia, Tiempo Real, Abandono y Movilidad)

### Añadido
- **HU-003 / HU-013 · Consulta por código QR móvil:** Generación de SVG de código QR en quiosco y emisión; endpoint público de consulta `/turno/qr/{uuid}` y API JSON asociada.
- **D-13 · Índice parcial único para QR:** Creación de `idx_turnos_qr_token_unico` sobre `turnos` con expresión de filtro parcial para compatibilidad 100 % no destructiva con registros antiguos.
- **D-03 · Ventanilla única con reserva atómica:** Mecanismo `SET NX EX 10` en Redis junto con verificación de MongoDB para prevenir asignación concurrente de múltiples turnos a una misma ventanilla.
- **TT-011 / D-04 · Hash de turno llamado con TTL:** Estructura Hash en Redis (`grupo2:qline:turno:{codigo}`) con expiración a los 180 s para gobernar el tiempo de presentación del cliente.
- **D-05 / D-07 · Notificaciones Pub/Sub y WebSocket:** Canal `grupo2:qline:eventos` con difusión WebSocket (`/ws/eventos` y `/ws/turno/qr/{uuid}`) y sondeo de respaldo HTTP cada 3 s.
- **HU-008 · Detección y barrido de abandono:** Hilo daemon periódico que detecta turnos cuyo plazo de 180 s expiró en Redis y los transiciona idempotentemente a `abandonado` en MongoDB.
- **HU-012 · Reconciliación y recuperación de cola:** Script `recuperacion.py` para sincronizar turnos `pendiente` desde MongoDB hacia Redis tras una pérdida o reinicio sin vaciar datos.
- **HU-009 · Pantalla pública de llamados:** Interfaz `/pantalla` de sala con reloj local, sonidos Web Audio, indicador en vivo y visualización adaptativa.
- **D-15 · Descarga de historial en JSON:** Endpoint `/api/historial/descargar` con exportación completa de registros filtrados.
- **D-23 · Localización horaria:** Módulo `app/formato.py` con filtros Jinja2 para mostrar fechas y horas legibles en zona horaria local (`America/Costa_Rica`).

### Seguridad y Despliegue
- **D-22 · Excepción controlada en Apache (.htaccess):** Acceso público sin credenciales exclusivamente a las tres rutas del QR (`/turno/qr/{uuid}`, `/api/turnos/qr/{uuid}`, `/ws/turno/qr/{uuid}`) y recursos estáticos, preservando autenticación básica en panel, cola, historial y administración.

---

## [0.2.0] - 2026-10-18 (Seguimiento 2 · Ciclo de Atención, Persistencia y Analítica)

### Añadido
- **TT-001 / TT-002 · Contrato estricto en MongoDB:** Esquema `$jsonSchema` estricto a nivel de colección (`turnos_schema.py`) y validador en memoria en Python.
- **TT-003 · Índices analíticos y operacionales:** Índices sobre `estado`, `ventanilla`, marcas de tiempo y código en MongoDB.
- **TT-005 · Generador de datos sintéticos:** Script reproducible `generar_datos_sinteticos.py` con generación determinista basada en semilla fija, validación de contrato y carga no destructiva.
- **HU-004 / HU-005 / HU-006 / HU-007 · Operación de ventanillas:** Flujo de atención (`iniciar_atencion`, `finalizar_atencion`) y vista de panel `/panel`.
- **HU-010 · Historial de turnos:** Vista de consulta paginada `/historial` con filtros multicriterio.
- **HU-011 · Dashboard analítico:** Indicadores de volumen, tiempos promedio de espera y porcentaje de cumplimiento de SLA en `/dashboard` calculados mediante aggregation pipelines en MongoDB.
- **Guía interactiva de demostración:** Ruta `/demo` para ejecución guiada paso a paso.

---

## [0.1.0] - 2026-10-08 (Seguimiento 1 · Fundaciones y Concurrencia Base)

### Añadido
- Estructura base de la aplicación con FastAPI y Jinja2.
- **TT-006 / TT-007 · Cola con prioridad en Redis:** Implementación de Sorted Set `grupo2:qline:cola:atencion_general` con cálculo de puntaje por nivel de prioridad y marca de tiempo en milisegundos.
- **D-02 · Extracción atómica:** Asignación garantizada sin duplicados mediante `ZPOPMIN`.
- **HU-001 / HU-002 · Emisión y consulta básica:** Emisión inicial de turnos (`/emitir`) y consulta por código (`/turno/{codigo}`).
- **TT-009 · Constantes unificadas:** Definición centralizada de estados, prioridades, servicios y ventanillas (`app/constantes.py`).
- Administrador básico de colecciones MongoDB para depuración de laboratorio.
- Licencia MIT y documentación inicial de arquitectura.
