# Checklist de accesibilidad y responsive (UI-06)

Marcar solo lo realmente verificado. Anotar fecha, pantalla y dispositivo. Los defectos se devuelven al dueño del módulo.

| Pantalla | Contraste AA | Foco visible | Teclado completo | Objetivo táctil ≥ 44 px | Móvil (≈375 px) | Escritorio | Estado/prioridad sin depender del color | Resultado / defecto |
|---|---|---|---|---|---|---|---|---|
| Inicio `/` | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Acerca de | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Quiosco | ☐ | ☐ | ☐ | ☐ (72 px) | ☐ | ☐ | ☐ | |
| Emisión / ticket | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Consulta / turno QR | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Cola / operador (UI-04) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |
| Pantalla de sala (UI-04) | ☐ | ☐ | n/a | n/a | ☐ | ☐ | ☐ | |
| Dashboard / historial (UI-05) | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | |

## Páginas de error
- ☐ `/ruta-inexistente` responde **404** (verificar código HTTP, no solo el texto).
- ☐ Ruta protegida sin permiso responde **403**.
- ☐ Error forzado en entorno de prueba responde **500** sin traza ni rutas internas visibles.
- ☐ Rutas `/api` siguen devolviendo JSON.

## Otras comprobaciones
- ☐ Enlace «Saltar al contenido» funciona con Tab.
- ☐ `prefers-reduced-motion` respetado.
- ☐ Un solo lugar con vidrio (opciones del quiosco); respaldo sólido si el navegador no soporta `backdrop-filter`.
- ☐ Ninguna página nueva expone CRUD/administración.
