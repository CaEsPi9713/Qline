# Ventanillas dinámicas conectadas a la operación (P09)

> Informe generado por un script con los resultados de **esa ejecución**; no se escribe a mano.

- Fecha (UTC): 2026-11-02 22:08:48
- Python: 3.12.3 · Linux

## Resultado global

**OK** · 3 casos.

| Caso | Resultado | Qué se comprobó |
|---|---|---|
| El catálogo reconoce la ventanilla nueva | OK | V-98 figura entre las ventanillas activas |
| El motor guarda un turno con la ventanilla nueva | OK | ACEPTA |
| Desactivada, deja de operar | OK | V-98 ya no figura entre las activas |

## Qué hace el motor de MongoDB

- El motor ACEPTA la ventanilla nueva: el validador de la colección ya admite el formato V-NN (la operación con ventanillas dinámicas funciona de extremo a extremo).

## Alcance

- Se usó la ventanilla `V-98` y el turno `Z-901`, eliminados al terminar. No se tocaron turnos reales, la cola ni Redis.
- La aplicación (llamar, panel, atención, historial) acepta cualquier ventanilla activa del catálogo; la ventanilla única y la liberación en Redis funcionan igual con cualquier identificador (`SET NX` sobre `grupo2:qline:ventanilla:{id}:actual`).
