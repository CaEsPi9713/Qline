# QLine

Sistema de gestión de filas y turnos: emisión con prioridad, llamado por ventanilla, seguimiento por QR, historial y estadísticas.
Proyecto final de **Tópicos Avanzados de Bases de Datos**, Universidad Nacional · Grupo 2 / Query Logic.

> **BORRADOR (TT-022, Abigail).** Se cierra al final, después de UI-07. Todo lo marcado `[VERIFICAR]` o `[COMPLETAR: nombre]` debe contrastarse con el código integrado antes de publicar. No incluir secretos ni capturas con credenciales.

## 1. Arquitectura
- **FastAPI** (Python 3.12) con plantillas **Jinja2**.
- **MongoDB** (PyMongo): historial de turnos, ventanillas y métricas.
- **Redis** (redis-py): cola en tiempo real, claves con TTL de 180 s y canales de actualización en vivo.
- Seguimiento por **QR** y actualización en vivo del estado del turno.

`[COMPLETAR: Alessandro]` diagrama y mapa de claves Redis (`docs/arquitectura/redis_claves.md`).
`[COMPLETAR: Carlos]` contrato de colecciones e índices MongoDB.

## 2. Prerrequisitos
- Python 3.12
- MongoDB `[VERIFICAR versión]`
- Redis `[VERIFICAR versión]`
- Git

## 3. Variables de entorno
Copie `.env.example` a `.env` y complete los valores. Nunca suba `.env` al repositorio.

| Variable | Descripción | Ejemplo |
|---|---|---|
| `MONGO_URI` `[VERIFICAR nombre]` | Conexión a MongoDB | `mongodb://localhost:27017` |
| `MONGO_DB` `[VERIFICAR nombre]` | Base de datos | `qline` |
| `REDIS_URL` `[VERIFICAR nombre]` | Conexión a Redis | `redis://localhost:6379/0` |

## 4. Instalación
```bash
git clone <URL-del-repositorio>        # [COMPLETAR: URL real]
cd <carpeta-del-proyecto>
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt        # [VERIFICAR nombre del archivo]
cp .env.example .env
```

## 5. Carga de datos sintéticos
`[COMPLETAR: Carlos]` comando del script reproducible (TT-028), salida esperada y precauciones (no borra datos reales).

## 6. Arranque
```bash
uvicorn app.main:app --reload          # [VERIFICAR módulo:app]
```
Abrir `http://localhost:8000` `[VERIFICAR puerto]`.

## 7. Operaciones
| Pantalla | Ruta | Uso |
|---|---|---|
| Inicio | `/` | Portada y accesos públicos |
| Quiosco | `/quiosco` | Emisión de turnos regular y preferencial |
| Consulta por QR | `/consultar` | Seguimiento del estado del turno |
| Acerca de | `/acerca` | Equipo y repositorio |
| Cola, panel, sala | `[VERIFICAR rutas]` | Operación (`[COMPLETAR: Alessandro]`) |
| Dashboard e historial | `[VERIFICAR rutas]` | Métricas y consulta (`[COMPLETAR: Carlos]`) |
| Salud | `/salud` | Estado de app, Redis y Mongo (S4-M06, si se integra) |

Estados de turno: `pendiente`, `llamado`, `en_atencion`, `atendido`, `abandonado`.

## 8. Seguridad
- Sin credenciales en el repositorio, README, `portal.yml`, scripts ni capturas.
- La portada pública no expone CRUD ni administración (protección Apache `[VERIFICAR .htaccess]`).
- Páginas de error 403/404/500 sin trazas ni detalles de infraestructura.
- Datos de demostración sintéticos.

## 9. Interfaz y accesibilidad
Sistema de diseño en `docs/diseno/design-system.md`; checklist en `docs/diseno/checklist_accesibilidad_ui06.md`.

## 10. Capturas
`[COMPLETAR: Aaron, desde UI-07]` capturas reales de escritorio, móvil y quiosco: `docs/capturas/`.

## 11. Pruebas
`[COMPLETAR: cada responsable]` cómo ejecutar sus pruebas.

## 12. Enlaces
- Repositorio: `[COMPLETAR]`
- CHANGELOG: `CHANGELOG.md`
- Release: `[COMPLETAR tag v0.9.0 o v1.0.0 según decisión del equipo]`

## 13. Equipo
Aaron Benavides · Abigail Urbina · Alessandro Cambronero · Carlos Espinoza.

## Licencia
MIT.
