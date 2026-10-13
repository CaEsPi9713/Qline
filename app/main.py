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
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient

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
