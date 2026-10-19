"""
MongoDB Web Admin (versión FastAPI) - base de pruebas para el proyecto QLine.
Equivalente a la versión PHP: listar/crear colecciones y CRUD de documentos.
"""
import json
import os
import re
from pathlib import Path
from urllib.parse import quote_plus

from bson import ObjectId, json_util
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient
from redis.exceptions import RedisError

from app import atencion
from app import cola as cola_redis
from app.excepciones import ErrorAtencion
from app.panel_atencion import estado_ventanillas
from app.redis_atencion import liberar_turno
from app.schemas import TurnoEnAtencion, TurnoFinalizado
from app.llamado import LlamadoError, llamar_siguiente_turno
from app.constantes import SERVICIO_NOMBRE, VENTANILLAS
from app.redis_client import verificar_conexion as verificar_redis

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")

MONGO_USER = os.getenv("MONGO_USER", "")
MONGO_PASS = os.getenv("MONGO_PASS", "")
MONGO_DB = os.getenv("MONGO_DB", "")
MONGO_HOST = os.getenv("MONGO_HOST", "127.0.0.1")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))

# Prefijo público cuando la app se publica en una subruta (ej. /proyecto/qline).
# Apache lo quita antes de pasar la petición a la app; aquí solo se usa para
# construir los enlaces y redirecciones que ve el navegador.
_bp = os.getenv("BASE_PATH", "").strip().strip("/")
BASE = f"/{_bp}" if _bp else ""

MENSAJES = {
    "insertado": "Documento insertado correctamente.",
    "actualizado": "Documento actualizado correctamente.",
    "eliminado": "Documento eliminado correctamente.",
}

app = FastAPI(title="MongoDB Web Admin")
app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

_client = None


def get_db():
    """Cliente único reutilizable (PyMongo maneja su propio pool de conexiones)."""
    global _client
    if _client is None:
        uri = (
            f"mongodb://{quote_plus(MONGO_USER)}:{quote_plus(MONGO_PASS)}"
            f"@{MONGO_HOST}:{MONGO_PORT}/{quote_plus(MONGO_DB)}"
            f"?authSource={quote_plus(MONGO_DB)}"
        )
        _client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return _client[MONGO_DB]


def nombre_valido(nombre: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]+", nombre))


def a_json_bonito(doc: dict) -> str:
    return json_util.dumps(doc, indent=2, ensure_ascii=False, json_options=json_util.RELAXED_JSON_OPTIONS)


def json_a_documento(texto: str) -> dict:
    texto = texto.strip()
    if not texto:
        raise ValueError("Debe ingresar un documento JSON.")
    doc = json_util.loads(texto)
    if not isinstance(doc, dict):
        raise ValueError("El JSON debe ser un objeto { ... }.")
    doc.pop("_id", None)
    return doc


def a_object_id(valor: str) -> ObjectId:
    try:
        return ObjectId(valor.strip())
    except (InvalidId, TypeError, AttributeError):
        raise ValueError("ID no válido.")


def ir(coleccion: str, **params) -> RedirectResponse:
    extra = "".join(f"&{k}={quote_plus(v)}" for k, v in params.items())
    return RedirectResponse(f"{BASE}/?coleccion={quote_plus(coleccion)}{extra}", status_code=303)


def render(request: Request, coleccion: str = "", editar: str = "", error: str = "",
           ok: str = "", json_texto: str = None):
    contexto = {
        "usuario": MONGO_USER, "base": BASE, "base_datos": MONGO_DB, "coleccion": coleccion,
        "colecciones": [], "documentos": [], "doc_editar": None, "id_editar": "",
        "mensaje": MENSAJES.get(ok, ""), "error": error, "json_texto": json_texto,
    }
    try:
        db = get_db()
        contexto["colecciones"] = sorted(db.list_collection_names())
        if coleccion and editar:
            try:
                doc = db[coleccion].find_one({"_id": a_object_id(editar)})
                if doc is None:
                    raise ValueError("Documento no encontrado.")
                contexto["doc_editar"] = a_json_bonito(doc)
                contexto["id_editar"] = editar
            except Exception as e:
                contexto["error"] = f"Error cargando documento: {e}"
        if coleccion:
            cursor = db[coleccion].find({}).sort("_id", -1).limit(50)
            contexto["documentos"] = [
                {"id": str(d.get("_id", "")), "json": a_json_bonito(d)} for d in cursor
            ]
    except Exception as e:
        contexto["error"] = contexto["error"] or f"Error de MongoDB: {e}"
    return templates.TemplateResponse(request, "index.html", contexto)


@app.get("/redis/estado")
def redis_estado():
    """Estado de la conexión a Redis (TT-006)."""
    return verificar_redis()


@app.get("/api/cola")
def api_cola():
    """Turnos disponibles en orden de atención (HU-004). Solo lectura."""
    try:
        return {"ok": True, "turnos": cola_redis.ver_cola()}
    except RedisError as e:
        return JSONResponse({"ok": False, "error": f"Redis no disponible: {e}"}, status_code=503)


def _llamar(ventanilla: str):
    """(resultado, error, status) para las rutas de llamada."""
    try:
        return llamar_siguiente_turno(get_db(), ventanilla), "", 200
    except cola_redis.ColaError as e:
        return None, str(e), 400
    except LlamadoError as e:
        return None, str(e), e.status
    except RedisError as e:
        return None, f"Redis no disponible: {e}", 503


@app.post("/api/llamar")
def api_llamar(ventanilla: str = Form(...)):
    """Llamar al siguiente turno desde una ventanilla (HU-005)."""
    res, error, status = _llamar(ventanilla.strip())
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=status)
    return {"ok": True, **res}


@app.post("/cola/llamar")
def cola_llamar(ventanilla: str = Form(...)):
    res, error, _ = _llamar(ventanilla.strip())
    if error:
        return RedirectResponse(f"{BASE}/cola?error={quote_plus(error)}", status_code=303)
    if res["codigo"] is None:
        msg = res["mensaje"]
    else:
        msg = f"{res['ventanilla']} llamó al turno {res['codigo']} ({res['prioridad']})."
    return RedirectResponse(f"{BASE}/cola?msg={quote_plus(msg)}", status_code=303)


@app.get("/cola", response_class=HTMLResponse)
def ver_cola(request: Request, msg: str = "", error: str = ""):
    turnos = []
    try:
        turnos = cola_redis.ver_cola()
    except RedisError as e:
        error = error or f"Redis no disponible: {e}"
    return templates.TemplateResponse(
        request, "cola.html",
        {"base": BASE, "servicio": SERVICIO_NOMBRE, "turnos": turnos, "error": error,
         "mensaje": msg, "ventanillas": VENTANILLAS},
    )


@app.exception_handler(ErrorAtencion)
def _error_atencion(request: Request, exc: ErrorAtencion):
    """Errores controlados del ciclo de atención: nunca un 500 sin explicar."""
    return JSONResponse({"ok": False, "error": exc.mensaje}, status_code=exc.status_code)


@app.post("/api/atencion/iniciar", response_model=TurnoEnAtencion)
def api_iniciar_atencion(codigo: str = Form(...), ventanilla: str = Form(...)):
    """Iniciar la atención de un turno llamado: llamado -> en_atencion (HU-006)."""
    return atencion.iniciar_atencion(get_db()["turnos"], codigo, ventanilla)


@app.post("/api/atencion/finalizar", response_model=TurnoFinalizado)
def api_finalizar_atencion(codigo: str = Form(...), ventanilla: str = Form(...)):
    """Finalizar la atención: en_atencion -> atendido y liberar Redis (HU-007)."""
    return atencion.finalizar_atencion(
        get_db()["turnos"], codigo, ventanilla,
        al_finalizar=lambda c: liberar_turno(c, ventanilla.strip()),
    )


def _redirigir_panel(**params) -> RedirectResponse:
    extra = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return RedirectResponse(f"{BASE}/panel?{extra}", status_code=303)


@app.get("/panel", response_class=HTMLResponse)
def panel_atencion(request: Request, msg: str = "", error: str = ""):
    """Panel del operador: turno actual por ventanilla con Iniciar / Finalizar."""
    ventanillas, avisos = [], []
    try:
        ventanillas, avisos = estado_ventanillas(get_db())
    except Exception as e:
        error = error or f"MongoDB no disponible: {e}"
    return templates.TemplateResponse(
        request, "panel.html",
        {"base": BASE, "servicio": SERVICIO_NOMBRE, "ventanillas": ventanillas,
         "avisos": avisos, "mensaje": msg, "error": error},
    )


@app.post("/panel/iniciar")
def panel_iniciar(codigo: str = Form(...), ventanilla: str = Form(...)):
    try:
        r = atencion.iniciar_atencion(get_db()["turnos"], codigo, ventanilla)
    except ErrorAtencion as e:
        return _redirigir_panel(error=e.mensaje)
    return _redirigir_panel(msg=f"{r['ventanilla']}: atención iniciada para {r['codigo']}.")


@app.post("/panel/finalizar")
def panel_finalizar(codigo: str = Form(...), ventanilla: str = Form(...)):
    try:
        r = atencion.finalizar_atencion(
            get_db()["turnos"], codigo, ventanilla,
            al_finalizar=lambda c: liberar_turno(c, ventanilla.strip()),
        )
    except ErrorAtencion as e:
        return _redirigir_panel(error=e.mensaje)
    msg = f"{r['ventanilla']}: atención de {r['codigo']} finalizada ({r['atencion_seg']} s)."
    if r["redis_liberado"] is False:
        msg += " Aviso: no se pudo limpiar el estado en Redis."
    return _redirigir_panel(msg=msg)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, coleccion: str = "", editar: str = "", ok: str = ""):
    return render(request, coleccion.strip(), editar.strip(), ok=ok)


@app.post("/crear_coleccion")
def crear_coleccion(request: Request, nombre_coleccion: str = Form("")):
    nombre = nombre_coleccion.strip()
    if not nombre_valido(nombre):
        return render(request, error="Nombre de colección no válido. Use letras, números, guion o guion bajo.")
    try:
        get_db().create_collection(nombre)
        return ir(nombre)
    except Exception as e:
        return render(request, error=f"Error creando colección: {e}")


@app.post("/insertar")
def insertar(request: Request, coleccion: str = "", json_doc: str = Form("", alias="json")):
    try:
        get_db()[coleccion].insert_one(json_a_documento(json_doc))
        return ir(coleccion, ok="insertado")
    except Exception as e:
        return render(request, coleccion, error=f"Error insertando: {e}", json_texto=json_doc)


@app.post("/actualizar")
def actualizar(request: Request, coleccion: str = "", id: str = Form(""),
               json_doc: str = Form("", alias="json")):
    try:
        doc = json_a_documento(json_doc)
        get_db()[coleccion].update_one({"_id": a_object_id(id)}, {"$set": doc})
        return ir(coleccion, ok="actualizado")
    except Exception as e:
        return render(request, coleccion, editar=id, error=f"Error actualizando: {e}")


@app.post("/eliminar")
def eliminar(request: Request, coleccion: str = "", id: str = Form("")):
    try:
        get_db()[coleccion].delete_one({"_id": a_object_id(id)})
        return ir(coleccion, ok="eliminado")
    except Exception as e:
        return render(request, coleccion, error=f"Error eliminando: {e}")
