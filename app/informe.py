"""
Encabezado común de los informes de evidencia generados por los scripts de recuperación.

Todo informe lleva la misma advertencia: lo genera el script con los resultados de esa
ejecución. Si un informe se generara con datos simulados (solo ocurre en pruebas), lo dice
en grande para que nadie lo presente como evidencia del servidor.
"""
from __future__ import annotations

import platform
from datetime import datetime, timezone


def encabezado(titulo: str, simulado: bool = False) -> str:
    texto = [f"# {titulo}", "",
             "> Informe generado por un script con los resultados de **esa ejecución**; no se escribe a mano.", "",
             f"- Fecha (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
             f"- Python: {platform.python_version()} · {platform.system()}"]
    if simulado:
        texto += ["", "> **SIMULADO.** Este informe se generó con MongoDB y Redis simulados. "
                      "**No es evidencia** del servidor y no debe presentarse como tal."]
    return "\n".join(texto) + "\n"
