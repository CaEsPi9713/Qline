# Checklist de accesibilidad y responsive (UI-06)

Marcar solo lo realmente verificado. Anotar fecha, pantalla y dispositivo. Los defectos se devuelven al dueño del módulo.

> **Estado 01/11/2026 (Alessandro, al integrar UI-03/UI-04):** lo marcado en «Móvil» y «Escritorio» se revisó a ojo en un navegador local con datos simulados (ancho ≈ 800 px y 375 px). **No se midió el contraste, ni se recorrió con el teclado, ni se probó en un celular real ni en el servidor**: esas casillas siguen sin marcar y siguen abiertas para Abigail y Aaron (UI-07).

| Pantalla | Contraste AA | Foco visible | Teclado completo | Objetivo táctil ≥ 44 px | Móvil (≈375 px) | Escritorio | Estado/prioridad sin depender del color | Resultado / defecto |
|---|---|---|---|---|---|---|---|---|
| Inicio `/` | ☐ | ☐ | ☐ | ☐ | ☑ | ☑ | ☐ | Revisada a ojo, sin medir contraste |
| Acerca de | ☐ | ☐ | ☐ | ☐ | ☐ | ☑ | ☐ | |
| Quiosco | ☐ | ☐ | ☐ | ☐ (72 px) | ☐ | ☑ | ☐ | Panel sólido y vidrio solo en las opciones (prueba automática y a ojo) |
| Emisión / ticket | ☐ | ☐ | ☐ | ☐ | ☐ | ☑ | ☐ | |
| Consulta / turno QR | ☐ | ☐ | ☐ | ☐ | ☑ | ☑ | ☐ | |
| Cola / operador (UI-04) | ☐ | ☐ | ☐ | ☐ | ☑ | ☑ | ☑ | Estado y prioridad con texto + símbolo (prueba automática) |
| Pantalla de sala (UI-04) | ☐ | ☐ | n/a | n/a | ☐ | ☑ | ☐ | |
| Dashboard / historial (UI-05) | ☐ | ☐ | ☐ | ☐ | ☐ | ☑ | ☐ | |

## Páginas de error
- ☑ `/ruta-inexistente` responde **404** con la página de error (prueba automática, `tests/test_fase0_integracion.py`).
- ☐ Ruta protegida sin permiso responde **403**.
- ☑ Error forzado en entorno de prueba responde **500** sin traza ni rutas internas visibles (prueba automática).
- ☑ Rutas `/api` siguen devolviendo JSON (prueba automática).

## Otras comprobaciones
- ☐ Enlace «Saltar al contenido» funciona con Tab. (El enlace está en todas las páginas públicas, con prueba automática; falta probar el recorrido con el teclado.)
- ☑ `prefers-reduced-motion` respetado (regla presente en `static/style.css`).
- ☑ Un solo lugar con vidrio (opciones del quiosco); respaldo sólido si el navegador no soporta `backdrop-filter` (prueba automática y regla `@supports`).
- ☑ Ninguna página nueva expone CRUD/administración (`/administracion` sigue protegida; `tests/test_htaccess.py`).
