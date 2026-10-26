# Plan del Seguimiento 3 · Abigail Urbina (`aurbina`)

**Hito:** integración, pruebas y medición (tag objetivo `v0.3.0`)
**Área:** ciclo de atención y continuidad operacional
**Estado:** implementado e integrado; falta la revisión de Abigail y las verificaciones marcadas como pendientes.
**Detalle y evidencia:** [`S3.md`](S3.md), sección 5 · decisiones D-12 a D-17 en [`../decisiones.md`](../decisiones.md).

> **Autoría.** El diseño de los módulos de dominio es de Abigail. Las piezas que faltaban en su entrega y la integración las implementó Alessandro Cambronero con asistencia de Claude Code (detalle en la nota de autoría de `S3.md`). Abigail debe revisar y hacer suyo este trabajo antes de la entrega.

## 1. Qué corresponde a Abigail en S3

| ID | Entregable | Estado |
|---|---|---|
| HU-008 | Abandono de turno llamado a los 180 s | Hecho; verificado en el servidor (flujo manual) |
| HU-012 | Recuperación de la cola tras pérdida de Redis | Hecho; verificado en el servidor |
| TT-012 | Estado temporal con TTL, lado abandono | Hecho: el barrido corre con la aplicación |
| TT-017 | Prueba de caída y rehidratación | Hecho; [`recuperacion.md`](../evidencia/recuperacion.md) |
| TT-018 | Mediciones (≥ 3 ejecuciones, mediana) | Hecho; [`rendimiento_recuperacion.md`](../evidencia/rendimiento_recuperacion.md) |
| TT-019 | Casos normal, conexión fallida y datos inválidos | Hecho; [`fallos_recuperacion.md`](../evidencia/fallos_recuperacion.md) |
| TT-020 | Decisiones técnicas | Hecho; D-12 a D-17 |
| — | Sección propia de `S3.md` | Hecha; pendiente de revisión por Abigail |

## 2. Contratos que se respetan

- Estados y transiciones oficiales; `llamado → abandonado` es la única transición nueva.
- Namespace `grupo2:qline:`; sin `FLUSHALL` ni `FLUSHDB`.
- TTL oficial de 180 s.
- Cola, contador y eventos son de Alessandro: se usan sus funciones y su fórmula de puntaje, no se reimplementan.

## 3. Cómo se ejecuta (en el servidor, con el entorno virtual activo)

```bash
python -m scripts.barrer_abandonos                     # una pasada del barrido (en producción corre sola con la app)
python -m scripts.rehidratar_cola                      # plan: no escribe nada
python -m scripts.rehidratar_cola --aplicar            # reconstruye la cola desde MongoDB
python -m scripts.probar_recuperacion --informe docs/evidencia/recuperacion.md
python -m scripts.medir_recuperacion --informe docs/evidencia/rendimiento_recuperacion.md
python -m scripts.probar_fallos_recuperacion --informe docs/evidencia/fallos_recuperacion.md
```

El índice del barrido (`idx_turnos_estado_llamado`) se crea con `python scripts/init_mongo.py --recrear --confirmar` o, sin borrar datos, con `create_index` sobre `{estado, timestamps.llamado}`.

## 4. Pendiente

- [ ] Verificar con un celular que el QR cambia a «Turno cancelado» y que la pantalla pública deja de listar el turno abandonado.
- [ ] Comprobar el barrido con varios *workers* de Gunicorn.
- [ ] Capturas de pantalla para la bitácora.
- [ ] Revisión del código y de la sección 5 de `S3.md` por Abigail.
- [ ] Abrir el PR hacia `development` y etiquetar `v0.3.0` cuando el equipo lo acuerde.

## 5. Archivos

```
app/       s3_comun, abandono, barrido, recuperacion, integracion_s3, datos_prueba, informe,
           prueba_recuperacion, mediciones_s3, fallos_s3
scripts/   barrer_abandonos, rehidratar_cola, probar_recuperacion, medir_recuperacion, probar_fallos_recuperacion
tests/     test_s3_fundamentos, test_integracion_s3, test_barrido_abandono, test_recuperacion,
           test_mediciones_s3, test_fallos_s3, test_e2e_abandono, test_demo
```

## 6. Convención de la bitácora

- **«Verificado en el servidor»:** ejecutado con MongoDB y Redis reales.
- **«Prueba automática»:** cubierto por `tests/` con MongoDB y Redis simulados en memoria; no sustituye a la prueba en el servidor.
- Los informes de `docs/evidencia/` los generan los scripts; no se escriben a mano.
