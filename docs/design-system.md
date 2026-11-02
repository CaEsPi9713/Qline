# Sistema de diseño QLine (UI-01)

Responsable: Abigail Urbina · Archivo fuente: `static/style.css` · Referencia: Fintech Dashboard UI (Md Iqbal Hasan).

## Colores
| Token | Valor | Uso |
|---|---|---|
| `--azul-marino` | `#0B111C` | Cabecera, texto principal, botón oscuro, fondo del quiosco |
| `--azul-grisaceo` | `#B8CBD8` | Texto secundario sobre oscuro, hover de contorno |
| `--turquesa` | `#5BB6C5` | Botón principal, página activa, acentos (nunca como texto sobre blanco) |
| `--verde` | `#538573` | Referencia de marca; para texto usar `--verde-texto` |
| `--blanco` | `#F7F7F7` | Fondo de página |
| `--verde-texto` | `#3D6858` | Ajuste por contraste: `#538573` queda cerca de 3.9:1 sobre `#F7F7F7` (< 4.5:1) |

Los valores base son referenciales y se ajustan solo si el contraste lo exige (sección 6 del plan).

## Tipografía
Pila del sistema (`Segoe UI`, `Helvetica Neue`, `Arial`) para que la demo funcione sin internet. Escala: 13 · 15 · 17 · 20 · 26 · 36 · 48 px. Interlineado 1.55 en texto, 1.2 en títulos. Líneas de máximo 68 caracteres.

## Espaciado y forma
Escala `--e1`…`--e8` (4 px a 64 px). Radios: 6 px (campos), 12 px (tarjetas y botones), 20 px (quiosco y ticket). Objetivo táctil mínimo 44 px; en quiosco 72 px.

## Componentes
`.barra`/`.nav` · `.tarjeta` · `.boton` (`--oscuro`, `--contorno`, `--grande`) · `.campo` · `.tabla` · `.mensaje` (`--error`, `--aviso`, `--ok`) · `.estado--{pendiente|llamado|en_atencion|atendido|abandonado}` · `.prioridad--{regular|preferencial}` · `.ticket` · `.heroe` · `.lista-equipo`.

Estados y prioridades se distinguen por **texto + símbolo** (○ ▲ ● ✓ ✕) y no solo por color.

## Regla única de vidrio
Solo `.opcion-turno` dentro de `.quiosco-escena` usa transparencia (≈15 %) y `backdrop-filter`. El panel `.quiosco-panel` («Bienvenido»), el ticket, el QR, la consulta, el operador, la sala, el dashboard, el historial, la portada y los errores son sólidos.

## Cómo colaborar sin pisar el CSS
- Clases compartidas: solo las modifica Abigail. Cambios propuestos por otros: avisar antes de integrar.
- Alessandro (UI-04) y Carlos (UI-05): estilos propios con prefijo `.cola-*`, `.panel-*`, `.dash-*`, usando los tokens `var(--…)`.
- Aaron (S4-M02): bloque `@media print` propio al final de `style.css`, sobre `.ticket`.
