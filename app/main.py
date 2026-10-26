"""
MongoDB Web Admin (versión FastAPI) - base de pruebas para el proyecto QLine.
Equivalente a la versión PHP: listar/crear colecciones y CRUD de documentos.
"""
import json
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from bson import ObjectId, json_util
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from redis.exceptions import RedisError

from app import atencion
from app import cola as cola_redis
from app import eventos
from app.excepciones import ErrorAtencion
from app.panel_atencion import estado_ventanillas
from app.redis_atencion import liberar_turno
from app.consulta_qr import QRError, consultar_por_token
from app.qr import generar_qr_svg
from app.rutas_eventos import registrar as registrar_rutas_eventos
from app.schemas import TurnoEnAtencion, TurnoFinalizado
from app.emitir import EmisionError, emitir_turno
from app.consultar import ConsultaError, consultar_turno
from app.llamado import LlamadoError, llamar_siguiente_turno
from app.constantes import ESTADOS, PRIORIDADES, SERVICIO_ID, SERVICIO_NOMBRE, VENTANILLAS
from app.redis_client import verificar_conexion as verificar_redis
from app.turnos_schema import TurnoValidationError, validar_documento_turno
from app.historial import exportar_historial_turnos, obtener_historial_turnos
from app.dashboard import calcular_metricas_dashboard, exportar_metricas_dashboard
from app.pantalla_publica import pantalla as _pantalla


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


@asynccontextmanager
async def _lifespan(app_):
    """Al arrancar: suscribe la pantalla pública al Hub de eventos (TT-013, HU-009) e inicia el barrido de abandono (HU-008)."""
    from app.tiempo_real import hub
    import json as _json
    _orig_repartir = hub._repartir

    def _repartir_con_pantalla(mensaje: str) -> None:
        _orig_repartir(mensaje)
        try:
            evento = _json.loads(mensaje)
            if isinstance(evento, dict):
                _pantalla.procesar_evento(evento)
        except Exception:
            pass

    hub._repartir = _repartir_con_pantalla

    # HU-008: barrido periódico que marca como abandonados los turnos llamados cuyo plazo venció.
    from app.integracion_s3 import crear_barrido_abandono
    barrido = crear_barrido_abandono()
    app_.state.barrido = barrido
    if barrido is not None:
        barrido.iniciar()
    try:
        yield
    finally:
        if barrido is not None:
            barrido.detener()
        hub._repartir = _orig_repartir


app = FastAPI(title="MongoDB Web Admin", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR.parent / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

def _version_css() -> int:
    """Fecha de modificación de style.css: cambia el enlace y obliga al navegador a recargarlo."""
    try:
        return int((BASE_DIR.parent / "static" / "style.css").stat().st_mtime)
    except OSError:
        return 0


templates.env.globals["css_version"] = _version_css()

registrar_rutas_eventos(app, get_db=lambda: get_db())


@app.get("/ws-prueba", response_class=HTMLResponse)
def prueba_tiempo_real(request: Request):
    """Verifica en el navegador si el WebSocket y los eventos de Redis funcionan por el proxy."""
    return templates.TemplateResponse(request, "ws_prueba.html", {"base": BASE})

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



def _parsear_iso_o_fecha(valor):
    """Convierte strings ISO o valores existentes a datetime UTC."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor
    if isinstance(valor, str):
        val = valor.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None
    return None


def normalizar_timestamps_turno(doc: dict) -> None:
    """Asegura que los timestamps en el documento sean datetime UTC para MongoDB."""
    if "timestamps" in doc and isinstance(doc["timestamps"], dict):
        for k in ("creado", "llamado", "inicio_atencion", "finalizado", "abandonado"):
            val = doc["timestamps"].get(k)
            if val is not None:
                parsed = _parsear_iso_o_fecha(val)
                doc["timestamps"][k] = parsed


def render(request: Request, coleccion: str = "", editar: str = "", error: str = "",
           ok: str = "", json_texto: str = None, filtro_estado: str = ""):
    plantilla_turnos = json.dumps({
        "codigo": "A-099",
        "servicio": SERVICIO_ID,
        "prioridad": "normal",
        "estado": "pendiente",
        "ventanilla": None,
        "operador": None,
        "timestamps": {
            "creado": datetime.now(timezone.utc).isoformat(),
            "llamado": None,
            "inicio_atencion": None,
            "finalizado": None,
            "abandonado": None,
        },
        "metricas": {
            "espera_seg": None,
            "atencion_seg": None,
        },
    }, indent=2)

    contexto = {
        "usuario": MONGO_USER, "base": BASE, "base_datos": MONGO_DB, "coleccion": coleccion,
        "colecciones": [], "documentos": [], "doc_editar": None, "id_editar": "",
        "mensaje": MENSAJES.get(ok, ""), "error": error, "json_texto": json_texto,
        "filtro_estado": filtro_estado, "plantilla_turnos": plantilla_turnos,
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
            query = {}
            if coleccion == "turnos" and filtro_estado:
                query["estado"] = filtro_estado
            cursor = db[coleccion].find(query).sort("_id", -1).limit(50)
            documentos = []
            for d in cursor:
                resumen_turno = None
                if coleccion == "turnos" and isinstance(d, dict):
                    resumen_turno = {
                        "codigo": d.get("codigo"),
                        "prioridad": d.get("prioridad"),
                        "estado": d.get("estado"),
                        "ventanilla": d.get("ventanilla"),
                    }
                documentos.append({
                    "id": str(d.get("_id", "")),
                    "json": a_json_bonito(d),
                    "resumen_turno": resumen_turno,
                })
            contexto["documentos"] = documentos
    except Exception as e:
        contexto["error"] = contexto["error"] or f"Error de MongoDB: {e}"
    return templates.TemplateResponse(request, "index.html", contexto)



@app.get("/demo", response_class=HTMLResponse)
def guia_demo(request: Request):
    """Guía ordenada para recorrer el flujo completo del Seguimiento 2."""
    redis_estado = verificar_redis()
    mongo_estado = {"ok": False, "turnos": 0, "error": ""}
    try:
        mongo_estado.update(ok=True, turnos=get_db()["turnos"].count_documents({}))
    except Exception as e:
        mongo_estado["error"] = str(e)[:150]
    cola_tam = None
    if redis_estado.get("ok"):
        try:
            cola_tam = cola_redis.tamano_cola()
        except RedisError:
            cola_tam = None
    return templates.TemplateResponse(
        request, "demo.html",
        {"base": BASE, "redis": redis_estado, "mongo": mongo_estado, "cola_tam": cola_tam},
    )


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


@app.post("/api/turnos/emitir")
async def api_emitir_turno(request: Request):
    """Emitir un nuevo turno para Atención General (HU-001)."""
    prioridad = ""
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            if isinstance(body, dict):
                prioridad = body.get("prioridad", "")
        except Exception:
            return JSONResponse({"ok": False, "error": "Cuerpo JSON inválido."}, status_code=400)
    else:
        try:
            form = await request.form()
            prioridad = form.get("prioridad", "")
        except Exception:
            return JSONResponse({"ok": False, "error": "Datos de formulario inválidos."}, status_code=400)

    try:
        resultado = emitir_turno(get_db(), prioridad)
        _publicar_evento(eventos.TURNO_EMITIDO, resultado["codigo"], "pendiente", prioridad=resultado.get("prioridad"))
        return {"ok": True, "turno": resultado}
    except EmisionError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)
    except RedisError:
        return JSONResponse({"ok": False, "error": "Redis no disponible temporalmente."}, status_code=503)
    except PyMongoError:
        return JSONResponse({"ok": False, "error": "MongoDB no disponible temporalmente."}, status_code=503)


@app.get("/emitir", response_class=HTMLResponse)
def vista_emitir(request: Request, error: str = ""):
    """Formulario web para emitir turno (HU-001)."""
    return templates.TemplateResponse(
        request,
        "emitir.html",
        {
            "base": BASE,
            "servicio": SERVICIO_NOMBRE,
            "error": error,
            "prioridad_seleccionada": "normal",
        },
    )


@app.post("/emitir", response_class=HTMLResponse)
def accion_emitir(request: Request, prioridad: str = Form("")):
    """Procesar emisión de turno desde formulario web (HU-001)."""
    try:
        turno = emitir_turno(get_db(), prioridad)
        _publicar_evento(eventos.TURNO_EMITIDO, turno["codigo"], "pendiente", prioridad=turno.get("prioridad"))
        qr_svg = generar_qr_svg(turno["qr_url"]) if turno.get("qr_url") else ""
        return templates.TemplateResponse(
            request,
            "turno_confirmado.html",
            {
                "base": BASE,
                "turno": turno,
                "servicio": SERVICIO_NOMBRE,
                "qr_url": turno.get("qr_url", ""),
                "qr_svg": qr_svg,
            },
        )
    except EmisionError as e:
        return templates.TemplateResponse(
            request,
            "emitir.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": str(e),
                "prioridad_seleccionada": prioridad,
            },
            status_code=e.status,
        )
    except (RedisError, PyMongoError):
        return templates.TemplateResponse(
            request,
            "emitir.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": "El servicio no se encuentra disponible temporalmente. Por favor intente de nuevo más tarde.",
                "prioridad_seleccionada": prioridad,
            },
            status_code=503,
        )


# --- HU-001: Modo quiosco para clientes (ampliación S3) ----------------------

@app.get("/quiosco", response_class=HTMLResponse)
def vista_quiosco(request: Request, error: str = ""):
    """Vista de emisión simplificada tipo quiosco (HU-001): sin navegación interna ni administrativa."""
    return templates.TemplateResponse(
        request,
        "quiosco.html",
        {
            "base": BASE,
            "servicio": SERVICIO_NOMBRE,
            "error": error,
            "prioridad_seleccionada": "normal",
        },
    )


@app.post("/quiosco", response_class=HTMLResponse)
def accion_quiosco(request: Request, prioridad: str = Form("")):
    """Procesar emisión desde el quiosco reutilizando el backend existente de HU-001."""
    try:
        turno = emitir_turno(get_db(), prioridad)
        _publicar_evento(eventos.TURNO_EMITIDO, turno["codigo"], "pendiente", prioridad=turno.get("prioridad"))
        qr_svg = generar_qr_svg(turno["qr_url"]) if turno.get("qr_url") else ""
        return templates.TemplateResponse(
            request,
            "quiosco_confirmado.html",
            {
                "base": BASE,
                "turno": turno,
                "servicio": SERVICIO_NOMBRE,
                "qr_url": turno.get("qr_url", ""),
                "qr_svg": qr_svg,
            },
        )
    except EmisionError as e:
        return templates.TemplateResponse(
            request,
            "quiosco.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": str(e),
                "prioridad_seleccionada": prioridad,
            },
            status_code=e.status,
        )
    except (RedisError, PyMongoError):
        return templates.TemplateResponse(
            request,
            "quiosco.html",
            {
                "base": BASE,
                "servicio": SERVICIO_NOMBRE,
                "error": "El servicio no se encuentra disponible temporalmente. Por favor solicite asistencia.",
                "prioridad_seleccionada": prioridad,
            },
            status_code=503,
        )


# --- HU-002: consulta de turnos (solo lectura) -------------------------------

@app.get("/api/turnos/{codigo}")
def api_consultar_turno(codigo: str):
    """Devuelve estado de MongoDB y posicion de Redis si sigue pendiente."""
    try:
        return {"ok": True, "turno": consultar_turno(get_db(), codigo)}
    except ConsultaError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status)
    except PyMongoError:
        return JSONResponse(
            {"ok": False, "error": "MongoDB no disponible temporalmente."},
            status_code=503,
        )


def _mostrar_consulta(request: Request, codigo: str = ""):
    """Comparte plantilla entre buscador y enlace directo por codigo."""
    turno = None
    error = ""
    status = 200
    if codigo.strip():
        try:
            turno = consultar_turno(get_db(), codigo)
        except ConsultaError as e:
            error = str(e)
            status = e.status
        except PyMongoError:
            error = "MongoDB no disponible temporalmente."
            status = 503

    return templates.TemplateResponse(
        request,
        "consultar.html",
        {
            "base": BASE,
            "servicio": SERVICIO_NOMBRE,
            "codigo": codigo,
            "turno": turno,
            "error": error,
        },
        status_code=status,
    )


@app.get("/consultar", response_class=HTMLResponse)
def vista_consultar(request: Request, codigo: str = ""):
    """Formulario de busqueda; GET /consultar?codigo=A-001."""
    return _mostrar_consulta(request, codigo)


# --- HU-013: consulta del turno desde el QR (solo lectura) ---------------------

_SIN_CACHE = {"Cache-Control": "no-store"}
_TITULO_QR = {
    400: "Código QR no válido",
    404: "Turno no encontrado",
    503: "No podemos consultar su turno ahora",
}


@app.get("/api/turnos/qr/{token}")
def api_turno_por_qr(token: str):
    """Estado y posición del turno asociado a un QR (UUID v4). Solo lectura."""
    try:
        return JSONResponse({"ok": True, "turno": consultar_por_token(get_db(), token)}, headers=_SIN_CACHE)
    except QRError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=e.status, headers=_SIN_CACHE)


@app.get("/turno/qr/{token}", response_class=HTMLResponse)
def vista_turno_por_qr(request: Request, token: str):
    """Página móvil a la que lleva el QR del ticket: se actualiza sola, sin recargar."""
    contexto = {"base": BASE, "token": token, "turno": None, "error": "", "reintentar": False,
                "servicio_nombre": SERVICIO_NOMBRE}
    status = 200
    try:
        contexto["turno"] = consultar_por_token(get_db(), token)
    except QRError as e:
        status = e.status
        contexto.update(error=str(e), error_titulo=_TITULO_QR.get(e.status, "No se pudo mostrar el turno"),
                        reintentar=e.status == 503)
    return templates.TemplateResponse(request, "turno_qr.html", contexto, status_code=status, headers=_SIN_CACHE)


@app.get("/turno/{codigo}", response_class=HTMLResponse)
def vista_turno(request: Request, codigo: str):
    """Enlace directo a la consulta de un turno concreto."""
    return _mostrar_consulta(request, codigo)


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
    redis_responde = True
    try:
        turnos = cola_redis.ver_cola()
    except RedisError as e:
        redis_responde = False
        error = error or f"Redis no disponible: {e}"
    # Ventanillas que ya tienen un turno: no se les puede llamar otro (una a la vez).
    ocupadas = {}
    try:
        ventanillas_estado, _ = estado_ventanillas(get_db(), usar_redis=redis_responde)
        ocupadas = {v["id"]: v["turno"]["codigo"] for v in ventanillas_estado if v["turno"]}
    except Exception:
        ocupadas = {}
    return templates.TemplateResponse(
        request, "cola.html",
        {"base": BASE, "servicio": SERVICIO_NOMBRE, "turnos": turnos, "error": error,
         "mensaje": msg, "ventanillas": VENTANILLAS, "ocupadas": ocupadas},
    )


@app.exception_handler(ErrorAtencion)
def _error_atencion(request: Request, exc: ErrorAtencion):
    """Errores controlados del ciclo de atención: nunca un 500 sin explicar."""
    return JSONResponse({"ok": False, "error": exc.mensaje}, status_code=exc.status_code)


def _publicar_evento(tipo: str, codigo: str, estado: str, ventanilla: str = None, prioridad: str = None) -> None:
    """Avisa en vivo un cambio de estado (TT-013). De mejor esfuerzo: nunca rompe ni deshace la operación."""
    try:
        eventos.publicar(tipo, codigo=codigo, estado=estado, ventanilla=ventanilla, prioridad=prioridad)
    except Exception:
        pass


def _confirmar_presencia(codigo: str) -> None:
    """El cliente se presentó: su Hash temporal deja de vencer. Si Redis falla, no se deshace la atención."""
    try:
        cola_redis.confirmar_presencia(codigo)
    except RedisError:
        pass


@app.post("/api/atencion/iniciar", response_model=TurnoEnAtencion)
def api_iniciar_atencion(codigo: str = Form(...), ventanilla: str = Form(...)):
    """Iniciar la atención de un turno llamado: llamado -> en_atencion (HU-006)."""
    resultado = atencion.iniciar_atencion(get_db()["turnos"], codigo, ventanilla)
    _confirmar_presencia(resultado["codigo"])
    _publicar_evento(eventos.ATENCION_INICIADA, resultado["codigo"], "en_atencion", resultado.get("ventanilla"))
    return resultado


@app.post("/api/atencion/finalizar", response_model=TurnoFinalizado)
def api_finalizar_atencion(codigo: str = Form(...), ventanilla: str = Form(...)):
    """Finalizar la atención: en_atencion -> atendido y liberar Redis (HU-007)."""
    resultado = atencion.finalizar_atencion(
        get_db()["turnos"], codigo, ventanilla,
        al_finalizar=lambda c: liberar_turno(c, ventanilla.strip()),
    )
    _publicar_evento(eventos.ATENCION_FINALIZADA, resultado["codigo"], "atendido", resultado.get("ventanilla"))
    return resultado


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
    _confirmar_presencia(r["codigo"])
    _publicar_evento(eventos.ATENCION_INICIADA, r["codigo"], "en_atencion", r.get("ventanilla"))
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
    _publicar_evento(eventos.ATENCION_FINALIZADA, r["codigo"], "atendido", r.get("ventanilla"))
    msg = f"{r['ventanilla']}: atención de {r['codigo']} finalizada ({r['atencion_seg']} s)."
    if r["redis_liberado"] is False:
        msg += " Aviso: no se pudo limpiar el estado en Redis."
    return _redirigir_panel(msg=msg)


@app.get("/", response_class=HTMLResponse)
def inicio(request: Request, coleccion: str = "", editar: str = "", ok: str = "", filtro_estado: str = ""):
    return render(request, coleccion.strip(), editar.strip(), ok=ok, filtro_estado=filtro_estado.strip())


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
        doc = json_a_documento(json_doc)
        if coleccion == "turnos":
            normalizar_timestamps_turno(doc)
            validar_documento_turno(doc)
        get_db()[coleccion].insert_one(doc)
        return ir(coleccion, ok="insertado")
    except TurnoValidationError as e:
        return render(request, coleccion, error=f"Validación de turno falló (TT-002): {e}", json_texto=json_doc)
    except Exception as e:
        return render(request, coleccion, error=f"Error insertando: {e}", json_texto=json_doc)


@app.post("/actualizar")
def actualizar(request: Request, coleccion: str = "", id: str = Form(""),
               json_doc: str = Form("", alias="json")):
    try:
        doc = json_a_documento(json_doc)
        if coleccion == "turnos":
            normalizar_timestamps_turno(doc)
            validar_documento_turno(doc)
        get_db()[coleccion].update_one({"_id": a_object_id(id)}, {"$set": doc})
        return ir(coleccion, ok="actualizado")
    except TurnoValidationError as e:
        return render(request, coleccion, editar=id, error=f"Validación de turno falló (TT-002): {e}", json_texto=json_doc)
    except Exception as e:
        return render(request, coleccion, editar=id, error=f"Error actualizando: {e}")


@app.post("/eliminar")
def eliminar(request: Request, coleccion: str = "", id: str = Form("")):
    try:
        get_db()[coleccion].delete_one({"_id": a_object_id(id)})
        return ir(coleccion, ok="eliminado")
    except Exception as e:
        return render(request, coleccion, error=f"Error eliminando: {e}")


# --- HU-010: Historial y Auditoría (Carlos Espinoza) -------------------------

@app.get("/api/historial")
def api_historial(
    estado: str = "",
    ventanilla: str = "",
    prioridad: str = "",
    codigo: str = "",
    limite: int = 100,
    salto: int = 0,
):
    """Consulta turnos históricos con filtros y métricas calculadas (HU-010)."""
    try:
        return obtener_historial_turnos(
            get_db(),
            estado=estado.strip() or None,
            ventanilla=ventanilla.strip() or None,
            prioridad=prioridad.strip() or None,
            codigo=codigo.strip() or None,
            limite=limite,
            salto=salto,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error al consultar historial: {e}"}, status_code=500)


@app.get("/api/historial/descargar")
def api_descargar_historial(
    estado: str = "",
    ventanilla: str = "",
    prioridad: str = "",
    codigo: str = "",
):
    """Descarga en archivo JSON todos los registros del historial filtrados (HU-010)."""
    try:
        datos = exportar_historial_turnos(
            get_db(),
            estado=estado.strip() or None,
            ventanilla=ventanilla.strip() or None,
            prioridad=prioridad.strip() or None,
            codigo=codigo.strip() or None,
        )
        contenido = json.dumps(datos, indent=2, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"historial_turnos_{timestamp}.json"
        return Response(
            content=contenido,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
            },
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error al exportar historial: {e}"}, status_code=500)



@app.get("/historial", response_class=HTMLResponse)
def vista_historial(
    request: Request,
    estado: str = "",
    ventanilla: str = "",
    prioridad: str = "",
    codigo: str = "",
):
    """Vista de supervisión y auditoría del historial de turnos (HU-010)."""
    try:
        res = obtener_historial_turnos(
            get_db(),
            estado=estado.strip() or None,
            ventanilla=ventanilla.strip() or None,
            prioridad=prioridad.strip() or None,
            codigo=codigo.strip() or None,
            limite=100,
        )
        return templates.TemplateResponse(
            request,
            "historial.html",
            {
                "base": BASE,
                "turnos": res["turnos"],
                "total": res["total"],
                "filtros": res["filtros"],
                "estados_disponibles": ESTADOS,
                "ventanillas_disponibles": VENTANILLAS,
                "prioridades_disponibles": PRIORIDADES,
                "error": "",
            },
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "historial.html",
            {
                "base": BASE,
                "turnos": [],
                "total": 0,
                "filtros": {"estado": estado, "ventanilla": ventanilla, "prioridad": prioridad, "codigo": codigo},
                "estados_disponibles": ESTADOS,
                "ventanillas_disponibles": VENTANILLAS,
                "prioridades_disponibles": PRIORIDADES,
                "error": f"Error cargando historial de MongoDB: {e}",
            },
            status_code=500,
        )


# --- HU-011: Dashboard y Métricas SLA (Carlos Espinoza) ----------------------

@app.get("/api/dashboard")
def api_dashboard(sla_espera: int = 300):
    """Indicadores operacionales y métricas SLA calculadas con aggregation pipelines (HU-011)."""
    try:
        return calcular_metricas_dashboard(get_db(), sla_espera_max_seg=sla_espera)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error calculando métricas: {e}"}, status_code=500)


@app.get("/api/dashboard/descargar")
def api_descargar_dashboard(sla_espera: int = 300):
    """Descarga en archivo JSON los indicadores y el cumplimiento de SLA actual (HU-011)."""
    try:
        datos = exportar_metricas_dashboard(get_db(), sla_espera_max_seg=sla_espera)
        contenido = json.dumps(datos, indent=2, ensure_ascii=False)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        nombre_archivo = f"dashboard_sla_{sla_espera}s_{timestamp}.json"
        return Response(
            content=contenido,
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{nombre_archivo}"',
            },
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Error al exportar dashboard: {e}"}, status_code=500)



@app.get("/dashboard", response_class=HTMLResponse)
def vista_dashboard(request: Request, sla_espera: int = 300):
    """Panel visual para supervisores con KPIs de espera, atención y SLA (HU-011)."""
    try:
        metricas = calcular_metricas_dashboard(get_db(), sla_espera_max_seg=sla_espera)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "base": BASE,
                "metricas": metricas,
                "error": "",
            },
        )
    except Exception as e:
        metricas_vacias = {
            "totales": {"esperando": 0, "llamados": 0, "en_atencion": 0, "atendidos": 0, "abandonados": 0, "total_turnos": 0},
            "promedios": {"espera_seg": 0.0, "atencion_seg": 0.0},
            "ventanillas": {"total_configuradas": len(VENTANILLAS), "activas": 0, "detalle": [{"ventanilla": v, "ocupada": False, "turnos_en_proceso": 0} for v in VENTANILLAS]},
            "sla": {"objetivo_max_espera_seg": sla_espera, "total_evaluados": 0, "cumplen": 0, "incumplen": 0, "porcentaje_cumplimiento": 100.0, "tasa_minima_requerida": 80.0, "estado": "CUMPLIDO"},
        }
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "base": BASE,
                "metricas": metricas_vacias,
                "error": f"Error conectando a MongoDB para calcular métricas: {e}",
            },
            status_code=500,
        )


# --- HU-009: Pantalla pública de llamados (Aaron Benavides) ------------------

def _obtener_llamados_actuales() -> list[dict]:
    """MongoDB decide el estado real; memoria como respaldo si MongoDB falla."""
    try:
        mongo = _pantalla.consultar_desde_mongo(get_db())
    except Exception:
        mongo = None
    # MongoDB vacío significa que no hay activos; no revivir caché obsoleta.
    if mongo is not None:
        return mongo
    return _pantalla.llamados_vigentes()


@app.get("/api/llamados")
def api_llamados():
    """Listado de llamados activos para pantalla de sala (HU-009)."""
    return {"ok": True, "llamados": _obtener_llamados_actuales()}


@app.get("/pantalla", response_class=HTMLResponse)
def vista_pantalla(request: Request):
    """Vista pública de llamados, sin datos personales (HU-009)."""
    return templates.TemplateResponse(
        request, "pantalla.html",
        {"base": BASE, "llamados": _obtener_llamados_actuales()},
    )
