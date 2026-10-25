# Plan del Seguimiento 3 · Abigail Urbina (`aurbina`)

**Hito:** integración, pruebas y medición (tag objetivo `v0.3.0`)
**Área:** ciclo de atención y continuidad operacional
**Fuentes:** Plan Maestro (§8 HU, §9 tareas, §10.3, §12.4, §18) y bitácora S3 en elaboración.

## 1. Qué te corresponde en S3

| ID | Entregable | Origen | Estado esperado S3 |
|---|---|---|---|
| HU-008 | Abandono de turno llamado a los 180 s | Plan §8 (S3: TARGET) | Integrado y probado |
| HU-012 | Recuperación de la cola tras pérdida de Redis | Plan §8 (S3: REQUIRED/TARGET) | Integrado y con evidencia antes/después |
| TT-012 | TTL / estado temporal — lado abandono (con Alessandro) | Plan §9 | Lado Redis ya hecho por Alessandro; falta el barrido |
| TT-017 | Prueba de caída y rehidratación | Plan §9 | Evidencia en el servidor |
| TT-018 | Mediciones de tu parte (recuperación, barrido), ≥ 3 ejecuciones, mediana | Plan §9 y §18.2 | Informe con mínimo, máximo y mediana |
| TT-019 | Casos normal, conexión fallida y datos inválidos de tus módulos | Plan §9 | Evidencia |
| TT-020 | Tus decisiones en `docs/decisiones.md` | Plan §9 | Sección completa |
| — | Tu sección de `docs/seguimientos/S3.md` | Plan §10.3 | Con hechos reales |

### Pendientes de la bitácora que dependen de ti
- HU-008: «el barrido de abandono debe pasar el turno a `abandonado`, liberar la ventanilla y publicar `turno_abandonado`» (acordado con Alessandro).
- HU-012: el caso abierto de Alessandro — un turno extraído de la cola cuyo cambio de estado no llegó a MongoDB queda `pendiente` fuera de la cola; «la rehidratación lo recupera».
- Requisito del seguimiento «Recuperación / rehidratación» y la parte de «mediciones de recuperación».

### Pendientes heredados de S2 (verificar en el servidor)
- Concurrencia real de iniciar/finalizar (PR-11 / PF-11) contra MongoDB real.
- Pruebas contra el JSON Schema real de Carlos.

## 2. Contratos que se respetan (no se modifican)
- Estados y transiciones oficiales; `llamado → abandonado` es la única transición nueva que implementas.
- Namespace `grupo2:qline:`; sin `FLUSHALL` / `FLUSHDB`.
- TTL oficial de 180 s.
- Cola, contador y eventos son de Alessandro: **se usan sus funciones**, no se reimplementan.

## 3. Fases

### Fase 0 · Preparación
- [ ] Sincronizar `aurbina` con `development` (con los aportes de Alessandro de S3).
- [ ] Leer `docs/arquitectura/redis_claves.md` y `tiempo_real.md` (contratos del Hash, de la ventanilla y de los eventos).
- [ ] Revisar `app/cola.py`, `app/llamado.py`, `app/eventos.py` y anotar nombres reales de funciones.
- [ ] Copiar los archivos de esta carpeta al repositorio y correr `python -m unittest discover -s tests -t . -v`.

### Fase 1 · Enlace con Redis (el único trabajo de adaptación)
- [ ] En `app/integracion_s3.py` enlazar `leer_cola`, `encolar`, `quitar` con las funciones de Alessandro.
- [ ] Reemplazar `publicar_evento` por el publicador de `app/eventos.py` (contrato exacto del mensaje).
- [ ] Confirmar con Alessandro: forma de la clave `ventanilla:{id}:actual` y si el contador usa la serie `A-`.
- [ ] Si la app ya tiene un cliente Redis que «falla rápido» (decisión D-10), usarlo en `conectar_redis`.

### Fase 2 · HU-008 / TT-012
- [ ] Integrar `barrer_abandonos` en el arranque de la app (`BarridoPeriodico`).
- [ ] Verificar en el servidor: llamar un turno, no iniciar, comprobar a los 180 s `redis-cli ttl` = -2 y estado `abandonado` en MongoDB.
- [ ] Verificar que el panel y la pantalla pública reflejan el abandono (evento `turno_abandonado`).
- [ ] Coordinar con Carlos un índice `{estado, timestamps.llamado}` para el barrido (TT-014).

### Fase 3 · HU-012 / TT-017
- [ ] Ejecutar `python -m scripts.rehidratar_cola` (plan) y luego `--aplicar`.
- [ ] Ejecutar `python -m scripts.probar_recuperacion --informe docs/evidencia/recuperacion.md`.
- [ ] Capturas: cola antes/después, contador, MongoDB.

### Fase 4 · TT-018 / TT-019
- [ ] Coordinar el momento con el equipo y ejecutar `python -m scripts.medir_recuperacion --informe docs/evidencia/rendimiento_recuperacion.md`.
- [ ] Completar la interpretación con los números reales (sin asumir cifras).
- [ ] Ejecutar los casos de `03_PLAN_PRUEBAS_S3.md` en el servidor y registrar resultados.

### Fase 5 · Cierre
- [ ] Completar `04_DECISIONES_ABIGAIL.md` y pasarlo a `docs/decisiones.md`.
- [ ] Abrir el PR (`05_PULL_REQUEST_S3.md`) hacia `development`.
- [ ] Completar tu sección de `S3.md` (`06_BITACORA_S3_ABIGAIL.md`) con hechos reales.

## 4. Convención de la bitácora S3
- **«Verificado en el servidor»:** ejecutado con MongoDB y Redis reales.
- **«Prueba automática»:** cubierto por `tests/` con simulados en memoria; no sustituye a la prueba en el servidor.
- Los informes generados con `--simulado` llevan el aviso **SIMULADO** y **no** deben presentarse como evidencia.

## 5. Archivos de este paquete
```
app/                 s3_comun, abandono, barrido, recuperacion, prueba_recuperacion,
                     mediciones_s3, datos_prueba, informe, simulacion, integracion_s3
scripts/             barrer_abandonos, rehidratar_cola, probar_recuperacion, medir_recuperacion
tests/               64 pruebas (63 ejecutan, 1 requiere servidor)
docs/s3_abigail/     este plan, 6 issues, diseño, plan de pruebas, decisiones, PR, bitácora
```
