# P07 · Preparación de la demostración en vivo

**Responsable:** Alessandro Cambronero · **Guion de exposición:** [`docs/presentacion/PRESENTACION_FINAL.md`](../presentacion/PRESENTACION_FINAL.md) (anexo P07, de Aaron) · **Guía en pantalla:** `/demo`

> La demo es en vivo con datos sintéticos y turnos emitidos en el momento. No promete cifras: las que se muestren salen de [`docs/evidencia/`](../evidencia/). Todo lo que figura aquí como «hecho» está probado con pruebas automáticas; lo ensayado en el servidor se marca aparte.

## 1. Qué incluye

| Pieza | Para qué |
|---|---|
| `python -m scripts.preparar_demo` | Comprueba MongoDB, Redis, los 6 índices de `turnos`, los datos sintéticos, la dirección de los QR, la zona horaria y el estado de partida. **No borra nada** y es idempotente |
| `--cargar-sinteticos` | Completa el historial `S-NNN` si hay menos de 500 turnos (upsert; no duplica) |
| `--en-espera N` | Deja al menos N turnos en la cola, emitiendo solo los que faltan (cada tercero, preferencial) |
| `/demo` | Guía de 25 pasos con «qué debe verse» en cada uno; el paso 25 cubre `/salud` y el cierre con nota |
| Guion de exposición | Anexo P07 de `PRESENTACION_FINAL.md`: 10 pasos por actor |

## 2. Lista de comprobación previa (15 minutos antes)

1. `python -m scripts.preparar_demo --cargar-sinteticos --en-espera 4` termina con «Lista para la demo»; ningún `ERROR`.
2. `/salud` responde `estado: ok` (también desde fuera, con credenciales de Apache).
3. La ficha «QR apunta a …» de `/demo` muestra el dominio público, no una dirección local.
4. La ficha «Abandono automático» indica «cada 10 s».
5. `/pantalla` abierta en la segunda pantalla, con el sonido activado (el navegador exige un clic).
6. Un celular con la red de la sala puede abrir un enlace de QR sin pedir contraseña.
7. Estado de partida: cola vacía o los turnos precargados a propósito; nadie «llamado» de pruebas anteriores.

## 3. Guion resumido

Emitir normal y preferencial en `/quiosco` → ticket con QR (imprimir) → abrir el QR en el celular → llamar desde `/panel` (sale primero el preferencial) → ver el cambio en la sala y en el celular → iniciar y **finalizar con motivo y nota** → aviso de fin en el celular → `/historial` y `/dashboard` → `/salud`.

**Limitaciones que se dicen tal cual:**
- La consulta por código acepta solo `A-NNN`; por eso la demo de consulta y QR usa turnos emitidos en vivo, no los sintéticos `S-NNN`.
- Las **ventanillas dinámicas (P09) no están en la demo**: el sistema opera con `V-01`, `V-02` y `V-03`.
- La estimación de espera (S4-M01) no se ejecutó (decisión D-32).
- El servidor no permite `collMod`: el campo `cierre` lo valida la aplicación, no el motor (D-31).

## 4. Plan B (si falla la red o un servicio)

| Falla | Qué hacer |
|---|---|
| El celular no abre el QR | Abrir el enlace del QR en una pestaña del equipo; el comportamiento es el mismo |
| Redis no responde | Mostrar `/salud` en 503 como evidencia del comportamiento controlado y pasar a la evidencia de `docs/evidencia/fallos.md` |
| Sin red hacia el servidor | Usar los turnos precargados (`--en-espera`) y las capturas de `docs/evidencia/capturas/` |
| La sala no suena | El aviso es opcional; la tarjeta parpadea igualmente |

## 5. Estado

| Punto | Estado |
|---|---|
| `scripts/preparar_demo.py` | Implementado; **prueba automática** (14 pruebas). Falta ejecutarlo en el servidor |
| `/demo` actualizada al flujo de S4 | Hecho; prueba automática de contenido y orden |
| Lista de comprobación y plan B | Redactados (este documento) |
| Ensayo completo con cronómetro | **Pendiente**: lo hace el equipo; anotar aquí los tiempos reales |
| Capturas para el plan B | **Pendientes** |

### Registro del ensayo (para completar con datos reales)

| Fecha | Quién | Duración | Qué falló / qué se ajustó |
|---|---|---|---|
| | | | |
