# QLine

**Sistema inteligente de gestión de filas y turnos en tiempo real**

> *"MongoDB conserva lo que ocurrió. Redis controla lo que ocurre ahora."*

Proyecto final de **Tópicos Avanzados de Bases de Datos** · Universidad Nacional · Equipo **Query Logic** (Grupo 2)

![Versión](https://img.shields.io/badge/versi%C3%B3n-v0.9.0--rc-blue)
![Python](https://img.shields.io/badge/python-3.12-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-009688)
![MongoDB](https://img.shields.io/badge/MongoDB-47A248)
![Redis](https://img.shields.io/badge/Redis-DC382D)
![Licencia](https://img.shields.io/badge/licencia-MIT-green)

## Contenido

1. [Qué es QLine](#1-qué-es-qline)
2. [Arquitectura](#2-arquitectura)
3. [Requisitos](#3-requisitos)
4. [Instalación](#4-instalación)
5. [Variables de entorno](#5-variables-de-entorno)
6. [Inicializar MongoDB y cargar datos](#6-inicializar-mongodb-y-cargar-datos)
7. [Ejecutar la aplicación](#7-ejecutar-la-aplicación)
8. [Pantallas y rutas](#8-pantallas-y-rutas)
9. [Operación](#9-operación)
10. [Pruebas y evidencia](#10-pruebas-y-evidencia)
11. [Seguridad y privacidad](#11-seguridad-y-privacidad)
12. [Documentación](#12-documentación)
13. [Ramas y equipo](#13-ramas-y-equipo)
14. [Licencia](#14-licencia)

## 1. Qué es QLine

QLine gestiona la fila de **un servicio** («Atención General»): el cliente saca su turno en un quiosco (con prioridad normal o preferencial), lo sigue desde el celular con un código QR, un operador lo llama desde una ventanilla y una pantalla de sala lo anuncia. Todo queda registrado para el historial y las estadísticas.

- **Cinco estados** de un turno: `pendiente`, `llamado`, `en_atencion`, `atendido` y `abandonado`. Un turno llamado que no se presenta en **180 s** pasa solo a `abandonado`.
- **Prioridad antes que llegada**; a igual prioridad, por orden de llegada.
- **Una ventanilla atiende un turno a la vez** y dos ventanillas nunca reciben el mismo turno.
- Sin datos personales del cliente: solo código, prioridad y tiempos.

## 2. Arquitectura

```text
 Cliente (celular)        Quiosco            Operador (panel)        Sala (pantalla)
        │                    │                     │                      │
        └──────────────┬─────┴─────────────┬───────┴──────────────┬───────┘
                       ▼                   ▼                      ▼
                 Apache (proxy, .htaccess, contraseña salvo el QR)
                                   │
                          FastAPI + Jinja2 (app/main.py)
                       ┌───────────┴────────────┐
                       ▼                        ▼
            Redis: lo que ocurre ahora     MongoDB: lo que ocurrió
   cola (Sorted Set) · ventanilla actual     colección `turnos` con JSON Schema,
   (String) · estado temporal (Hash, 180 s)  índices, historial y estadísticas
   · eventos (Pub/Sub → WebSocket)
```

| Pieza | Para qué sirve |
|---|---|
| **MongoDB** | Fuente de verdad del turno y de su historia: estados, marcas de tiempo, métricas y el cierre. Valida con `$jsonSchema` e indexa por código, estado, ventanilla y token del QR |
| **Redis** | Estado en vivo: la cola con prioridad (`ZADD`/`ZPOPMIN`), la reserva de ventanilla con `SET NX`, el Hash temporal con TTL de 180 s y el canal de eventos |
| **FastAPI + Jinja2** | API y pantallas. Un hilo por proceso escucha los eventos de Redis y los reparte por WebSocket |
| **Barrido de abandono** | Hilo de la aplicación que marca como abandonados los turnos llamados que vencieron (D-17 y D-18) |

El mapa completo de claves y canales de Redis está en [`docs/arquitectura/redis_claves.md`](docs/arquitectura/redis_claves.md). Si Redis falla, MongoDB queda correcto y la respuesta lo indica; si Redis pierde la cola, se reconstruye desde MongoDB (ver [Recuperación](#recuperación)).

## 3. Requisitos

- **Python 3.12** o superior.
- **MongoDB** con un usuario y una base de datos propios (por defecto `grupo2_db`).
- **Redis 7**. La aplicación no usa `CONFIG SET` ni `EVAL`, y tiene prohibido `FLUSHALL` y `FLUSHDB`.
- Para publicar: **Apache** con `mod_rewrite` y `mod_proxy_http`/`mod_proxy_wstunnel`, y que el hosting permita `AllowOverride` de autenticación y `FileInfo`.
- Un celular para probar el QR.

## 4. Instalación

```bash
git clone https://github.com/CaEsPi9713/Qline.git
cd Qline
python -m venv venv
source venv/bin/activate            # en Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                # y complete los valores (ver la sección 5)
```

Para ejecutar las pruebas: `pip install -r requirements-dev.txt` (ver [Pruebas](#10-pruebas-y-evidencia)).

## 5. Variables de entorno

Se leen del archivo `.env` (copia de [`.env.example`](.env.example)). **Nunca** suba el `.env` ni credenciales reales al repositorio.

| Variable | Para qué sirve | Valor por defecto / ejemplo |
|---|---|---|
| `MONGO_USER`, `MONGO_PASS` | Usuario y contraseña de MongoDB | los de su cuenta (el ejemplo trae marcadores) |
| `MONGO_DB` | Base de datos | `grupo2_db` |
| `MONGO_HOST`, `MONGO_PORT` | Servidor de MongoDB | `127.0.0.1`, `27017` |
| `REDIS_HOST`, `REDIS_PORT` | Servidor de Redis | `127.0.0.1`, `6379` |
| `REDIS_PASS` | Contraseña de Redis; vacía si no la pide | vacía |
| `BASE_PATH` | Subruta bajo la que Apache publica la aplicación | `/proyecto/qline` en el servidor del curso; vacía al ejecutar en la raíz |
| `PUBLIC_BASE_URL` | Dominio público de los enlaces del QR. Debe abrirse desde un celular: **nunca `localhost`** | `https://grupo2.crnube.net` |
| `BARRIDO_ABANDONO` | `1` (o ausente) activa el abandono automático; `0` lo apaga | `1` |
| `BARRIDO_INTERVALO_SEG` | Segundos entre pasadas del barrido | `10` |
| `ZONA_HORARIA` | Zona IANA con la que las pantallas muestran fechas y horas (los datos se guardan en UTC) | `America/Costa_Rica` |

## 6. Inicializar MongoDB y cargar datos

```bash
python scripts/init_mongo.py                 # esquema JSON Schema, índices y prueba de integridad
python scripts/generar_datos_sinteticos.py --cargar   # historial sintético (upsert, no duplica)
python -m scripts.preparar_demo              # comprueba que todo quedó listo (no borra nada)
```

- **Si `init_mongo` dice «Unauthorized» en `collMod`**: el usuario no puede cambiar el validador de una colección que ya existe. Los índices sí se aplican. La opción `--recrear --confirmar` **borra todos los turnos** y vuelve a crear la colección con el validador; úsela solo en un entorno de pruebas. El campo `cierre` (motivo y nota) funciona sin actualizar el validador (decisión D-31).
- `scripts/init_mongo.py` es idempotente y comprueba que MongoDB rechaza prioridades inválidas y códigos duplicados.

### Datos sintéticos (TT-005)

El generador crea turnos **100 % sintéticos**: solo códigos, prioridad, ventanilla y tiempos, sin datos personales. Simula la operación (prioridad antes que llegada, FIFO dentro de cada prioridad, 3 ventanillas, abandono a los 180 s) para que estados y marcas de tiempo sean coherentes.

- Documentos con el contrato de `turnos` (servicio `atencion_general`, prioridades `normal`/`preferencial`, ventanillas `V-01` a `V-03`, estados oficiales). Los campos que aún no aplican quedan en `null`.
- Códigos `S-001`, `S-002`, … La serie `S-` está separada de la serie `A-` de la operación real para no chocar con el contador de Redis ni con los turnos emitidos en vivo.
- Con los parámetros por defecto: 3 días simulados y 554 turnos, todos terminados (`atendido` o `abandonado`). Son **historial**: no dejan turnos `pendiente`, `llamado` ni `en_atencion`. Con `--con-activos` se obtiene la instantánea del corte, con turnos en espera y en curso (solo en MongoDB; no se encolan en Redis).

```bash
python scripts/generar_datos_sinteticos.py                          # vista previa: genera, valida y resume; no escribe nada
python scripts/generar_datos_sinteticos.py --salida datos.jsonl     # archivo JSON Lines (Extended JSON)
python scripts/generar_datos_sinteticos.py --cargar                 # upsert en MongoDB (no duplica)
python scripts/generar_datos_sinteticos.py --reiniciar --confirmar  # borra los sintéticos y vuelve a cargar
python scripts/generar_datos_sinteticos.py --limpiar --confirmar    # borra solo los códigos S-NNN
```

Opciones útiles: `--semilla`, `--dias`, `--fecha-fin`, `--llegadas-por-hora`, `--prefijo`, `--con-activos` y `--json`. Es reproducible (semilla y fecha fijas), validado antes de escribir y seguro: `--limpiar` y `--reiniciar` exigen `--confirmar` y solo tocan el prefijo sintético, nunca la serie `A-`.

`python scripts/sembrar_turnos_hu006.py` inserta seis turnos `A-015` a `A-020` en distintos estados para probar iniciar y finalizar atención (`--limpiar` los elimina). Usan la serie `A-`: no lo ejecute si ya existen turnos reales con esos códigos.

## 7. Ejecutar la aplicación

**Desarrollo** (en la raíz, con `BASE_PATH` vacío):

```bash
uvicorn app.main:app --reload --port 8000
```

Abra `http://127.0.0.1:8000/`. Con `PUBLIC_BASE_URL` local los QR no se abrirán desde un celular: para probarlos, publique la aplicación o apunte esa variable a una dirección accesible.

**Servidor** (gunicorn detrás de Apache): [`qline.service`](qline.service) es el ejemplo de unidad de systemd (`gunicorn app.main:app -k uvicorn.workers.UvicornWorker`). El puerto de gunicorn **debe coincidir** con el de las reglas de proxy del [`.htaccess`](.htaccess); revíselo al desplegar, porque el ejemplo de la unidad y el `.htaccess` del repositorio no usan el mismo.

## 8. Pantallas y rutas

Todo lo que no es del cliente exige usuario y contraseña de Apache (`.htaccess`). Solo son públicas las rutas del QR (siempre con un UUID de 36 caracteres) y `/static/` (decisión D-22).

| Quién | Ruta | Qué muestra |
|---|---|---|
| Cliente | `/turno/qr/{uuid}` | Estado de su turno en el celular, con actualización en vivo. **Pública** |
| Cliente | `/quiosco`, `/emitir` | Emisión de turno (normal o preferencial) con ticket, QR e impresión |
| Cliente | `/consultar` | Consulta de un turno por código |
| Sala | `/pantalla` | Turnos llamados y en atención, con aviso sonoro opcional |
| Operador | `/cola`, `/panel` | Cola con prioridad; llamado, inicio y fin de la atención (con motivo y nota opcionales) |
| Supervisor | `/historial`, `/dashboard` | Historial con filtros y descarga JSON; KPI y SLA |
| Administración | `/administracion`, `/admin/sucursales` | Administrador técnico de MongoDB; alta y baja de ventanillas (P09); mantenimiento de sucursales (RFC-004) |
| Equipo | `/demo`, `/salud`, `/acerca` | Guía de demostración; estado de la aplicación, Redis y MongoDB; equipo del proyecto |

`/salud` responde `{estado, app, redis, mongo, barrido}` con **200** si Redis y MongoDB responden y **503** si falla alguno, sin ningún dato de infraestructura (decisión D-29).

## 9. Operación

- **Flujo normal:** el cliente emite el turno → el operador llama desde `/cola` o `/panel` → *Iniciar atención* → *Finalizar atención* (opcionalmente con un motivo de una lista cerrada y una nota de hasta 200 caracteres, que se guardan en el campo `cierre` del turno).
- **Abandono:** un turno llamado que no inicia en 180 s pasa solo a `abandonado` (el barrido corre dentro de la aplicación; también `python -m scripts.barrer_abandonos`).
- **Demostración:** `python -m scripts.preparar_demo [--cargar-sinteticos] [--en-espera N]` comprueba el entorno y deja turnos en la cola sin borrar nada; después siga la guía de `/demo`.

### Recuperación

Si Redis pierde la cola, `python -m scripts.rehidratar_cola` muestra el plan y `--aplicar` la reconstruye desde MongoDB (idempotente; conviene con la atención detenida, decisión D-20).

### Zona horaria

MongoDB y las APIs guardan y entregan UTC; las pantallas muestran la hora de `ZONA_HORARIA` (decisión D-23).

## 10. Pruebas y evidencia

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -t . -v
```

La suite (más de 590 pruebas) usa Redis y MongoDB simulados (`fakeredis`, `mongomock`); sin esas dependencias se omiten las pruebas de rutas y de Redis. La prueba del QR legible exige además `zxing-cpp` y se omite si falta.

Las pruebas **contra los servicios reales** generan informes en [`docs/evidencia/`](docs/evidencia/) (índices, rendimiento, concurrencia, fallos, `/salud`, cierre con nota…). Cada informe indica lo que se ejecutó y cuándo; no se escriben a mano. La guía `/demo` lista el comando de cada uno.

> Convención de las bitácoras: «verificado en el servidor» es lo ejecutado con MongoDB y Redis reales; «prueba automática» es la suite de `tests/` con simulados.

**Capturas de pantalla:** pendientes de incorporar en `docs/evidencia/capturas/`.

## 11. Seguridad y privacidad

- **Sin secretos en el repositorio:** `.env` está ignorado y `.env.example` solo trae marcadores. Revise que ningún README, script ni captura incluya credenciales.
- **Apache protege todo salvo el QR**; el administrador de MongoDB (`/administracion` y sus rutas de escritura) nunca es público.
- **Sin datos personales:** no se pide nombre, cédula ni teléfono; el `qr_token` es un UUID v4 imposible de adivinar y solo da acceso de lectura a un turno.
- **Respuestas sin fugas:** `/salud`, `/redis/estado` y las páginas de error no muestran trazas, hosts, puertos ni usuarios; el detalle queda en el registro del servidor.
- **Notas de cierre:** se escapan siempre al mostrarse (no se usa `innerHTML` ni `|safe`).

## 12. Documentación

| Documento | Contenido |
|---|---|
| [`CHANGELOG.md`](CHANGELOG.md) | Cambios de S1 a S4 |
| [`docs/arquitectura/redis_claves.md`](docs/arquitectura/redis_claves.md) | Mapa de claves, tipos, TTL y recuperación de Redis |
| [`docs/arquitectura/tiempo_real.md`](docs/arquitectura/tiempo_real.md) | Pub/Sub y WebSocket |
| [`docs/arquitectura/qr_consulta.md`](docs/arquitectura/qr_consulta.md) | Consulta por QR |
| [`docs/decisiones.md`](docs/decisiones.md) | Decisiones técnicas y su motivo (D-01 a D-33) |
| [`docs/design-system.md`](docs/design-system.md) | Sistema de diseño: colores, componentes y regla del vidrio |
| [`docs/seguimientos/`](docs/seguimientos/) | Bitácoras S1 a S4 |
| [`docs/presentacion/`](docs/presentacion/) | Presentación final y guion de la demo |
| [`portal.yml`](portal.yml) | Ficha del proyecto para el portal del curso |

## 13. Ramas y equipo

- `main`: código estable. `development`: integración.
- Ramas de trabajo (derivadas de `development`): `cespinoza`, `abenavides`, `acambronero`, `aurbina`.

**Equipo Query Logic:** Aaron Benavides · Abigail Urbina · Alessandro Cambronero · Carlos Espinoza.

## 14. Licencia

Distribuido bajo licencia **MIT**. Ver [`LICENSE`](LICENSE).
