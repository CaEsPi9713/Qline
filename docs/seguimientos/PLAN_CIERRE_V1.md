# Plan de cierre · Entrega final v1.0.0

**Proyecto:** QLine · Grupo 2 / Query Logic · **Perfil B** (MongoDB + Redis)
**Fuente:** *Proyecto Final Open Source — Enunciado y Seguimientos* (secciones 2, 4, 5, 6 y 7)
**Elaborado:** 03/11/2026 · **Estado:** en ejecución. Avance del 03/11/2026: hecho C1 (`arquitectura.md`), C3 (README profesional), C4 (8 capturas con datos de demostración), C6 (`portal.yml` oficial: grupo de martes, video opcional y autores sin publicar), C7 (CHANGELOG cerrado en `[0.9.0]`), C8 (`S4.md` como bitácora; S1 a S3 cerradas), B3 (`scripts/crear_usuarios_demo.py`) y la limpieza de `docs/`; nuevo `scripts/verificar_entrega.py` (lista lo que falta antes del tag). **Retirar este archivo de `docs/seguimientos/` antes del tag `v1.0.0`**: es un documento de trabajo del equipo
**La presentación (`.pptx`) la prepara otro compañero y queda fuera de este plan**; en la sección 8 va la lista de lo que debe saber para actualizarla.

> Convención de las bitácoras: «verificado en el servidor» es lo ejecutado con MongoDB y Redis reales; «prueba automática» es la suite de `tests/` con simulados.

---

## 1. Qué hay que entregar y cuándo

| Hito | Martes | Viernes | Qué se entrega |
|---|---|---|---|
| **Seguimiento 4** (semana 16) | 3 nov | 6 nov | `docs/seguimientos/S4.md` + tag `v0.9.0`, antes de las 6:00 p.m. Opcional si el grupo adelanta y expone en la semana 16 (entonces entrega `v1.0.0`) |
| **Exposición y entrega final** (semana 17) | 10 nov | 13 nov | Release `v1.0.0` en GitHub **y** PDF `Proyecto_Final_Grupo_2.pdf` en el Aula Virtual, ambos **antes de las 6:00 p.m. del día en que se expone**. Los commits posteriores al tag no cuentan |

Ponderación: seguimientos 40 % (el S4 vale 10 %), **repositorio y documentación 20 %**, **exposición y demo en vivo 25 %**, asistencia a las semanas 16 y 17 15 %.

**Rúbrica del repositorio (20 %):** instalación reproducible solo con el README **30**, README y arquitectura **25**, datos, pruebas y mediciones **20**, buenas prácticas open source **15**, historial de equipo **10**. La instalación reproducible es lo que más pesa y es lo que menos hemos comprobado.

---

## 2. Dónde estamos frente al enunciado

| # | Entregable (sección 5) | Estado hoy | Brecha |
|---|---|---|---|
| 1 | **Repositorio**: código, licencia, `.gitignore`, `.env.example`, estructura, commits de todos | **Casi.** MIT, `.gitignore` y `.env.example` correctos; sin secretos en todo el historial (revisado); 4 integrantes con commits y PR #1 a #8 | `main` está **57 commits atrás** de `development` (su último merge es del 13/10). El copyright de `LICENSE` es solo de Carlos. El código vive en `app/` y no en `src/` (se explica en el README). **No se pudo comprobar si hay Issues y un Project con hitos** (no hay `gh` instalado): revisarlo a mano en GitHub |
| 2 | **README** completo | **Parcial.** 14 secciones, variables y rutas al día | Faltan **capturas**, **video**, **roadmap**, quién usa el sistema y el inicio de sesión por roles. Cifras viejas («más de 590 pruebas», «D-01 a D-34»). Su instalación **nunca la probó otra persona** (TT-021) |
| 3 | **Datos** | **Listo.** `init_mongo`, `generar_datos_sinteticos`, `cargar_datos_release` (serie `L-NNN`, idempotente), sin datos personales | Falta repetir `cargar_datos_release` en el servidor y comprobar 0 insertados y 0 actualizados |
| 4 | **Arquitectura**: diagrama, motores, flujos y responsabilidad de cada motor | **Parcial.** El README trae un esquema y hay documentos sueltos (`redis_claves`, `tiempo_real`, `qr_consulta`) | Falta **un documento único** con diagrama, flujos, qué dato vive en cada motor, qué pasa si uno falla y cómo se mantienen consistentes, ya con usuarios y roles |
| 5 | **Pruebas**: normal, error de conexión, datos inválidos y **tabla de mediciones con su interpretación** | **Parcial.** Suite de 984 pruebas e informes en `docs/evidencia/` | Falta un documento que los reúna y los **interprete**. Informes del servidor sin traer al repositorio: `salud.md`, `cierre.md` |
| 6 | **Demo**: video de 3 a 5 minutos enlazado en el README | **No existe.** | Grabarlo. La guía `/demo` quedó **anterior al inicio de sesión**: hay que adaptarla |
| 7 | **Release**: tag `v1.0.0` como Release de GitHub con `CHANGELOG.md` | **No existe ningún tag**, ni `v0.1.0`, `v0.2.0`, `v0.3.0` ni `v0.9.0` (ni local ni en GitHub). `CHANGELOG.md` sí existe | Crear los 3 tags atrasados (S1, S2 y S3), `v0.9.0` y `v1.0.0` |
| 8 | **Roadmap** (1 mes, 6 meses, trabajo final de graduación) | **No existe.** | Escribirlo en el README |
| 9 | **Bitácoras** `S1.md` a `S4.md` | S1 a S3 existen. **`S4.md` sigue en formato de plan** («por empezar») | Convertirlo al formato de bitácora (completado con enlaces, pendiente y por qué, bloqueos, decisiones y responsables) |
| 10 | **`portal.yml`** | Existe, pero **no usa el formato oficial** del enunciado (es una estructura anidada propia) | Reescribirlo con las claves oficiales: `nombre`, `resumen`, `problema`, `usuarios`, `motores`, `lenguaje`, `licencia`, `repositorio`, `demo_video`, `demo_url`, `captura`, `grupo`, `dia`, `periodo`, `autores_publicos`. La `captura` y el video no existen aún |
| — | **PDF** `Proyecto_Final_Grupo_2.pdf` | **No existe.** | Portada con **cédulas**, enlaces, credenciales de prueba y la presentación exportada |

**Servidor:** `https://grupo2.crnube.net/proyecto/qline/` ya tiene el inicio de sesión (las fases 1 a 4 se ven desplegadas). La vista interactiva del operador y el aviso nuevo de `/cola` hay que confirmarlos.

---

## 3. Plan por fases

Responsables **propuestos**; el equipo los confirma. Cada tarea indica cómo se sabe que está hecha.

### Fase A · Dejar el repositorio publicable (primero, hoy)

| # | Tarea | Resp. | Hecho cuando |
|---|---|---|---|
| A1 | PR `acambronero` → `development` con todo lo acumulado y aprobación de otra persona | Alessandro / revisa Abigail | PR aprobado y fusionado, suite en verde |
| A2 | PR `development` → `main` (hoy `main` es del 13/10) | Alessandro / revisa Aaron | `main` contiene el estado a entregar |
| A3 | Pedir a cada integrante que confirme **qué commit marca** S1, S2 y S3. Candidatos según el historial: `v0.1.0` → `f53c771` (13/10, hoy punta de `main`), `v0.2.0` → `7934ecf` (PR #2, 18/10), `v0.3.0` → `7182058` (26/10) | Equipo | Tres hashes acordados |
| A4 | Crear y subir los tags atrasados `v0.1.0`, `v0.2.0`, `v0.3.0` (anotados) y dejarlo escrito en `S1.md`, `S2.md` y `S3.md` (la fecha del tag será de hoy y se explica) | Equipo (sube quien tenga permisos) | `git ls-remote --tags origin` los lista |
| A5 | Revisar en GitHub: **Issues** con responsable, un **hito por seguimiento** y un Project. Si faltan, crearlos con la lista de tareas de `S1` a `S4` (TT-xxx) y cerrar los hechos con enlace al commit | Aaron | Backlog visible, hitos S1 a S4 cerrados |
| A6 | `LICENSE`: copyright del equipo («Query Logic · Grupo 2» y los 4 nombres) en lugar de solo Carlos | Equipo decide | `LICENSE` actualizado |
| A7 | Corregir la incoherencia de puerto: `qline.service` usa el 8001 y el `.htaccess` pasa al 18002 (ya anotada en el README). Una instalación limpia tropezaría ahí | Alessandro | README, servicio y `.htaccess` coinciden |

### Fase B · Servidor listo y verificado

| # | Tarea | Resp. | Hecho cuando |
|---|---|---|---|
| B1 | Desplegar el código final; poner `SECRETO_SESION` en el `.env` del servidor; reiniciar | Alessandro | `/salud` responde y el inicio de sesión funciona |
| B2 | Verificaciones pendientes del inicio de sesión (D-35): ingreso y POST de personal detrás de Apache, índices únicos de `usuarios` (nombre y ventanilla), WebSocket de la vista del operador | Alessandro | Cada una anotada como «verificado en el servidor» con fecha |
| B3 | Crear **usuarios de demostración** con nombres de solo letras (por ejemplo `administrador`, `supervisor`, `operador`) y contraseñas que **solo van en el PDF**, nunca en el repositorio. Propuesta: `scripts/crear_usuarios_demo.py`, que lee las contraseñas del entorno | Alessandro | Los tres roles entran y el operador tiene ventanilla asignada |
| B4 | Verificaciones heredadas: `preparar_demo`, `reporte_diario`, segunda ejecución de `cargar_datos_release` (debe dar 0 y 0), vista previa de impresión del ticket, pantallas rediseñadas con Ctrl+F5 | Carlos (datos) y Abigail (pantallas) | Resultado anotado en `S4.md` |
| B5 | Regenerar en el servidor las evidencias que faltan y traerlas al repositorio: `salud.md` y `cierre.md` (y comprobar `ventanillas_dinamicas.md`) | Alessandro / Carlos | Archivos en `docs/evidencia/` generados por sus scripts, no escritos a mano |
| B6 | **Apache:** el profesor debe poder entrar. Mientras el `.htaccess` siga pidiendo contraseña, el PDF lleva **también** la clave de Apache de pruebas. Decidir si se abren al público las rutas del cliente | Equipo | Una persona ajena entra con solo lo que dice el PDF |

### Fase C · Documentación (20 % de la nota y el 25 % de la exposición dependen de esto)

| # | Tarea | Resp. | Hecho cuando |
|---|---|---|---|
| C1 | **`docs/arquitectura/arquitectura.md`:** diagrama de la aplicación y los motores (Mermaid, que GitHub dibuja), los flujos (emitir, llamar, atender, abandono, recuperación, inicio de sesión), **qué dato vive en cada motor y por qué**, modelo de datos (colecciones `turnos`, `ventanillas`, `sucursales`, `usuarios`; mapa de claves de Redis), consistencia entre motores y tabla de **qué pasa si cae Redis o MongoDB**. Responde las 4 preguntas de la sección 3 del enunciado | Alessandro con Carlos | Enlazado desde el README |
| C2 | **`docs/pruebas.md`:** casos normal, error de conexión y datos inválidos (con el informe que los respalda) y la **tabla de mediciones** (al menos 3 operaciones, 3 ejecuciones o más, mediana) **con su interpretación** | Carlos y Abigail | Cada medición enlaza a su informe y dice qué demuestra |
| C3 | **README final:** quién usa QLine (cliente, operador, supervisor, administrador), inicio de sesión y roles, creación del primer administrador, capturas, video, roadmap, equipo y aportes, cifras al día (984 pruebas, D-01 a D-35), enlace a `arquitectura.md` y a `pruebas.md`, y una nota de que las credenciales de prueba están en el PDF | Abigail (dueña de TT-022) con Alessandro | `tests/test_readme.py` en verde y revisado por otra persona |
| C4 | **Capturas** en `docs/img/` (portada, quiosco, ticket con QR, consulta móvil, sala, vista del operador, asignaciones, dashboard, usuarios) tomadas del servidor y **sin credenciales ni datos reales a la vista**. Una de ellas es la `captura` del `portal.yml` | Abigail y Aaron | Insertadas en el README |
| C5 | **Roadmap:** 1 mes (por ejemplo, restablecer contraseña por el propio usuario, exportes, más servicios), 6 meses (varias sedes con colas por sucursal a partir del RFC-004, aviso por mensaje al celular, copias de seguridad) y como trabajo final de graduación | Todos aportan, Aaron redacta | Sección en el README |
| C6 | **`portal.yml` oficial** con las claves del enunciado y `autores_publicos` **solo con quienes lo autoricen**; `demo_url` con la dirección del servidor | Aaron | Formato idéntico al del enunciado |
| C7 | **`CHANGELOG.md`:** cerrar `[Sin publicar]` como `[1.0.0]` con fecha | Aaron | Coincide con el release |
| C8 | **`S4.md` como bitácora** y actualizar `docs/decisiones.md` | Alessandro y Aaron | Cumple el contenido mínimo del enunciado |
| C9 | Adaptar la guía **`/demo`** y `P07_PREPARACION_DEMO.md` al inicio de sesión (entrar como operador, supervisor y administrador) | Alessandro | Un ensayo completo sigue la guía sin saltos |

### Fase D · Instalación desde cero (30 puntos de la rúbrica)

| # | Tarea | Resp. | Hecho cuando |
|---|---|---|---|
| D1 | Clonar en un equipo limpio y seguir **solo el README**: entorno virtual, `pip install`, `.env`, `init_mongo`, carga de datos, primer administrador, arrancar, iniciar sesión, correr la suite | **Una persona que no haya configurado el entorno** (propuesta: Aaron o Abigail) | Se anotan el equipo, la fecha, cada tropiezo y su corrección en `docs/evidencia/instalacion_limpia.md` |
| D2 | Corregir el README con lo que falló y **repetir** con otra persona o en un equipo distinto | Quien hizo D1 y otra persona | Segunda instalación sin tropiezos |
| D3 | La prueba del QR exige `zxing-cpp`, que no está en `requirements-dev.txt`: incluirlo o aclararlo | Alessandro | La suite corre completa en el equipo limpio |

### Fase E · Video de demostración (3 a 5 minutos)

| # | Tarea | Resp. | Hecho cuando |
|---|---|---|---|
| E1 | Guion de 5 minutos: problema, sacar turno en el quiosco, QR en el celular, operador llama e inicia, finalización con nota, sala, supervisor (dashboard y asignación) y administrador (usuarios) | Alessandro | Guion cronometrado |
| E2 | Grabar con datos de demostración y **sin credenciales a la vista**; subirlo a un sitio que el profesor pueda abrir sin cuenta (YouTube en modo no listado o equivalente) | Quien se ofrezca | Enlace probado desde una ventana privada |
| E3 | Poner el enlace en el README, en `portal.yml` y en el PDF | Aaron | Los tres coinciden |

### Fase F · Congelar, etiquetar y entregar

| # | Tarea | Resp. | Hecho cuando |
|---|---|---|---|
| F1 | **Congelar el código** un día antes. Después solo se corrigen errores | Equipo | Acordado en el canal |
| F2 | Lista previa: suite en verde, `git status` limpio, búsqueda de secretos en el árbol, `test_readme` y enlaces, instalación limpia ya repetida | Alessandro | Lista marcada |
| F3 | Fusionar a `main` y crear el tag anotado `v1.0.0`; **publicarlo como Release de GitHub** con las notas tomadas del `CHANGELOG.md` | Equipo, con confirmación de todos | La página del Release existe y el tag apunta al commit final |
| F4 | **PDF** `Proyecto_Final_Grupo_2.pdf`: portada (curso, nombre del proyecto, grupo 2, día, **nombres completos y cédulas** de los 4), enlaces al repositorio y al Release v1.0.0, enlace al video, URL de la aplicación, **credenciales de prueba** (las de Apache y las de los tres roles; nunca las de MongoDB, GitHub ni el servidor) y la presentación exportada a PDF | Alessandro arma todo menos la presentación; el compañero entrega el PDF de la presentación | Un solo archivo con el nombre exacto |
| F5 | Subir el PDF al Aula Virtual | Un integrante | Comprobante de entrega |

### Fase G · Exposición (20 a 25 min + 5 de preguntas, todos participan, cámara encendida)

| Bloque | Tiempo | Quién propone |
|---|---|---|
| Problema, usuario y alcance | 2-3 min | Aaron |
| Arquitectura: qué dato vive en cada motor y por qué | 4-6 min | Carlos y Alessandro |
| **Demo en vivo** del flujo principal (no se acepta solo video) | 8-10 min | Alessandro (operación) con Abigail (interfaz) |
| Pruebas y mediciones | 3-4 min | Carlos |
| Lecciones aprendidas y roadmap | 3-4 min | Aaron y Abigail |

- **Dos ensayos completos con cronómetro**, el segundo con la guía `/demo` y el plan B (video corto de respaldo y capturas) a mano.
- El profesor puede pedir **un cambio pequeño en datos, consulta o código** durante la demo. Preparar cinco ejemplos y que cada uno sepa hacerlos en su parte: cambiar el umbral del SLA, dar de alta una ventanilla, filtrar el historial por otra prioridad, agregar un motivo de cierre, cambiar el tiempo de abandono.
- Cada integrante debe poder **explicar su parte y su código**; con tarjetas de preguntas probables por persona.

---

## 4. Calendario

Hoy es **martes 3 de noviembre**.

| Día (martes / viernes) | Qué se hace |
|---|---|
| **Hoy** | Fase A completa. **Si el grupo es de martes y no expone, el S4 vence hoy a las 6:00 p.m.:** `S4.md` honesto y tag `v0.9.0`; lo que falte pasa a la v1.0.0 (lo atrasado puede completarse en el siguiente, pero los puntos no se recuperan) |
| Mié 4 (o jue 5) | Fase B: despliegue, verificaciones, usuarios de demostración y evidencias del servidor |
| Jue 5 y vie 6 (o vie 6 y sáb 7) | Fase C: arquitectura, pruebas y mediciones, README, roadmap, `portal.yml`, capturas. **Si el grupo es de viernes, el S4 vence el vie 6 a las 6:00 p.m.** |
| Sáb 7 (o dom 8) | Fase D: instalación desde cero, primera ronda |
| Dom 8 (o lun 9) | Fase E: video; D2, segunda instalación; primer ensayo |
| Lun 9 (o jue 12) | **Congelar el código**; segundo ensayo; F2 |
| **Mar 10 (o vie 13)** | Tag `v1.0.0`, Release y PDF **antes de las 6:00 p.m.** (meta: tag a las 12:00 y PDF a las 3:00 p.m.) y exposición |

Si hay posibilidad de exponer ya en la **semana 16**, el enunciado dice que se entrega directamente `v1.0.0`; con el estado actual no lo recomiendo, porque instalación limpia, video y documentación aún no existen.

---

## 5. Riesgos

| Riesgo | Por qué importa | Qué hacer |
|---|---|---|
| Nadie ha probado el README | 30 puntos de la rúbrica; es lo que más suele fallar | Fase D con alguien que no configuró nada, y repetirla |
| Los tags atrasados salen con fecha de hoy | El profesor verá tags tardíos de S1 a S3 | Decirlo en las bitácoras, sin ocultarlo |
| `main` desactualizada | Quien clone `main` obtendría un proyecto de hace tres semanas | A2 antes de cualquier otra cosa |
| Apache pide clave | El profesor no podría entrar a la demo desplegada | B6: clave en el PDF y comprobación con una persona ajena |
| Credenciales en capturas o video | Rúbrica de «sin secretos» | Revisar cada imagen y cada fotograma antes de publicar |
| Cambio de último momento después del tag | Los commits posteriores no cuentan | Congelar el código un día antes |
| Pruebas que solo pasan con servicios simulados | El enunciado pide evidencia real | Mantener los informes del servidor generados por sus scripts |

---

## 6. Qué cubre cada punto de la rúbrica

| Criterio | Puntos | Se cubre con |
|---|---|---|
| Instalación reproducible solo con el README | 30 | Fase D, A7, B1 y C3 |
| README y documentación de arquitectura | 25 | C1, C3, C4 y C5 |
| Datos, pruebas y mediciones documentadas | 20 | B4, B5, C2 y los scripts de carga |
| Buenas prácticas open source | 15 | A6, C6, C7, F3 y el análisis de secretos (F2) |
| Historial de trabajo en equipo | 10 | A1 a A5 (PR, issues, hitos) |
| Demo en vivo (exposición, 35) | 35 | Fases B, C9, E y G |
| Justificación de arquitectura (25) | 25 | C1 y el bloque de arquitectura de la exposición |
| Dominio técnico y cambios pedidos (20) | 20 | Preparación de cambios pequeños en la Fase G |

---

## 7. Decisiones que necesito del equipo

1. **¿Martes o viernes?** Define si el S4 vence hoy o el viernes y qué columna del calendario aplica.
2. **¿Se expone en la semana 16 o en la 17?** Recomendado: semana 17.
3. **Cédulas y nombres completos** de los cuatro, para la portada del PDF.
4. **Autores públicos:** quién autoriza que su nombre aparezca en el portal.
5. **Copyright de `LICENSE`:** «Query Logic · Grupo 2» o los cuatro nombres.
6. **Dónde se aloja el video** (propuesta: YouTube no listado).
7. **Quién hace la instalación desde cero** (debe ser alguien que no haya configurado el entorno).
8. **¿Existen Issues y un Project con hitos en GitHub?** No pude comprobarlo desde aquí.
9. **Apache:** ¿se deja la contraseña para todo, o se abren las rutas del cliente para la demo?

---

## 8. Insumos para quien prepara la presentación

No se hace aquí, pero esto cambió desde la última versión del `.pptx`:

- Inicio de sesión con tres roles (operador, supervisor, administrador) y registro con aprobación del administrador; el cliente y la sala no necesitan sesión.
- El supervisor asigna la ventanilla de cada operador; el operador ya no elige.
- Nueva vista del operador: turno en curso, cola en vivo, avisos y atajos de teclado.
- Gestión de usuarios y acceso por el administrador.
- RFC-004 (sucursales) es un **extra**, no multisucursal real (D-34).
- Cifras: más de 1000 pruebas automáticas, decisiones D-01 a D-35.
- Arquitectura: Redis decide lo que ocurre ahora, MongoDB conserva lo que ocurrió; lo que pasa si Redis cae.
