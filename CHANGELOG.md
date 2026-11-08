# Registro de Cambios (CHANGELOG) - QLine

Todos los cambios notables en este proyecto están documentados en este archivo.
El formato se basa en [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y este proyecto se adhiere a [Semantic Versioning](https://semver.org/lang/es/).

Estado de versión actual: **v0.9.0** (release candidate del Seguimiento 4, 03/11/2026). La versión final **v1.0.0** se publica antes de la exposición del 10/11/2026. Los tags `v0.1.0`, `v0.2.0` y `v0.3.0` se crearon de forma retroactiva el 03/11/2026 sobre el último commit de cada seguimiento.

---

## [Sin publicar]

Para la **v1.0.0**: instalación desde cero verificada por una persona que no configuró el entorno, presentación final y, de forma opcional, el video de demostración.

### Documentación
- README: qué hacer cuando `python -m venv` falla con «ensurepip is not available» (servidor sin permisos de administrador): entorno sin `pip` y `get-pip.py`, o `virtualenv`.

### Añadido
- `scripts/crear_usuarios_demo.py`: crea los usuarios de demostración (administrador, supervisor y operador con su ventanilla) con contraseñas generadas que se muestran una sola vez para copiarlas al PDF de entrega. Idempotente, no escribe archivos y no pisa cuentas existentes; `--restablecer`, `--ventanilla` y `--sin-asignar` ajustan su comportamiento.

---

## [0.9.0] - 2026-11-03 (Seguimiento 4 · Release candidate y entrega a sucursal)

Incluye lo de la candidata `0.9.0-rc` (más abajo) y lo que se añadió después.

### Documentación y entrega
- **README profesional:** el problema y la solución, 8 capturas (`docs/img/`), quién usa QLine, funcionalidades, arquitectura con diagrama, instalación paso a paso (con la creación del primer administrador), variables de entorno, datos de prueba, tabla de mediciones, seguridad, roadmap y equipo.
- **`docs/arquitectura/arquitectura.md`:** diagrama de la aplicación y los motores, qué dato vive en cada motor y por qué, modelo de datos, flujos, consistencia entre motores, qué pasa si algo falla y mediciones.
- **`portal.yml` con el formato oficial del enunciado** (claves planas). Quedan por completar el día del grupo, el enlace del video y los autores públicos.
- **`scripts/verificar_entrega.py`:** revisa archivos obligatorios, ficha del portal, enlaces de la documentación, secretos versionados, tags y árbol de trabajo, e indica qué falta antes del release.
- **`docs/` limpia para la entrega:** se retiran los planes de trabajo internos, reportes personales, guiones y borradores (siguen en el historial de git); el plan de desarrollo pasa a `docs/plan/` y la especificación funcional a `docs/especificacion_funcional.md`. `scripts/verificar_ui07.py` ya no escribe su informe dentro de `docs/`.

### Añadido
- **Inicio de sesión del personal por rol (Fases 1 y 2):** `app/auth.py` guarda solo un hash `scrypt` de la contraseña, firma la sesión en una cookie `HttpOnly` y `SameSite=Lax`, bloquea 5 minutos tras 5 intentos fallidos y relee el usuario en cada petición, de modo que deshabilitarlo o cambiarle el rol surte efecto al instante. Páginas `/login`, `/registro` (queda pendiente hasta que el administrador la habilite) y `/salir`.
- **Permisos por rol:** operador (`/cola`, `/panel`), supervisor (además historial, dashboard y guía de demo) y administrador (además administración y sucursales). El cliente, el quiosco, la consulta por QR, la pantalla de sala y `/salud` siguen sin pedir sesión. El menú muestra solo lo que corresponde al rol, con el usuario y «Cerrar sesión». Los POST de personal comprueban que vengan de la misma página (`Sec-Fetch-Site`, con `Origin`/`Referer` de respaldo).
- **Gestión de usuarios y acceso (Fase 3):** pantalla `/admin/usuarios` para que el administrador habilite o rechace solicitudes (asignando el rol), deshabilite, cambie el rol y restablezca contraseñas. No puede deshabilitarse ni cambiarse el rol a sí mismo, ni dejar el sistema sin un administrador activo. Cada cambio cierra las sesiones abiertas de esa persona y anota quién lo hizo y cuándo. La portada de `/administracion` avisa cuántas solicitudes hay pendientes.
- **Asignación de ventanillas (Fase 4):** pantalla `/supervisor/asignaciones` para que el supervisor (o el administrador) asigne a cada operador su ventanilla. Una por operador y un operador por ventanilla, con índice único parcial en MongoDB; no se reasigna ni se quita con un turno `llamado` o `en_atencion`, y deshabilitar o cambiar de rol a un operador libera la suya.
- **El operador ya no elige ventanilla:** el servidor le impone la asignada al llamar, iniciar y finalizar (pedir otra responde 403); `/cola` le muestra «Usted atiende en la ventanilla V-0X» sin selector, `/panel` solo su ventanilla y, sin ventanilla asignada, «Pida a su supervisor que le asigne una». El supervisor y el administrador siguen eligiendo cualquiera, y llamar sin indicarla responde 422 como antes.
- **Vista interactiva del operador (Fase 5):** `/cola` pasa a ser su pantalla de trabajo, con el turno en curso y sus acciones (llamar, iniciar, finalizar con motivo y nota), la cola de espera con cuánto lleva esperando cada turno, y sus números (en espera, preferenciales, atendidos por él hoy y atención media). Se actualiza sola por WebSocket (con consulta cada 5 s si el socket cae y cada 30 s de respaldo), con cuenta regresiva de presentación, cronómetros, aviso de turnos preferenciales (sonido opcional), indicador «En vivo» y atajos `N`, `I` y `F` (esta última lleva el foco a «Finalizar» para confirmar con Intro). Funciona sin JavaScript como formularios. Nueva API `GET /api/operador/estado`; el supervisor y el administrador abren la misma vista de cualquier ventanilla con `/cola?ventanilla=V-0X`, y `/panel` de todas las ventanillas queda para supervisión (el operador que lo abre pasa a `/cola`).
- **Trazabilidad:** al llamar un turno se guarda en `operador` el usuario que lo llamó; el historial ya lo mostraba.
- **Nombre de usuario solo con letras:** acepta mayúsculas y minúsculas (de 3 a 30 letras de la A a la Z) y rechaza números, espacios, tildes y caracteres especiales, con un mensaje que explica la regla. «Ana» y «ana» siguen siendo la misma cuenta. Antes admitía minúsculas, números, punto, guion y guion bajo.
- `scripts/crear_admin.py` crea al primer administrador o le restablece la contraseña.
- `tests/test_acceso_roles.py` recorre todas las rutas contra la política y falla si aparece una sin clasificar; `tests/test_auth.py` y `tests/test_login.py` cubren el hash, la sesión, el bloqueo, el registro y el script; `tests/apoyo_sesion.py` da a las pruebas existentes un cliente con sesión.
- Variable de entorno `SECRETO_SESION` (ver README y `.env.example`).

### Seguridad
- Se desactivan `/docs`, `/redoc` y `/openapi.json`, que exponían el esquema de la API.
- Las rutas de diagnóstico (`/redis/estado`, `/ws-prueba`, `/api/eventos/*`) pasan a ser solo del administrador.
- La administración genérica de MongoDB oculta el hash de la colección `usuarios` y ya no permite insertar, editar ni eliminar sus documentos a mano (se gestionan en `/admin/usuarios`).
- El formulario de ingreso rechazaba a un navegador legítimo porque las páginas públicas piden `no-referrer` y el navegador envía entonces `Origin: null`; ahora la comprobación de origen usa `Sec-Fetch-Site`, con `Origin` y `Referer` de respaldo.
- Se detectó con la prueba de inventario una ruta `PUT /api/admin/sucursales/{codigo}` que habría quedado sin protección y se corrigió.
- En `/administracion` el nombre `usuario` del contexto (el usuario de MongoDB) chocaba con el de la sesión; el primero pasa a llamarse `usuario_mongo`.
- El encabezado con sesión pone la marca y el usuario arriba y el menú completo debajo, y no crece de más según el rol.

### Notas
- El `.htaccess` no se modifica (D-35): el Basic Auth de Apache sigue como puerta exterior, así que el personal verá además la clave de Apache y las páginas del cliente la seguirán pidiendo salvo el QR y `/static/`.

---

## [0.9.0-rc] - 2026-11-01 (Seguimiento 4 · candidata inicial; actualizada el 2026-11-02)

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
- **S4-M06 · Endpoint `/salud` (Alessandro):** `GET /salud` responde `{estado, app, redis, mongo, barrido}` con 200 si Redis y MongoDB responden y 503 si falla alguno, nunca 500 y sin datos de infraestructura (D-29). Evidencia con `scripts/probar_salud.py`: **verificado en el servidor** (5 casos).
- **S4-M03 · Motivo y nota opcionales de cierre (Alessandro):** al finalizar la atención el operador puede indicar un motivo de una lista cerrada y una nota de hasta 200 caracteres, guardados en el campo raíz opcional `cierre` en la misma escritura de la finalización; compatible con los turnos anteriores y sin cambiar los cinco estados (D-31). Formulario plegado en el panel. Evidencia con `scripts/probar_cierre.py`: **verificado en el servidor** (7 casos).
- **P09 · Ventanillas dinámicas (Carlos y Alessandro):** catálogo en MongoDB (colección `ventanillas`) con alta, desactivación y reactivación desde `/administracion` (Carlos), conectado a la operación (Alessandro): solo las ventanillas activas pueden llamar, aparecen en el panel y en `/cola`, y el historial filtra por cualquiera (`ventanillas_activas(db)`); la regla «una ventanilla, un turno» y las claves de Redis son las mismas para todas (D-30). Probado con 4 ventanillas simultáneas sin duplicados. Evidencia con `scripts/probar_ventanillas.py`: **verificado en el servidor**.
- **S4-M04 · Historial con fechas y paginación (Carlos):** filtros por rango de fechas, paginación y exportación JSON de lo filtrado.
- **P02 · Estadísticas de atención (Carlos y Alessandro):** dashboard con KPI de espera, atención y abandono, afluencia por hora con hora pico, rendimiento por ventanilla, bandas de espera, semáforo y diagnóstico operativo (Carlos); **desglose por fecha** con gráfico y tabla por día (turnos, atendidos, abandonados, % de abandono, espera y atención promedio y cumplimiento del SLA), en hora local, con filtro de rango `fecha_desde`/`fecha_hasta` también en `/api/dashboard` y en la descarga JSON (Alessandro).
- **S4-M05 · Reporte diario reproducible (Carlos):** `scripts/reporte_diario.py` genera el reporte de operación y SLA en JSON y Markdown.
- **TT-028 · Carga de release (Carlos, corregida por Alessandro):** `scripts/cargar_datos_release.py` carga una serie propia `L-NNN` de historial (solo turnos terminados), es idempotente y nunca escribe ni borra `A-NNN` ni `S-NNN`. **Verificado en el servidor** (50 turnos, sin tocar los existentes).
- **RFC-004 · Mantenimiento de sucursales (Carlos):** módulo y pantalla `/admin/sucursales` con capacidad parametrizable de ventanillas. **Extra del trabajo, no previsto en el plan alternativo** (que no incluye sucursales): solo cataloga sedes y aprovisiona sus ventanillas; la operación sigue siendo de un solo servicio y una sola sede (D-34).
- **UI-01 a UI-04 y UI-06 · Sistema de diseño y pantallas (Abigail y Alessandro):** paleta azul marino y turquesa con acentos, portada, «Acerca de», páginas 403/404/500 sin trazas, quiosco en tema claro con vidrio discreto solo en las tarjetas de elección, ticket compartido entre quiosco y emisión web, y cola, panel y sala con superficies sólidas y estados con texto y símbolo.
- **Acentos de color por módulo:** Cliente azul, Operador turquesa, Supervisor verde y Administración ámbar en el menú, la etiqueta y el título de cada pantalla interna, las tablas, los avisos y los gráficos del dashboard, con colores sólidos y contraste AA verificado por prueba.
- **`/administracion`:** el administrador de MongoDB pasa a su propia pantalla (D-33), con el panel de ventanillas y sucursales; `/` es la portada.
- **P07 · Preparación de la demostración (Alessandro):** `scripts/preparar_demo.py` comprueba el entorno y deja turnos en espera sin borrar nada; la guía `/demo` pasa a 25 pasos con cierre con nota, `/salud` y plan B.
- **TT-022 · README final (Alessandro):** arquitectura, requisitos, variables de entorno, instalación, operación, seguridad y documentación.
- **TT-027 · Mapa de claves de Redis revisado (Alessandro):** contrastado con el código integrado; `tests/test_redis_claves_doc.py` y `tests/test_redis_claves_codigo.py` impiden que el documento y el código se separen.

### Modificado
- `app/templates/turno_qr.html`: Actualización de mensajes para estado atendido, bloque de instrucciones de espera e integración de identidad institucional.
- `app/templates/quiosco_confirmado.html`: Incorporación de botón de impresión, marca institucional en ticket y suspensión del temporizador durante impresión.
- `app/templates/turno_confirmado.html`: Incorporación de botón de impresión y marca institucional en ticket.
- `static/style.css`: Inclusión de clases `.ticket-institucion`, `.btn-imprimir` y bloque `@media print` con diseño sobrio y de alto contraste.
- Esquema de `turnos`: el campo `ventanilla` pasa de una lista fija (`V-01` a `V-03`) al patrón `^V-\d{2,}$`, tanto en el JSON Schema como en el validador en memoria; las pruebas que usaban `V-99` como inválida usan `X-99`.
- `GET /redis/estado` responde solo `{"ok": true|false}`.
- La confirmación de `/emitir` usa la plantilla pública y ya no muestra al cliente la navegación de operación.

### Corregido
- **`/consultar` mostraba el formulario pero nunca el resultado:** el rediseño de UI-03 había quitado el bloque que pinta el turno. Se restituye con el diseño público (código, estado, prioridad, ventanilla y posición en la cola) y quedan pruebas del caso con turno, inexistente y mal escrito.
- **Ventanillas con código consecutivo:** el alta de una ventanilla (formulario de administración y `POST /api/ventanillas`) asigna siempre el siguiente `V-NN` (V-04, V-05… V-08), sin pedir ni aceptar el código. Cuenta también las inactivas para no reutilizar un código.
- Tras fusionar las ramas se habían perdido las variables de color `--c-*` y chocaban nombres de clase (`.contenedor`, `.nav`, `.paso`, `.ticket`): restauradas y resueltas; `tests/test_estilos.py` falla si una variable CSS se usa sin definir.
- La emisión web enviaba la prioridad `regular` en lugar de `normal`.
- La versión original de la carga de release (TT-028) sobrescribía la serie real `A-001` a `A-050` y su opción `--limpiar` borraba todos los turnos del servicio.
- Los enlaces y formularios nuevos no usaban el prefijo de despliegue (`BASE_PATH`) y se rompían bajo Apache.
- Las páginas de error y la ruta `/acerca` existían pero no estaban registradas.

### Seguridad
- `/salud`, `/redis/estado` y las páginas de error no revelan hosts, puertos, usuarios, versiones ni trazas; el detalle queda en el registro del servidor.
- Las notas de cierre se escapan siempre al mostrarse.
- `/administracion`, `/admin/sucursales` y las rutas de ventanillas siguen protegidas por Apache; solo el seguimiento por QR es público.

### Límites conocidos y no incluido
- **S4-M01 · Estimación de espera:** no se ejecutó; el Plan Maestro excluye la predicción y no hubo autorización escrita (D-32).
- **TT-024 · Video:** sustituido por la demostración en vivo; sujeto a la ratificación docente.
- **Validador de `turnos`:** el usuario del curso no puede ejecutar `collMod`; para aceptar ventanillas nuevas el validador de la colección debe actualizarse en el servidor (el equipo lo hizo y lo comprobó con `probar_ventanillas`). Una instalación nueva con `init_mongo` ya lo crea correcto.
- La consulta por código admite solo la serie `A-NNN`; los turnos sintéticos `S-NNN` y de release `L-NNN` no se consultan por código.
- Aún sin publicar: los tags `v0.2.0`, `v0.3.0` y el de esta versión (TT-029); capturas de pantalla; contra-firma de la instalación limpia (TT-021).

---

## [0.3.0] - 2026-10-26 (Seguimiento 3 · Concurrencia, Tiempo Real, Abandono y Movilidad)

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

## [0.2.0] - 2026-10-19 (Seguimiento 2 · Ciclo de Atención, Persistencia y Analítica)

### Añadido
- **TT-001 / TT-002 · Contrato estricto en MongoDB:** Esquema `$jsonSchema` estricto a nivel de colección (`turnos_schema.py`) y validador en memoria en Python.
- **TT-003 · Índices analíticos y operacionales:** Índices sobre `estado`, `ventanilla`, marcas de tiempo y código en MongoDB.
- **TT-005 · Generador de datos sintéticos:** Script reproducible `generar_datos_sinteticos.py` con generación determinista basada en semilla fija, validación de contrato y carga no destructiva.
- **HU-004 / HU-005 / HU-006 / HU-007 · Operación de ventanillas:** Flujo de atención (`iniciar_atencion`, `finalizar_atencion`) y vista de panel `/panel`.
- **HU-010 · Historial de turnos:** Vista de consulta paginada `/historial` con filtros multicriterio.
- **HU-011 · Dashboard analítico:** Indicadores de volumen, tiempos promedio de espera y porcentaje de cumplimiento de SLA en `/dashboard` calculados mediante aggregation pipelines en MongoDB.
- **Guía interactiva de demostración:** Ruta `/demo` para ejecución guiada paso a paso.

---

## [0.1.0] - 2026-10-13 (Seguimiento 1 · Fundaciones y Concurrencia Base)

### Añadido
- Estructura base de la aplicación con FastAPI y Jinja2.
- **TT-006 / TT-007 · Cola con prioridad en Redis:** Implementación de Sorted Set `grupo2:qline:cola:atencion_general` con cálculo de puntaje por nivel de prioridad y marca de tiempo en milisegundos.
- **D-02 · Extracción atómica:** Asignación garantizada sin duplicados mediante `ZPOPMIN`.
- **HU-001 / HU-002 · Emisión y consulta básica:** Emisión inicial de turnos (`/emitir`) y consulta por código (`/turno/{codigo}`).
- **TT-009 · Constantes unificadas:** Definición centralizada de estados, prioridades, servicios y ventanillas (`app/constantes.py`).
- Administrador básico de colecciones MongoDB para depuración de laboratorio.
- Licencia MIT y documentación inicial de arquitectura.
