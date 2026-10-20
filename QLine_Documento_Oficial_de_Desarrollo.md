# QLine — Documento Oficial de Desarrollo del MVP

**Sistema de gestión de filas y turnos en tiempo real**

| Campo | Valor |
|---|---|
| Producto | QLine |
| Tipo de documento | Documento oficial de desarrollo (fuente funcional de verdad del MVP) |
| Lenguaje de implementación conocido | Python |
| Equipo | 4 desarrolladores |
| Backlog | 16 Historias de Usuario (4 por desarrollador) |
| Motores de datos | Redis (operación actual) y MongoDB (persistencia) |
| Branch de integración | `development` |
| Branch final | `main` |
| Estado del documento | Vigente. Las decisiones abiertas están en la sección 35 |

**Convención de este documento:** todo aquello que no fue definido por el equipo se marca como **Decisión pendiente del equipo** o **Contrato técnico a definir antes de integración**. Ningún lector (persona o IA) debe completar esos puntos por su cuenta.

---

# 1. Portada

**QLine**
*Gestión de filas y turnos en tiempo real*

Documento destinado a:

- Aaron Benavides (`abenavides`)
- Alessandro Cambronero (`acambronero`)
- Abigail Urbina (`aurbina`)
- Carlos Espinoza (`cespinoza`)
- El profesor, para comprender alcance y arquitectura.
- Las IA utilizadas por cada desarrollador como contexto de trabajo.

---

# 2. Propósito del documento

Este documento define **qué debe hacer QLine**, no **cómo debe programarse**. Sirve para:

1. **El equipo de cuatro desarrolladores:** repartir el trabajo sin solapamientos y sin decisiones contradictorias entre branches.
2. **El profesor:** comprender el alcance, la arquitectura conceptual y la distribución del trabajo.
3. **Las IA de desarrollo:** cada desarrollador podrá entregar este documento (o su sección individual, ver secciones 24 a 28) como contexto de trabajo.
4. **Integración, pruebas y validación final:** contiene los criterios, checklists y reglas de consistencia que se usarán para integrar y declarar terminado el MVP.

## 2.1 Qué define este documento

- Qué debe hacer el sistema.
- Qué debe cumplir cada Historia de Usuario.
- Qué información comparten los módulos (contratos).
- Qué validaciones son obligatorias.
- Qué dependencias existen y de qué tipo son.
- Qué debe comprobarse durante integración.

## 2.2 Qué NO define este documento

Este documento **no impone**:

- framework web específico (Flask, FastAPI, Django u otro);
- librerías específicas;
- estructura de carpetas;
- patrones de diseño o arquitectura de código (MVC, Repository, hexagonal u otros);
- estrategia específica de endpoints;
- herramienta de frontend ni framework JavaScript;
- ORM u ODM;
- metodología Agile particular;
- estrategia interna de testing;
- la forma exacta de escribir el código.

Se conoce únicamente que el sistema se desarrollará con **Python**. Cada desarrollador define su metodología interna de trabajo dentro de su branch.

## 2.3 Principios obligatorios

1. **No inventar funcionalidades.** No se agrega nada fuera del alcance especificado. Si se detecta que falta una decisión, se marca como **Decisión pendiente del equipo**. No se completan por cuenta propia reglas de negocio no especificadas.
2. **No determinar cómo programa cada desarrollador.** Ver 2.2.
3. **Las Historias de Usuario representan comportamiento.** No son Historias de Usuario: benchmarks, reglas generales, validaciones comunes, Definition of Done, contratos de datos, pruebas de concurrencia, pruebas de recuperación, validación de estados ni manejo transversal de errores. Estos se documentan como reglas globales, contratos compartidos, validaciones técnicas, criterios transversales y requisitos de integración.

---

# 3. Descripción del producto

**QLine** es un sistema web que administra filas de atención en organizaciones como:

- clínicas;
- municipalidades;
- cooperativas;
- universidades;
- centros de servicio.

El sistema permite:

- generar turnos;
- asignar un identificador único;
- generar un QR relacionado con el turno;
- consultar estado y posición;
- visualizar una cola activa;
- manejar prioridades;
- trabajar con múltiples ventanillas;
- evitar asignaciones duplicadas;
- iniciar atenciones;
- finalizar atenciones;
- gestionar expiración o abandono;
- mostrar turnos llamados en una pantalla pública;
- gestionar servicios;
- gestionar ventanillas;
- conservar historial;
- generar métricas;
- medir cumplimiento de SLA;
- recuperar la cola después de una pérdida de Redis.

---

# 4. Problema

QLine busca resolver problemas frecuentes en la atención presencial:

- desorden en las filas;
- dificultad para conocer quién sigue;
- falta de visibilidad para el usuario;
- múltiples operadores trabajando simultáneamente;
- riesgo de que dos operadores tomen el mismo turno;
- dificultad para manejar prioridades;
- falta de historial;
- falta de trazabilidad;
- pérdida del estado operacional ante una falla temporal;
- dificultad para medir tiempos de espera y atención.

## 4.1 Diferenciador técnico: concurrencia

El principal diferenciador técnico del MVP es el manejo de **concurrencia**.

Ejemplo con la cola:

```text
A-015
A-016
A-017
```

Dos operadores solicitan aproximadamente al mismo tiempo el siguiente turno.

**Resultado correcto:**

```text
Ventanilla 1 → A-015
Ventanilla 2 → A-016
```

**Resultado no permitido:**

```text
Ventanilla 1 → A-015
Ventanilla 2 → A-015
```

El sistema debe garantizar:

```text
Turnos asignados duplicados = 0
```

---

# 5. Propuesta de valor

QLine permite administrar filas de atención de forma **rápida, concurrente, trazable, persistente y recuperable**.

Los cuatro pilares del producto:

| Pilar | Significado |
|---|---|
| **Tiempo real** | La cola refleja el estado operacional actual. |
| **Concurrencia** | Dos operadores no deben obtener el mismo turno. |
| **Persistencia** | MongoDB mantiene el historial y los datos confirmados. |
| **Recuperación** | La cola activa puede reconstruirse tras una pérdida temporal de Redis. |

---

# 6. Alcance

El alcance del MVP son exactamente las **16 Historias de Usuario** de la sección 15, más las reglas globales (21), validaciones técnicas (22) y requisitos generales de proyecto (32).

- Dentro del alcance: todo lo descrito en las secciones 3 y 15.
- Fuera del alcance: ver sección 31.
- Cualquier funcionalidad no incluida en las 16 HU solo puede aparecer como **posible mejora futura**.

---

# 7. Arquitectura conceptual

QLine utiliza **dos motores de datos con responsabilidades diferentes**.

```text
                        QLINE
                          │
                  Aplicación Web
                       Python
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
           REDIS                    MONGODB
       Operación actual            Persistencia
             │                         │
       Cola activa                   Turnos
       Prioridades                   Historial
       Concurrencia                  Eventos
       Disponibilidad                Servicios
       Estados temporales            Ventanillas
       Expiración                    Métricas
```

Esta arquitectura es **conceptual**. No determina framework, estructura de código ni patrón de diseño.

---

# 8. Responsabilidad de MongoDB

MongoDB es la **fuente persistente de información**.

Debe permitir conservar:

- turnos;
- servicios;
- ventanillas;
- estados persistentes;
- historial;
- eventos;
- timestamps;
- tiempo de espera;
- tiempo de atención;
- datos para el dashboard;
- información utilizada para SLA.

> **MongoDB conserva lo que ocurrió.**

MongoDB debe permitir reconstruir el contexto persistente aun cuando Redis pierda información temporal.

---

# 9. Responsabilidad de Redis

Redis representa el **estado operacional inmediato**.

Se utiliza conceptualmente para:

- cola activa;
- orden de atención;
- prioridades;
- obtener el siguiente turno;
- concurrencia;
- disponibilidad actual;
- estados temporales;
- expiración cuando corresponda.

> **Redis controla lo que ocurre ahora.**

Redis **no** debe considerarse la única fuente persistente de los turnos.

## 9.1 Separación de responsabilidades

| Aspecto | Redis | MongoDB |
|---|---|---|
| Cola activa y orden de atención | Sí | No es su función operacional |
| Obtener el siguiente turno | Sí | No |
| Control de concurrencia | Sí | No |
| Estados temporales / expiración | Sí | Registra el resultado persistente |
| Historial y eventos | No | Sí |
| Servicios y ventanillas | No es fuente | Sí |
| Métricas y SLA | No es fuente | Sí (datos base) |
| Reconstrucción tras falla | Se reconstruye | Es la fuente de reconstrucción |

No deben mezclarse responsabilidades Redis/MongoDB sin justificación documentada y aprobada por el equipo.

---

# 10. Resiliencia

Si Redis pierde la cola activa, MongoDB debe conservar información suficiente para reconstruirla.

```text
Redis falla
    ↓
MongoDB conserva los turnos pendientes
    ↓
Redis vuelve a estar disponible
    ↓
Se identifican los turnos pendientes
    ↓
Se reconstruye la cola
    ↓
Continúa la operación
```

La reconstrucción debe:

- considerar solamente turnos válidos;
- respetar prioridad;
- respetar orden de llegada;
- evitar duplicados;
- evitar pérdida de turnos pendientes;
- mantener consistencia con MongoDB.

Responsable principal: Abigail Urbina (HU-016). La validación técnica asociada está en la sección 22.3.

---

# 11. Perfiles

## 11.1 Cliente / usuario

Puede:

- generar un turno;
- recibir su código;
- recibir QR;
- consultar su turno;
- conocer su estado;
- conocer su posición.

## 11.2 Operador

Puede:

- visualizar la cola;
- obtener el siguiente turno;
- iniciar una atención;
- finalizar una atención.

## 11.3 Supervisor

Puede:

- gestionar servicios;
- gestionar ventanillas;
- consultar historial;
- visualizar métricas;
- consultar indicadores SLA.

> La autenticación empresarial avanzada y los roles complejos están fuera del alcance (sección 31). Cómo se distinguen los perfiles dentro del MVP es una **Decisión pendiente del equipo** (sección 35).

---

# 12. Contratos compartidos

Los siguientes contratos son comunes a todos los desarrolladores. **No deben modificarse unilateralmente.** Si un desarrollador considera necesario modificar un contrato, debe elevarlo como decisión del equipo **antes** de implementarlo.

## 12.1 Contrato mínimo de Turno

Como mínimo, un turno debe poder representar conceptualmente:

```json
{
  "codigo": "A-015",
  "servicio_id": "cajas",
  "prioridad": "preferencial",
  "estado": "en_espera",
  "ventanilla_id": null,
  "creado_en": "...",
  "llamado_en": null,
  "inicio_atencion": null,
  "finalizado_en": null
}
```

Reglas sobre el contrato:

- Los módulos pueden requerir información adicional.
- No deben eliminarse campos compartidos.
- No debe cambiarse su significado unilateralmente.
- No deben crearse estructuras incompatibles con otros módulos.

> El ejemplo es ilustrativo del contenido mínimo. El formato exacto del código de turno y de los valores de prioridad y estado en almacenamiento queda como **Decisión pendiente del equipo** (sección 35). Los nombres de campo del ejemplo deben tomarse como el contrato mínimo conceptual vigente.

## 12.2 Contrato mínimo de Servicio

```text
id
nombre
activo
```

## 12.3 Contrato mínimo de Ventanilla

```text
id
nombre
activo
```

## 12.4 Contrato Redis

Antes de integrar módulos, el equipo deberá definir y documentar:

- formato de claves;
- identificación de cada cola;
- dato utilizado para identificar un turno;
- representación de prioridad;
- estructura necesaria para ordenar turnos;
- información temporal almacenada;
- mecanismo conceptual de expiración.

> **Contrato técnico a definir antes de integración.**

Este documento no define una estructura Redis definitiva porque aún no fue aprobada por el equipo.

## 12.5 Prioridades

Debe existir una **lista central de prioridades permitidas**.

Regla general de ordenamiento:

```text
1. Prioridad
2. Orden de llegada
```

Entre turnos con la misma prioridad se respeta el orden de llegada.

La lista exacta de prioridades es:

> **Decisión pendiente del equipo.**

Ningún desarrollador debe inventar prioridades adicionales unilateralmente.

---

# 13. Estados y reglas

## 13.1 Estados oficiales

**Flujo principal:**

```text
En espera
    ↓
Llamado
    ↓
En atención
    ↓
Atendido
```

**Flujo alternativo:**

```text
En espera → Expirado
```

No deben crearse estados adicionales sin acuerdo del equipo.

## 13.2 Tabla de transiciones

| Desde | Hacia | Permitida | HU relacionada |
|---|---|---|---|
| En espera | Llamado | Sí | HU-007 |
| Llamado | En atención | Sí | HU-009 |
| En atención | Atendido | Sí | HU-010 |
| En espera | Expirado | Sí | HU-006 |
| Cualquier otra | — | No definida en este documento | Decisión pendiente si se requiere |

## 13.3 Reglas de transición (no permitido)

No debe permitirse:

- llamar un turno expirado;
- atender un turno expirado;
- iniciar un turno que no esté llamado;
- finalizar normalmente un turno que no inició atención;
- regresar un turno atendido a espera;
- asignar nuevamente un turno atendido;
- asignar el mismo turno simultáneamente a dos ventanillas.

---

# 14. Épicas

| Épica | Nombre | Historias |
|---|---|---|
| 1 | Emisión y seguimiento | HU-001, HU-002, HU-003 |
| 2 | Cola en tiempo real | HU-004, HU-005 |
| 3 | Continuidad y expiración | HU-006 |
| 4 | Operación de ventanillas | HU-007, HU-008, HU-009, HU-010 |
| 5 | Visualización pública | HU-011 |
| 6 | Configuración operacional | HU-012, HU-013 |
| 7 | Historial y supervisión | HU-014, HU-015 |
| 8 | Recuperación | HU-016 |

---

# 15. Historias de Usuario completas

> Backlog oficial: **16 HU**, 4 por desarrollador. No se crean HU adicionales, no se eliminan y no se cambia su numeración.

## ÉPICA 1 — Emisión y seguimiento

### HU-001 — Generar turno

**Como** cliente
**Quiero** generar un turno para un servicio
**Para** ingresar a la fila correspondiente.

**Criterios de aceptación**

- El cliente puede seleccionar un servicio activo.
- Puede seleccionar una prioridad válida.
- Se genera un código de turno único.
- Se registra fecha y hora de creación.
- El turno inicia en estado `En espera`.
- El turno queda incorporado a la fila correspondiente.
- Se muestra confirmación de creación.
- Un error no debe dejar el turno parcialmente creado.
- No deben existir códigos duplicados.

---

### HU-002 — Generar e identificar turno mediante QR

**Como** cliente
**Quiero** disponer de un QR asociado a mi turno
**Para** poder identificar y consultar posteriormente mi turno.

**Criterios de aceptación**

- Cada QR corresponde únicamente a un turno.
- El QR permite identificar el turno.
- No debe exponer información sensible.
- Un QR inválido produce una respuesta controlada.
- No deben existir asociaciones duplicadas entre QR y turno.
- El QR debe seguir identificando correctamente el turno mientras este exista en el sistema.

---

### HU-003 — Consultar mi turno

**Como** cliente
**Quiero** consultar mi turno
**Para** conocer mi estado y posición dentro de la fila.

**Criterios de aceptación**

Debe mostrarse:

- código;
- servicio;
- prioridad;
- estado;
- cantidad de turnos antes.

Además:

- la posición debe corresponder a la cola vigente;
- un turno atendido no debe aparecer como pendiente;
- un turno expirado debe mostrar ese estado;
- un identificador inválido debe manejarse de forma controlada.

---

## ÉPICA 2 — Cola en tiempo real

### HU-004 — Visualizar cola activa

**Como** operador
**Quiero** visualizar los turnos disponibles
**Para** conocer el estado actual de la fila.

**Criterios de aceptación**

- Solo aparecen turnos disponibles para atención.
- Se muestra código.
- Se muestra servicio.
- Se muestra prioridad.
- Se respeta el orden vigente.
- Consultar la cola no modifica su contenido.
- Un turno asignado deja de mostrarse como disponible.
- Un turno expirado no aparece como disponible.

---

### HU-005 — Gestionar prioridades

**Como** organización
**Quiero** ordenar los turnos según prioridad y orden de llegada
**Para** aplicar correctamente las reglas de atención.

**Criterios de aceptación**

- Se respetan las prioridades oficiales.
- Una prioridad superior recibe la precedencia establecida.
- Turnos con igual prioridad mantienen orden de llegada.
- La regla se aplica consistentemente.
- La prioridad permanece asociada al turno durante su ciclo.

---

## ÉPICA 3 — Continuidad y expiración

### HU-006 — Gestionar expiración o abandono

**Como** organización
**Quiero** controlar turnos que dejan de ser válidos
**Para** evitar mantener indefinidamente turnos abandonados.

**Criterios de aceptación**

- Puede existir un período de expiración configurable.
- Al vencer el período, el turno deja de estar disponible.
- El turno pasa al estado correspondiente.
- El evento queda registrado.
- Un turno expirado no puede llamarse posteriormente.
- La expiración no debe eliminar la trazabilidad histórica del turno.

---

## ÉPICA 4 — Operación de ventanillas

### HU-007 — Llamar al siguiente turno

**Como** operador
**Quiero** obtener el siguiente turno disponible
**Para** continuar la atención de la fila.

**Criterios de aceptación**

- Cada solicitud obtiene como máximo un turno.
- Se respeta prioridad.
- Se respeta orden de llegada.
- El turno cambia a `Llamado`.
- Se registra la ventanilla.
- El turno deja de estar disponible para otros operadores.
- Si no existen turnos pendientes, se informa claramente.

---

### HU-008 — Evitar asignaciones duplicadas

**Como** organización
**Quiero** impedir que dos operadores obtengan el mismo turno
**Para** garantizar una operación concurrente correcta.

**Criterios de aceptación**

- Varias solicitudes pueden ejecutarse simultáneamente.
- Cada operador debe recibir un turno diferente.
- Un turno no puede quedar asignado simultáneamente a dos ventanillas.
- La prueba debe poder repetirse sin producir duplicados.

Resultado obligatorio:

```text
Turnos asignados duplicados = 0
```

---

### HU-009 — Iniciar atención

**Como** operador
**Quiero** iniciar un turno previamente llamado
**Para** registrar correctamente el inicio de la atención.

**Criterios de aceptación**

- Solo un turno `Llamado` puede iniciar atención.
- Cambia a estado `En atención`.
- Se registra fecha y hora de inicio.
- Se conserva la ventanilla responsable.
- No puede iniciar simultáneamente en otra ventanilla.

---

### HU-010 — Finalizar atención

**Como** operador
**Quiero** finalizar una atención
**Para** registrar correctamente que el servicio terminó.

**Criterios de aceptación**

- Solo un turno `En atención` puede finalizar normalmente.
- Cambia a estado `Atendido`.
- Se registra fecha y hora.
- Puede determinarse la duración.
- El turno deja definitivamente la cola activa.
- No puede volver a asignarse.

---

## ÉPICA 5 — Visualización pública

### HU-011 — Pantalla pública

**Como** cliente en sala de espera
**Quiero** visualizar los turnos llamados
**Para** saber cuándo y dónde debo ser atendido.

**Criterios de aceptación**

- Se muestra código del turno.
- Se muestra ventanilla.
- Pueden mostrarse llamados recientes.
- No se muestran datos personales.
- La información corresponde al estado vigente.
- Un turno finalizado no debe mantenerse indefinidamente como llamado activo.

---

## ÉPICA 6 — Configuración operacional

### HU-012 — Gestionar servicios

**Como** supervisor
**Quiero** administrar servicios
**Para** controlar las filas disponibles.

**Criterios de aceptación**

- Crear servicio.
- Activar servicio.
- Desactivar servicio.
- Solo servicios activos permiten nuevos turnos.
- Desactivar un servicio no elimina su historial.
- Un servicio utilizado históricamente debe seguir siendo identificable.

---

### HU-013 — Gestionar ventanillas

**Como** supervisor
**Quiero** administrar ventanillas
**Para** controlar los puntos disponibles de atención.

**Criterios de aceptación**

- Crear ventanilla.
- Activar ventanilla.
- Desactivar ventanilla.
- Solo ventanillas activas pueden recibir nuevos turnos.
- El historial conserva la ventanilla utilizada.
- Desactivar una ventanilla no elimina su historial.

---

## ÉPICA 7 — Historial y supervisión

### HU-014 — Consultar historial

**Como** supervisor
**Quiero** consultar turnos procesados
**Para** disponer de trazabilidad de la operación.

**Criterios de aceptación**

Debe poder consultarse:

- código;
- servicio;
- prioridad;
- estado;
- ventanilla;
- creación;
- llamado;
- inicio de atención;
- finalización.

Debe poder determinarse:

- tiempo de espera;
- duración de atención.

Además:

- los datos históricos permanecen disponibles aunque el turno ya no exista en Redis;
- los registros deben corresponder con eventos confirmados del sistema.

---

### HU-015 — Dashboard y métricas SLA

**Como** supervisor
**Quiero** visualizar indicadores operacionales
**Para** conocer el estado y desempeño del servicio.

**Criterios de aceptación**

Como mínimo mostrar:

- turnos esperando;
- turnos atendidos;
- tiempo promedio de espera;
- tiempo promedio de atención;
- ventanillas activas.

Además:

- debe poder definirse un objetivo SLA;
- debe poder determinarse cumplimiento o incumplimiento;
- las métricas deben derivarse de información real registrada por QLine;
- los valores mostrados deben poder verificarse con los datos persistidos.

---

## ÉPICA 8 — Recuperación

### HU-016 — Recuperar cola tras pérdida de Redis

**Como** organización
**Quiero** reconstruir la cola activa después de una falla
**Para** continuar operando sin perder turnos pendientes válidos.

**Criterios de aceptación**

- MongoDB conserva los turnos pendientes.
- Se identifican los turnos `En espera`.
- Puede reconstruirse la cola.
- Se respeta prioridad.
- Se respeta orden de llegada.
- No aparecen duplicados.
- No se pierden turnos pendientes válidos.
- La cantidad recuperada coincide con los pendientes persistidos.
- La reconstrucción no modifica indebidamente el historial.

---

# 16. Criterios de aceptación: resumen de trazabilidad

Los criterios de aceptación de cada HU están completos en la sección 15 y son la **fuente funcional de verdad**. Esta tabla solo ayuda a verificar que no se perdió ninguno.

| HU | Nº de criterios (bloques de lista) | Notas |
|---|---|---|
| HU-001 | 9 | |
| HU-002 | 6 | |
| HU-003 | 5 campos + 4 reglas | |
| HU-004 | 8 | |
| HU-005 | 5 | |
| HU-006 | 6 | |
| HU-007 | 7 | |
| HU-008 | 4 + resultado obligatorio | Duplicados = 0 |
| HU-009 | 5 | |
| HU-010 | 6 | |
| HU-011 | 6 | |
| HU-012 | 6 | |
| HU-013 | 6 | |
| HU-014 | 9 campos + 2 derivados + 2 reglas | |
| HU-015 | 5 indicadores + 4 reglas | |
| HU-016 | 9 | |

---

# 17. Distribución por desarrollador

La distribución es exactamente la siguiente.

| Desarrollador | Branch | Área principal | HU asignadas | Total |
|---|---|---|---|---|
| **Aaron Benavides** | `abenavides` | Experiencia del cliente y visualización | HU-001, HU-002, HU-003, HU-011 | 4 |
| **Alessandro Cambronero** | `acambronero` | Cola activa, prioridad y concurrencia | HU-004, HU-005, HU-007, HU-008 | 4 |
| **Abigail Urbina** | `aurbina` | Ciclo de atención, expiración y recuperación | HU-006, HU-009, HU-010, HU-016 | 4 |
| **Carlos Espinoza** | `cespinoza` | Configuración, historial y supervisión | HU-012, HU-013, HU-014, HU-015 | 4 |

Verificación: 16 HU, cada una con un único responsable.

| HU | Responsable |
|---|---|
| HU-001 | Aaron |
| HU-002 | Aaron |
| HU-003 | Aaron |
| HU-004 | Alessandro |
| HU-005 | Alessandro |
| HU-006 | Abigail |
| HU-007 | Alessandro |
| HU-008 | Alessandro |
| HU-009 | Abigail |
| HU-010 | Abigail |
| HU-011 | Aaron |
| HU-012 | Carlos |
| HU-013 | Carlos |
| HU-014 | Carlos |
| HU-015 | Carlos |
| HU-016 | Abigail |

---

# 18. Dependencias

Se distinguen dos categorías.

## 18.1 Dependencia funcional

Una funcionalidad necesita conceptualmente a otra para completar su **flujo**.

```text
HU-010 Finalizar atención
       ↓
HU-009 Iniciar atención
```

Existe una relación funcional real: no se puede finalizar una atención que nunca inició.

## 18.2 Dependencia de integración

Una funcionalidad utilizará finalmente información proporcionada por otro módulo, pero **puede desarrollarse previamente con datos controlados**.

```text
HU-003 Consultar mi turno
       ↓
HU-004 Cola activa
```

Esto **no** significa que Aaron deba esperar a Alessandro. Puede utilizar:

- datos sintéticos;
- mocks;
- fixtures;
- colas precargadas;
- registros controlados;

siempre que respeten el contrato común.

---

# 19. Mapa de dependencias

| # | Relación | Tipo | Descripción | Responsables | ¿Bloquea? |
|---|---|---|---|---|---|
| 1 | HU-001 → HU-012 | Integración | Generar turno consume servicios válidos. | Aaron / Carlos | No. Aaron usa servicios sintéticos compatibles con el contrato. |
| 2 | HU-002 → HU-001 | Funcional | El QR necesita existir asociado a un turno. | Aaron (ambas) | Sí, orden lógico interno. |
| 3 | HU-003 → HU-004 | Integración | Consultar posición necesita conocer el estado de la cola. | Aaron / Alessandro | No. Se desarrolla con cola de prueba. |
| 4 | HU-011 → HU-007 | Integración | La pantalla pública muestra turnos llamados. | Aaron / Alessandro | No. Se prueba con turnos sintéticos `Llamado`. |
| 5 | HU-005 → HU-004 | Funcional interna | Las prioridades determinan el orden de la cola. | Alessandro (ambas) | Sí, orden lógico interno. |
| 6 | HU-007 → HU-013 | Integración | Llamar siguiente utiliza una ventanilla válida. | Alessandro / Carlos | No. Usa ventanilla controlada. |
| 7 | HU-008 → HU-007 | Funcional | La prueba de concurrencia ocurre sobre la asignación del siguiente turno. | Alessandro (ambas) | Sí, orden lógico interno. |
| 8 | HU-006 → Contrato de cola | Integración | Expiración requiere conocer la estructura operacional acordada. | Abigail | No espera el desarrollo completo de HU-004. |
| 9 | HU-009 → HU-007 | Integración | Iniciar atención necesita un turno previamente llamado. | Abigail / Alessandro | No. Usa turno sintético `Llamado`. |
| 10 | HU-010 → HU-009 | Funcional | Finalizar requiere una atención iniciada. | Abigail (ambas) | Sí, orden lógico interno. |
| 11 | HU-014 → HU-009 / HU-010 | Integración | El historial usa información producida en el ciclo de atención. | Carlos / Abigail | No. Carlos usa documentos históricos sintéticos. |
| 12 | HU-015 → HU-013 / HU-014 | Interna al bloque de Carlos | El dashboard usa ventanillas e información histórica. | Carlos (todas) | Dependencias internas al bloque. |
| 13 | HU-016 → MongoDB + contrato Redis | Integración | Recuperación requiere turnos persistidos, contrato de cola, prioridad y orden de llegada. | Abigail | No requiere esperar la implementación completa si los contratos están definidos. |

**Resumen:** las dependencias **funcionales** (2, 5, 7, 10) ocurren siempre dentro del bloque de un mismo desarrollador. Ninguna dependencia funcional cruza entre desarrolladores.

---

# 20. Regla contra bloqueos

> ## **Una dependencia de integración NO debe bloquear el desarrollo.**

Cuando el contrato correspondiente esté definido, cualquier desarrollador puede utilizar:

- mocks;
- fixtures;
- documentos sintéticos;
- colecciones precargadas;
- estructuras controladas;
- simulaciones;

para desarrollar su Historia de Usuario de forma independiente.

Solo las dependencias **funcionales** dentro de un mismo flujo requieren respetar el orden lógico correspondiente.

**Condición:** el dato simulado debe respetar el contrato compartido (sección 12). Un mock incompatible con el contrato invalida la integración posterior. Mientras el **contrato Redis** (12.4) y la **lista de prioridades** (12.5) no estén definidos, deben resolverse primero como decisión del equipo; es lo único que sí condiciona el trabajo de HU-005, HU-006 y HU-016.

---

# 21. Reglas globales

Aplican transversalmente a todas las HU.

## 21.1 Integridad

Debe validarse:

- código de turno único;
- servicio válido;
- prioridad válida;
- ventanilla válida;
- estado permitido;
- campos obligatorios.

## 21.2 Consistencia

```text
Turno atendido   → NO permanece en cola activa
Turno expirado   → NO puede ser llamado
Turno llamado    → NO debe seguir disponible
Turno asignado   → NO puede pertenecer simultáneamente a dos ventanillas
Recuperación     → NO debe producir duplicados
```

## 21.3 Manejo de errores

Una operación fallida:

- debe producir una respuesta controlada;
- no debe dejar silenciosamente estados contradictorios;
- no debe producir duplicados al reintentarse;
- no debe eliminar información previamente confirmada;
- no debe ocultar errores críticos.

---

# 22. Validaciones técnicas del MVP

> Estas validaciones **no** son nuevas Historias de Usuario.

## 22.1 Concurrencia

Ejecutar solicitudes concurrentes de múltiples operadores.

Registrar:

- cantidad de solicitudes;
- turnos obtenidos;
- turnos únicos;
- duplicados.

Resultado obligatorio:

```text
Duplicados = 0
```

La prueba debe contemplar múltiples solicitudes concurrentes y permitir repetición.

Plantilla de registro:

| Ejecución | Solicitudes | Turnos obtenidos | Turnos únicos | Duplicados |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

## 22.2 Rendimiento

Comparar operaciones equivalentes, cuando técnicamente corresponda, entre:

```text
Redis
vs
MongoDB
```

Registrar:

- cantidad de ejecuciones;
- tiempo mínimo;
- tiempo máximo;
- promedio;
- mediana cuando corresponda.

No se establece por anticipado que "Redis debe ser X% más rápido". **La mejora debe medirse, no asumirse.**

Plantilla de registro:

| Operación equivalente | Motor | Ejecuciones | Mín | Máx | Promedio | Mediana |
|---|---|---|---|---|---|---|
| | Redis | | | | | |
| | MongoDB | | | | | |

## 22.3 Recuperación

Proceso mínimo:

```text
1. Crear turnos pendientes
2. Confirmar persistencia
3. Simular pérdida de Redis
4. Restaurar disponibilidad
5. Reconstruir cola
6. Comparar antes y después
```

Resultado esperado:

```text
100% de turnos pendientes válidos recuperados
```

sin duplicados.

Plantilla de registro:

| Dato | Antes de la pérdida | Después de la reconstrucción |
|---|---|---|
| Turnos pendientes | | |
| Orden de atención | | |
| Duplicados | | |

---

# 23. Definition of Done global

Una Historia de Usuario solo puede considerarse completada cuando:

- [ ] cumple todos sus criterios de aceptación;
- [ ] respeta los contratos compartidos;
- [ ] respeta los estados oficiales;
- [ ] valida entradas inválidas;
- [ ] maneja errores de manera controlada;
- [ ] no introduce duplicados;
- [ ] no rompe funcionalidades previamente integradas;
- [ ] puede demostrarse utilizando datos de prueba;
- [ ] es compatible con las dependencias establecidas;
- [ ] no incluye funcionalidades fuera del alcance;
- [ ] puede integrarse con `development`.

---

# 24. Instrucciones generales para IA de desarrollo

> Esta sección es reutilizable. Cada desarrollador puede copiarla a su IA, junto con las secciones 12, 13, 15 (sus HU), 19 y su contexto individual.

```text
Estás colaborando en el desarrollo del MVP QLine.

Debes trabajar exclusivamente sobre las Historias de Usuario asignadas al desarrollador.

Las Historias de Usuario y sus criterios de aceptación representan la fuente funcional de verdad.

Debes respetar todos los contratos comunes definidos para QLine.

No modifiques unilateralmente:

- estructura de Turno;
- estados;
- prioridades;
- contratos de Servicio;
- contratos de Ventanilla;
- contratos de integración.

No inventes reglas de negocio.

No agregues funcionalidades fuera del alcance.

Si encuentras una decisión necesaria que no está definida, detente y solicita aclaración.

No asumas información faltante.

Una dependencia de integración no significa que debas esperar a otro desarrollador.

Puedes utilizar mocks, fixtures, documentos sintéticos o estructuras controladas siempre que respeten los contratos comunes.

No modifiques módulos pertenecientes a otro desarrollador salvo que exista una necesidad real de integración y autorización.

Antes de implementar una HU debes revisar:

1. Historia de Usuario.
2. Criterios de aceptación.
3. Contratos involucrados.
4. Dependencias.
5. Estados afectados.
6. Riesgos de consistencia.
7. Posibles efectos sobre otros módulos.

Antes de marcar una HU como terminada debes comprobar todos sus criterios de aceptación.

No determines por tu cuenta un framework o metodología que no haya sido proporcionado por el desarrollador.

Prioriza:

- correctitud;
- consistencia;
- trazabilidad;
- mantenibilidad;
- idempotencia cuando corresponda;
- manejo de errores;
- compatibilidad con integración.

Trabaja de forma incremental.

No realices cambios masivos sin comprender primero el estado actual del branch.

Si recibes código existente:

- analízalo antes de modificarlo;
- evita romper funcionalidades existentes;
- identifica dependencias;
- conserva compatibilidad con los contratos comunes.

Si una Historia de Usuario depende de otro módulo todavía no integrado, utiliza datos controlados y deja claramente identificado el punto de integración futura.

No declares una Historia de Usuario terminada mientras exista un criterio de aceptación sin validar.
```

---

# 25. Contexto individual — Aaron Benavides

| Campo | Valor |
|---|---|
| Nombre | Aaron Benavides |
| Branch | `abenavides` |
| Área funcional | Experiencia del cliente y visualización pública |
| HU | HU-001, HU-002, HU-003, HU-011 |

## 25.1 Historias de Usuario completas

Ver sección 15: **HU-001** (Generar turno), **HU-002** (QR), **HU-003** (Consultar mi turno), **HU-011** (Pantalla pública). Todos sus criterios de aceptación aplican íntegramente.

## 25.2 Dependencias

| Relación | Tipo | ¿Espera? |
|---|---|---|
| HU-001 → HU-012 (servicios de Carlos) | Integración | No |
| HU-002 → HU-001 | Funcional (interna) | Orden lógico propio |
| HU-003 → HU-004 (cola de Alessandro) | Integración | No |
| HU-011 → HU-007 (llamados de Alessandro) | Integración | No |

## 25.3 Contratos relevantes

- Contrato de Turno (12.1).
- Contrato de Servicio (12.2).
- Estados oficiales (13.1).
- Identificación de cola (contrato Redis 12.4, pendiente).
- Llamados de ventanilla (turno en estado `Llamado` con ventanilla asignada).

## 25.4 Datos que puede simular

- servicios sintéticos;
- cola controlada;
- turnos de prueba;
- llamados simulados.

Aaron **no necesita esperar** a HU-012 para comenzar HU-001, ni a HU-004 para comenzar HU-003, ni a HU-007 para comenzar HU-011.

## 25.5 Puntos de integración futura

- Selección de servicio en HU-001 ↔ servicios reales de HU-012.
- Inserción del turno en la fila ↔ contrato Redis y cola activa de HU-004/HU-005.
- Posición en HU-003 ↔ cola vigente de HU-004.
- Lista de llamados en HU-011 ↔ turnos llamados por HU-007.

## 25.6 NO le corresponde

- administración de servicios;
- administración de ventanillas;
- concurrencia del operador;
- recuperación Redis;
- historial administrativo;
- dashboard.

## 25.7 Contexto para pasar a la IA

```text
Eres el asistente de Aaron Benavides (branch abenavides) en el MVP QLine.
Tus HU: HU-001 Generar turno, HU-002 QR, HU-003 Consultar mi turno, HU-011 Pantalla pública.
Área: experiencia del cliente y visualización pública.
Respeta contratos de Turno y Servicio, estados oficiales (En espera → Llamado → En atención → Atendido; En espera → Expirado), identificación de cola y llamados de ventanilla.
Puedes simular: servicios, cola, turnos y llamados. No esperes a HU-012, HU-004 ni HU-007.
HU-002 depende funcionalmente de HU-001 (ambas tuyas).
No desarrolles: administración de servicios/ventanillas, concurrencia del operador, recuperación Redis, historial, dashboard.
No inventes prioridades, formato de código de turno ni estructura Redis: son decisiones pendientes del equipo. Si las necesitas, detente y pregunta.
No muestres datos personales ni información sensible en el QR ni en la pantalla pública.
Antes de terminar una HU, verifica todos sus criterios de aceptación y la Definition of Done global.
```

---

# 26. Contexto individual — Alessandro Cambronero

| Campo | Valor |
|---|---|
| Nombre | Alessandro Cambronero |
| Branch | `acambronero` |
| Área funcional | Cola activa, prioridad y concurrencia |
| HU | HU-004, HU-005, HU-007, HU-008 |

## 26.1 Historias de Usuario completas

Ver sección 15: **HU-004** (Visualizar cola activa), **HU-005** (Gestionar prioridades), **HU-007** (Llamar siguiente), **HU-008** (Evitar asignaciones duplicadas). Todos sus criterios de aceptación aplican íntegramente.

## 26.2 Dependencias

| Relación | Tipo | ¿Espera? |
|---|---|---|
| HU-005 → HU-004 | Funcional (interna) | Orden lógico propio |
| HU-007 → HU-013 (ventanillas de Carlos) | Integración | No |
| HU-008 → HU-007 | Funcional (interna) | Orden lógico propio |

Sus HU son consumidas por: HU-003 y HU-011 (Aaron), HU-009 (Abigail). Estas dependencias de integración no deben bloquear a quienes las consumen.

## 26.3 Contratos relevantes

- Contrato de Turno (12.1).
- Prioridades y regla de ordenamiento (12.5).
- Contrato Redis (12.4, pendiente) — especialmente crítico para su bloque.
- Contrato de Ventanilla (12.3).
- Transición `En espera → Llamado` (13.2).

## 26.4 Datos que puede simular

- turnos precargados;
- servicios sintéticos;
- ventanillas controladas.

## 26.5 Puntos de integración futura

- Turnos que entran a la cola desde HU-001.
- Ventanillas reales de HU-013.
- Turno `Llamado` consumido por HU-009 (Abigail) y HU-011 (Aaron).
- Turnos expirados retirados de la cola por HU-006 (Abigail).
- Cola reconstruida por HU-016 (Abigail).

## 26.6 Debe garantizar especialmente

```text
Duplicados = 0
```

## 26.7 NO le corresponde

- QR;
- pantalla pública;
- historial;
- dashboard;
- administración de servicios;
- recuperación completa de Redis.

## 26.8 Contexto para pasar a la IA

```text
Eres el asistente de Alessandro Cambronero (branch acambronero) en el MVP QLine.
Tus HU: HU-004 Visualizar cola activa, HU-005 Gestionar prioridades, HU-007 Llamar siguiente, HU-008 Evitar asignaciones duplicadas.
Área: cola activa, prioridad y concurrencia.
Regla de orden: 1) prioridad, 2) orden de llegada. La lista de prioridades NO está definida: es decisión pendiente del equipo; no inventes prioridades.
Contrato Redis (claves, identificación de cola, ordenamiento) está pendiente de definir antes de integración; no lo inventes como definitivo.
Garantía obligatoria: Turnos asignados duplicados = 0, con prueba concurrente repetible (registrar solicitudes, turnos obtenidos, únicos, duplicados).
Transición que te corresponde: En espera → Llamado. Un turno expirado no puede llamarse. Consultar la cola no la modifica.
Puedes simular: turnos precargados, servicios, ventanillas. No esperes a HU-013.
No desarrolles: QR, pantalla pública, historial, dashboard, administración de servicios, recuperación completa de Redis.
Antes de terminar una HU, verifica todos sus criterios de aceptación y la Definition of Done global.
```

---

# 27. Contexto individual — Abigail Urbina

| Campo | Valor |
|---|---|
| Nombre | Abigail Urbina |
| Branch | `aurbina` |
| Área funcional | Ciclo de atención, expiración y continuidad |
| HU | HU-006, HU-009, HU-010, HU-016 |

## 27.1 Historias de Usuario completas

Ver sección 15: **HU-006** (Expiración o abandono), **HU-009** (Iniciar atención), **HU-010** (Finalizar atención), **HU-016** (Recuperar cola tras pérdida de Redis). Todos sus criterios de aceptación aplican íntegramente.

## 27.2 Dependencias

| Relación | Tipo | ¿Espera? |
|---|---|---|
| HU-006 → Contrato de cola | Integración | No espera HU-004 completa |
| HU-009 → HU-007 (Alessandro) | Integración | No |
| HU-010 → HU-009 | Funcional (interna) | Orden lógico propio |
| HU-016 → MongoDB + contrato Redis | Integración | No, si los contratos están definidos |

## 27.3 Contratos relevantes

- Contrato de Turno (12.1) y sus timestamps.
- Estados oficiales y transiciones (13).
- Contrato Redis (12.4, pendiente) — crítico para HU-006 y HU-016.
- Prioridades y orden de llegada (12.5).

## 27.4 Datos que puede simular

- turnos sintéticos `Llamado`;
- turnos sintéticos `En atención`;
- colas precargadas;
- documentos MongoDB de prueba.

## 27.5 Transiciones a respetar

```text
En espera → Expirado
Llamado → En atención → Atendido
```

## 27.6 Debe asegurar que la recuperación

- no duplique;
- no pierda pendientes;
- respete prioridad;
- respete llegada.

## 27.7 Puntos de integración futura

- Turnos `Llamado` provenientes de HU-007.
- Datos de ciclo de atención consumidos por HU-014 y HU-015 (Carlos).
- Cola reconstruida con el mismo ordenamiento que HU-005.

## 27.8 NO le corresponde

- generación de turnos;
- QR;
- pantalla pública;
- servicios;
- ventanillas;
- dashboard.

## 27.9 Contexto para pasar a la IA

```text
Eres el asistente de Abigail Urbina (branch aurbina) en el MVP QLine.
Tus HU: HU-006 Expiración o abandono, HU-009 Iniciar atención, HU-010 Finalizar atención, HU-016 Recuperar cola tras pérdida de Redis.
Área: ciclo de atención, expiración y continuidad.
Transiciones: En espera → Expirado; Llamado → En atención → Atendido. Solo un turno Llamado puede iniciar; solo uno En atención puede finalizar; un turno expirado no puede llamarse ni atenderse.
El período de expiración puede ser configurable; su valor por defecto y su comportamiento sobre turnos Llamado no iniciados NO están definidos: decisión pendiente del equipo.
La expiración debe registrar el evento y NO borrar la trazabilidad.
HU-016: reconstruir la cola desde MongoDB con turnos En espera, respetando prioridad y orden de llegada, sin duplicados, sin pérdidas, sin modificar indebidamente el historial; la cantidad recuperada debe coincidir con los pendientes persistidos. Proceso de validación: crear pendientes, confirmar persistencia, simular pérdida de Redis, restaurar, reconstruir, comparar.
Contrato Redis pendiente de definir antes de integración; no lo inventes como definitivo.
Puedes simular: turnos Llamado, turnos En atención, colas precargadas, documentos MongoDB. No esperes a HU-007.
No desarrolles: generación de turnos, QR, pantalla pública, servicios, ventanillas, dashboard.
Antes de terminar una HU, verifica todos sus criterios de aceptación y la Definition of Done global.
```

---

# 28. Contexto individual — Carlos Espinoza

| Campo | Valor |
|---|---|
| Nombre | Carlos Espinoza |
| Branch | `cespinoza` |
| Área funcional | Configuración, historial y supervisión |
| HU | HU-012, HU-013, HU-014, HU-015 |

## 28.1 Historias de Usuario completas

Ver sección 15: **HU-012** (Gestionar servicios), **HU-013** (Gestionar ventanillas), **HU-014** (Consultar historial), **HU-015** (Dashboard y métricas SLA). Todos sus criterios de aceptación aplican íntegramente.

## 28.2 Dependencias

| Relación | Tipo | ¿Espera? |
|---|---|---|
| HU-014 → HU-009 / HU-010 (Abigail) | Integración | No |
| HU-015 → HU-013 / HU-014 | Internas a su bloque | Orden lógico propio |

Sus HU son consumidas por: HU-001 (servicios, Aaron) y HU-007 (ventanillas, Alessandro). Esas dependencias de integración no deben bloquear a quienes las consumen.

## 28.3 Contratos relevantes

- Contrato de Servicio (12.2).
- Contrato de Ventanilla (12.3).
- Contrato de Turno (12.1) y sus timestamps oficiales.
- Estados oficiales (13.1).

## 28.4 Datos que puede simular

- turnos históricos sintéticos;
- timestamps simulados;
- servicios de prueba;
- ventanillas de prueba.

## 28.5 Debe garantizar

Que desactivar elementos:

- no elimine historial;
- no rompa registros anteriores.

## 28.6 Puntos de integración futura

- Servicios activos expuestos para HU-001.
- Ventanillas activas expuestas para HU-007.
- Historial alimentado por los eventos reales de HU-006, HU-009 y HU-010.
- Métricas SLA derivadas de datos persistidos reales.

## 28.7 NO le corresponde

- concurrencia;
- llamada del siguiente turno;
- QR;
- expiración;
- recuperación Redis.

## 28.8 Contexto para pasar a la IA

```text
Eres el asistente de Carlos Espinoza (branch cespinoza) en el MVP QLine.
Tus HU: HU-012 Gestionar servicios, HU-013 Gestionar ventanillas, HU-014 Consultar historial, HU-015 Dashboard y métricas SLA.
Área: configuración, historial y supervisión.
Contratos mínimos: Servicio {id, nombre, activo}; Ventanilla {id, nombre, activo}. No los modifiques unilateralmente.
Desactivar un servicio o ventanilla NO elimina historial y los registros históricos deben seguir siendo identificables.
Historial: código, servicio, prioridad, estado, ventanilla, creación, llamado, inicio de atención, finalización; derivables: tiempo de espera y duración de atención. Debe seguir disponible aunque el turno ya no exista en Redis.
Dashboard mínimo: turnos esperando, turnos atendidos, tiempo promedio de espera, tiempo promedio de atención, ventanillas activas; más objetivo SLA y cumplimiento/incumplimiento. Valores verificables contra datos persistidos. El valor del objetivo SLA NO está definido: decisión pendiente del equipo.
Puedes simular: turnos históricos, timestamps, servicios y ventanillas de prueba. No esperes a HU-009/HU-010.
No desarrolles: concurrencia, llamada del siguiente turno, QR, expiración, recuperación Redis.
Antes de terminar una HU, verifica todos sus criterios de aceptación y la Definition of Done global.
```

---

# 29. Branches e integración

Branches existentes:

```text
abenavides
acambronero
aurbina
cespinoza
development
main
```

Flujo esperado:

```text
Branch personal
      ↓
Pull Request
      ↓
development
      ↓
Integración y validación
      ↓
main
```

Este documento **no exige** ninguna metodología interna adicional dentro de cada branch personal.

---

# 30. Módulos visibles

QLine tendrá conceptualmente las siguientes vistas o módulos funcionales:

| # | Vista / módulo | HU relacionadas |
|---|---|---|
| 1 | Generar turno | HU-001 |
| 2 | Mi turno / QR | HU-002, HU-003 |
| 3 | Cola en tiempo real | HU-004, HU-005 |
| 4 | Panel del operador | HU-007, HU-008 |
| 5 | Gestión de atención | HU-009, HU-010 (y HU-006 en lo operacional) |
| 6 | Servicios y ventanillas | HU-012, HU-013 |
| 7 | Historial | HU-014 |
| 8 | Dashboard | HU-015 |

Adicionalmente: **pantalla pública de llamados** (HU-011).

Estas vistas representan **funcionalidades visibles**. No deben interpretarse como obligación de crear nueve archivos o nueve componentes técnicos. HU-016 (recuperación) es una capacidad del sistema, no una vista.

---

# 31. Fuera del alcance

NO forma parte del MVP:

- aplicación móvil nativa;
- WhatsApp;
- SMS;
- pagos;
- mapas;
- Machine Learning;
- Inteligencia Artificial;
- predicción automática de tiempos;
- modelos M/M/c;
- múltiples sucursales complejas;
- agenda avanzada de citas;
- autenticación empresarial avanzada;
- roles complejos;
- funcionalidades no incluidas en las 16 HU.

Pueden aparecer únicamente como **posibles mejoras futuras** (roadmap).

---

# 32. Requisitos generales del proyecto

Además del desarrollo funcional, el proyecto debe contemplar:

- [ ] repositorio público;
- [ ] GitHub;
- [ ] licencia open source;
- [ ] `.gitignore`;
- [ ] `.env.example`;
- [ ] no publicar credenciales;
- [ ] README;
- [ ] explicación del problema;
- [ ] explicación de arquitectura;
- [ ] instrucciones de instalación;
- [ ] variables de entorno;
- [ ] datos de prueba;
- [ ] dataset sintético o script reproducible;
- [ ] capturas;
- [ ] evidencia de funcionamiento;
- [ ] issues o tareas;
- [ ] commits distribuidos;
- [ ] pruebas;
- [ ] demostración;
- [ ] release final;
- [ ] roadmap.

Estos son **requisitos de ingeniería y entrega**. No son Historias de Usuario adicionales.

---

# 33. Checklist de integración

Antes de integrar un branch a `development`, comprobar:

- [ ] HU completadas según sus criterios de aceptación;
- [ ] contratos respetados;
- [ ] estados válidos;
- [ ] no existen credenciales publicadas;
- [ ] datos sintéticos disponibles;
- [ ] errores controlados;
- [ ] no existen cambios innecesarios sobre módulos ajenos;
- [ ] no se agregaron funcionalidades fuera del alcance;
- [ ] dependencias de integración identificadas;
- [ ] flujo principal funciona con datos controlados;
- [ ] no se introdujeron inconsistencias conocidas.

---

# 34. Checklist final del MVP

Antes de considerar QLine terminado, debe poder demostrarse el flujo completo:

```text
Generar turno
    ↓
Agregarlo a la cola
    ↓
Consultar estado y posición
    ↓
Aplicar prioridades
    ↓
Llamar siguiente
    ↓
Evitar asignación duplicada
    ↓
Iniciar atención
    ↓
Finalizar atención
    ↓
Consultar historial
    ↓
Visualizar métricas
```

También debe poder demostrarse:

- [ ] **Concurrencia:** `Duplicados = 0`.
- [ ] **Persistencia:** los turnos procesados permanecen disponibles históricamente.
- [ ] **Recuperación:** Redis pierde cola → MongoDB conserva pendientes → cola reconstruida.
- [ ] **Expiración:** los turnos expirados no pueden continuar siendo atendidos.
- [ ] **Consistencia:** MongoDB y Redis no reflejan estados operacionalmente contradictorios.

---

# 35. Decisiones pendientes

Estos puntos **no están definidos** en el material fuente. Ningún desarrollador ni IA debe resolverlos por su cuenta: deben decidirse en equipo y documentarse antes de que afecten la integración.

| # | Decisión pendiente del equipo | Afecta a | Prioridad sugerida de resolución |
|---|---|---|---|
| 1 | Lista exacta de prioridades permitidas y su precedencia relativa. | HU-001, HU-005, HU-004, HU-007, HU-016 | Antes de integrar |
| 2 | **Contrato técnico a definir antes de integración:** contrato Redis (formato de claves, identificación de cada cola, dato que identifica un turno, representación de prioridad, estructura de ordenamiento, información temporal, mecanismo conceptual de expiración). | HU-001, 003, 004, 005, 006, 007, 008, 009, 016 | Antes de integrar |
| 3 | Formato exacto del código de turno (el ejemplo `A-015` es ilustrativo) y regla de unicidad/generación. | HU-001, HU-002, HU-003 | Antes de integrar |
| 4 | Valores almacenados para estados y prioridades (nomenclatura exacta, p. ej. `en_espera`). | Todas | Antes de integrar |
| 5 | Si hay una cola por servicio o una cola global, y qué servicio(s) atiende cada operador/ventanilla al llamar el siguiente turno. | HU-004, HU-007, HU-008 | Antes de integrar |
| 6 | Valor del período de expiración y desde qué momento se cuenta; qué ocurre con turnos `Llamado` que no inician atención (no está definido en los estados oficiales). | HU-006, HU-007, HU-009 | Antes de integrar |
| 7 | Cómo se registra el evento de expiración en el contrato de Turno (el contrato mínimo no incluye un campo de expiración) y qué estructura tienen los "eventos" en MongoDB. | HU-006, HU-014, HU-015 | Antes de integrar |
| 8 | Qué contiene el QR (identificador que no exponga información sensible) y cuándo se considera inválido. | HU-002, HU-003 | Antes de integrar |
| 9 | Valor del objetivo SLA y qué intervalo mide (espera, atención u otro). | HU-015 | Antes de la demostración |
| 10 | Cuántos "llamados recientes" muestra la pantalla pública y por cuánto tiempo permanece visible un llamado. | HU-011 | Antes de la demostración |
| 11 | Qué prioridad se aplica si el cliente no selecciona ninguna al generar un turno. | HU-001 | Antes de integrar |
| 12 | Cómo se distinguen los perfiles Cliente / Operador / Supervisor dentro del MVP (la autenticación empresarial y los roles complejos están fuera de alcance). | HU-004, 007, 009, 010, 012–015 | Antes de la demostración |
| 13 | Comportamiento al desactivar una ventanilla o servicio con turnos en curso o pendientes. | HU-007, HU-012, HU-013 | Antes de integrar |
| 14 | Mecanismo mediante el cual se solicita ejecutar la reconstrucción de cola (HU-016) y cómo se actualiza la vista en tiempo real (HU-004/HU-011). | HU-004, HU-011, HU-016 | Antes de la demostración |
| 15 | Observación de consistencia de nombres: el contrato mínimo usa `llamado_en`, `inicio_atencion` y `finalizado_en`. Confirmar si se mantiene tal cual como nomenclatura oficial de timestamps. | Todas | Antes de integrar |

---

## Revisión interna final del documento

- [x] Existen exactamente 16 HU con ID único (HU-001 a HU-016), sin renumeración.
- [x] Cada desarrollador tiene exactamente 4 HU; ninguna HU queda sin responsable ni pertenece a dos desarrolladores.
- [x] Dependencias identificadas (13 relaciones oficiales) y diferenciadas entre funcionales e integración.
- [x] Las dependencias de integración no bloquean el desarrollo (sección 20).
- [x] Contratos compartidos y estados consistentes entre sí.
- [x] Redis y MongoDB tienen responsabilidades diferenciadas.
- [x] Recuperación, concurrencia, expiración, QR, pantalla pública, dashboard/SLA, historial, servicios y ventanillas contemplados.
- [x] No se agregó funcionalidad externa al MVP.
- [x] No se definió framework ni metodología específicos.
- [x] No se inventaron reglas: lo no especificado figura en la sección 35.
