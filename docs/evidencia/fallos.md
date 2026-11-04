# Casos normal, conexión fallida y datos inválidos (TT-019, módulos de Alessandro)

> Informe generado por `scripts/probar_fallos_redis.py` con los resultados de **esa ejecución**; no se escribe a mano.

## Entorno

- Fecha (UTC): 2026-10-24 17:46:43
- Python: 3.12.3 · Linux
- Aplicación probada: http://127.0.0.1:18002
- Instancia con Redis inalcanzable: http://127.0.0.1:18099

## Resultado global

**OK** · 28 casos ejecutados · 0 fuera de lo esperado · **0 respuestas 500**.

## 1. Caso normal

La aplicación con Redis y MongoDB disponibles responde lo esperado.

| Caso | Petición | Esperado | Estado obtenido | Tiempo (ms) | Resultado |
|---|---|---|---|---|---|
| Estado de Redis | `GET /redis/estado` | 200 con ok=true | 200 | 2 | OK |
| Cola activa (API) | `GET /api/cola` | 200 con la lista de turnos | 200 | 1 | OK |
| Vista de la cola | `GET /cola` | 200 con la página | 200 | 56 | OK |
| Panel de atención | `GET /panel` | 200 con la página | 200 | 15 | OK |
| Estado del receptor de eventos | `GET /api/eventos/estado` | 200 con ok=true | 200 | 1 | OK |
| Evento de prueba por Pub/Sub | `POST /api/eventos/prueba` | 200: el evento se publicó | 200 | 1 | OK |

## 2. Datos inválidos

Cada dato incorrecto produce una respuesta controlada con su código HTTP; nada llega a la base de datos.

| Caso | Petición | Esperado | Estado obtenido | Tiempo (ms) | Resultado |
|---|---|---|---|---|---|
| Llamar con una ventanilla inexistente | `POST /api/llamar` | 400 con el motivo | 400 | 1 | OK |
| Llamar sin indicar ventanilla | `POST /api/llamar` | 422 (dato obligatorio) | 422 | 2 | OK |
| Emitir con una prioridad inválida | `POST /api/turnos/emitir` | 400 con las opciones válidas | 400 | 1 | OK |
| Consultar por QR con un texto que no es UUID | `GET /api/turnos/qr/basura` | 400 «no es válido» | 400 | 1 | OK |
| Consultar por QR con un UUID v1 (versión incorrecta) | `GET /api/turnos/qr/dfe73de0-cfd2-11f1-8faf-06caf48927c3` | 400: solo se aceptan UUID v4 | 400 | 1 | OK |
| Consultar por QR con un intento de inyección | `GET /api/turnos/qr/%27%20OR%201%3D1%20--` | 400 sin consultar la base de datos | 400 | 1 | OK |
| Consultar por QR con un UUID inexistente | `GET /api/turnos/qr/e4cc8856-1209-4cb1-bbe8-a0435433dcfd` | 404 «no corresponde a ningún turno» | 404 | 2 | OK |
| Página del QR con un UUID inválido | `GET /turno/qr/basura` | 400 con página controlada, sin traza | 400 | 20 | OK |
| Página del QR con un UUID inexistente | `GET /turno/qr/e4cc8856-1209-4cb1-bbe8-a0435433dcfd` | 404 con página controlada, sin traza | 404 | 3 | OK |
| Consultar un turno inexistente por código | `GET /api/turnos/A-7777` | 404 | 404 | 2 | OK |
| Iniciar la atención de un turno inexistente | `POST /api/atencion/iniciar` | 404 | 404 | 3 | OK |
| Iniciar la atención con un código inválido | `POST /api/atencion/iniciar` | 422 | 422 | 1 | OK |
| Finalizar con una ventanilla inválida | `POST /api/atencion/finalizar` | 422 | 422 | 2 | OK |

## 3. Conexión fallida: Redis no responde

Con Redis inalcanzable, cada ruta responde de forma controlada y la consulta por QR sigue mostrando el estado que conserva MongoDB.

| Caso | Petición | Esperado | Estado obtenido | Tiempo (ms) | Resultado |
|---|---|---|---|---|---|
| Estado de Redis | `GET /redis/estado` | 200 informando ok=false (no se rompe) | 200 | 6 | OK |
| Cola activa (API) | `GET /api/cola` | 503 «Redis no disponible» | 503 | 1 | OK |
| Vista de la cola | `GET /cola` | 200: la página muestra el aviso en lugar de romperse | 200 | 57 | OK |
| Llamar al siguiente | `POST /api/llamar` | 503 controlado | 503 | 2 | OK |
| Emitir un turno | `POST /api/turnos/emitir` | 503 controlado: no deja un turno a medias | 503 | 2 | OK |
| Publicar un evento | `POST /api/eventos/prueba` | 503 controlado | 503 | 2 | OK |
| Panel de atención | `GET /panel` | 200: el panel sigue mostrando el estado de MongoDB | 200 | 14 | OK |
| Consulta por QR de un turno existente (API) | `GET /api/turnos/qr/6ede846e-9958-4875-a016-18762fc67ed3` | 200: se muestra el estado de MongoDB con un aviso de Redis | 200 | 4 | OK |
| Consulta por QR de un turno existente (página) | `GET /turno/qr/6ede846e-9958-4875-a016-18762fc67ed3` | 200: la página se muestra | 200 | 22 | OK |

## Alcance y límites

- La «conexión fallida» se simula con una segunda instancia de la app apuntada a un puerto de Redis donde no hay nada; no se detiene el Redis compartido.
- Los tiempos incluyen el intento de conexión que falla: la app está configurada para fallar rápido (sin reintentos) en lugar de dejar esperando al usuario.
- No se prueba la caída de MongoDB (no se puede detener el servidor del curso); su manejo controlado se cubre con las pruebas automáticas del repositorio.
- El rechazo de documentos por el JSON Schema de MongoDB corresponde a Carlos (TT-019 de su módulo).
