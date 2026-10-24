# Tiempo real en QLine (TT-013)

Las pantallas en vivo (pantalla pública HU-009 y consulta por QR HU-013) se enteran de los cambios de los turnos por **Redis Pub/Sub + WebSocket**, con **consulta periódica como respaldo**.

```text
 emitir / llamar / iniciar / finalizar / abandonar
                   │  eventos.publicar(...)         (mejor esfuerzo: nunca rompe la operación)
                   ▼
        Redis Pub/Sub  grupo2:qline:eventos
                   │
                   ▼  un hilo por proceso de la app (app/tiempo_real.py)
              WebSocket  /ws/eventos[?codigo=A-001]  ──▶  navegador
```

Si el WebSocket no estuviera disponible, cada página sigue actualizándose consultando su propia API JSON cada pocos segundos: sigue siendo actualización automática, sin recargar a mano.

## Mensaje de evento (contrato para Aaron y Abigail)

JSON pequeño, **sin datos personales**. Los campos sin valor se omiten.

```json
{
  "tipo": "turno_llamado",
  "ts": "2026-10-24T16:44:09.829Z",
  "codigo": "A-001",
  "estado": "llamado",
  "ventanilla": "V-01",
  "prioridad": "normal"
}
```

| `tipo` | Cuándo se publica | `estado` | Quién lo dispara |
|---|---|---|---|
| `turno_emitido` | Se emite un turno | `pendiente` | Emisión (HU-001) |
| `turno_llamado` | Una ventanilla llama al siguiente | `llamado` | Llamar siguiente (HU-005) |
| `atencion_iniciada` | El cliente se presenta | `en_atencion` | Iniciar atención (HU-006) |
| `atencion_finalizada` | Se cierra la atención | `atendido` | Finalizar atención (HU-007) |
| `turno_abandonado` | Pasan 180 s sin presentarse | `abandonado` | Abandono (HU-008) |
| `prueba` | Solo verificación del canal | — | `/ws-prueba` |

Además, el servidor envía por el WebSocket: `conectado` (al abrir) y `latido` (cada 25 s, para mantener viva la conexión a través de proxies).

> **Estado:** los cuatro eventos del flujo principal ya se publican (Fase 4). Falta solo `turno_abandonado`, que debe publicar el barrido de abandono de Abigail (HU-008).

### Dónde se publica cada evento

| Evento | Lugar | Solo si… |
|---|---|---|
| `turno_emitido` | `POST /api/turnos/emitir` y `POST /emitir` (`app/main.py`) | la emisión tuvo éxito |
| `turno_llamado` | `llamar_siguiente_turno` (`app/llamado.py`) | se asignó un turno (no con la cola vacía ni con la ventanilla ocupada) |
| `atencion_iniciada` | `POST /api/atencion/iniciar` y `POST /panel/iniciar` | la transición `llamado → en_atencion` se hizo |
| `atencion_finalizada` | `POST /api/atencion/finalizar` y `POST /panel/finalizar` | la transición `en_atencion → atendido` se hizo |

Se publica **después** de que MongoDB confirmó el cambio, y una operación rechazada (409, 404, 422…) no publica nada. Si Redis no puede publicar, la operación de negocio no se rompe ni se deshace.

## Cómo publicar un evento desde el código

```python
from app import eventos
eventos.publicar(eventos.TURNO_ABANDONADO, codigo="A-001", estado="abandonado", ventanilla="V-01")
```

Devuelve la cantidad de receptores, o `None` si Redis no está disponible (no lanza excepción).

**Para Abigail (HU-008):** al marcar un turno como `abandonado` en MongoDB, llamar a `eventos.publicar(eventos.TURNO_ABANDONADO, codigo=..., estado="abandonado", ventanilla=...)`. Con eso la consulta por QR y la pantalla pública se enteran al instante.

## Endpoints

| Ruta | Para qué |
|---|---|
| `GET /ws/eventos` (WebSocket) | Eventos de los turnos. `?codigo=A-001` filtra por un turno |
| `GET /ws/ping` (WebSocket) | Bienvenida, latido y eco: comprueba el WebSocket sin Redis |
| `POST /api/eventos/prueba` | Publica un evento `prueba` |
| `GET /api/eventos/estado` | Estado del receptor (`suscrito`, `clientes`, `hilo_activo`) |
| `GET /ws-prueba` | Página que ejecuta las comprobaciones desde el navegador |

## Verificar el WebSocket en el servidor

1. **La app, sin Apache** (con el entorno virtual activo y la app corriendo):

   ```bash
   python scripts/probar_websocket.py
   ```

   Debe terminar en `Todo OK`. Si falla, el problema está en la app, en Redis o en el puerto.

2. **A través de Apache:** abrir `https://grupo2.crnube.net/proyecto/qline/ws-prueba` y pulsar *Ejecutar la prueba*.

| Script | Página | Diagnóstico |
|---|---|---|
| OK | Todo OK | El WebSocket funciona por el proxy |
| OK | Falla el paso 1 | La app está bien; Apache bloquea el WebSocket (ver abajo) |
| Falla | — | Revisar la app y Redis |

## Apache: regla necesaria (verificada en el servidor del curso)

El `.htaccess` reenvía las peticiones con `RewriteRule ... [P]`, y por `http://` los WebSocket no pasan: `/ws-prueba` falló desde el paso 1 aunque `scripts/probar_websocket.py` (directo a la app) daba `Todo OK`. Con estas dos líneas **antes** de las reglas HTTP, los cuatro pasos de `/ws-prueba` pasan:

```apache
RewriteCond %{HTTP:Upgrade} =websocket [NC]
RewriteRule ^(.*)$ ws://127.0.0.1:18002/$1 [P,L]
```

- La condición solo afecta a las peticiones que piden WebSocket; el resto del sitio no cambia.
- No requiere reiniciar Apache ni la app, y no se necesitaron permisos de administrador.
- El `.htaccess` del repositorio ya incluye la regla. Si se despliega en otro servidor y no existe `mod_proxy_wstunnel`, esas peticiones fallarán; en ese caso se quita la regla y las pantallas usan consulta periódica a su API JSON (previsto en el diseño).

## Qué no hace esto

- No cambia estados, prioridades ni la cola, y no usa claves nuevas de Redis (solo el canal ya previsto en el contrato).
- No envía notificaciones push, SMS ni WhatsApp (fuera de alcance).
- No recibe datos del cliente: el WebSocket solo envía.
