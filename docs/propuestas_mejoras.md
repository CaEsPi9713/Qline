# QLine · Propuestas de mejora para hablar con el equipo

**Estado:** borrador para discutir. Nada de esto está hecho ni aprobado.
**Criterio:** tareas de dificultad media (1 a 3 días de trabajo de una persona), sin cambios de arquitectura, que se apoyan en lo que ya existe y que se pueden demostrar en la exposición. Las tareas obligatorias de S4 (README, `CHANGELOG.md`, `portal.yml`, video, instalación desde cero) tienen prioridad sobre todo lo de aquí; ver [`S4.md`](seguimientos/S4.md).

Escala de esfuerzo: **S** = medio día, **M** = 1 a 2 días, **L** = 2 a 3 días.

---

## 1. Propuestas

### A. Experiencia del cliente

| # | Mejora | Qué aporta | Esfuerzo | Dónde toca |
|---|---|---|---|---|
| A1 | **Posición y tiempo estimado en la página del QR** («Hay 3 personas antes que usted · espera aprox. 12 min») | Es lo primero que el cliente quiere saber. El tiempo se calcula con la mediana de atención del historial (Mongo) y las posiciones, con la cola (Redis) | M | `consulta_qr`, `turno_qr.html`, aggregation sobre `turnos` |
| A2 | **Aviso cuando se acerca el turno** (vibración y mensaje en la página del QR cuando faltan 2 turnos o al ser llamado) | Hace útil el WebSocket que ya funciona y evita que el cliente esté mirando el celular | S | `turno_qr.html` (JS), evento ya publicado |
| A3 | **Cancelar el turno desde el QR** («Ya no voy a esperar») | Cierra el ciclo del cliente, reduce abandonos falsos y reutiliza el estado `cancelado` | M | ruta nueva pública con UUID, `.htaccess`, cola Redis |
| A4 | **Pantalla de sala con anuncio por voz** (`speechSynthesis` del navegador: «Turno A-014, ventanilla 2») | Efecto muy visible en la demo, sin dependencias nuevas | S | `pantalla.html` |
| A5 | **Impresión del ticket** (CSS de impresión con QR, hora y posición) | El quiosco queda completo | S | `quiosco_confirmado.html`, `style.css` |

### B. Operación y atención

| # | Mejora | Qué aporta | Esfuerzo | Dónde toca |
|---|---|---|---|---|
| B1 | **Varias ventanillas con nombre** (Ventanilla 1, 2, 3) y panel por ventanilla | Hoy la atención es de ventanilla única; esto muestra mejor la concurrencia con Redis | L | `main.py`, claves de ventanilla, `panel` |
| B2 | **Pausar y reanudar una ventanilla** (descanso) y **pasar al final de la cola** a quien no responde | Funciones reales de un sistema de turnos | M | cola Redis (`ZADD`), panel |
| B3 | **Notas y motivo de cierre** al terminar una atención (campo opcional y lista de motivos) | Datos más ricos para el dashboard | S | esquema `turnos` (opcional), panel, historial |
| B4 | **Servicios configurables** desde un archivo o colección (nombre, letra de serie, prioridad) | Quita valores fijos del código y facilita la demostración con otro caso (banco, clínica) | M | `datos_prueba`, quiosco, `turnos_schema` |

### C. Datos, dashboard y reportes

| # | Mejora | Qué aporta | Esfuerzo | Dónde toca |
|---|---|---|---|---|
| C1 | **Gráficos en el dashboard** (turnos por hora, espera promedio por servicio, abandono por día) con una librería ligera de gráficos | Hace visible el trabajo de agregaciones de Carlos | M | `dashboard.html`, endpoints existentes |
| C2 | **Filtros y paginación en el historial** (por fecha, estado, servicio) y **descarga CSV** además de JSON | Resuelve la deuda de exportar todo en memoria (S4 §4.2) | M | `historial.py`, `historial.html` |
| C3 | **Informe diario automático** (resumen en Markdown o JSON generado por un script) | Evidencia reproducible y material para la presentación | S | `scripts/` |

### D. Calidad y profesionalismo

| # | Mejora | Qué aporta | Esfuerzo | Dónde toca |
|---|---|---|---|---|
| D1 | **Endpoint `/salud`** (estado de Mongo, Redis, barrido y versión) y panel de estado | Una operación seria lo tiene; sirve para la demo y el despliegue | S | `main.py` |
| D2 | **Registro estructurado (logging)** de llamados, abandonos y rehidrataciones | Trazabilidad y menos `print` | S | módulos de cola y barrido |
| D3 | **Integración continua** con GitHub Actions: ejecuta `python -m unittest discover` en cada PR | Demuestra calidad y evita romper `development` | S | `.github/workflows/test.yml` |
| D4 | **Límite de peticiones** en la emisión pública (por IP, con Redis) | Evita que alguien llene la cola; usa una estructura de Redis más | M | emisión web, Redis `INCR` + `EXPIRE` |
| D5 | **Diseño responsive y accesibilidad** (contraste, foco, etiquetas, lectores de pantalla) en quiosco, QR y pantalla | Mejora la percepción de calidad | M | plantillas y `style.css` |
| D6 | **Cierre de deuda técnica de S4**: consulta por cualquier serie, vigencia del `qr_token`, acotar `/static/` en `.htaccess` | Cierra riesgos ya identificados | M | `consulta_qr`, `.htaccess` |

---

## 2. Qué recomiendo priorizar

Pocas piezas, de alto efecto en la demo y con riesgo bajo:

1. **A1 (posición y tiempo estimado)**: es la mejora más visible para el cliente.
2. **A2 (aviso al acercarse el turno) y A4 (voz en sala)**: bajo esfuerzo y muy lucidoras.
3. **C1 (gráficos del dashboard)**: muestra MongoDB trabajando.
4. **D1 (`/salud`) y D3 (integración continua)**: aspecto profesional con poco trabajo.
5. **D6 (deuda técnica)**: lo que ya sabemos que está pendiente.

Dejaría **B1 (varias ventanillas)** solo si sobra tiempo: toca el corazón de la cola y la regla de ventanilla única, y es lo que más puede romper lo ya verificado.

## 3. Reparto sugerido (para discutir)

| Integrante | Área natural | Propuestas |
|---|---|---|
| Alessandro | Redis, cola, tiempo real | A2, A3, B2, D1, D4 |
| Aaron | Cliente y pantallas | A4, A5, D5 |
| Carlos | MongoDB e historial | A1 (cálculo del tiempo), C1, C2, C3 |
| Abigail | Abandono, recuperación, pruebas | D2, D3, D6 |

## 4. Reglas para no poner en riesgo la entrega

- Cada mejora va en su propia rama, con **pruebas automáticas** y su PR a `development`.
- Nada de lo nuevo se marca como «verificado en el servidor» sin ejecutarlo allá (convención de S3).
- Si una mejora cambia el esquema de MongoDB, se documenta en `decisiones.md` y se avisa antes: el servidor no actualiza el esquema de una colección ya creada.
- **Congelar funcionalidades** una semana antes de la entrega para dejar tiempo a README, video e instalación desde cero.
- Ninguna mejora debe debilitar la protección del `.htaccess`: toda ruta pública nueva (como A3) se limita al patrón con UUID y se agrega a `tests/test_htaccess.py`.

## 5. Preguntas para el equipo

1. ¿Cuántos días reales quedan antes de congelar funcionalidades?
2. ¿Se busca tag `v0.9.0` o `v1.0.0`? Con `v1.0.0` conviene incluir al menos A1 y C1.
3. ¿Aceptamos las propuestas que añaden dependencias de interfaz (gráficos)? Habría que fijar versión y cargarla de un CDN permitido.
4. ¿La pantalla de sala y el quiosco se quedan detrás de la contraseña de Apache o se abren? Afecta A4.
5. ¿Quién revisa cada PR? Propongo que nadie apruebe el suyo.

---

# Parte II · De demo a producto: sesiones por rol

**Punto de partida (verificado en el código):** hoy la aplicación no tiene usuarios ni sesiones. Lo único que protege el acceso es la contraseña Basic de Apache (`.htaccess`), que es una sola para todos, y las rutas del QR que quedan públicas (D-22). Cualquiera que entre puede llamar turnos, ver el historial y hasta borrar documentos (`/insertar`, `/actualizar`, `/eliminar`, `/crear_coleccion`). Eso sirve para enseñarlo al profesor, pero no para una entrega final.

**Objetivo:** que la entrega se comporte como un sistema real. El cliente y la pantalla de sala no inician sesión; el personal sí, y cada rol ve solo lo suyo.

## 6. Roles y qué ve cada uno

| Rol | ¿Inicia sesión? | Qué puede hacer | Rutas actuales |
|---|---|---|---|
| **Cliente** | No | Sacar turno (web o quiosco), ver su turno por QR, cancelarlo (A3) | `/emitir`, `/quiosco`, `/turno/qr/{token}`, `/api/turnos/qr/{token}`, `/ws/turno/qr/{token}` |
| **Pantalla de sala** | No | Solo mostrar los llamados (datos sin información personal) | `/pantalla`, `/api/llamados`, `/ws/eventos` |
| **Operador** (ventanilla) | Sí | Llamar, iniciar y finalizar atención, ver la cola | `/panel`, `/cola`, `/cola/llamar`, `/api/llamar`, `/api/atencion/*` |
| **Supervisor** | Sí | Monitoreo en solo lectura: cola, historial, dashboard, descargas | `/cola`, `/historial`, `/dashboard`, `/api/historial*`, `/api/dashboard*`, `/api/cola` |
| **Administrador** | Sí | Todo lo anterior, gestión de usuarios y herramientas técnicas | el resto (`/demo`, `/redis/estado`, CRUD de Mongo) |

Reglas de diseño:
- Lo público se define por **lista cerrada** (cliente y pantalla); todo lo demás exige sesión.
- Un rol superior incluye los inferiores.
- Las rutas del cliente siguen identificándose por UUID (`qr_token`), sin cuenta.

## 7. Propuestas de sesiones y roles

| # | Mejora | Qué aporta | Esfuerzo |
|---|---|---|---|
| E1 | **Colección `usuarios`** (usuario, nombre, rol, ventanilla, hash de contraseña, activo) con índice único sobre `usuario` y esquema JSON | Base del control de acceso; usa MongoDB como el resto del modelo | M |
| E2 | **Contraseñas con hash** usando `hashlib.scrypt` o `pbkdf2_hmac` de la biblioteca estándar, con sal por usuario | Sin dependencias nuevas; la contraseña nunca se guarda ni se muestra | S |
| E3 | **Sesión en Redis**: al iniciar sesión se crea `grupo2:qline:sesion:<id>` (Hash con usuario y rol) con TTL de 8 h y se entrega en una cookie `HttpOnly`, `SameSite=Lax` y `Secure` | Funciona con varios *workers* de Gunicorn, caduca sola, permite cerrar sesión de verdad y es otra estructura de Redis en uso | M |
| E4 | **Pantallas `/login` y `/logout`** y una página de inicio que redirige según el rol (operador a `/panel`, supervisor a `/dashboard`, administrador a un menú) | Es lo primero que ve el personal; sustituye al índice técnico actual | S |
| E5 | **Dependencia `requiere_rol(...)` de FastAPI** en cada ruta, con 401 (sin sesión) o 403 (rol insuficiente) y redirección al login en las páginas | Cierra el acceso en la propia aplicación | M |
| E6 | **Menú por rol** en `base.html`: cada quien ve solo sus enlaces, su nombre y el botón de cerrar sesión | Percepción de producto terminado | S |
| E7 | **Operador atado a una ventanilla**: al iniciar sesión se le asigna la suya y el panel llama en su nombre | Conecta con B1 (varias ventanillas) y con la regla de ventanilla única | M |
| E8 | **Bitácora de quién hizo qué**: el turno guarda `llamado_por` y `atendido_por`, y el historial lo muestra | Trazabilidad real; amplía el esquema (ver riesgos) | M |
| E9 | **Token CSRF** en los formularios POST y **límite de intentos de inicio de sesión** con `INCR` + `EXPIRE` en Redis | Seguridad mínima esperable; reutiliza D4 | M |
| E10 | **WebSocket del personal autenticado**: `/ws/eventos` valida la cookie para operador y supervisor; la pantalla de sala usa un canal público que solo lleva códigos | Resuelve el riesgo abierto de S4 §4.1 (bucle de contraseña) | M |
| E11 | **Gestión de usuarios** para el administrador (crear, desactivar, cambiar rol, reiniciar contraseña) | Evita editar la base a mano | M |

## 8. Separar «demo» de «entrega final»

Hoy conviven en la misma aplicación las herramientas de demostración y las de operación. Para la entrega:

| # | Mejora | Qué aporta | Esfuerzo |
|---|---|---|---|
| F1 | **Variable `MODO_DEMO`** (apagada por defecto). Apagada, `/demo`, `/ws-prueba`, `/redis/estado` y el CRUD de Mongo responden 404; encendida, solo el administrador entra | La entrega no expone herramientas de prueba y la demo sigue disponible cuando se necesite | S |
| F2 | **Script `scripts/crear_usuarios.py`** que crea el administrador inicial leyendo la contraseña de una variable de entorno o pidiéndola por consola; los usuarios de ejemplo (operador, supervisor) solo en modo demo | Instalación reproducible sin contraseñas en el repositorio | S |
| F3 | **Página de inicio pública sobria** (nombre del sistema, botón «Sacar turno», enlace «Acceso del personal») en lugar del índice técnico | Primera impresión de producto | S |
| F4 | **Páginas de error 403, 404 y 500** con plantilla propia | Pulido | S |
| F5 | **Pruebas de autorización**: una prueba por ruta que confirma qué rol entra y cuál no (la tabla de la sección 6 convertida en prueba) | Evita que una ruta nueva quede abierta por olvido, como `tests/test_htaccess.py` hace con Apache | M |
| F6 | **Revisar el `.htaccess`**: con login propio, la contraseña de Apache deja de ser la protección principal | Ver la decisión abierta de la sección 11 | S |

## 9. Orden sugerido (de menos a más riesgo)

1. **F5 como tabla de rutas y roles**: define qué es público y qué no antes de tocar nada.
2. **E1, E2, F2**: usuarios y contraseñas, sin afectar todavía a nadie.
3. **E3, E4, E5**: sesión, login y protección de rutas, en una rama aparte.
4. **E6, E7, E10**: menú, ventanilla por operador y WebSocket autenticado.
5. **F1, F3, F4**: modo demo y pulido.
6. **E8, E9, E11**: autoría, CSRF y gestión de usuarios, si hay tiempo.

Un buen corte de entrega es **E1 a E6 + F1 + F2 + F5**: sesiones reales por rol, demo aislada y una prueba que garantiza el control de acceso.

## 10. Reparto sugerido (para discutir)

| Integrante | Propuestas |
|---|---|
| Alessandro | E3, E5, E10 (sesión en Redis, dependencias de rol, WebSocket) |
| Carlos | E1, E8, E11 (colección `usuarios`, esquema, autoría en el historial) |
| Aaron | E4, E6, F3, F4 (login, menú por rol, inicio y errores) |
| Abigail | E2, E9, F2, F5 (contraseñas, CSRF, script de usuarios, pruebas de autorización) |

## 11. Riesgos y decisiones abiertas

1. **Contraseña de Apache frente a login propio.** El servidor del curso protege el sitio con `.htpasswd`. Si se mantiene, el personal tendría dos contraseñas y el WebSocket seguiría con el problema del bucle. Opciones: (a) quitar el Basic de Apache y proteger con el login propio, lo que hay que **consultar con el profesor**; (b) mantenerlo solo como candado de la fase de pruebas. Recomiendo (a) para la entrega, con F1 y E5 ya activos para que no quede nada abierto.
2. **Cambio de esquema.** `llamado_por` y `atendido_por` (E8) y la colección `usuarios` (E1) requieren crear o actualizar validadores en el servidor, que no se actualizan solos en una colección existente. Hacerlo con un script y una decisión nueva en `decisiones.md`.
3. **Contraseñas e información sensible.** Nunca en el repositorio, en `docs/` ni en `.env.example`. El administrador inicial se crea con F2.
4. **Pantalla de sala y quiosco sin sesión.** Quedan públicos por diseño, igual que el QR. El quiosco permite emitir turnos, así que conviene el límite de peticiones (D4).
5. **Tiempo.** Es un cambio transversal que toca todas las rutas. Hacerlo en una sola rama de integración y no mezclarlo con las mejoras de la Parte I hasta que esté estable.
6. **Verificación.** Probar en el servidor, con un celular y con dos navegadores a la vez (operador y supervisor), antes de marcar nada como hecho.

## 12. Preguntas adicionales para el equipo

1. ¿Aceptamos los cuatro roles (cliente, operador, supervisor, administrador) o basta con operador y administrador?
2. ¿Consultamos al profesor sobre quitar la contraseña de Apache? Sin su respuesta, la entrega depende del riesgo 1.
3. ¿Habrá una sola ventanilla o varias (B1)? Cambia cómo se asigna el operador.
4. ¿Los usuarios de ejemplo se dejan en la entrega o solo en modo demo?
