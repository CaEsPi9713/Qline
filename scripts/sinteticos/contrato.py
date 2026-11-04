"""Estructura del documento `turnos` (sección 4.5 del plan).

Las constantes de negocio (estados, prioridades, ventanillas, TTL) viven en
app.constantes; aquí solo se describe la forma del documento.
"""

CAMPOS_TURNO = ("codigo", "servicio", "prioridad", "estado", "ventanilla",
                "operador", "timestamps", "metricas")
CAMPOS_TIMESTAMPS = ("creado", "llamado", "inicio_atencion", "finalizado", "abandonado")
CAMPOS_METRICAS = ("espera_seg", "atencion_seg")
