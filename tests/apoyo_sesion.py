"""Apoyo para las pruebas: un cliente de la aplicación que ya trae una sesión abierta del rol indicado.

El usuario se inserta directamente en la base de pruebas (sin calcular un hash por prueba) y la cookie se firma con
el mismo mecanismo de producción: así las rutas protegidas se prueban de verdad, sin ningún atajo en el código de la app.
"""
import os
from datetime import datetime, timezone

try:
    from fastapi.testclient import TestClient
except ImportError:           # pragma: no cover
    TestClient = object

os.environ.setdefault("SECRETO_SESION", "secreto-de-pruebas-de-la-suite")


def sembrar_usuario(db, rol: str, usuario: str = None) -> dict:
    """Inserta (si falta) un usuario activo con ese rol y devuelve su documento."""
    nombre = usuario or f"{rol}-prueba"
    ahora = datetime.now(timezone.utc)
    db["usuarios"].update_one(
        {"usuario": nombre},
        {"$setOnInsert": {"usuario": nombre, "hash": "sin-clave", "rol": rol, "estado": "activo", "ventanilla_asignada": None,
                          "version_sesion": 1, "intentos_fallidos": 0, "bloqueado_hasta": None, "ultimo_acceso": None,
                          "creado_en": ahora, "actualizado_en": ahora, "habilitado_por": None}},
        upsert=True)
    return db["usuarios"].find_one({"usuario": nombre})


class ClienteConSesion(TestClient):
    """`TestClient(main.app)` que inicia sesión como `rol` (administrador por defecto) con la base que use `main.get_db()`."""

    def __init__(self, app, *args, rol: str = "administrador", **kwargs):
        super().__init__(app, *args, **kwargs)
        if rol:
            self.iniciar_sesion(rol)

    def iniciar_sesion(self, rol: str, usuario: str = None) -> "ClienteConSesion":
        from app import auth, main
        try:
            doc = sembrar_usuario(main.get_db(), rol, usuario)
        except Exception:               # sin base de pruebas disponible: el cliente queda sin sesión
            return self
        self.cookies.set(auth.NOMBRE_COOKIE, auth.crear_token(doc))
        return self

    def iniciar_sesion_en(self, db, rol: str = "administrador", usuario: str = None) -> "ClienteConSesion":
        """Como `iniciar_sesion`, pero sembrando el usuario en `db`: para pruebas que parchean `get_db` con su propia base."""
        from app import auth
        self.cookies.set(auth.NOMBRE_COOKIE, auth.crear_token(sembrar_usuario(db, rol, usuario)))
        return self

    def cerrar_sesion(self) -> "ClienteConSesion":
        from app import auth
        self.cookies.delete(auth.NOMBRE_COOKIE)
        return self


def base_con_usuarios(**colecciones) -> dict:
    """Base de pruebas hecha con un `dict` de colecciones (algunas pruebas simulan así a MongoDB): añade la de usuarios."""
    import mongomock
    return {"usuarios": mongomock.MongoClient()["pruebas_acceso"]["usuarios"], **colecciones}
