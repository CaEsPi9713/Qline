# QLine · Seguimiento 2 · Abigail Urbina (`aurbina`)

**Área:** Ciclo de atención y continuidad operacional
**Rama personal:** `aurbina` → Pull Request hacia `development`
**Meta S2:** Núcleo funcional punta a punta con MongoDB + Redis reales, tag `v0.2.0`

---

## 1. Resumen de lo que te corresponde en S2

| ID | Tipo | Título | Prioridad | Estado S2 |
|---|---|---|---|---|
| HU-006 | Historia | Iniciar atención | MUST | REQUIRED |
| HU-007 | Historia | Finalizar atención | MUST | REQUIRED |
| TT-005 | Técnica | Script/datos sintéticos reproducibles | — | REQUIRED |
| — | Técnica | Panel funcional de atención (soporte de HU-006/007) | — | REQUIRED |
| TT-009 | Equipo | Constantes comunes (servicio, ventanillas, prioridades, TTL) | — | REQUIRED antes de integración |
| TT-010 | Equipo | Sanear baseline y README (eliminar `=======`) | — | REQUIRED antes de `v0.2.0` |

### Paralelo / opcional en S2 (no debe desplazar el núcleo)

| ID | Título | Expectativa S2 |
|---|---|---|
| HU-008 | Abandono de turno llamado (180 s) | Puede avanzarse; no es requisito de la demo |
| HU-012 | Recuperación de la cola tras pérdida de Redis | Solo diseñar compatibilidad |
| TT-012 | TTL / estado temporal (con Alessandro) | S3 |
| TT-017 | Prueba de caída y rehidratación | S3 |

### Fuera de tu responsabilidad (no implementar)
JSON Schema MongoDB · cola Redis / ZPOPMIN · emisión y consulta del cliente · dashboard SLA.

---

## 2. Issues para crear en GitHub

### HU-006 · Iniciar atención

**Épica:** EP-04
**Responsable:** Abigail Urbina / `aurbina`
**Seguimiento:** S2

#### Historia
Como operador
Quiero iniciar la atención de un turno llamado
Para registrar cuándo comienza el servicio.

#### Criterios de aceptación
- [ ] Solo acepta turnos en estado `llamado`.
- [ ] Cambia el estado a `en_atencion`.
- [ ] Registra `timestamps.inicio_atencion`.
- [ ] Conserva la ventanilla asignada.
- [ ] No puede iniciar el mismo turno simultáneamente en dos ventanillas.
- [ ] Un error (turno inexistente, estado inválido, ventanilla inválida) genera respuesta controlada.

#### Dependencias
- Contrato `turnos` (Carlos) — dependencia de integración, no bloquea.
- HU-005 (Alessandro) — dependencia funcional; usar turno controlado mientras tanto.

#### Evidencia esperada
- Captura/demostración del cambio `llamado` → `en_atencion` en MongoDB con `inicio_atencion`.
- Evidencia de respuesta controlada para estado inválido.

---

### HU-007 · Finalizar atención

**Épica:** EP-04
**Responsable:** Abigail Urbina / `aurbina`
**Seguimiento:** S2

#### Historia
Como operador
Quiero finalizar la atención
Para cerrar correctamente el turno y conservar su historial.

#### Criterios de aceptación
- [ ] Solo acepta turnos en estado `en_atencion`.
- [ ] Cambia el estado a `atendido`.
- [ ] Registra `timestamps.finalizado`.
- [ ] Permite calcular `metricas.atencion_seg` (inicio_atencion → finalizado).
- [ ] El turno no queda en la cola activa de Redis.
- [ ] El historial permanece en MongoDB.

#### Dependencias
- HU-006 (dependencia funcional).
- Contrato `turnos` (Carlos).

#### Evidencia esperada
- MongoDB mostrando estado `atendido` con todos los timestamps y `atencion_seg`.
- Prueba de que no se puede finalizar un turno que nunca inició atención.

---

### TT-005 · Script/datos sintéticos reproducibles

**Responsable:** Abigail Urbina / `aurbina`
**Seguimiento:** S2

#### Objetivo
Disponer de datos de prueba reproducibles, compatibles con el modelo `turnos`, sin datos personales reales.

#### Criterios de finalización
- [ ] Script ejecutable que genera turnos sintéticos con el contrato de la sección 4.5.
- [ ] Usa únicamente `servicio = atencion_general`, prioridades `normal`/`preferencial`, ventanillas `V-01`/`V-02`/`V-03` y estados oficiales.
- [ ] Incluye turnos en distintos estados (`pendiente`, `llamado`, `en_atencion`, `atendido`, `abandonado`) con timestamps coherentes.
- [ ] Es reproducible (semilla fija) y no duplica códigos al volver a ejecutarse.
- [ ] Respeta el JSON Schema de Carlos (campos aún no aplicables en `null`).
- [ ] Documentado en README: cómo ejecutarlo y qué genera.
- [ ] Sin datos personales ni secretos.

#### Contratos afectados
MongoDB (`turnos`) · documentación

#### Evidencia
Archivo del script, salida de ejecución y captura de los documentos insertados.

---

### TT-0XX · Panel funcional de atención

**Responsable:** Abigail Urbina / `aurbina`
**Seguimiento:** S2

#### Objetivo
Interfaz mínima para que un operador inicie y finalice la atención de un turno llamado.

#### Criterios de finalización
- [ ] Vista con el turno actual de la ventanilla (V-01/V-02/V-03).
- [ ] Botón/acción **Iniciar atención** (HU-006).
- [ ] Botón/acción **Finalizar atención** (HU-007).
- [ ] Muestra mensajes claros ante errores controlados.
- [ ] Separada del CRUD administrativo de turnos (Carlos).
- [ ] No agrega estados, prioridades ni autenticación compleja.

#### Evidencia
Capturas del panel y flujo grabado/demostrable.

---

## 3. Plan de actividades (orden sugerido)

### Fase 0 · Preparación
- [ ] Sincronizar `aurbina` desde `development` (tras saneamiento de baseline).
- [ ] Confirmar que la aplicación base inicia.
- [ ] Leer contratos: modelo `turnos` (§4.5), estados (§4.4), namespace Redis (§5).
- [ ] Verificar que existan constantes comunes (TT-009); si no, coordinar con el equipo.
- [ ] Revisar estructura actual del repositorio y listar qué archivos habrá que cambiar **antes** de programar.

### Fase 1 · Desarrollo con turno controlado (sin esperar a HU-005)
Usar un turno de prueba:

```json
{
  "codigo": "A-015",
  "estado": "llamado",
  "ventanilla": "V-01"
}
```

- [ ] Implementar lógica de **iniciar atención** (validar estado `llamado`, setear `en_atencion` + `inicio_atencion`).
- [ ] Implementar lógica de **finalizar atención** (validar `en_atencion`, setear `atendido` + `finalizado`, calcular `atencion_seg`).
- [ ] Validaciones de transiciones prohibidas:
  - [ ] iniciar un turno que no esté `llamado`;
  - [ ] finalizar un turno que nunca inició atención;
  - [ ] `pendiente` → `atendido` directo;
  - [ ] `atendido` → `pendiente`;
  - [ ] mismo turno activo en dos ventanillas.
- [ ] Respuestas controladas: turno inexistente, estado inválido, ventanilla inválida.
- [ ] Idempotencia: reintentar no genera doble inicio ni doble finalización.

### Fase 2 · Panel de atención
- [ ] Crear endpoints/rutas FastAPI para iniciar y finalizar.
- [ ] Crear plantilla Jinja2 del panel por ventanilla.
- [ ] Conectar acciones del panel con la lógica de las HU.

### Fase 3 · Datos sintéticos (TT-005)
- [ ] Diseñar script con semilla fija y turnos en todos los estados.
- [ ] Validar contra el JSON Schema de Carlos.
- [ ] Probar ejecución repetida sin duplicados.
- [ ] Documentar uso en README.

### Fase 4 · Integración real
- [ ] Reemplazar el turno controlado por el flujo real: Aaron emite → Alessandro llama → tú inicias/finalizas.
- [ ] Al finalizar, confirmar que el turno **no** permanece en la cola Redis (consistencia MongoDB/Redis, §17).
- [ ] Verificar claves Redis solo con el prefijo `grupo2:qline:`; sin `FLUSHALL`/`FLUSHDB`.
- [ ] Probar el flujo punta a punta (demo, §5 de este archivo).

### Fase 5 · Cierre
- [ ] Revisar Definition of Done y checklist de PR (secciones 4 y 5).
- [ ] Abrir PR hacia `development` con Issue asociado.
- [ ] Aportar tu sección real en `docs/seguimientos/S2.md` (solo hechos reales).
- [ ] Cerrar o reprogramar con justificación los Issues de S2.

### Fase 6 · Paralelo (solo si hay capacidad)
- [ ] **HU-008:** esbozar abandono a los 180 s (TTL oficial; estado final `abandonado`; `timestamps.abandonado`).
- [ ] **HU-012:** diseñar cómo rehidratar `pendiente` desde MongoDB respetando prioridad y llegada, sin duplicados ni turnos `atendido`/`abandonado`.

---

## 4. Definition of Done (tus HU)

- [ ] Cumple todos los criterios de aceptación.
- [ ] Respeta el modelo `turnos`, estados y prioridades oficiales.
- [ ] Usa el namespace `grupo2:qline:` cuando toca Redis.
- [ ] Maneja entradas inválidas de forma controlada.
- [ ] Sin inconsistencias conocidas entre MongoDB y Redis.
- [ ] Tiene evidencia de prueba (ejecutada de verdad).
- [ ] No rompe funcionalidad ya integrada.
- [ ] PR revisable, sin secretos, sin alcance no aprobado.

## 5. Checklist de Pull Request

- [ ] Rama sincronizada con `development`.
- [ ] Issue asociado (HU-006 / HU-007 / TT-005 / panel).
- [ ] Criterios de aceptación revisados.
- [ ] Sin secretos.
- [ ] Sin `FLUSHALL` / `FLUSHDB`.
- [ ] Claves Redis con `grupo2:qline:`.
- [ ] Estados y prioridades oficiales.
- [ ] Datos de prueba no reales.
- [ ] La aplicación inicia.
- [ ] Funcionalidad demostrable.
- [ ] Dependencias de integración identificadas.
- [ ] No se modificaron módulos ajenos sin necesidad.

---

## 6. Parte de la demo S2 donde participas

```
1. Emitir turno normal A-001                  (Aaron)
2. Emitir turno preferencial A-002            (Aaron)
3. Mostrar ambos en MongoDB
4. Mostrar cola Redis / vista de cola         (Alessandro)
5. Prioridad coloca A-002 primero
6. V-01 llama siguiente -> A-002              (Alessandro)
7. >>> Iniciar atención                       (Abigail · HU-006)
8. >>> Finalizar atención                     (Abigail · HU-007)
9. >>> Mostrar MongoDB con estado y timestamps finales
10. Mostrar CRUD de turnos + JSON Schema      (Carlos)
```

Mensaje técnico a dominar: MongoDB conserva el registro; Redis administra la cola activa; la llamada del siguiente turno es atómica.

---

## 7. Pruebas mínimas a ejecutar y documentar

| Caso | Resultado esperado |
|---|---|
| Iniciar turno `llamado` | Pasa a `en_atencion` con `inicio_atencion` |
| Iniciar turno `pendiente` | Rechazo controlado |
| Iniciar turno inexistente | Respuesta controlada (no error 500) |
| Finalizar turno `en_atencion` | Pasa a `atendido` con `finalizado` y `atencion_seg` |
| Finalizar turno `llamado` (sin iniciar) | Rechazo controlado |
| Finalizar turno ya `atendido` | Rechazo controlado / sin doble finalización |
| Reintentar iniciar el mismo turno | Sin doble inicio |
| Ejecutar script sintético dos veces | Sin códigos duplicados |

> No declarar pruebas como aprobadas sin ejecutarlas, ni inventar resultados en `S2.md`.

---

## 8. Preguntas que debes poder responder en el seguimiento

1. ¿Qué dato vive en MongoDB y por qué?
2. ¿Qué dato vive en Redis y por qué?
3. ¿Por qué Redis ayuda a evitar la doble asignación?
4. ¿Cuál es la entidad central y cuáles son los estados válidos?
5. ¿Cómo funciona la prioridad preferencial vs normal?
6. ¿Qué significa el namespace `grupo2:qline:`?
7. ¿Qué ocurre si Redis falla?
8. ¿Por qué existe CRUD administrativo si el historial normal no se elimina?
9. ¿Qué parte desarrollaste tú personalmente (HU-006, HU-007, TT-005, panel)?

---

## 9. Prompt base para tu asistente de IA

```
Estás colaborando en el proyecto QLine. El documento maestro es la fuente de verdad.

Soy Abigail Urbina, rama aurbina. Mis tareas de S2: HU-006 Iniciar atención,
HU-007 Finalizar atención, TT-005 datos sintéticos y el panel funcional de atención.

No desarrolles funcionalidades de otros responsables. No inventes estados, prioridades,
claves Redis ni campos MongoDB. Usa el turno controlado
{"codigo":"A-015","estado":"llamado","ventanilla":"V-01"} mientras HU-005 no esté integrada.
Antes de modificar código, revisa la estructura y explica qué archivos cambiarán.
Trabaja incrementalmente, valida cada criterio de aceptación y no declares pruebas
aprobadas sin ejecutarlas.
```
