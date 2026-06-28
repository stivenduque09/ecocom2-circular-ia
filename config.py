# ====================================================================
# CONFIGURACIÓN CENTRALIZADA — EcoCom2 Circular IA
# ====================================================================

import os
from shapely.geometry import Polygon

# ── PERSISTENCIA ────────────────────────────────────────────────────
REPORTES_FILE = "/tmp/ecocom2_reportes.json"

# ── COORDENADAS Comuna 2 ────────────────────────────────────────────
LAT_C = 6.3104
LON_C = -75.5552

# ── POLÍGONO COMUNA 2 — SANTA CRUZ, MEDELLÍN ──────────────────────
# Verificado con calles reales (imágenes del proyecto)
# Barrios incluidos (11 oficiales):
#   La Rosa · Santa Cruz · Moscú No.1 · Villa Niza · Andalucía
#   Villa del Socorro · La Francia · La Frontera
#   Playón de los Comuneros · Pablo VI · La Isla
# Límites reales:
#   Sur:   La Rosa / Calle 92-95    (lat ≈ 6.296)
#   Norte: Playón — antes de Bello  (lat ≈ 6.317, NO incluye Zamora)
#   Oeste: Carrera 52               (lon ≈ -75.560 a -75.562)
#   Este:  antes de Popular/ladera  (lon ≈ -75.550 a -75.553)
POLIGONO_COMUNA2 = Polygon([
    (-75.5613, 6.2933),  # Sur-occidente (Carrera 52 - Santa Cruz)
    (-75.5608, 6.2965),  # Subiendo por el límite con Castilla
    (-75.5598, 6.3005),
    (-75.5585, 6.3055),
    (-75.5560, 6.3098),  # Norte
    (-75.5540, 6.3100),
    (-75.5500, 6.3032),  # Oriente norte
    (-75.5498, 6.2980),  # Oriente medio
    (-75.5500, 6.2935),  # Moscú
    (-75.5500, 6.2895),  # Suroriente
    (-75.5555, 6.2890),  # Sur
    (-75.5590, 6.2895),
    (-75.5613, 6.2933),  # Cierre
])

# ── BARRIOS DE LA COMUNA 2 ──────────────────────────────────────────
BARRIOS = [
    "La Isla",
    "Playón de los Comuneros",
    "Pablo VI",
    "La Frontera",
    "La Francia",
    "Andalucía",
    "Villa del Socorro",
    "Villa Niza",
    "Moscú No. 1",
    "Santa Cruz",
    "La Rosa",
]

# ── YOLO CONFIGURATION ──────────────────────────────────────────────
YOLO_CONFIDENCE = 0.05  # conf=0.05 detecta más objetos en imágenes de basura real
YOLO_MODEL = "yolov8m.pt"

# ── MATERIALES — CLASIFICACIÓN DE OBJETOS ──────────────────────────
# Formato: "objeto_yolo": ("nombre_es", "material", "peso_kg", "es_reciclable")
MATERIALES = {
    # ── Plástico ──────────────────────────────────────────────────────
    "bottle": ("Botella plástica", "Plástico", 0.05, True),
    "cup": ("Vaso / Recipiente plástico", "Plástico", 0.03, True),
    "chair": ("Silla plástica", "Plástico", 2.00, True),
    "bench": ("Banco plástico", "Plástico", 2.50, True),
    "bucket": ("Balde plástico", "Plástico", 0.50, True),
    "bowl": ("Recipiente plástico", "Plástico", 0.15, True),
    "toy": ("Juguete plástico", "Plástico", 0.50, True),
    "frisbee": ("Disco plástico", "Plástico", 0.10, True),
    # Bolsas de basura — YOLO las detecta como handbag/backpack en baja confianza
    "handbag": ("Bolsa de basura / Bolso", "Plástico", 0.40, True),
    "backpack": ("Bolsa / Mochila", "Textil", 0.50, True),
    "suitcase": ("Bolsa grande / Maleta", "Textil", 1.00, True),
    # ── Papel / Cartón ────────────────────────────────────────────────
    "book": ("Libro / Cuaderno", "Papel", 0.30, True),
    "newspaper": ("Periódico / Papel", "Papel", 0.10, True),
    "box": ("Caja de cartón", "Cartón", 0.30, True),
    # ── Vidrio ────────────────────────────────────────────────────────
    "wine glass": ("Botella / Copa de vidrio", "Vidrio", 0.20, True),
    "vase": ("Frasco / Jarrón de vidrio", "Vidrio", 0.80, True),
    # ── Aluminio / Metal ──────────────────────────────────────────────
    "can": ("Lata de aluminio", "Aluminio", 0.02, True),
    "knife": ("Cuchillo / Utensilio metal", "Metal", 0.10, True),
    "fork": ("Tenedor / Utensilio metal", "Metal", 0.05, True),
    "spoon": ("Cuchara / Utensilio metal", "Metal", 0.05, True),
    "scissors": ("Tijeras", "Metal", 0.10, True),
    # ── Electrónico ───────────────────────────────────────────────────
    "cell phone": ("Celular", "Electrónico", 0.20, True),
    "laptop": ("Portátil", "Electrónico", 2.50, True),
    "keyboard": ("Teclado", "Electrónico", 0.60, True),
    "mouse": ("Ratón de computador", "Electrónico", 0.10, True),
    "remote": ("Control remoto", "Electrónico", 0.20, True),
    "tv": ("Televisor", "Electrónico", 8.00, True),
    "clock": ("Reloj", "Electrónico", 0.30, True),
    # ── Orgánico ──────────────────────────────────────────────────────
    "banana": ("Banano", "Orgánico", 0.10, True),
    "apple": ("Manzana", "Orgánico", 0.15, True),
    "orange": ("Naranja", "Orgánico", 0.20, True),
    "broccoli": ("Brócoli", "Orgánico", 0.25, True),
    "carrot": ("Zanahoria", "Orgánico", 0.10, True),
    "potted plant": ("Planta / Matero", "Orgánico", 1.00, True),
    "pizza": ("Residuo de comida", "Orgánico", 0.30, True),
    "sandwich": ("Residuo de comida", "Orgánico", 0.20, True),
    "hot dog": ("Residuo de comida", "Orgánico", 0.15, True),
    "cake": ("Residuo de comida", "Orgánico", 0.20, True),
    "donut": ("Residuo de comida", "Orgánico", 0.10, True),
    # ── Madera / Mixto ────────────────────────────────────────────────
    "dining table": ("Mesa / Madera", "Madera", 12.00, True),
    "couch": ("Sofá / Mueble", "Mixto", 15.00, True),
    "bed": ("Cama / Colchón", "Mixto", 20.00, True),
    "umbrella": ("Paraguas", "Mixto", 0.50, True),
    "tie": ("Corbata / Textil", "Textil", 0.10, True),
    # ── No aplica / No reciclable ──────────────────────────────────────
    "person": ("Persona", "—", 0, False),
    "dog": ("Perro", "—", 0, False),
    "cat": ("Gato", "—", 0, False),
    "car": ("Vehículo", "—", 0, False),
    "bus": ("Bus", "—", 0, False),
    "truck": ("Camión", "—", 0, False),
    "bicycle": ("Bicicleta", "—", 0, False),
    "motorcycle": ("Moto", "—", 0, False),
    "traffic light": ("Semáforo", "—", 0, False),
    "stop sign": ("Señal tráfico", "—", 0, False),
    "bird": ("Ave", "—", 0, False),
    "toothbrush": ("Cepillo dental", "—", 0, False),
}

# ── ESTADOS DE REPORTES ─────────────────────────────────────────────
ESTADOS = ["🔴 Pendiente", "🟡 En proceso de recolección", "✅ Resuelto"]

# ── CLASIFICACIÓN DE ZONAS ─────────────────────────────────────────
CLASIFICACION_THRESHOLDS = {
    "critico": (0, 0.30),      # <30% reciclable
    "mixto": (0.30, 0.60),      # 30-60% mixto
    "verde": (0.60, 1.01),      # ≥60% reciclables
    "puntual": 2,               # ≤2 residuos
}

# ── MAPA MANUAL PARA CLASIFICACIÓN SIN IA ────────────────────────
MAP_MANUAL = {
    "🏗️ Escombros / Residuos de construcción": (
        "🔴 Punto crítico — Acumulación sin valorización",
        "Escombros",
        5.0,  # peso por unidad
    ),
    "🗑️ Basura doméstica mezclada / bolsas": (
        "🔴 Punto crítico — Acumulación sin valorización",
        "Residuo mixto",
        0.5,
    ),
    "🧹 Residuos orgánicos (comida, vegetación)": (
        "🟡 Punto amarillo — Residuos mixtos",
        "Orgánico",
        0.3,
    ),
    "♻️ Materiales reciclables sin identificar": (
        "🟢 Punto verde — Alta valorización reciclable",
        "Reciclable",
        0.4,
    ),
    "⚠️ Mezcla de varios tipos": (
        "🟡 Punto amarillo — Residuos mixtos",
        "Mixto",
        1.0,
    ),
}

MAP_MANUAL_CRITICO = {
    "🏗️ Escombros / Residuos de construcción": (
        "🔴 Punto crítico — Acumulación sin valorización",
        "Escombros",
        5.0,
    ),
    "🗑️ Basura doméstica mezclada / bolsas": (
        "🔴 Punto crítico — Acumulación sin valorización",
        "Residuo mixto",
        0.8,
    ),
    "🧹 Residuos orgánicos (comida, vegetación)": (
        "🟡 Punto amarillo — Residuos mixtos",
        "Orgánico",
        0.3,
    ),
    "⚠️ Mezcla de varios tipos": (
        "🔴 Punto crítico — Acumulación sin valorización",
        "Mixto",
        1.5,
    ),
}

# ── ADMIN PASSWORD (CAMBIAR EN PRODUCCIÓN) ──────────────────────────
ADMIN_PASSWORD = os.getenv("ECOCOM2_ADMIN_PASSWORD", "ecocom2admin2026")

# ── GEOPY CONFIGURATION ─────────────────────────────────────────────
GEOPY_TIMEOUT = 8
GEOPY_USER_AGENT = "ecocom2_v4"
GEOPY_REVERSE_AGENT = "ecocom2_v4_rev"

# ── VERSIÓN ─────────────────────────────────────────────────────────
VERSION = "4.2"
PROJECT_NAME = "EcoCom2 Circular IA"
DEVELOPER = "Brandon Duque"
INSTITUTION = "ITM Medellín"
