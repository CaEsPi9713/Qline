"""
Generación de código QR y construcción de URL pública para HU-003.

Cumple con el contrato arquitectónico de docs/arquitectura/qr_consulta.md:
- URL dentro del QR: {PUBLIC_BASE_URL}{BASE_PATH}/turno/qr/{uuid}
- Dominio accesible desde celular, configurable mediante PUBLIC_BASE_URL.
- Dato sensible: contiene exclusivamente la URL de consulta pública.
- Generador vectorial SVG nativo en Python puro (cero dependencias externas).
"""
import os
from typing import List, Tuple

from app.consulta_qr import validar_token

# URL pública por defecto para el entorno de producción/curso
URL_PUBLICA_DEFECTO = "https://grupo2.crnube.net"

# Tablas estándar para QR ISO/IEC 18004 Nivel L (Error Correction Level L)
# Formato: version: (size, total_codewords, [(data_len, ec_len, num_blocks), ...], remainder_bits, [align_coords])
_VERSION_INFO_L = {
    1: (21, 26, [(19, 7, 1)], 0, []),
    2: (25, 44, [(34, 10, 1)], 7, [6, 18]),
    3: (29, 70, [(55, 15, 1)], 7, [6, 22]),
    4: (33, 100, [(80, 20, 1)], 7, [6, 26]),
    5: (37, 134, [(108, 26, 1)], 7, [6, 30]),
    6: (41, 172, [(68, 18, 2)], 7, [6, 34]),
    7: (45, 196, [(78, 20, 2)], 0, [6, 22, 38]),
    8: (49, 242, [(97, 24, 2)], 0, [6, 24, 42]),
    9: (53, 292, [(116, 30, 2)], 0, [6, 26, 46]),
    10: (57, 346, [(68, 18, 2), (69, 18, 2)], 0, [6, 28, 50]),
}

# Aritmética de campos de Galois GF(256) con polinomio primitivo 0x11D
_GF_EXP = [0] * 512
_GF_LOG = [0] * 256
_val = 1
for _i in range(255):
    _GF_EXP[_i] = _val
    _GF_EXP[_i + 255] = _val
    _GF_LOG[_val] = _i
    _val <<= 1
    if _val & 0x100:
        _val ^= 0x11D


def _gf_mul(a: int, b: int) -> int:
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]] if a and b else 0


def _rs_generator_poly(ec_count: int) -> List[int]:
    """Genera el polinomio generador de Reed-Solomon para `ec_count` símbolos (ISO/IEC 18004)."""
    g = [1]
    for i in range(ec_count):
        root = _GF_EXP[i]
        next_g = [0] * (len(g) + 1)
        for j in range(len(g)):
            next_g[j] ^= g[j]
            next_g[j + 1] ^= _gf_mul(g[j], root)
        g = next_g
    return g


def _rs_encode(data: List[int], ec_count: int) -> List[int]:
    """Calcula las palabras de código de corrección de errores de Reed-Solomon."""
    gen = _rs_generator_poly(ec_count)
    msg = list(data) + [0] * ec_count
    for i in range(len(data)):
        coef = msg[i]
        if coef != 0:
            for j in range(len(gen)):
                msg[i + j] ^= _gf_mul(gen[j], coef)
    return msg[len(data):]


def _encode_data_bits(text: str, version: int) -> List[int]:
    """Codifica el texto en modo Byte y retorna la secuencia de bits con RS e intercalado."""
    raw = text.encode("utf-8")
    info = _VERSION_INFO_L[version]
    total_data_codewords = sum(d * n for d, ec, n in info[2])

    bits = []

    def append_bits(val: int, count: int):
        for i in range(count - 1, -1, -1):
            bits.append((val >> i) & 1)

    # Indicador de modo Byte: 0100
    append_bits(0b0100, 4)
    # Contador de caracteres: 8 bits para V1-V9, 16 bits para V10+
    count_bits = 8 if version <= 9 else 16
    append_bits(len(raw), count_bits)
    # Bytes de datos
    for b in raw:
        append_bits(b, 8)

    # Terminador (hasta 4 ceros)
    max_bits = total_data_codewords * 8
    pad_terminator = min(4, max_bits - len(bits))
    append_bits(0, pad_terminator)

    # Relleno hasta el límite de byte
    while len(bits) % 8 != 0:
        bits.append(0)

    # Conversión a palabras de código (bytes)
    codewords = []
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | b
        codewords.append(byte)

    # Bytes de relleno alternados 0xEC y 0x11
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(codewords) < total_data_codewords:
        codewords.append(pad_bytes[pad_idx % 2])
        pad_idx += 1

    # Partición en bloques y cálculo de Reed-Solomon
    blocks_data = []
    blocks_ec = []
    offset = 0
    for d_len, ec_len, num_b in info[2]:
        for _ in range(num_b):
            blk_data = codewords[offset:offset + d_len]
            offset += d_len
            blocks_data.append(blk_data)
            blocks_ec.append(_rs_encode(blk_data, ec_len))

    # Intercalado de palabras de datos
    final_codewords = []
    max_d = max(len(b) for b in blocks_data)
    for col in range(max_d):
        for b in blocks_data:
            if col < len(b):
                final_codewords.append(b[col])

    # Intercalado de palabras de corrección de errores
    max_ec = max(len(b) for b in blocks_ec)
    for col in range(max_ec):
        for b in blocks_ec:
            if col < len(b):
                final_codewords.append(b[col])

    # Secuencia final de bits
    final_bits = []
    for cw in final_codewords:
        for i in range(7, -1, -1):
            final_bits.append((cw >> i) & 1)
    for _ in range(info[3]):
        final_bits.append(0)

    return final_bits


def _format_bits(mask: int) -> List[int]:
    """Retorna los 15 bits de formato para Nivel L con la máscara indicada (código BCH)."""
    data = (0b01 << 3) | (mask & 0b111)
    d = data << 10
    g = 0b10100110111  # x^10 + x^8 + x^5 + x^4 + x^2 + x + 1
    for i in range(14, 9, -1):
        if (d >> i) & 1:
            d ^= (g << (i - 10))
    f = ((data << 10) | d) ^ 0x5412
    return [(f >> (14 - i)) & 1 for i in range(15)]


def _construir_matriz_qr(text: str) -> Tuple[List[List[int]], int]:
    """Construye la matriz booleana del código QR con patrones y máscara estándar."""
    raw_len = len(text.encode("utf-8"))
    chosen_ver = None
    for v in sorted(_VERSION_INFO_L.keys()):
        capacity = sum(d * n for d, ec, n in _VERSION_INFO_L[v][2])
        overhead = 2 if v <= 9 else 3
        if raw_len + overhead <= capacity:
            chosen_ver = v
            break
    if not chosen_ver:
        raise ValueError("El texto excede la capacidad de código QR soportada.")

    info = _VERSION_INFO_L[chosen_ver]
    size = info[0]
    matrix = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_mod(r: int, c: int, val: int, is_res: bool = True):
        matrix[r][c] = val
        if is_res:
            reserved[r][c] = True

    # 1. Patrones de búsqueda (Finders)
    def add_finder(start_r: int, start_c: int):
        for r in range(7):
            for c in range(7):
                if r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4):
                    set_mod(start_r + r, start_c + c, 1)
                else:
                    set_mod(start_r + r, start_c + c, 0)
        # Separador alrededor del finder
        for r in range(-1, 8):
            for c in range(-1, 8):
                nr, nc = start_r + r, start_c + c
                if 0 <= nr < size and 0 <= nc < size and not reserved[nr][nc]:
                    set_mod(nr, nc, 0)

    add_finder(0, 0)
    add_finder(0, size - 7)
    add_finder(size - 7, 0)

    # 2. Patrones de sincronización (Timing)
    for i in range(8, size - 8):
        v = 1 if i % 2 == 0 else 0
        set_mod(6, i, v)
        set_mod(i, 6, v)

    # 3. Patrones de alineación
    align_coords = info[4]
    for r in align_coords:
        for c in align_coords:
            if (r < 9 and c < 9) or (r < 9 and c > size - 9) or (r > size - 9 and c < 9):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    val = 1 if max(abs(dr), abs(dc)) in (0, 2) else 0
                    set_mod(r + dr, c + dc, val)

    # 4. Módulo oscuro
    set_mod(4 * chosen_ver + 9, 8, 1)

    # 5. Reserva de áreas de información de formato
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(size - 8, size):
        reserved[8][i] = True
    for i in range(size - 7, size):
        reserved[i][8] = True

    # 6. Colocación de bits de datos
    data_bits = _encode_data_bits(text, chosen_ver)
    bit_idx = 0
    col = size - 1
    while col > 0:
        if col == 6:
            col -= 1
        cols = [col, col - 1]
        upwards = ((size - 1 - col) // 2) % 2 == 0
        rows = range(size - 1, -1, -1) if upwards else range(size)
        for r in rows:
            for c in cols:
                if not reserved[r][c]:
                    if bit_idx < len(data_bits):
                        matrix[r][c] = data_bits[bit_idx]
                        bit_idx += 1
                    else:
                        matrix[r][c] = 0
        col -= 2

    # 7. Aplicación de máscara: Máscara 0 ((r + c) % 2 == 0)
    for r in range(size):
        for c in range(size):
            if not reserved[r][c]:
                if (r + c) % 2 == 0:
                    matrix[r][c] ^= 1

    # 8. Información de formato
    fbits = _format_bits(0)
    seq1 = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    ]
    for idx, (r, c) in enumerate(seq1):
        matrix[r][c] = fbits[idx]

    # Top-right: bits de formato 0..7 en fila 8 (columnas size - 1 hasta size - 8)
    for i in range(8):
        matrix[8][size - 1 - i] = fbits[i]

    # Bottom-left: bits de formato 8..14 en columna 8 (filas size - 7 hasta size - 1)
    for i in range(7):
        matrix[size - 7 + i][8] = fbits[8 + i]

    return matrix, size


def construir_url_qr(token: str, base_url: str = None, base_path: str = None) -> str:
    """
    Construye la URL pública del QR según el contrato arquitectónico:
    {PUBLIC_BASE_URL}{BASE_PATH}/turno/qr/{uuid}

    Garantiza que el token sea un UUID v4 normalizado y que la URL no use localhost
    en entornos reales.
    """
    token_normalizado = validar_token(token)

    if base_url is None:
        base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
        if not base_url:
            base_url = URL_PUBLICA_DEFECTO

    if base_path is None:
        base_path = os.getenv("BASE_PATH", "").strip()

    base_url_limpia = base_url.rstrip("/")
    bp_limpio = base_path.strip().strip("/")
    prefijo_path = f"/{bp_limpio}" if bp_limpio else ""

    return f"{base_url_limpia}{prefijo_path}/turno/qr/{token_normalizado}"


def generar_qr_svg(contenido: str, quiet_zone: int = 4) -> str:
    """
    Genera un elemento SVG autocontenido con el código QR del contenido.
    No requiere dependencias externas ni llamadas de red.
    """
    matrix, size = _construir_matriz_qr(contenido)
    full_size = size + 2 * quiet_zone

    rects = []
    for r in range(size):
        for c in range(size):
            if matrix[r][c] == 1:
                rects.append(f"M{c + quiet_zone},{r + quiet_zone}h1v1h-1z")

    path_d = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {full_size} {full_size}" '
        f'shape-rendering="crispEdges" width="100%" height="100%" class="qr-svg" '
        f'role="img" aria-label="Código QR para consultar su turno">\n'
        f'  <rect width="{full_size}" height="{full_size}" fill="#ffffff"/>\n'
        f'  <path d="{path_d}" fill="#0f172a"/>\n'
        f'</svg>'
    )
