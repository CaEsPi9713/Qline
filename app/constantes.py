"""
Constantes comunes de QLine (TT-009).

Fuente única de los contratos aprobados en docs/Plan de Desarrollo QLINE.
Ningún módulo debe redefinir servicio, ventanillas, prioridades, estados,
TTL ni el prefijo de claves Redis.
"""

# --- Servicio (MVP: uno solo) -------------------------------------------
SERVICIO_ID = "atencion_general"
SERVICIO_NOMBRE = "Atención General"

# --- Ventanillas ---------------------------------------------------------
VENTANILLAS = ("V-01", "V-02", "V-03")

# --- Prioridades ---------------------------------------------------------
PRIORIDAD_NORMAL = "normal"
PRIORIDAD_PREFERENCIAL = "preferencial"
PRIORIDADES = (PRIORIDAD_NORMAL, PRIORIDAD_PREFERENCIAL)

# --- Estados del turno ---------------------------------------------------
ESTADO_PENDIENTE = "pendiente"
ESTADO_LLAMADO = "llamado"
ESTADO_EN_ATENCION = "en_atencion"
ESTADO_ATENDIDO = "atendido"
ESTADO_ABANDONADO = "abandonado"
ESTADOS = (
    ESTADO_PENDIENTE,
    ESTADO_LLAMADO,
    ESTADO_EN_ATENCION,
    ESTADO_ATENDIDO,
    ESTADO_ABANDONADO,
)

# Transiciones permitidas (origen -> destinos)
TRANSICIONES = {
    ESTADO_PENDIENTE: (ESTADO_LLAMADO,),
    ESTADO_LLAMADO: (ESTADO_EN_ATENCION, ESTADO_ABANDONADO),
    ESTADO_EN_ATENCION: (ESTADO_ATENDIDO,),
    ESTADO_ATENDIDO: (),
    ESTADO_ABANDONADO: (),
}

# --- Tiempos -------------------------------------------------------------
TTL_ABANDONO_SEG = 180

# --- Redis ---------------------------------------------------------------
REDIS_PREFIJO = "grupo2:qline:"

CLAVE_CONTADOR = f"{REDIS_PREFIJO}contador:{SERVICIO_ID}"
CLAVE_COLA = f"{REDIS_PREFIJO}cola:{SERVICIO_ID}"
CLAVE_EVENTOS = f"{REDIS_PREFIJO}eventos"


def clave_ventanilla_actual(ventanilla: str) -> str:
    return f"{REDIS_PREFIJO}ventanilla:{ventanilla}:actual"


def clave_turno(codigo: str) -> str:
    return f"{REDIS_PREFIJO}turno:{codigo}"
