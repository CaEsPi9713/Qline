# Guion de verificación en el servidor · Seguimiento 3

Pasos para comprobar con MongoDB y Redis reales lo que las pruebas automáticas solo cubren con simulados. Cada paso dice qué debe verse; lo que no se pueda comprobar se registra como **pendiente** en `S3.md`, no como hecho.

Necesitas: la aplicación corriendo, el entorno virtual activo, un **celular** con datos móviles o con el wifi del curso, y una **segunda pantalla** (otra pestaña, otra computadora o una tablet).

Orden recomendado: 0 → 1 → 2 → 3 → 4. Los bloques 3 y 4 se hacen con la atención "limpia" (sin turnos llamados).

---

## 0 · Preparación

```bash
git pull
```
```bash
python -c "from app.main import get_db; from app.turnos_schema import INDICES_TURNOS; c=get_db()['turnos']; [print(c.create_index(i['keys'], **i['options'])) for i in INDICES_TURNOS]"
```
Reinicia la aplicación como siempre. El comando de índices debe imprimir 6 nombres (los que ya existían no se vuelven a crear).

Variables del `.env` del servidor:
```bash
grep -E "^(PUBLIC_BASE_URL|BASE_PATH|BARRIDO_ABANDONO|BARRIDO_INTERVALO_SEG)" .env
```
- `PUBLIC_BASE_URL` debe ser el dominio público (por ejemplo `https://grupo2.crnube.net`) y **nunca** `localhost`. Si falta, la aplicación usa el dominio del curso.
- `BASE_PATH` debe coincidir con la ruta bajo la que Apache publica la aplicación.
- `BARRIDO_ABANDONO` en `1` (o ausente) para que el abandono funcione solo.

## 1 · Aaron · Quiosco, QR y pantalla pública (HU-001, HU-003, HU-009)

### 1.0 · Rutas del cliente sin contraseña (decisión D-22)

Antes de seguir, sube el `.htaccess` nuevo (guarda una copia: `cp .htaccess .htaccess.bak`). Si el sitio responde 500, restaura la copia.

Con un token real (el que sale en `qr_url` al emitir un turno), desde el servidor o desde tu computadora:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://grupo2.crnube.net/proyecto/qline/api/turnos/qr/<UUID>
curl -s -o /dev/null -w "%{http_code}\n" https://grupo2.crnube.net/proyecto/qline/turno/qr/<UUID>
curl -s -o /dev/null -w "%{http_code}\n" https://grupo2.crnube.net/proyecto/qline/panel
curl -s -o /dev/null -w "%{http_code}\n" https://grupo2.crnube.net/proyecto/qline/api/llamados
```

Debe verse **200**, **200**, **401** y **401**: las dos rutas del cliente abren sin contraseña y todo lo demás sigue protegido. Luego abre el enlace del QR en el celular (mejor en una ventana privada): no debe pedir usuario ni contraseña, y la página debe decir "En vivo" (el WebSocket conecta) en lugar de "Actualizando cada 3 s".

| # | Qué hacer | Qué debe verse |
|---|---|---|
| 1.1 | En el celular o en una tablet abre `/quiosco`, ponla a **pantalla completa** y elige una prioridad | Vista sin menús de operación ni administración. La confirmación muestra el código del turno y un QR |
| 1.2 | Pulsa derecho / inspecciona el enlace bajo el QR | La URL empieza por el dominio público, incluye `BASE_PATH` y termina en `/turno/qr/<uuid>`. Sin `localhost` |
| 1.3 | Con **otro** celular, escanea el QR de la pantalla | Se abre la página del turno con su estado ("En espera") y el indicador "En vivo" |
| 1.4 | Abre `/pantalla` en la segunda pantalla | "Sin turnos llamados actualmente" y la luz de conexión en vivo en verde |
| 1.5 | Desde `/cola` llama al siguiente turno con V-01 | **En la pantalla** aparece el turno con V-01, sin recargar. **En el celular** la página cambia sola a "¡Es su turno!" con la cuenta regresiva |
| 1.6 | En `/panel` pulsa *Iniciar atención* y luego *Finalizar* | La pantalla pasa el turno a "En atención" y luego lo retira; el celular muestra "En atención" y "Atendido" |
| 1.7 | Con el celular, vuelve a abrir el enlace del turno ya atendido | Muestra el estado final "Atendido" |

Evidencia sugerida: una captura de la pantalla de sala con un turno llamado, una del celular con el QR escaneado y una del ticket del quiosco.

```bash
python -m scripts.probar_qr_token --informe docs/evidencia/qr_token.md
```
Debe terminar en **CORRECTO** (turno con token aceptado, repetido rechazado, turnos sin token conviven, la consulta usa `IXSCAN`). La línea "informativo" indica si el motor valida el formato del token; en la ejecución del 27/10/2026 dijo **SÍ**.

## 2 · Alessandro + Abigail · Abandono y recuperación (HU-008, HU-012)

Ya verificados en el servidor (ver `S3.md`, sección 5). Falta solo lo que depende del celular:

| # | Qué hacer | Qué debe verse |
|---|---|---|
| 2.1 | Emite un turno desde `/quiosco`, escanea el QR con el celular y llámalo desde `/cola`. **No inicies la atención** | El celular muestra "¡Es su turno!" y la cuenta regresiva |
| 2.2 | Espera unos 3 minutos con el celular abierto | Al vencer el plazo el celular cambia **solo** a "Turno cancelado"; `/pantalla` deja de listarlo; `/panel` muestra la ventanilla libre; `/historial?estado=abandonado` lo muestra |
| 2.3 | `redis-cli ttl grupo2:qline:turno:<codigo>` (antes de los 180 s) | Un número menor que 180 que baja; después del vencimiento, `-2` |

## 3 · Carlos · Descargas y evidencia de MongoDB (HU-010, HU-011, TT-014, TT-015)

| # | Qué hacer | Qué debe verse |
|---|---|---|
| 3.1 | En `/historial` pulsa **Descargar JSON** (con y sin filtros) | Se baja `historial_turnos_<fecha>.json`; con un filtro, `total_exportados` coincide con los registros filtrados |
| 3.2 | En `/dashboard` cambia el umbral (120, 300, 600) y pulsa **Descargar JSON** | Se baja `dashboard_sla_<umbral>s_<fecha>.json` con el umbral elegido |
| 3.3 | `python scripts/medir_indices_mongo.py --informe docs/evidencia/indices_mongo.md` | Las 4 consultas con `IXSCAN` y 554 documentos |

## 4 · Cierre

Al terminar, deja el entorno listo para la demo:
```bash
redis-cli del grupo2:qline:contador:atencion_general grupo2:qline:cola:atencion_general grupo2:qline:ventanilla:V-01:actual grupo2:qline:ventanilla:V-02:actual grupo2:qline:ventanilla:V-03:actual
```
Anota en `S3.md` qué pasos se verificaron, la fecha y qué falló, si algo falló.
