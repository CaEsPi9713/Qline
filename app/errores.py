"""UI-06 · Páginas de error con códigos HTTP verdaderos y sin exponer trazas.

Uso (en app/main.py, después de crear `app` y `templates`):

    from app.errores import registrar_errores
    registrar_errores(app, templates)

ADAPTAR: si tu versión de Starlette es antigua, TemplateResponse recibe
(nombre, {"request": request, ...}, status_code=...) en lugar de (request, nombre, contexto).
Las rutas de API (JSON) conservan el comportamiento por defecto de FastAPI.
"""
import logging

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

log = logging.getLogger("qline.errores")

PLANTILLAS = {403: "403.html", 404: "404.html"}


def _quiere_json(request: Request) -> bool:
    return request.url.path.startswith("/api") or "application/json" in request.headers.get("accept", "")


def registrar_errores(app, templates):
    @app.exception_handler(StarletteHTTPException)
    async def manejar_http(request: Request, exc: StarletteHTTPException):
        if exc.status_code in PLANTILLAS and not _quiere_json(request):
            return templates.TemplateResponse(
                request, PLANTILLAS[exc.status_code], {}, status_code=exc.status_code
            )
        return await http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def manejar_error(request: Request, exc: Exception):
        log.exception("Error no controlado en %s", request.url.path)   # el detalle queda solo en el log
        if _quiere_json(request):
            return JSONResponse({"detail": "Error interno del servidor"}, status_code=500)
        return templates.TemplateResponse(request, "500.html", {}, status_code=500)
