# Contrato del QR: HU-003 (Aaron) ↔ HU-013 (Alessandro)

Es el único punto de acople entre las dos historias. Ninguna toca el contrato operacional de Redis (código `A-NNN`, contador y cola no cambian).

## Lo que debe producir HU-003 (emisión del turno)

| Elemento | Contrato |
|---|---|
| Campo en MongoDB | `qr_token` en el documento `turnos`: **UUID v4** en formato de cadena, minúsculas, generado con `uuid.uuid4()`. Independiente de `codigo` |
| Cuándo | Al emitir cada turno nuevo, **en el mismo `insert_one`** (no en un segundo paso), para no confirmar un turno incompleto |
| Unicidad | Índice único parcial sobre los `qr_token` de tipo cadena (lo define Carlos; sin `collMod` ni `--recrear`) |
| Turnos anteriores y sintéticos | Pueden no tener `qr_token`; siguen consultándose por código (HU-002) |
| URL dentro del QR | `{URL_PUBLICA}{BASE_PATH}/turno/qr/{uuid}` — el dominio accesible desde el celular, **nunca `localhost`** |
| Dato sensible | El QR contiene solo esa URL: ni el código visible ni credenciales |

`URL_PUBLICA` debe salir de una variable de entorno (por ejemplo `PUBLIC_BASE_URL=https://grupo2.crnube.net`) documentada en `.env.example`, que es de Aaron.

## Lo que ofrece HU-013 (consulta)

| Ruta | Respuesta |
|---|---|
| `GET /turno/qr/{uuid}` | Página móvil (sin navegación interna) que se actualiza sola |
| `GET /api/turnos/qr/{uuid}` | JSON `{"ok": true, "turno": {...}}` con código, servicio, prioridad, estado, ventanilla, `turnos_antes`, `posicion`, `segundos_restantes`, `aviso` |
| `GET /ws/turno/qr/{uuid}` (WebSocket) | Solo señales `{"tipo": "actualizar"}`: la página vuelve a consultar su JSON |

Todas son de solo lectura, no devuelven el token ni el `_id`, y envían `Cache-Control: no-store`.

### Errores

| Situación | Código | Qué ve el cliente |
|---|---|---|
| El texto no es un UUID v4 | 400 | «Código QR no válido» |
| Ningún turno tiene ese token | 404 | «Turno no encontrado» |
| MongoDB no disponible | 503 | «No podemos consultar su turno ahora» (la página se reintenta sola) |
| Redis no disponible | 200 | El estado de MongoDB, con un aviso en lugar de la posición |

### Actualización automática

1. La página abre `/ws/turno/qr/{uuid}`; al recibir una señal vuelve a consultar su JSON (como máximo cada 0,7 s).
2. Si el WebSocket no abre en 5 s o se corta, pasa sola a consultar cada 3 s y reintenta el WebSocket cada 15 s.
3. Aunque el WebSocket esté en vivo, consulta además cada 30 s por seguridad.

La señal es anónima a propósito: la posición cambia cuando se llama a **otros** turnos, pero el cliente no debe enterarse de sus códigos.

## Dependencias abiertas

- **Eventos de negocio:** emitir, llamar, iniciar y finalizar ya publican en `grupo2:qline:eventos` (Fase 4), por lo que la página del QR se actualiza al instante. Falta solo el evento de **abandono**, que depende del barrido de Abigail (HU-008); hasta entonces, un turno que vence se refleja con la consulta de seguridad de 30 s.
- **Datos de demostración:** hasta que HU-003 genere el token, `python scripts/crear_turnos_qr_demo.py` emite turnos por el flujo real y les agrega un `qr_token`.
