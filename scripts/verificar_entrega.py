"""
Revisa que el repositorio esté listo para la entrega final (release v1.0.0) y dice qué falta.

    python -m scripts.verificar_entrega             # informe; código de salida 1 solo si hay errores
    python -m scripts.verificar_entrega --estricto  # código de salida 1 también si hay pendientes (úselo antes del tag)

Cada línea es OK, PENDIENTE (un dato o paso que el equipo debe completar), AVISO (conviene revisarlo) o ERROR
(algo está mal). No modifica nada. Las comprobaciones de git se omiten si no hay un repositorio git disponible.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

CAMPOS_PORTAL = ("nombre", "resumen", "problema", "usuarios", "motores", "lenguaje", "licencia", "repositorio",
                 "demo_video", "demo_url", "captura", "grupo", "dia", "periodo", "autores_publicos")
ARCHIVOS_OBLIGATORIOS = (
    "README.md", "CHANGELOG.md", "LICENSE", "portal.yml", ".env.example", ".gitignore", "requirements.txt",
    "docs/arquitectura/arquitectura.md", "docs/arquitectura/redis_claves.md", "docs/decisiones.md",
    "docs/evidencia/README.md", "docs/seguimientos/S1.md", "docs/seguimientos/S2.md", "docs/seguimientos/S3.md",
    "docs/seguimientos/S4.md", "scripts/init_mongo.py", "scripts/crear_admin.py",
)
TAGS = ("v0.1.0", "v0.2.0", "v0.3.0", "v0.9.0", "v1.0.0")
# Cadena de conexión con usuario y clave escritos (no las que se arman con {variables}) o una variable secreta con valor.
PATRON_URI = re.compile(r"mongodb(\+srv)?://[^\s:@/{}]+:[^\s@/{}]+@")
PATRON_VARIABLE = re.compile(r"(MONGO_PASS|REDIS_PASS|SECRETO_SESION)=[^\s#]{4,}")


def leer_portal(texto: str) -> dict:
    """Lee el formato plano del portal: `clave: valor`, con listas `[a, b]` y comentarios con `#` al inicio de línea."""
    datos: dict = {}
    for numero, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        if linea.startswith((" ", "\t")) or ":" not in linea:
            raise ValueError(f"línea {numero}: el formato debe ser plano, una clave por línea")
        clave, _, valor = linea.partition(":")
        valor = valor.strip()
        if valor.startswith("[") and valor.endswith("]"):
            interior = valor[1:-1].strip()
            datos[clave.strip()] = [x.strip().strip("'\"") for x in interior.split(",")] if interior else []
        else:
            datos[clave.strip()] = valor.strip("'\"")
    return datos


def _git(raiz: Path, *args: str):
    try:
        r = subprocess.run(["git", *args], cwd=raiz, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _enlaces_rotos(raiz: Path) -> list:
    rotos = []
    omitir = {"venv", ".git", "node_modules", "__pycache__"}
    for md in raiz.rglob("*.md"):
        if omitir & set(md.relative_to(raiz).parts):
            continue
        texto = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", md.read_text(encoding="utf-8", errors="replace"), flags=re.S))
        for destino in re.findall(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", texto):
            if destino.startswith(("http://", "https://", "mailto:", "#")):
                continue
            ruta = destino.split("#")[0]
            if ruta and not (md.parent / ruta).exists():
                rotos.append(f"{md.relative_to(raiz)} -> {destino}")
    return sorted(rotos)


def revisar(raiz: Path = RAIZ) -> list:
    """Devuelve [(estado, comprobación, detalle)]; estado es OK, PENDIENTE, AVISO o ERROR."""
    r: list = []

    def ok(nombre, detalle=""): r.append(("OK", nombre, detalle))
    def pendiente(nombre, detalle): r.append(("PENDIENTE", nombre, detalle))
    def aviso(nombre, detalle): r.append(("AVISO", nombre, detalle))
    def error(nombre, detalle): r.append(("ERROR", nombre, detalle))

    # Archivos que la entrega exige
    faltan = [a for a in ARCHIVOS_OBLIGATORIOS if not (raiz / a).exists()]
    (error("Archivos obligatorios", "faltan: " + ", ".join(faltan)) if faltan
     else ok("Archivos obligatorios", f"{len(ARCHIVOS_OBLIGATORIOS)} presentes"))
    for carpeta in ("scripts", "data", "docs"):
        if not (raiz / carpeta).is_dir():
            error("Estructura", f"falta la carpeta {carpeta}/")

    readme_texto = (raiz / "README.md").read_text(encoding="utf-8") if (raiz / "README.md").exists() else ""

    # Ficha del portal
    portal = raiz / "portal.yml"
    if portal.exists():
        try:
            d = leer_portal(portal.read_text(encoding="utf-8"))
        except ValueError as e:
            d = None
            error("portal.yml", f"formato no válido: {e}")
        if d is not None:
            sobran, faltan = sorted(set(d) - set(CAMPOS_PORTAL)), [c for c in CAMPOS_PORTAL if c not in d]
            if sobran or faltan:
                error("portal.yml", "campos distintos de los del enunciado" + (f"; faltan: {', '.join(faltan)}" if faltan else "")
                      + (f"; sobran: {', '.join(sobran)}" if sobran else ""))
            else:
                ok("portal.yml", "claves del formato oficial")
                if d["licencia"] != "MIT":
                    aviso("portal.yml", f"licencia {d['licencia']!r}: debe coincidir con LICENSE")
                if not (raiz / d["captura"]).is_file():
                    error("portal.yml", f"la captura {d['captura']} no existe")
                if not isinstance(d["motores"], list) or not d["motores"]:
                    error("portal.yml", "motores debe ser una lista")
                if d["dia"] not in ("martes", "viernes"):
                    pendiente("portal.yml · dia", "debe ser martes o viernes")
                video = d["demo_video"]
                if not video:
                    aviso("Video de demostración", "sin enlace (es opcional)")
                elif not video.startswith("https://"):
                    error("portal.yml · demo_video", "debe ser un enlace https")
                else:
                    ok("portal.yml · demo_video", video)
                    if video in readme_texto:
                        ok("README · video", "enlazado")
                    else:
                        pendiente("README · video", "el enlace del video debe estar también en el README")
                if not d["autores_publicos"]:
                    aviso("portal.yml · autores_publicos", "vacío: no se publica ningún nombre (solo con autorización)")

    # README y changelog
    changelog = (raiz / "CHANGELOG.md").read_text(encoding="utf-8") if (raiz / "CHANGELOG.md").exists() else ""
    if re.search(r"(?m)^## \[1\.0\.0\]", changelog):
        ok("CHANGELOG · v1.0.0", "sección presente")
    else:
        pendiente("CHANGELOG · v1.0.0", "falta la sección [1.0.0] (se cierra el día del release; hoy el último cierre es [0.9.0])")
    rotos = _enlaces_rotos(raiz)
    (error("Enlaces de la documentación", f"{len(rotos)} rotos: " + "; ".join(rotos[:5])) if rotos
     else ok("Enlaces de la documentación", "ninguno roto"))

    # Secretos y git
    if _git(raiz, "rev-parse", "--git-dir") is None:
        aviso("Git", "no hay repositorio git: se omiten tags, secretos y árbol de trabajo")
        return r
    versionados = (_git(raiz, "ls-files") or "").splitlines()
    if ".env" in versionados:
        error("Secretos", ".env está versionado")
    hallazgos = []
    for ruta in versionados:
        archivo = raiz / ruta
        if ruta == ".env.example" or not archivo.is_file() or archivo.suffix in {".jpg", ".png", ".pptx", ".pdf", ".ico"}:
            continue
        try:
            contenido = archivo.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Las pruebas llevan credenciales falsas a propósito, para comprobar que nunca se filtran.
        if ruta.startswith("tests/"):
            continue
        if PATRON_VARIABLE.search(contenido) or PATRON_URI.search(contenido):
            hallazgos.append(ruta)
    (error("Secretos", "posibles credenciales en: " + ", ".join(hallazgos[:5])) if hallazgos
     else ok("Secretos", "ninguna credencial en los archivos versionados"))
    tags = set((_git(raiz, "tag", "-l") or "").split())
    faltan_tags = [t for t in TAGS if t not in tags]
    (pendiente("Tags", "faltan: " + ", ".join(faltan_tags)) if faltan_tags else ok("Tags", ", ".join(TAGS)))
    sucio = (_git(raiz, "status", "--porcelain") or "").strip()
    (aviso("Árbol de trabajo", "hay cambios sin confirmar") if sucio else ok("Árbol de trabajo", "limpio"))
    return r


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--estricto", action="store_true", help="falla también si hay pendientes")
    args = p.parse_args(argv)
    resultados = revisar()
    for estado, nombre, detalle in resultados:
        print(f"  {estado:<9} {nombre}" + (f": {detalle}" if detalle else ""))
    conteo = {e: sum(1 for x in resultados if x[0] == e) for e in ("OK", "PENDIENTE", "AVISO", "ERROR")}
    print(f"\n{conteo['OK']} OK · {conteo['PENDIENTE']} pendientes · {conteo['AVISO']} avisos · {conteo['ERROR']} errores")
    if conteo["ERROR"] or (args.estricto and conteo["PENDIENTE"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
