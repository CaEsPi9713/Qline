"""
Generador de la presentación final editable de QLine en formato PPTX (TT-025).
Aplica paleta Fintech sólida:
- Fondo: Marino oscuro / Blanco suave
- Tipografía: Segoe UI / Arial
- Sin degradados agresivos ni efectos innecesarios.
"""

import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def crear_presentacion():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # Paleta Fintech aprobada
    C_NAVY = RGBColor(11, 17, 28)       # #0B111C
    C_SLATE = RGBColor(30, 41, 59)      # #1E293B
    C_TEAL = RGBColor(91, 182, 197)     # #5BB6C5
    C_GREEN = RGBColor(83, 133, 115)    # #538573
    C_WHITE = RGBColor(255, 255, 255)
    C_MUTED = RGBColor(148, 163, 184)   # #94A3B8
    C_DARK = RGBColor(15, 23, 42)       # #0F172A

    blank_layout = prs.slide_layouts[6]

    diapositivas_datos = [
        # 1. Portada
        {
            "titulo": "QLine: Sistema Inteligente de Gestión de Filas y Turnos",
            "subtitulo": "«MongoDB conserva lo que ocurrió. Redis controla lo que ocurre ahora.»",
            "categoria": "SEGUIMIENTO 4 · ENTREGA FINAL Y RELEASE",
            "puntos": [
                "Curso: Tópicos Avanzados de Bases de Datos · Universidad Nacional (UNA)",
                "Equipo: Query Logic (Grupo 2)",
                "Integrantes: Aaron Benavides, Abigail Urbina, Alessandro Cambronero, Carlos Espinoza",
                "Stack: FastAPI · Redis (Sorted Sets/Hashes/PubSub) · MongoDB ($jsonSchema/Aggregations) · Jinja2",
                "Versión: 0.9.0-rc (Release Candidate)"
            ],
            "fondo_oscuro": True
        },
        # 2. Problema y Objetivos
        {
            "titulo": "1. Introducción y Problema Abordado",
            "subtitulo": "Ineficiencia y saturación en salas de espera tradicionales",
            "categoria": "CONTEXTO Y JUSTIFICACIÓN",
            "puntos": [
                "Problema en atención presencial: Incertidumbre del usuario, aglomeraciones físicas en ventanilla y falta de visibilidad del avance de la fila.",
                "Desafío de concurrencia: Evitar asignación de turnos duplicados entre múltiples operadores concurrentes.",
                "Desafío de resiliencia: Si un motor en memoria se reinicia o desconecta, la persistencia histórica y el estado de la cola no pueden perderse.",
                "Objetivo general: Implementar un sistema de turnos desacoplado, atómico y de alta velocidad con seguimiento en tiempo real y persistencia auditable."
            ],
            "fondo_oscuro": False
        },
        # 3. Objetivos y Alcance
        {
            "titulo": "2. Objetivos y Alcance Técnico",
            "subtitulo": "Delimitación estricta de alcance acordado en el Plan Maestro",
            "categoria": "ALCANCE DEL SISTEMA",
            "puntos": [
                "Un solo servicio oficial: 'Atención General' (servicio_id: atencion_general).",
                "Dos niveles de prioridad: 'Normal' (general) y 'Preferencial' (adultos mayores, discapacidad, embarazadas).",
                "Tres ventanillas base de atención: V-01, V-02, V-03.",
                "Cinco estados oficiales inmutables: pendiente -> llamado -> en_atencion -> atendido / abandonado.",
                "Ventana de atención con TTL estricto: 180 segundos para presentarse tras el llamado.",
                "Exclusiones deliberadas: No predicción de tiempos de espera sin muestra histórica, no exportación a CSV (solo JSON auditado), no multisucursal."
            ],
            "fondo_oscuro": False
        },
        # 4. Arquitectura del Sistema
        {
            "titulo": "3. Arquitectura del Sistema",
            "subtitulo": "Desacoplamiento operacional entre Redis y MongoDB",
            "categoria": "ARQUITECTURA DE SOFTWARE",
            "puntos": [
                "Capa Web / API: FastAPI en Python 3.12, sirviendo endpoints REST, WebSockets y plantillas server-side Jinja2.",
                "Capa en Memoria (Redis): Cola atómica viva, control de concurrencia de ventanilla única, Hash con TTL y bus Pub/Sub de eventos.",
                "Capa Persistente (MongoDB): Fuente de verdad definitiva, validación de esquema $jsonSchema, índices parciales y aggregation pipelines analíticos.",
                "Seguridad perimetral (Apache): Autenticación básica selectiva; acceso público sin contraseña reservado para la consulta móvil por QR y recursos estáticos."
            ],
            "fondo_oscuro": False
        },
        # 5. Responsabilidades de Redis
        {
            "titulo": "4. Responsabilidades de Redis",
            "subtitulo": "Alta velocidad, atomicidad y sincronización en tiempo real",
            "categoria": "MOTOR EN MEMORIA",
            "puntos": [
                "Cola ordenada (Sorted Set): grupo2:qline:cola:atencion_general ordenada por puntaje (prioridad * 10¹³ + hora_ms).",
                "Asignación atómica (ZPOPMIN): Extracción segura del siguiente turno en un solo comando atómico de Redis (turnos duplicados = 0).",
                "Ventanilla única (SET NX EX 10): Reserva de ventanilla en Redis que bloquea clics simultáneos y previene doble atención concurrente.",
                "Ventana de llamado (Hash con TTL): grupo2:qline:turno:{codigo} con TTL de 180 s para gobernar el tiempo de presentación.",
                "Bus de eventos (Pub/Sub): Canal grupo2:qline:eventos para propagar cambios a WebSockets en sala y móviles."
            ],
            "fondo_oscuro": False
        },
        # 6. Responsabilidades de MongoDB
        {
            "titulo": "5. Responsabilidades de MongoDB",
            "subtitulo": "Persistencia definitiva, integridad documental y analítica",
            "categoria": "BASE DE DATOS DOCUMENTAL",
            "puntos": [
                "Fuente de verdad auditable: Colección 'turnos' con historial completo y marcas de tiempo ISO 8601 en UTC.",
                "Esquema estricto ($jsonSchema): Validación estricta a nivel de motor (turnos_schema.py) que rechaza estados, campos y tipos no permitidos.",
                "Evolución no destructiva: Índice parcial único idx_turnos_qr_token_unico sobre qr_token que respeta registros previos sin recrear colección.",
                "Índices optimizados: Búsqueda por código (idx_turnos_codigo_unico), historial (idx_turnos_estado_creado) y barrido (idx_turnos_estado_llamado).",
                "Aggregation Pipelines: Conteo de estados y métricas de cumplimiento de SLA calculados en el motor en < 2 ms sin transferir colecciones."
            ],
            "fondo_oscuro": False
        },
        # 7. Gestión de Cola y Prioridades
        {
            "titulo": "6. Gestión de la Cola y Prioridades",
            "subtitulo": "Modelo matemático de prioridad estricta con orden de llegada",
            "categoria": "LÓGICA DE COLA",
            "puntos": [
                "Fórmula del Score en Sorted Set: puntaje = nivel * 10¹³ + hora_llegada_ms.",
                "Nivel 0 para Preferencial y Nivel 1 para Normal: Preferencial siempre tiene un score menor (~10¹² frente a ~10¹³).",
                "Extracción con ZPOPMIN: Redis devuelve el menor score. La prioridad domina estrictamente sobre la hora de llegada.",
                "Dentro de una misma prioridad: El desempate se resuelve por orden de llegada (FIFO exacto en milisegundos).",
                "Precisión numérica: 1.2 * 10¹³ es representable exactamente en enteros de 64 bits y en coma flotante IEEE 754 (límite 2⁵³ ≈ 9 * 10¹⁵)."
            ],
            "fondo_oscuro": False
        },
        # 8. Flujo Quiosco, Ticket y QR
        {
            "titulo": "7. Flujo de Quiosco, Ticket y QR Móvil",
            "subtitulo": "Experiencia del cliente de autoservicio y seguimiento personal",
            "categoria": "EXPERIENCIA DEL CLIENTE",
            "puntos": [
                "Emisión en Quiosco (/quiosco): Selección táctil directa entre atención Normal y Preferencial sin solicitar datos personales.",
                "Generación de ticket: Código único de turno, QR en SVG vectorial inline, fecha y hora local (America/Costa_Rica).",
                "Ticket imprimible (S4-M02): Impresión limpia vía window.print() con @media print y pausa del temporizador de retorno de 25 s.",
                "Seguimiento móvil (/turno/qr/{uuid}): Acceso público en celular que muestra estado, turnos por delante y cuenta regresiva.",
                "Instrucciones y finalización (P01/P05): Mensaje de espera autoactualizable y aviso explícito para cerrar la pestaña al ser atendido."
            ],
            "fondo_oscuro": False
        },
        # 9. Flujo del Operador y Ventanilla
        {
            "titulo": "8. Flujo del Operador y Ventanilla",
            "subtitulo": "Operación ágil en ventanilla con control de estados",
            "categoria": "OPERACIÓN EN VENTANILLA",
            "puntos": [
                "Panel de operador (/panel): Selección de ventanilla asignada (V-01, V-02, V-03) y estado de ocupación actual.",
                "Llamado del siguiente turno: Invoca /api/llamar, ejecuta ZPOPMIN en Redis, reserva ventanilla (SET NX) y actualiza MongoDB a 'llamado'.",
                "Inicio de atención: El operador confirma la presencia del usuario; el turno pasa a 'en_atencion' y se elimina el Hash con TTL.",
                "Finalización de atención: El turno concluye exitosamente en 'atendido', liberando la ventanilla para el próximo llamado.",
                "Bloqueo de colisiones: Si un operador intenta llamar mientras su ventanilla está ocupada, la API responde 409 Conflict."
            ],
            "fondo_oscuro": False
        },
        # 10. Concurrencia, TTL, Abandono y Recuperación
        {
            "titulo": "9. Concurrencia, TTL, Abandono y Recuperación",
            "subtitulo": "Resiliencia operacional ante ausencias y fallos de servicio",
            "categoria": "RESILIENCIA Y RECUPERACIÓN",
            "puntos": [
                "Abandono automático (HU-008): Barrido daemon periódico que evalúa turnos llamados con más de 180 s de antigüedad.",
                "Condición dual de abandono: Requiere expiración del Hash en Redis y validación en MongoDB; transición idempotente (update_one).",
                "Fecha de abandono coherente: Se registra timestamps.abandonado = timestamps.llamado + 180 s, no la hora del barrido.",
                "Recuperación / Reconciliación (HU-012): Script recuperacion.py reconcilia pendientes de MongoDB hacia Redis tras pérdida total o reinicio.",
                "No destructiva: No vacía la cola existente; sólo reencola los turnos faltantes calculando su score original en milisegundos."
            ],
            "fondo_oscuro": False
        },
        # 11. Dashboard y Reportes
        {
            "titulo": "10. Dashboard Analítico y Reportes",
            "subtitulo": "Supervisión operacional en tiempo real y cumplimiento de SLA",
            "categoria": "ANALÍTICA Y AUDITORÍA",
            "puntos": [
                "Métricas en tiempo real (/dashboard): Turnos en espera, llamados, en atención, atendidos y abandonados.",
                "Tiempos promedio: Cálculo de tiempo promedio de espera (creado a llamado) y tiempo promedio de atención (llamado a atendido).",
                "Cumplimiento de SLA: Medición de porcentaje de turnos atendidos dentro del umbral configurable (por defecto 300 s).",
                "Historial paginado (/historial): Búsqueda multicriterio por estado, ventanilla, prioridad y rango de fechas.",
                "Exportación de datos: Descargas completas en formato JSON estructurado (/api/historial/descargar y /api/dashboard/descargar)."
            ],
            "fondo_oscuro": False
        },
        # 12. Pruebas y Mediciones Reales
        {
            "titulo": "11. Pruebas y Mediciones Reales en el Servidor",
            "subtitulo": "Contraste estricto entre hipótesis teóricas de S1 y mediciones empíricas",
            "categoria": "EVIDENCIA EXPERIMENTAL",
            "puntos": [
                "Suite automatizada local: 513 pruebas ejecutadas, 512 aprobadas, 1 omitida (decodificador independiente sin zxing-cpp), 0 fallos.",
                "Concurrencia formal (TT-016): 259 asignaciones verificadas en servidor con 10 consumidores simultáneos -> 0 turnos duplicados.",
                "Latencia Redis (TT-018): INCR: 0.108 ms · ZADD: 0.126 ms · ZPOPMIN: 0.135 ms (mediana de 5 ejecuciones de 200 ops).",
                "Comparativa con MongoDB: find_one_and_update ($inc): 0.376 ms · insert_one: 0.347 ms · find_one_and_update: 0.493 ms.",
                "Contraste de Hipótesis: Hipótesis 1 (Redis < 2 ms) -> CUMPLIDA. Hipótesis 2 (mejora > 85 % frente a Mongo) -> NO CUMPLIDA (mejora real: 63.7 % a 72.7 %).",
                "Índices MongoDB (TT-014): IXSCAN examina 1 documento en 0.42 ms frente a COLLSCAN con 554 documentos en 0.65 ms."
            ],
            "fondo_oscuro": False
        },
        # 13. Limitaciones Conocidas
        {
            "titulo": "12. Limitaciones Conocidas y Deuda Técnica",
            "subtitulo": "Límites arquitectónicos aceptados y decisiones pendientes",
            "categoria": "LIMITACIONES Y DEUDA TÉCNICA",
            "puntos": [
                "Excepción de autenticación Apache: Rutas /turno/qr/{uuid} son públicas sin contraseña (D-22); quiosco y pantalla requieren login inicial de Apache.",
                "Expiración de Hash en Redis: Al no contar con CONFIG SET en el hosting para notificaciones de llaves, el abandono depende del barrido periódico.",
                "Vigencia del QR: El qr_token no posee expiración temporal automática posterior al estado de atendido.",
                "Servicio único: La arquitectura actual está diseñada y optimizada para 'Atención General'; no admite múltiples sucursales ni servicios dinámicos.",
                "Entorno de producción: Validaciones físicas en pantallas gigantes y escaneo con celular en campus requieren verificación presencial del equipo."
            ],
            "fondo_oscuro": False
        },
        # 14. Conclusiones y Demostración
        {
            "titulo": "13. Conclusiones y Demostración en Vivo",
            "subtitulo": "Aportes del equipo y secuencia paso a paso de la demo",
            "categoria": "CONCLUSIONES Y DEMOSTRACIÓN",
            "puntos": [
                "Aportes del equipo: Alessandro (Redis, concurrencia, tiempo real), Carlos (MongoDB, esquema, historial, analítica), Abigail (diseño visual, quiosco, accesibilidad), Aaron (cliente, tickets, QR, presentación, release).",
                "Secuencia de demostración en vivo (P07):",
                "  1. Abrir pantalla pública (/pantalla) y quiosco (/quiosco) en ventanas visibles.",
                "  2. Emitir turno normal y turno preferencial en el quiosco; mostrar ticket con QR y probar impresión.",
                "  3. Abrir la URL del QR móvil en el navegador o teléfono y observar el estado en espera.",
                "  4. En el panel (/panel), seleccionar V-01 y llamar turno: verificar que el preferencial sale primero (prioridad respetada).",
                "  5. Observar actualización inmediata en la pantalla de sala y en la vista móvil del QR.",
                "  6. Iniciar atención, finalizar turno y verificar aviso de cierre en el móvil.",
                "  7. Consultar el dashboard (/dashboard) e historial (/historial) y verificar métricas y descarga JSON."
            ],
            "fondo_oscuro": True
        }
    ]

    for data in diapositivas_datos:
        slide = prs.slides.add_slide(blank_layout)
        
        # Fondo
        bg_shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(7.5)
        )
        bg_shape.line.fill.background()
        if data["fondo_oscuro"]:
            bg_shape.fill.solid()
            bg_shape.fill.fore_color.rgb = C_NAVY
            color_titulo = C_WHITE
            color_sub = C_TEAL
            color_cat = C_MUTED
            color_texto = C_WHITE
        else:
            bg_shape.fill.solid()
            bg_shape.fill.fore_color.rgb = C_WHITE
            color_titulo = C_NAVY
            color_sub = C_SLATE
            color_cat = C_TEAL
            color_texto = C_DARK

        # Barra decorativa superior
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(0.6), Inches(11.733), Inches(0.06))
        bar.fill.solid()
        bar.fill.fore_color.rgb = C_TEAL if data["fondo_oscuro"] else C_GREEN
        bar.line.fill.background()

        # Categoría
        tb_cat = slide.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(11.733), Inches(0.4))
        p_cat = tb_cat.text_frame.paragraphs[0]
        p_cat.text = data["categoria"]
        p_cat.font.size = Pt(11)
        p_cat.font.bold = True
        p_cat.font.color.rgb = color_cat

        # Título
        tb_title = slide.shapes.add_textbox(Inches(0.8), Inches(1.15), Inches(11.733), Inches(0.8))
        p_title = tb_title.text_frame.paragraphs[0]
        p_title.text = data["titulo"]
        p_title.font.size = Pt(26)
        p_title.font.bold = True
        p_title.font.color.rgb = color_titulo

        # Subtítulo
        tb_sub = slide.shapes.add_textbox(Inches(0.8), Inches(1.95), Inches(11.733), Inches(0.5))
        p_sub = tb_sub.text_frame.paragraphs[0]
        p_sub.text = data["subtitulo"]
        p_sub.font.size = Pt(15)
        p_sub.font.italic = True
        p_sub.font.color.rgb = color_sub

        # Contenido / Puntos
        tb_body = slide.shapes.add_textbox(Inches(0.8), Inches(2.6), Inches(11.733), Inches(4.3))
        tf = tb_body.text_frame
        tf.word_wrap = True

        for i, punto in enumerate(data["puntos"]):
            p = tf.add_paragraph() if i > 0 else tf.paragraphs[0]
            p.text = "•  " + punto
            p.font.size = Pt(14)
            p.font.color.rgb = color_texto
            p.space_after = Pt(10)
            p.line_spacing = 1.2

    output_dir = os.path.join("docs", "presentacion")
    os.makedirs(output_dir, exist_ok=True)
    pptx_path = os.path.join(output_dir, "QLine_Presentacion_Final.pptx")
    prs.save(pptx_path)
    print("Presentación PPTX generada exitosamente en:", pptx_path)

if __name__ == "__main__":
    crear_presentacion()
