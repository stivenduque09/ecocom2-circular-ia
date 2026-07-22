import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium
from streamlit_folium import st_folium
import pandas as pd
from shapely.geometry import Point, Polygon
import json, os
import sqlite3
import unicodedata
import difflib
from pathlib import Path
from datetime import datetime
import base64
from io import BytesIO

# ====================================================================
# PERSISTENCIA — SQLite en vez de JSON en /tmp
#
# /tmp se borra en cada reinicio en la mayoría de hostings (incluido
# Streamlit Community Cloud), así que los reportes se perdían sin
# aviso. SQLite en una carpeta junto al script sobrevive reinicios
# normales de la app.
#
# ⚠️ Si despliegas en Streamlit Community Cloud (share.streamlit.io):
# el contenedor se reconstruye desde el repo de GitHub en cada redeploy
# o cuando la app "despierta" tras dormir, así que NINGÚN archivo local
# (ni este) sobrevive eso. En ese caso se necesita una base de datos
# externa (Google Sheets o Supabase son las opciones más simples).
# Si es tu caso, avísame y lo conectamos.
#
# Las funciones cargar_reportes_disco() / guardar_reportes_disco()
# mantienen la misma firma que antes, así que el resto del código no
# cambia: sigue trabajando con listas de diccionarios normales.
# ====================================================================
DB_PATH = Path(__file__).resolve().parent / "data" / "ecocom2.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_CAMPOS    = ["Código","Sector","Referencia","Objetos","Peso (Kg)",
              "Predominante","Clasificación","Lat","Lon","Fecha","Estado","FotoB64","Observaciones"]
_COLUMNAS  = ["codigo","sector","referencia","objetos","peso_kg",
              "predominante","clasificacion","lat","lon","fecha","estado","foto_b64","observaciones"]

def _conectar_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _crear_tabla():
    try:
        with _conectar_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reportes (
                    codigo TEXT PRIMARY KEY,
                    sector TEXT,
                    referencia TEXT,
                    objetos INTEGER,
                    peso_kg REAL,
                    predominante TEXT,
                    clasificacion TEXT,
                    lat REAL,
                    lon REAL,
                    fecha TEXT,
                    estado TEXT,
                    foto_b64 TEXT,
                    observaciones TEXT
                )
            """)
            # Migración suave: si la tabla ya existía de una versión anterior
            # sin la columna "observaciones", la agregamos sin perder datos.
            try:
                conn.execute("ALTER TABLE reportes ADD COLUMN observaciones TEXT")
            except Exception:
                pass  # la columna ya existe
    except Exception:
        pass

_crear_tabla()

def cargar_reportes_disco():
    try:
        with _conectar_db() as conn:
            filas = conn.execute("SELECT * FROM reportes ORDER BY fecha ASC").fetchall()
        return [
            {campo: fila[col] for campo, col in zip(_CAMPOS, _COLUMNAS)}
            for fila in filas
        ]
    except Exception:
        return []

def guardar_reportes_disco(reportes):
    """Reescribe toda la tabla con la lista actual (mismo comportamiento
    que el guardado completo del JSON anterior)."""
    try:
        with _conectar_db() as conn:
            conn.execute("DELETE FROM reportes")
            conn.executemany(
                f"INSERT INTO reportes ({','.join(_COLUMNAS)}) "
                f"VALUES ({','.join('?' * len(_COLUMNAS))})",
                [tuple(r.get(campo) for campo in _CAMPOS) for r in reportes]
            )
    except Exception:
        pass

# ====================================================================
# 1. CONFIGURACIÓN
# ====================================================================
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon="♻️", layout="wide")

st.markdown("""
<style>
    /* ── Fondo principal: blanco roto / crema cálido ─────────────── */
    .stApp {
        background-color: #f0fdf4;
        color: #1a2e1a;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    .block-container { padding-top: 1rem; max-width: 1200px; }

    /* Fondo del sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #166534 0%, #15803d 100%) !important;
        border-right: 3px solid #4ade80;
    }

    [data-testid="stSidebar"] * { color: #f0fdf4 !important; }

    [data-testid="stSidebar"] .stRadio label {
        font-size: 15px !important; font-weight: 600 !important;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
        background: rgba(255,255,255,0.10) !important;
        border-radius: 8px !important; padding: 8px 12px !important;
        margin: 3px 0 !important; transition: background 0.2s !important;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
        background: rgba(255,255,255,0.22) !important;
    }

    [data-testid="stSidebar"] .badge-ok {
        background: #14532d !important;
        border: 2px solid #4ade80 !important;
        border-radius: 10px !important; padding: 10px 14px !important;
    }
    [data-testid="stSidebar"] .badge-warn {
        background: #451a03 !important;
        border: 2px solid #f59e0b !important;
        border-radius: 10px !important; padding: 10px 14px !important;
    }
    [data-testid="stSidebar"] .badge-err {
        background: #450a0a !important;
        border: 2px solid #f87171 !important;
        border-radius: 10px !important; padding: 10px 14px !important;
    }

    [data-testid="stSidebar"] details {
        background: rgba(0, 40, 20, 0.70) !important;
        border: 1px solid rgba(74,222,128,0.45) !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] details > summary {
        background: rgba(0, 50, 25, 0.50) !important;
        border-radius: 8px !important;
        padding: 8px 12px !important;
        font-weight: 600 !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebar"] details[open] > summary {
        border-radius: 8px 8px 0 0 !important;
        border-bottom: 1px solid rgba(74,222,128,0.25) !important;
    }
    [data-testid="stSidebar"] details > div {
        background: rgba(0, 40, 20, 0.55) !important;
        border-radius: 0 0 8px 8px !important;
        padding: 8px 6px !important;
    }

    [data-testid="stSidebar"] input[type="text"],
    [data-testid="stSidebar"] input[type="password"],
    [data-testid="stSidebar"] input {
        background: #f0fdf4 !important;
        color: #14532d !important;
        border: 1px solid #4ade80 !important;
        border-radius: 6px !important;
    }

    [data-testid="stSidebar"] .ecocom2-footer {
        background: rgba(0, 30, 15, 0.55) !important;
        border: 1px solid rgba(74,222,128,0.35) !important;
        border-radius: 6px !important;
    }

    h1 { color: #166534 !important; font-size: 2rem !important; font-weight: 800 !important; }
    h2 { color: #15803d !important; font-weight: 700 !important; }
    h3 { color: #16a34a !important; font-weight: 600 !important; }

    header { 
        background-color: transparent !important; 
            }
    .badge-ok {
        background: #dcfce7; border: 2px solid #16a34a;
        border-radius: 10px; padding: 12px 16px;
        color: #14532d; font-weight: 700; font-size: 14px;
        box-shadow: 0 2px 8px rgba(22,163,74,0.15);
    }
    .badge-warn {
        background: #fefce8; border: 2px solid #ca8a04;
        border-radius: 10px; padding: 12px 16px;
        color: #713f12; font-weight: 700; font-size: 14px;
        box-shadow: 0 2px 8px rgba(202,138,4,0.15);
    }
    .badge-err {
        background: #fef2f2; border: 2px solid #dc2626;
        border-radius: 10px; padding: 12px 16px;
        color: #7f1d1d; font-weight: 700; font-size: 14px;
        box-shadow: 0 2px 8px rgba(220,38,38,0.15);
    }

    .metric-card {
        background: #ffffff;
        border: 2px solid #bbf7d0;
        border-radius: 14px; padding: 18px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(22,163,74,0.10);
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-card h2, .metric-card h3 { margin: 0 0 4px 0 !important; }
    .metric-card p { color: #4b5563 !important; font-size: 13px !important; margin: 0; }

    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg, #16a34a, #15803d) !important;
        color: white !important; border: none !important;
        font-weight: 700 !important; font-size: 15px !important;
        border-radius: 10px !important; padding: 10px 20px !important;
        box-shadow: 0 4px 12px rgba(22,163,74,0.35) !important;
        transition: all 0.2s !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 16px rgba(22,163,74,0.45) !important;
    }

    div[data-testid="stButton"] button[kind="secondary"] {
        background: #ffffff !important; color: #166534 !important;
        border: 2px solid #16a34a !important;
        font-weight: 600 !important; border-radius: 10px !important;
    }

    div[data-testid="stTextInput"] input {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; font-size: 15px !important;
        background: #ffffff !important; color: #1a2e1a !important;
        padding: 10px 14px !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #16a34a !important;
        box-shadow: 0 0 0 3px rgba(22,163,74,0.15) !important;
    }

    /* ── Text area (Observaciones): antes heredaba tema oscuro y el
       texto escrito quedaba invisible (negro sobre negro) ─────────── */
    div[data-testid="stTextArea"] textarea {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; font-size: 15px !important;
        background: #ffffff !important; color: #14532d !important;
        padding: 10px 14px !important;
    }
    div[data-testid="stTextArea"] textarea::placeholder {
        color: #9ca3af !important;
    }
    div[data-testid="stTextArea"] textarea:focus {
        border-color: #16a34a !important;
        box-shadow: 0 0 0 3px rgba(22,163,74,0.15) !important;
    }

    /* ── Input auxiliar oculto que recibe lat,lon desde el botón de GPS.
       No se muestra al usuario — solo transporta el dato del navegador
       (JS) hacia Streamlit (Python) reusando un widget normal. ────── */
    input[placeholder="GPS_HIDDEN_INPUT"] {
        position: absolute !important;
        width: 1px !important; height: 1px !important;
        opacity: 0 !important; pointer-events: none !important;
    }
    div:has(> div > div > input[placeholder="GPS_HIDDEN_INPUT"]) {
        max-height: 0 !important; margin: 0 !important; padding: 0 !important;
        overflow: hidden !important;
    }
    /* Etiquetas de los campos (antes casi invisibles sobre fondo claro) */
    div[data-testid="stTextInput"] label,
    div[data-testid="stTextArea"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stFileUploader"] label {
        color: #14532d !important;
        font-weight: 600 !important;
    }

    /* Captions (ej. "📍 Detectado automáticamente...") — heredaban un
       gris muy claro casi invisible sobre el fondo crema de la app ─── */
    div[data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p,
    .stApp small {
        color: #4b5563 !important;
        opacity: 1 !important;
    }

    div[data-testid="stSelectbox"] > div > div {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; background: #ffffff !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        background: #dcfce7; border-radius: 10px; padding: 4px;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent; border-radius: 8px;
        color: #166534 !important; font-weight: 600;
        padding: 8px 14px;
    }
    .stTabs [aria-selected="true"] {
        background: #16a34a !important; color: white !important;
        border-radius: 8px;
    }

    div[data-testid="stExpander"] {
        border: 1px solid #bbf7d0 !important;
        border-radius: 10px !important;
        background: #ffffff !important;
        margin-bottom: 8px !important;
    }

    div[data-testid="stDataFrameContainer"] {
        border: 2px solid #bbf7d0;
        border-radius: 10px; overflow: hidden;
    }

    div[data-testid="stInfo"] {
        background: #eff6ff !important; border-left: 4px solid #3b82f6 !important;
        color: #1e3a5f !important; border-radius: 8px !important;
    }
    div[data-testid="stWarning"] {
        background: #fefce8 !important; border-left: 4px solid #f59e0b !important;
        color: #713f12 !important; border-radius: 8px !important;
    }
    div[data-testid="stSuccess"] {
        background: #f0fdf4 !important; border-left: 4px solid #16a34a !important;
        color: #14532d !important; border-radius: 8px !important;
    }
    div[data-testid="stError"] {
        background: #fef2f2 !important; border-left: 4px solid #dc2626 !important;
        color: #7f1d1d !important; border-radius: 8px !important;
    }

    div[data-testid="stFileUploader"] {
        background: #f0fdf4 !important; border: 2px dashed #4ade80 !important;
        border-radius: 12px !important; padding: 16px !important;
    }

.chat-burbuja-bot {
    background: #99FFFF !important;
    color: #064e3b !important;
    border: 2px solid #4ade80 !important;
    border-radius: 12px !important;
    padding: 12px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    margin-bottom: 10px !important;
}

.chat-burbuja-user {
    background: #e2e8f0 !important;
    color: #1e293b !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 12px !important;
    padding: 12px !important;
    margin-bottom: 10px !important;
    text-align: right !important;
}

.chat-container{
    background: #ffffff !important;
    border: 2px solid #86efac !important;
    border-radius: 12px !important;
    padding: 12px !important;
}

.chat-container *{
    color:#14532d !important;
}

.chat-container textarea,
.chat-container input{
    background:#ffffff !important;
    color:#14532d !important;
    border:2px solid #86efac !important;
}

.chat-container textarea::placeholder,
.chat-container input::placeholder{
    color:#6b7280 !important;
}

[data-testid="stSidebar"] .stButton button {
    background-color: #ffffff !important;
    border: 2px solid #86efac !important;
    border-radius: 8px !important;
}

[data-testid="stSidebar"] .stButton button p {
    color: #14532d !important;
    font-weight: 500 !important;
}

[data-testid="stSidebar"] .stButton button:hover {
    background-color: #f0fdf4 !important;
    border-color: #16a34a !important;
}
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO COMUNA 2 — SANTA CRUZ, MEDELLÍN
#    Desde Estación Acevedo (sur) → Andalucía → Comuneros → Santa Cruz
#    → Villa del Socorro (norte). Límite oeste = Autopista Norte.
# ====================================================================
# ============================================================
# Polígono COMUNA 2 — SANTA CRUZ, Medellín
# Verificado con calles reales (imágenes del proyecto)
#
# Barrios incluidos (11 oficiales):
#   La Rosa · Santa Cruz · Moscú No.1 · Villa Niza · Andalucía
#   Villa del Socorro · La Francia · La Frontera
#   Playón de los Comuneros · Pablo VI · La Isla
#
# Límites reales:
#   Sur:   La Rosa / Calle 92-95    (lat ≈ 6.296)
#   Norte: Playón — antes de Bello  (lat ≈ 6.317, NO incluye Zamora)
#   Oeste: Carrera 52               (lon ≈ -75.560 a -75.562)
#   Este:  antes de Popular/ladera  (lon ≈ -75.550 a -75.553)
#          Santo Domingo y Popular  quedan FUERA (son otra comuna)
# ============================================================
POLIGONO_COMUNA2 = Polygon([

    # Sur-occidente (Carrera 52 - Santa Cruz)

    (-75.5613, 6.2933),

    # Subiendo por el límite con Castilla

    (-75.5608, 6.2965),

    (-75.5598, 6.3005),

    (-75.5585, 6.3055),

    # Norte

    (-75.5560, 6.3098),

    (-75.5540, 6.3100),

    # Oriente norte

    (-75.5500, 6.3032),

    # Oriente medio

    (-75.5498, 6.2980),

    # Moscú

    (-75.5500, 6.2935),

    # Suroriente

    (-75.5500, 6.2895),

    # Sur

    (-75.5555, 6.2890),

    (-75.5590, 6.2895),

    # Cierre

    (-75.5613, 6.2933)

])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

# Centro de la Comuna 2
LAT_C = 6.3104
LON_C = -75.5552

# ====================================================================
# 3. SESIÓN
# ====================================================================
for k, v in {
    "lat": None, "lon": None, "validado": False, "fuera": True,
    "direccion": "", "reporte_ok": False, "cache": None,
    "seccion": "info",   # "info" | "residuo" | "critico" | "historial"
    "click_barrio": None,   # barrio adivinado del último punto tocado en el mapa
    "mis_codigos": [],      # códigos de reportes publicados en ESTA sesión de navegador
    "gps_procesado": None,  # última lectura de GPS ya procesada (evita loops)
    "gps_lat": None, "gps_lon": None,   # última posición GPS real del dispositivo
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()

# Recordar cuántos de "mis" reportes ya estaban Resueltos la última vez
# que el ciudadano vio su historial — así podemos avisarle solo de los
# CAMBIOS nuevos (cierre de ciclo), no repetir el mismo aviso siempre.
if "mis_estados_vistos" not in st.session_state:
    st.session_state.mis_estados_vistos = {}

# ====================================================================
# 4. MODELO YOLO — conf 0.05 para detectar más objetos en basura real
# ====================================================================
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")
modelo = cargar_modelo()

# ====================================================================
# 5. MATERIALES — incluye bolsas de basura y más residuos reales
# ====================================================================
MAT = {
    # ── Plástico ──────────────────────────────────────────────────────
    "bottle":         ("Botella plástica",         "Plástico",    0.05, True),
    "cup":            ("Vaso / Recipiente plástico","Plástico",    0.03, True),
    "chair":          ("Silla plástica",            "Plástico",    2.00, True),
    "bench":          ("Banco plástico",            "Plástico",    2.50, True),
    "bucket":         ("Balde plástico",            "Plástico",    0.50, True),
    "bowl":           ("Recipiente plástico",       "Plástico",    0.15, True),
    "toy":            ("Juguete plástico",          "Plástico",    0.50, True),
    "frisbee":        ("Disco plástico",            "Plástico",    0.10, True),
    # Bolsas de basura — YOLO las detecta como handbag/backpack en baja confianza
    "handbag":        ("Bolsa de basura / Bolso",   "Plástico",    0.40, True),
    "backpack":       ("Bolsa / Mochila",           "Textil",      0.50, True),
    "suitcase":       ("Bolsa grande / Maleta",     "Textil",      1.00, True),
    # ── Papel / Cartón ────────────────────────────────────────────────
    "book":           ("Libro / Cuaderno",          "Papel",       0.30, True),
    "newspaper":      ("Periódico / Papel",         "Papel",       0.10, True),
    "box":            ("Caja de cartón",            "Cartón",      0.30, True),
    # ── Vidrio ────────────────────────────────────────────────────────
    "wine glass":     ("Botella / Copa de vidrio",  "Vidrio",      0.20, True),
    "vase":           ("Frasco / Jarrón de vidrio", "Vidrio",      0.80, True),
    # ── Aluminio / Metal ──────────────────────────────────────────────
    "can":            ("Lata de aluminio",          "Aluminio",    0.02, True),
    "knife":          ("Cuchillo / Utensilio metal","Metal",       0.10, True),
    "fork":           ("Tenedor / Utensilio metal", "Metal",       0.05, True),
    "spoon":          ("Cuchara / Utensilio metal", "Metal",       0.05, True),
    "scissors":       ("Tijeras",                   "Metal",       0.10, True),
    # ── Electrónico ───────────────────────────────────────────────────
    "cell phone":     ("Celular",                   "Electrónico", 0.20, True),
    "laptop":         ("Portátil",                  "Electrónico", 2.50, True),
    "keyboard":       ("Teclado",                   "Electrónico", 0.60, True),
    "mouse":          ("Ratón de computador",       "Electrónico", 0.10, True),
    "remote":         ("Control remoto",            "Electrónico", 0.20, True),
    "tv":             ("Televisor",                 "Electrónico", 8.00, True),
    "clock":          ("Reloj",                     "Electrónico", 0.30, True),
    # ── Orgánico ──────────────────────────────────────────────────────
    "banana":         ("Banano",                    "Orgánico",    0.10, True),
    "apple":          ("Manzana",                   "Orgánico",    0.15, True),
    "orange":         ("Naranja",                   "Orgánico",    0.20, True),
    "broccoli":       ("Brócoli",                   "Orgánico",    0.25, True),
    "carrot":         ("Zanahoria",                 "Orgánico",    0.10, True),
    "potted plant":   ("Planta / Matero",           "Orgánico",    1.00, True),
    "pizza":          ("Residuo de comida",         "Orgánico",    0.30, True),
    "sandwich":       ("Residuo de comida",         "Orgánico",    0.20, True),
    "hot dog":        ("Residuo de comida",         "Orgánico",    0.15, True),
    "cake":           ("Residuo de comida",         "Orgánico",    0.20, True),
    "donut":          ("Residuo de comida",         "Orgánico",    0.10, True),
    # ── Madera / Mixto ────────────────────────────────────────────────
    "dining table":   ("Mesa / Madera",             "Madera",     12.00, True),
    "couch":          ("Sofá / Mueble",             "Mixto",      15.00, True),
    "bed":            ("Cama / Colchón",            "Mixto",      20.00, True),
    "umbrella":       ("Paraguas",                  "Mixto",       0.50, True),
    "tie":            ("Corbata / Textil",          "Textil",      0.10, True),
    # ── No aplica / No reciclable ──────────────────────────────────────
    "person":         ("Persona",     "—", 0, False),
    "dog":            ("Perro",       "—", 0, False),
    "cat":            ("Gato",        "—", 0, False),
    "car":            ("Vehículo",    "—", 0, False),
    "bus":            ("Bus",         "—", 0, False),
    "truck":          ("Camión",      "—", 0, False),
    "bicycle":        ("Bicicleta",   "—", 0, False),
    "motorcycle":     ("Moto",        "—", 0, False),
    "traffic light":  ("Semáforo",    "—", 0, False),
    "stop sign":      ("Señal tráfico","—",0, False),
    "bird":           ("Ave",         "—", 0, False),
    "toothbrush":     ("Cepillo dental","—",0, False),
}

# ====================================================================
# 6. HELPERS
# ====================================================================
@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar(direccion: str):
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4", timeout=8)
        r = geo.geocode(f"{direccion}, Medellín, Antioquia, Colombia")
        if r:
            return r.latitude, r.longitude, r.address
    except Exception:
        pass
    return None, None, None


def _normalizar_txt(txt: str) -> str:
    """Quita tildes/mayúsculas para comparar nombres de barrio sin ruido."""
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode("ascii")
    return txt.lower().strip()


def adivinar_barrio(texto_nominatim: str):
    """Intenta emparejar el barrio que devuelve Nominatim con la lista
    oficial de BARRIOS. Primero por substring (ej. 'Moscú' → 'Moscú No. 1'),
    y si no, por similitud aproximada. Devuelve None si no hay match confiable."""
    if not texto_nominatim:
        return None
    objetivo = _normalizar_txt(texto_nominatim)
    for b in BARRIOS:
        nb = _normalizar_txt(b)
        if nb in objetivo or objetivo in nb:
            return b
    normalizados = {_normalizar_txt(b): b for b in BARRIOS}
    match = difflib.get_close_matches(objetivo, normalizados.keys(), n=1, cutoff=0.6)
    return normalizados[match[0]] if match else None


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar_inversa(lat: float, lon: float):
    """Devuelve (direccion_legible, barrio_adivinado_o_None)."""
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4_rev", timeout=6)
        r = geo.reverse(f"{lat}, {lon}", language="es")
        if r and r.raw.get("address"):
            a = r.raw["address"]
            partes = []
            calle  = a.get("road") or a.get("pedestrian") or a.get("path") or ""
            num    = a.get("house_number", "")
            barrio_raw = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
            if calle:
                partes.append(calle + (f" #{num}" if num else ""))
            if barrio_raw:
                partes.append(barrio_raw)
            partes.append("Medellín")
            direccion = ", ".join(partes) if partes else r.address
            return direccion, adivinar_barrio(barrio_raw)
        return f"{lat:.5f}, {lon:.5f}", None
    except Exception:
        return f"{lat:.5f}, {lon:.5f}", None


def img_a_b64(img_pil, max_px=200) -> str:
    """Convierte una imagen PIL a base64 JPEG thumbnail para el popup del mapa."""
    try:
        thumb = img_pil.copy()
        thumb.thumbnail((max_px, max_px))
        buf = BytesIO()
        thumb.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def es_residente():
    return st.session_state.validado and not st.session_state.fuera


def set_ubicacion(lat, lon, direccion=""):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.validado = True
    st.session_state.fuera = not POLIGONO_COMUNA2.contains(Point(lon, lat))
    st.session_state.direccion = direccion


def analizar(img, imgsz=640):
    """Ejecuta YOLOv8 sobre la imagen.
    imgsz: resolución de inferencia. Más alto = detecta mejor objetos
    pequeños/lejanos (útil en fotos de Punto Crítico, que suelen abarcar
    más área que una foto de un solo residuo), a costa de más tiempo de
    cómputo. Debe ser múltiplo de 32 (640, 960, 1280...).
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            img.save(tmp.name)
            tmp_path = tmp.name
        return modelo(tmp_path, conf=0.15, imgsz=imgsz)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _iou(caja_a, caja_b):
    """Intersección sobre unión entre dos cajas [x1,y1,x2,y2]."""
    xa1, ya1, xa2, ya2 = caja_a
    xb1, yb1, xb2, yb2 = caja_b
    ix1, iy1 = max(xa1, xb1), max(ya1, yb1)
    ix2, iy2 = min(xa2, xb2), min(ya2, yb2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _deduplicar_detecciones(objetos, iou_umbral=0.55):
    """Evita doble conteo entre clases distintas con cajas muy solapadas."""
    ordenados = sorted(objetos, key=lambda o: o[1], reverse=True)
    conservados = []
    for nombre, conf, caja in ordenados:
        if any(_iou(caja, c[2]) >= iou_umbral for c in conservados):
            continue
        conservados.append((nombre, conf, caja))
    return conservados


def procesar(resultados):
    """
    Clasifica la escena según ratio de reciclables:
    🟢 Verde      ≥60% reciclables  → alta valorización
    🟡 Amarillo   30-60% mixto      → mezcla
    🔴 Rojo       <30% reciclables  → acumulación sin valor (como la foto de basura)
    """
    objetos = []
    for r in resultados:
        for box in r.boxes:
            nombre = modelo.names[int(box.cls[0])]
            conf   = float(box.conf[0])
            caja   = box.xyxy[0].tolist()
            objetos.append((nombre, conf, caja))

    if not objetos:
        return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados", 0

    UMBRAL_CONF_CLASE_DESCONOCIDA = 0.40
    objetos = [
        (nombre, conf, caja) for nombre, conf, caja in objetos
        if nombre in MAT or conf >= UMBRAL_CONF_CLASE_DESCONOCIDA
    ]

    if not objetos:
        return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados", 0

    objetos = _deduplicar_detecciones(objetos)

    conteo = Counter(o[0] for o in objetos)
    mejor  = {n: max(c for nn, c, _ in objetos if nn == n) for n in conteo}

    tabla, peso_total, residuos, no_rec = [], 0.0, 0, 0
    cnt_mat = Counter()

    for obj, cant in conteo.items():
        nom, mat, peso_u, recicl = MAT.get(obj, (obj.replace("_"," ").title(), "Desconocido", 0.1, False))
        conf = f"{mejor[obj]*100:.0f}%"
        if recicl:
            residuos += cant
            p = round(peso_u * cant, 2)
            peso_total += p
            cnt_mat[mat] += cant
            tabla.append({"Objeto": nom, "Material": mat,
                          "Cant.": cant, "Peso (kg)": p,
                          "Confianza": conf, "♻️": "✅ Sí"})
        else:
            no_rec += cant
            tabla.append({"Objeto": nom, "Material": "—",
                          "Cant.": cant, "Peso (kg)": 0,
                          "Confianza": conf, "♻️": "❌ No"})

    tipo  = cnt_mat.most_common(1)[0][0] if cnt_mat else "Mixto"
    total = residuos + no_rec
    ratio = residuos / total if total > 0 else 0

    ESCALA_ALERTA_OBJ, ESCALA_CRITICA_OBJ = 15, 30      # cant. de objetos
    PESO_ALERTA_KG,    PESO_CRITICA_KG    = 20.0, 50.0   # kg estimados
    gran_volumen    = residuos >= ESCALA_ALERTA_OBJ  or peso_total >= PESO_ALERTA_KG
    volumen_critico = residuos >= ESCALA_CRITICA_OBJ or peso_total >= PESO_CRITICA_KG

    if volumen_critico:
        nivel = "🔴 Punto crítico — Gran acumulación, recolección urgente"
    elif total <= 2 and ratio >= 0.5:
        nivel = "🟢 Residuo puntual"
    elif ratio < 0.30:
        nivel = "🔴 Punto crítico — Acumulación sin valorización"
    elif gran_volumen:
        nivel = "🟡 Punto amarillo — Buen material, pero gran volumen"
    elif ratio >= 0.60:
        nivel = "🟢 Punto verde — Alta valorización reciclable"
    else:
        nivel = "🟡 Punto amarillo — Residuos mixtos"

    return tabla, residuos, round(peso_total, 2), tipo, nivel, total


def badge(txt, tipo="ok"):
    cls = {"ok":"badge-ok","warn":"badge-warn","err":"badge-err"}[tipo]
    st.markdown(f'<div class="{cls}">{txt}</div><br>', unsafe_allow_html=True)


def progreso_pasos(paso_actual: int, labels=None):
    """Indicador horizontal 'Paso X de N' para el flujo de reportar."""
    labels = labels or ["Dirección", "Punto en mapa", "Foto", "Publicar"]
    total = len(labels)
    cols = st.columns(total)
    for i, (col, label) in enumerate(zip(cols, labels), start=1):
        with col:
            if i < paso_actual:
                st.markdown(
                    f'<div style="text-align:center;color:#16a34a;font-weight:700;'
                    f'font-size:12px;padding:4px 2px;border-bottom:3px solid #16a34a;">'
                    f'✅ {label}</div>', unsafe_allow_html=True)
            elif i == paso_actual:
                st.markdown(
                    f'<div style="text-align:center;color:#16a34a;font-weight:700;'
                    f'font-size:12px;padding:4px 2px;border-bottom:3px solid #4ade80;">'
                    f'🟢 {label}</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="text-align:center;color:#9ca3af;font-weight:500;'
                    f'font-size:12px;padding:4px 2px;border-bottom:3px solid #e5e7eb;">'
                    f'⚪ {label}</div>', unsafe_allow_html=True)


def metricas(residuos, peso, nivel):
    c1, c2, c3 = st.columns(3)
    color = "#4ade80" if "🟢" in nivel else ("#fbbf24" if "🟡" in nivel else "#f87171")
    with c1:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color}">{residuos}</h3>'
                    f'<p style="margin:0;font-size:12px">Reciclables</p></div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color}">{peso} kg</h3>'
                    f'<p style="margin:0;font-size:12px">Peso estimado</p></div>',
                    unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color};font-size:14px">'
                    f'{nivel}</h3><p style="margin:0;font-size:12px">Clasificación</p></div>',
                    unsafe_allow_html=True)


def _widget_dictado(placeholder_substr: str, key_html: str):
    """Botón de '🎤 Dictar' que usa el reconocimiento de voz nativo del
    navegador (Web Speech API) para llenar el campo de Observaciones
    hablando en vez de escribiendo.

    Cómo funciona:
    - No sube audio a ningún servidor: todo el reconocimiento ocurre
      en el navegador (Chrome / Edge en Android, PC y la mayoría de
      celulares Android). Safari / iOS y Firefox NO lo soportan todavía.
    - Al terminar de hablar, el texto reconocido se escribe directo en
      el campo de Observaciones correspondiente (se identifica por su
      placeholder, que es único para cada campo).
    - Es un truco: como el widget vive en un iframe de Streamlit,
      accedemos al documento del padre (window.parent.document) para
      encontrar el textarea real y disparamos un evento 'input' para
      que Streamlit detecte el cambio como si el usuario hubiera escrito.
    """
    import streamlit.components.v1 as components
    placeholder_js = placeholder_substr.replace("'", "\\'")
    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;">
      <button id="btn_{key_html}" type="button" style="
          background:linear-gradient(135deg,#16a34a,#15803d);
          color:white;border:none;border-radius:8px;
          padding:8px 16px;font-weight:700;font-size:13px;
          cursor:pointer;display:inline-flex;align-items:center;gap:6px;">
        🎤 Dictar observación por voz
      </button>
      <span id="estado_{key_html}" style="font-size:12px;color:#6b7280;margin-left:8px;"></span>
      <script>
        (function() {{
          const btn = document.getElementById("btn_{key_html}");
          const estado = document.getElementById("estado_{key_html}");
          const SR = window.webkitSpeechRecognition || window.SpeechRecognition;
          if (!SR) {{
            estado.innerText = "⚠️ Tu navegador no soporta dictado por voz (usa Chrome/Edge)";
            btn.disabled = true;
            btn.style.opacity = "0.5";
            return;
          }}
          btn.addEventListener("click", function() {{
            const recognition = new SR();
            recognition.lang = "es-CO";
            recognition.interimResults = false;
            recognition.maxAlternatives = 1;
            estado.innerText = "🔴 Escuchando... habla ahora";
            btn.disabled = true;
            recognition.start();

            recognition.onresult = function(event) {{
              const texto = event.results[0][0].transcript;
              try {{
                const areas = window.parent.document.querySelectorAll('textarea');
                let encontrado = false;
                for (const ta of areas) {{
                  if (ta.placeholder && ta.placeholder.includes('{placeholder_js}')) {{
                    const setter = Object.getOwnPropertyDescriptor(
                      window.parent.HTMLTextAreaElement.prototype, 'value').set;
                    const previo = ta.value ? ta.value + " " : "";
                    setter.call(ta, previo + texto);
                    ta.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    encontrado = true;
                    break;
                  }}
                }}
                estado.innerText = encontrado
                  ? "✅ Texto agregado: \\"" + texto + "\\""
                  : "⚠️ No encontré el campo — copia el texto manualmente: " + texto;
              }} catch (e) {{
                estado.innerText = "✅ Reconocido: \\"" + texto + "\\" (cópialo en el campo)";
              }}
            }};
            recognition.onerror = function(event) {{
              estado.innerText = "⚠️ No se pudo escuchar (" + event.error + "). Intenta de nuevo.";
            }};
            recognition.onend = function() {{
              btn.disabled = false;
            }};
          }});
        }})();
      </script>
    </div>
    """
    components.html(html, height=45)


def _widget_gps(key_html: str = "gps"):
    """Botón '📍 Usar mi ubicación GPS' que pide la posición real del
    dispositivo al navegador (navigator.geolocation) y la entrega a
    Streamlit escribiéndola en un input oculto (mismo truco que el
    dictado por voz: encontrar el elemento por su placeholder único,
    fijar el valor con el setter nativo y disparar 'input' + 'blur'
    para que Streamlit detecte el cambio y vuelva a ejecutar el script).

    Requiere permiso de ubicación del navegador (aparece un popup la
    primera vez). Solo funciona sobre HTTPS (o localhost).
    """
    import streamlit.components.v1 as components
    html = f"""
    <div style="font-family:'Segoe UI',Arial,sans-serif;">
      <button id="btn_{key_html}" type="button" style="
          background:linear-gradient(135deg,#16a34a,#15803d);
          color:white;border:none;border-radius:8px;
          padding:8px 16px;font-weight:700;font-size:13px;
          cursor:pointer;display:inline-flex;align-items:center;gap:6px;">
        📍 Usar mi ubicación GPS
      </button>
      <span id="estado_{key_html}" style="font-size:12px;color:#6b7280;margin-left:8px;"></span>
      <script>
        (function() {{
          const btn = document.getElementById("btn_{key_html}");
          const estado = document.getElementById("estado_{key_html}");
          if (!navigator.geolocation) {{
            estado.innerText = "⚠️ Tu navegador no soporta geolocalización";
            btn.disabled = true;
            btn.style.opacity = "0.5";
            return;
          }}
          btn.addEventListener("click", function() {{
            estado.innerText = "📡 Obteniendo tu ubicación...";
            btn.disabled = true;
            navigator.geolocation.getCurrentPosition(
              function(pos) {{
                const lat = pos.coords.latitude;
                const lon = pos.coords.longitude;
                const valor = lat + "," + lon;
                try {{
                  const inputs = window.parent.document.querySelectorAll('input');
                  let encontrado = false;
                  for (const inp of inputs) {{
                    if (inp.placeholder === 'GPS_HIDDEN_INPUT') {{
                      const setter = Object.getOwnPropertyDescriptor(
                        window.parent.HTMLInputElement.prototype, 'value').set;
                      setter.call(inp, valor);
                      inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                      inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                      inp.blur();
                      encontrado = true;
                      break;
                    }}
                  }}
                  estado.innerText = encontrado
                    ? "✅ Ubicación detectada, verificando..."
                    : "⚠️ No se pudo comunicar con la app.";
                }} catch (e) {{
                  estado.innerText = "⚠️ Error al enviar la ubicación.";
                }}
                btn.disabled = false;
              }},
              function(err) {{
                let msg = "⚠️ No pudimos obtener tu ubicación.";
                if (err.code === 1) msg = "⚠️ Permiso de ubicación denegado.";
                if (err.code === 2) msg = "⚠️ Ubicación no disponible.";
                if (err.code === 3) msg = "⚠️ Se agotó el tiempo de espera.";
                estado.innerText = msg + " Busca tu dirección manualmente.";
                btn.disabled = false;
              }},
              {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }}
            );
          }});
        }})();
      </script>
    </div>
    """
    components.html(html, height=45)


def nav_tabs(seccion_actual):
    """Barra de navegación como pestañas usando botones — funciona en celular."""
    SECCIONES = [
        ("info",      "📍 Info del punto"),
        ("residuo",   "📸 Reportar Residuo"),
        ("critico",   "🚨 Punto Crítico"),
        ("historial", "📋 Historial"),
    ]
    cols = st.columns(len(SECCIONES))
    for col, (key, label) in zip(cols, SECCIONES):
        with col:
            es_activa = seccion_actual == key
            btn_type = "primary" if es_activa else "secondary"
            if st.button(label, key=f"nav_{key}",
                         use_container_width=True, type=btn_type):
                st.session_state.seccion = key
                st.rerun()

# ====================================================================
# 7. BARRA LATERAL
# ====================================================================
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## ♻️ EcoCom2")

if st.session_state.validado:
    if not st.session_state.fuera:
        st.sidebar.markdown(
            f'<div class="badge-ok" style="font-size:12px;">✅ Dentro de la Comuna 2<br>'
            f'<span style="font-weight:normal">{st.session_state.direccion[:55]}</span></div>',
            unsafe_allow_html=True)
    else:
        st.sidebar.markdown(
            '<div class="badge-err" style="font-size:12px;">🛑 Fuera de la Comuna 2<br>'
            '<span style="font-weight:normal">Solo lectura del mapa</span></div>',
            unsafe_allow_html=True)
else:
    st.sidebar.markdown(
        '<div class="badge-warn" style="font-size:12px;">⚠️ Sin verificar<br>'
        '<span style="font-weight:normal">Ingresa tu dirección abajo</span></div>',
        unsafe_allow_html=True)

st.sidebar.markdown("---")

PAGINAS = ["🏠 Inicio y Mapa", "📊 Comuna en Cifras", "🛡️ Panel Admin", "ℹ️ Información"]
menu = st.sidebar.radio("Menú", PAGINAS)

st.sidebar.markdown("---")
es_admin = st.session_state.get("admin_ok", False)

if not es_admin:
    with st.sidebar.expander("🔐 Acceso Administrador"):
        pwd = st.text_input("Contraseña:", type="password", key="adm_pwd",
                            placeholder="Ingresa la contraseña")
        if st.button("Ingresar", key="adm_login", type="primary",
                     use_container_width=True):
            if pwd == "ecocom2admin2026":
                st.session_state.admin_ok = True
                st.success("✅ Sesión iniciada")
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta")
else:
    st.sidebar.markdown(
        '<div class="badge-ok" style="font-size:12px;margin-bottom:6px;">'
        '🛡️ Admin activo<br>'
        '<span style="font-weight:normal">Brandon Duque · ITM</span></div>',
        unsafe_allow_html=True)
    if st.sidebar.button("🔓 Cerrar sesión", key="adm_logout",
                         use_container_width=True):
        st.session_state.admin_ok = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div class="ecocom2-footer" style="font-size:11px;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#16a34a">EcoCom2 v5.0</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#16a34a">Brandon Duque</b>
</div>""", unsafe_allow_html=True)

# ====================================================================
# 8. INICIO Y MAPA
# ====================================================================
if menu == "🏠 Inicio y Mapa":
    st.title("♻️ EcoCom2 Circular IA")
    st.caption("Gestión inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    if "agente_msgs" not in st.session_state:
        st.session_state.agente_msgs = [
            {"role": "assistant",
             "content": "¡Hola! 👋 Soy EcoBot, tu asistente de EcoCom2.\n\n¿En qué te ayudo hoy?"}
        ]
    if "agente_pendiente" not in st.session_state:
        st.session_state.agente_pendiente = False

    def llamar_ecobot(mensajes_historial: list) -> str:
        SISTEMA_AGENTE = """Eres EcoBot, el asistente amigable de EcoCom2 Circular IA,
una app para reportar residuos en la Comuna 2 - Santa Cruz de Medellín, Colombia.

Responde en español, de forma CORTA (máximo 3 oraciones), amigable y clara.
Usa emojis. Sé accesible para niños, adultos y personas mayores.

La app permite:
- Verificar si el usuario vive en la Comuna 2
- Tocar el mapa para marcar el punto del residuo
- La IA (YOLOv8) analiza la foto y detecta materiales
- 🟢 Verde: ≥60% reciclables | 🟡 Amarillo: mezcla | 🔴 Rojo: basura sin valorizar
- El reporte queda visible en el mapa comunitario

Pasos para reportar:
1. Escribe tu dirección y presiona Verificar
2. Toca el mapa en el punto del residuo
3. Presiona "Reportar Residuo" o "Punto Crítico"
4. Sube una foto
5. La IA analiza automáticamente
6. Presiona Publicar

Redirige preguntas no relacionadas al tema de residuos."""
        try:
            import requests
            api_key = ""
            try:
                api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
            except Exception:
                pass

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["x-api-key"] = api_key

            mensajes_api = [
                {"role": m["role"], "content": m["content"]}
                for m in mensajes_historial
            ]
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json={
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 250,
                    "system": SISTEMA_AGENTE,
                    "messages": mensajes_api,
                },
                timeout=20,
            )
            if resp.status_code == 200:
                return resp.json()["content"][0]["text"]
            else:
                return ("⚠️ No pude conectarme ahora. "
                        "Pasos: 1️⃣ Verifica dirección 2️⃣ Toca el mapa "
                        "3️⃣ Sube foto 4️⃣ Publica.")
        except Exception:
            return ("🤖 Sin conexión al asistente. "
                    "Pasos: 1️⃣ Verifica dirección 2️⃣ Toca el mapa "
                    "3️⃣ Sube foto 4️⃣ Publica.")

    if st.session_state.agente_pendiente:
        st.session_state.agente_pendiente = False
        with st.spinner("🤖 EcoBot está pensando..."):
            respuesta = llamar_ecobot(st.session_state.agente_msgs)
        st.session_state.agente_msgs.append({"role": "assistant", "content": respuesta})
        st.rerun()

    with st.sidebar.expander("🤖 Asistente EcoCom2", expanded=False):
        st.markdown("""
<div class="eco-chat-header-gradient" style="background:linear-gradient(135deg,#4ade80,#16a34a);
border-radius:10px;padding:10px 14px;font-weight:700;
font-size:14px;text-align:center;margin-bottom:10px;">
🤖 Hola, soy EcoBot<br>
<span style="font-weight:400;font-size:12px">Te ayudo a reportar residuos</span>
</div>""", unsafe_allow_html=True)

        for msg in st.session_state.agente_msgs[-6:]:
            if msg["role"] == "assistant":
                st.markdown(
                    f'<div style="background:#f0fdf4;border:1px solid #bbf7d0;'
                    f'border-radius:10px;padding:10px;font-size:13px;'
                    f'color:#14532d;margin-bottom:6px;">'
                    f'🤖 {msg["content"]}</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="background:#dcfce7;border-radius:10px;'
                    f'padding:8px 10px;font-size:13px;color:#166534;'
                    f'text-align:right;margin-bottom:6px;">'
                    f'👤 {msg["content"]}</div>',
                    unsafe_allow_html=True)

        pregunta = st.text_input(
            "Pregunta:", placeholder="¿Cómo reporto basura?",
            key="agente_input", label_visibility="collapsed")

        col_send, col_clear = st.columns([3, 1])
        with col_send:
            enviar = st.button("Enviar ➤", key="agente_enviar",
                               type="primary", use_container_width=True)
        with col_clear:
            if st.button("🗑️", key="agente_limpiar", use_container_width=True,
                         help="Limpiar chat"):
                st.session_state.agente_msgs = [st.session_state.agente_msgs[0]]
                st.rerun()

        if enviar and pregunta.strip():
            st.session_state.agente_msgs.append(
                {"role": "user", "content": pregunta.strip()})
            with st.spinner("🤖 EcoBot está pensando..."):
                respuesta = llamar_ecobot(st.session_state.agente_msgs)
            st.session_state.agente_msgs.append(
                {"role": "assistant", "content": respuesta})
            st.rerun()

        st.markdown("<p style='font-size:11px;color:#6b7280;margin:8px 0 4px 0;'>Preguntas rápidas:</p>",
                    unsafe_allow_html=True)
        preguntas_rapidas = [
            "¿Cómo reporto basura?",
            "¿Qué significa 🔴 rojo?",
            "¿Cómo verifico mi dirección?",
            "¿Para qué sirve la IA?",
        ]
        for pq in preguntas_rapidas:
            if st.button(pq, key=f"pq_{pq[:15]}", use_container_width=True):
                st.session_state.agente_msgs.append({"role": "user", "content": pq})
                st.session_state.agente_pendiente = True
                st.rerun()

    dir_auto = st.session_state.get("click_dir") or st.session_state.get("direccion") or ""

    with st.form(key="form_direccion", clear_on_submit=False):
        c_inp, c_btn = st.columns([5, 1])
        with c_inp:
            dir_inp = st.text_input(
                "📍 Dirección:",
                value=dir_auto,
                placeholder="Toca el mapa o escribe tu dirección en la Comuna 2...",
                label_visibility="collapsed",
                key="dir_campo",
            )
        with c_btn:
            verificar_clicked = st.form_submit_button(
                "🔍 Verificar", type="primary", use_container_width=True)

    if verificar_clicked:
        if dir_inp.strip():
            with st.spinner("Buscando..."):
                lat, lon, addr = geocodificar(dir_inp.strip())
            if lat:
                set_ubicacion(lat, lon, addr)
                st.rerun()
            else:
                st.error("❌ No encontré esa dirección. Intenta: Cra 50 #107-62, Andalucía")
        else:
            st.warning("Escribe o toca el mapa para obtener una dirección.")

    # ── GPS EN TIEMPO REAL ────────────────────────────────────────────
    # Botón que pide la posición real del dispositivo. Si el GPS cae
    # DENTRO de la Comuna 2, verificamos automáticamente (sin tener que
    # buscar la dirección ni tocar el mapa) — agiliza todo el proceso.
    # Si el GPS cae FUERA, no autoverificamos nada: dejamos el flujo
    # manual de siempre (buscar dirección / tocar el mapa), tal como
    # ya funcionaba antes.
    st.caption("¿Estás parado(a) frente al residuo ahora mismo? Usa tu ubicación GPS "
               "para verificarte al instante, sin buscar nada.")
    gps_raw = st.text_input(
        "gps_hidden", key="gps_raw_input", placeholder="GPS_HIDDEN_INPUT",
        label_visibility="collapsed",
    )
    _widget_gps("gps_dir")

    if gps_raw and gps_raw != st.session_state.get("gps_procesado"):
        st.session_state.gps_procesado = gps_raw
        try:
            glat_str, glon_str = gps_raw.split(",")
            glat, glon = float(glat_str), float(glon_str)
            st.session_state.gps_lat = glat
            st.session_state.gps_lon = glon
            dentro_gps = POLIGONO_COMUNA2.contains(Point(glon, glat))
            if dentro_gps:
                with st.spinner("📍 Estás dentro de la Comuna 2 — verificando dirección..."):
                    dir_gps, barrio_gps = geocodificar_inversa(glat, glon)
                set_ubicacion(glat, glon, dir_gps)
                st.session_state.click_barrio = barrio_gps
                st.success(f"✅ ¡Verificado por GPS! Estás en: {dir_gps}")
            else:
                st.warning(
                    "🛑 Tu GPS indica que estás **fuera** de la Comuna 2. "
                    "Puedes ver tu posición en el mapa (punto morado), pero para "
                    "reportar necesitas buscar tu dirección o tocar el punto "
                    "manualmente dentro del área piloto."
                )
            st.rerun()
        except Exception:
            pass

    if st.session_state.validado:
        if not st.session_state.fuera:
            badge(f"✅ <b>Dentro de la Comuna 2</b> — {st.session_state.direccion[:80]}", "ok")
        else:
            badge(f"🛑 Fuera de la Comuna 2 — {st.session_state.direccion[:70]}<br>"
                  f"<span style='font-weight:normal;font-size:12px'>"
                  f"Puedes usar el analizador de materiales, pero no publicar reportes.</span>", "err")
        if st.button("🔄 Cambiar dirección", key="cambiar_dir"):
            for k in ["validado","lat","lon","fuera","direccion",
                      "click_lat","click_lon","click_dir","click_barrio",
                      "punto_lat","punto_lon","cache",
                      "gps_lat","gps_lon","gps_procesado"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")
    st.markdown("### 🗺️ Toca el punto exacto del residuo en el mapa")
    st.caption("Al tocar, la dirección aparece automáticamente arriba y puedes reportar directo.")

    lat_c = st.session_state.get("lat") or st.session_state.get("gps_lat") or LAT_C
    lon_c = st.session_state.get("lon") or st.session_state.get("gps_lon") or LON_C

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=14, tiles="CartoDB positron")

    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_p, color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        tooltip="📍 Área piloto — Comuna 2 Santa Cruz (Acevedo → Villa del Socorro)"
    ).add_to(mapa)

    if st.session_state.get("validado") and st.session_state.get("lat"):
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker(
            location=[st.session_state.lat, st.session_state.lon],
            popup=f"🏠 {st.session_state.direccion}",
            tooltip="🏠 Tu dirección verificada",
            icon=folium.Icon(color=col_pin, icon="home", prefix="fa")
        ).add_to(mapa)

    if st.session_state.get("click_lat"):
        folium.Marker(
            location=[st.session_state.click_lat, st.session_state.click_lon],
            popup=f"📌 {st.session_state.get('click_dir','Punto seleccionado')}",
            tooltip="📌 Punto seleccionado",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(mapa)

    # Pin de posición GPS real del dispositivo (distinto del pin de
    # dirección verificada y del pin de punto seleccionado) — se
    # muestra incluso si el GPS cae fuera de la Comuna 2, solo como
    # referencia visual de dónde estás parado.
    if st.session_state.get("gps_lat"):
        folium.Marker(
            location=[st.session_state.gps_lat, st.session_state.gps_lon],
            popup="📍 Tu posición GPS actual",
            tooltip="📍 Tu ubicación en tiempo real",
            icon=folium.Icon(color="purple", icon="crosshairs", prefix="fa")
        ).add_to(mapa)

    for rep in st.session_state.reportes:
        niv = rep.get("Clasificación", "🟢")
        col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
        foto_b64 = rep.get("FotoB64", "")
        img_html = (f'<br><img src="data:image/jpeg;base64,{foto_b64}" '
                    f'style="width:180px;border-radius:6px;margin-top:6px;">'
                    if foto_b64 else "")
        obs_txt = rep.get("Observaciones", "")
        obs_html = f"📝 {obs_txt[:80]}<br>" if obs_txt else ""
        popup_html = (
            f"<div style='font-family:sans-serif;min-width:190px;'>"
            f"<b style='color:{col}'>{niv}</b><br>"
            f"<b>{rep['Código']}</b><br>"
            f"📍 {rep['Sector']}<br>"
            f"📌 {rep.get('Referencia','')[:40]}<br>"
            f"{obs_html}"
            f"♻️ {rep['Objetos']} obj | ⚖️ {rep['Peso (Kg)']} kg<br>"
            f"🕐 {rep.get('Fecha','')}<br>"
            f"🔖 {rep.get('Estado','')}"
            f"{img_html}</div>"
        )
        folium.CircleMarker(
            location=[rep["Lat"], rep["Lon"]], radius=12,
            color=col, fill=True, fill_color=col, fill_opacity=0.85,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"{rep['Código']} — {niv}"
        ).add_to(mapa)

    mapa_data = st_folium(mapa, width="100%", height=340,
                          returned_objects=["last_clicked"])

    if mapa_data and mapa_data.get("last_clicked"):
        clk = mapa_data["last_clicked"]
        lat_clk = round(clk["lat"], 7)
        lon_clk = round(clk["lng"], 7)
        if (lat_clk != st.session_state.get("click_lat") or
                lon_clk != st.session_state.get("click_lon")):
            st.session_state.click_lat = lat_clk
            st.session_state.click_lon = lon_clk
            with st.spinner("📍 Detectando dirección..."):
                dir_obtenida, barrio_obtenido = geocodificar_inversa(lat_clk, lon_clk)
            st.session_state.click_dir = dir_obtenida
            st.session_state.click_barrio = barrio_obtenido
            if not st.session_state.get("validado"):
                set_ubicacion(lat_clk, lon_clk, dir_obtenida)
            st.rerun()

    clat       = st.session_state.get("click_lat")
    clon       = st.session_state.get("click_lon")
    cdir       = st.session_state.get("click_dir", "")
    dentro_clk = POLIGONO_COMUNA2.contains(Point(clon, clat)) if clat else False

    if clat:
        st.markdown("")
        color_card = "#4ade80" if dentro_clk else "#ef4444"
        estado_txt = "✅ Dentro de la Comuna 2" if dentro_clk else "🛑 Fuera del área piloto"
        st.markdown(
            f'<div style="background:rgba(16,185,129,0.08);border:1px solid {color_card};'
            f'border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
            f'<span style="color:{color_card};font-weight:bold;font-size:14px;">📌 {cdir}</span><br>'
            f'<span style="color:#9ca3af;font-size:12px;">{estado_txt} · {clat:.5f}, {clon:.5f}</span>'
            f'</div>',
            unsafe_allow_html=True)

        if dentro_clk and es_residente():
            st.markdown("")
            st.session_state.punto_para_reporte = {
                "lat": clat, "lon": clon, "dir": cdir
            }
            bc1, bc2, bc3 = st.columns([2, 2, 1])
            with bc1:
                if st.button("📸 Reportar Residuo",
                             type="primary", use_container_width=True, key="btn_ir_rep"):
                    st.session_state.seccion = "residuo"
                    st.rerun()
            with bc2:
                if st.button("🚨 Punto Crítico",
                             use_container_width=True, key="btn_ir_crit"):
                    st.session_state.seccion = "critico"
                    st.rerun()
            with bc3:
                if st.button("✖", use_container_width=True, key="btn_quit",
                             help="Quitar punto seleccionado"):
                    for k in ["click_lat","click_lon","click_dir","click_barrio",
                               "cache","punto_para_reporte"]:
                        st.session_state.pop(k, None)
                    st.rerun()
        elif clat and not es_residente():
            badge("⚠️ Verifica tu dirección arriba para reportar en este punto.", "warn")

    st.markdown("")

    st.markdown("")
    seccion = st.session_state.get("seccion", "info")

    if seccion != "info":
        iconos = {"residuo": "📸 Reportar Residuo", "critico": "🚨 Punto Crítico",
                  "historial": "📋 Historial"}
        st.markdown(
            f'<div style="border-bottom:2px solid #4ade80;padding:6px 0 4px 0;'
            f'color:#4ade80;font-weight:bold;font-size:15px;margin-bottom:12px;">'
            f'{iconos.get(seccion,"")}</div>',
            unsafe_allow_html=True)

    if seccion == "info":
        if not clat:
            st.info("👆 Toca cualquier punto del mapa y usa los botones que aparecen para reportar.")

    # ── SECCIÓN: Reportar Residuo ──────────────────────────────────────
    elif seccion == "residuo":
        st.markdown("### 📸 Reportar Residuo")

        _paso_r = 1
        if es_residente(): _paso_r = 2
        if clat and dentro_clk: _paso_r = 3
        if st.session_state.get("cache"): _paso_r = 4
        progreso_pasos(_paso_r)
        st.markdown("")

        if not es_residente():
            badge("⚠️ Verifica tu dirección para reportar.", "warn")
        elif not clat or not dentro_clk:
            badge("⚠️ Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"📌 {pdir}", "ok")

            r1, r2 = st.columns(2)
            with r1:
                _barrio_sugerido = st.session_state.get("click_barrio")
                r_barrio = st.selectbox(
                    "Barrio:", BARRIOS,
                    index=BARRIOS.index(_barrio_sugerido) if _barrio_sugerido in BARRIOS else 0,
                    key="r_barrio"
                )
                if _barrio_sugerido:
                    st.caption(f"📍 Detectado automáticamente: {_barrio_sugerido} · puedes cambiarlo si no es correcto")
            with r2:
                r_ref = st.text_input("Referencia (edita si quieres):",
                                      value=pdir, key="r_ref")

            # ── OBSERVACIONES — describe lo que ves en la foto ──────────
            # Campo libre para que el ciudadano cuente detalles que la IA
            # no puede ver por sí sola (ej. "lleva ahí 3 días", "bloquea
            # el andén", "hay olor fuerte"). Queda guardado junto al
            # reporte y es visible para el administrador y en el mapa.
            r_obs = st.text_area(
                "📝 Observaciones (opcional):",
                placeholder="Describe lo que ves en la foto: hace cuánto está ahí, "
                            "si bloquea el paso, olores, riesgos, etc.",
                key="r_obs", height=80,
            )
            _widget_dictado("Describe lo que ves en la foto", "dictado_r")

            r_img = st.file_uploader("📷 Foto del residuo:",
                                     type=["jpg","jpeg","png"], key="r_img")
            if r_img:
                img = Image.open(r_img)
                if st.button("🔍 Analizar con IA", type="primary",
                             use_container_width=True, key="r_analizar"):
                    with st.spinner("Analizando imagen (conf ≥ 5%)..."):
                        res = analizar(img)
                    co, cd = st.columns(2)
                    with co:
                        st.markdown("**📷 Original**")
                        st.image(img, use_container_width=True)
                    with cd:
                        st.markdown("**🤖 Detecciones IA**")
                        st.image(res[0].plot(), use_container_width=True)

                    tabla, residuos, peso, tipo, nivel, _ = procesar(res)
                    if tabla:
                        df_t = pd.DataFrame(tabla)
                        df_si = df_t[df_t["♻️"] == "✅ Sí"]
                        df_no = df_t[df_t["♻️"] == "❌ No"]
                        if not df_si.empty:
                            st.markdown("**♻️ Reciclables:**")
                            st.dataframe(df_si, use_container_width=True, hide_index=True)
                        if not df_no.empty:
                            st.markdown("**⚠️ No aprovechables:**")
                            st.dataframe(df_no, use_container_width=True, hide_index=True)

                    if residuos == 0 and len(tabla) == 0:
                        st.warning(
                            "⚠️ La IA no reconoció objetos específicos. "
                            "Esto ocurre con escombros, basura mezclada o bolsas oscuras. "
                            "Clasifica manualmente:"
                        )
                        tipo_manual = st.selectbox(
                            "¿Qué tipo de residuo observas en la imagen?",
                            [
                                "🏗️ Escombros / Residuos de construcción",
                                "🗑️ Basura doméstica mezclada / bolsas",
                                "🧹 Residuos orgánicos (comida, vegetación)",
                                "♻️ Materiales reciclables sin identificar",
                                "⚠️ Mezcla de varios tipos",
                            ],
                            key="r_tipo_manual"
                        )
                        cant_manual = st.slider(
                            "Cantidad aproximada de residuos visibles:",
                            1, 20, 5, key="r_cant_manual"
                        )
                        MAP_MANUAL = {
                            "🏗️ Escombros / Residuos de construcción":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Escombros", round(cant_manual * 5.0, 1)),
                            "🗑️ Basura doméstica mezclada / bolsas":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Residuo mixto", round(cant_manual * 0.5, 1)),
                            "🧹 Residuos orgánicos (comida, vegetación)":
                                ("🟡 Punto amarillo — Residuos mixtos",
                                 "Orgánico", round(cant_manual * 0.3, 1)),
                            "♻️ Materiales reciclables sin identificar":
                                ("🟢 Punto verde — Alta valorización reciclable",
                                 "Reciclable", round(cant_manual * 0.4, 1)),
                            "⚠️ Mezcla de varios tipos":
                                ("🟡 Punto amarillo — Residuos mixtos",
                                 "Mixto", round(cant_manual * 1.0, 1)),
                        }
                        nivel, tipo, peso = MAP_MANUAL[tipo_manual]
                        residuos = cant_manual if "reciclable" in tipo_manual.lower() else 0
                        metricas(residuos, peso, nivel)
                    else:
                        metricas(residuos, peso, nivel)

                    st.session_state.cache = {
                        "Código":        f"REP-{len(st.session_state.reportes)+200}",
                        "Sector":        r_barrio,
                        "Referencia":    r_ref,
                        "Objetos":       residuos,
                        "Peso (Kg)":     peso,
                        "Predominante":  tipo,
                        "Clasificación": nivel,
                        "Lat": plat, "Lon": plon,
                        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Estado": "🔴 Pendiente",
                        "FotoB64": img_a_b64(img),
                        "Observaciones": r_obs.strip(),
                    }

            if st.session_state.get("cache"):
                r = st.session_state.cache
                st.markdown(f"**Listo:** {r['Clasificación']} · {r['Objetos']} reciclables · {r['Peso (Kg)']} kg")
                if r.get("Observaciones"):
                    st.markdown(f"**📝 Observaciones:** {r['Observaciones']}")
                cp, cc = st.columns(2)
                with cp:
                    if st.button("🚀 PUBLICAR EN EL MAPA", type="primary",
                                 use_container_width=True, key="r_publicar"):
                        st.session_state.reportes.append(r)
                        st.session_state.mis_codigos.append(r["Código"])
                        st.session_state.mis_estados_vistos[r["Código"]] = r["Estado"]
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache = None
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir","click_barrio"]:
                            st.session_state.pop(k, None)
                        st.success("✅ ¡Publicado! Guardado permanentemente en el mapa.")
                        st.rerun()
                with cc:
                    if st.button("❌ Cancelar", use_container_width=True, key="r_cancelar"):
                        st.session_state.cache = None
                        st.rerun()

    # ── SECCIÓN: Punto Crítico ─────────────────────────────────────────
    elif seccion == "critico":
        st.markdown("### 🚨 Registrar Punto Crítico")

        _paso_c = 1
        if es_residente(): _paso_c = 2
        if clat and dentro_clk: _paso_c = 3
        if st.session_state.get("cache_critico"): _paso_c = 4
        progreso_pasos(_paso_c, labels=["Dirección", "Punto en mapa", "Foto", "Registrar"])
        st.markdown("")

        if not es_residente():
            badge("⚠️ Verifica tu dirección para registrar alertas.", "warn")
        elif not clat or not dentro_clk:
            badge("⚠️ Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"🚨 {pdir}", "err")

            cr1, cr2 = st.columns(2)
            with cr1:
                _barrio_sugerido_cr = st.session_state.get("click_barrio")
                cr_barrio = st.selectbox(
                    "Barrio:", BARRIOS,
                    index=BARRIOS.index(_barrio_sugerido_cr) if _barrio_sugerido_cr in BARRIOS else 0,
                    key="cr_barrio"
                )
                if _barrio_sugerido_cr:
                    st.caption(f"📍 Detectado automáticamente: {_barrio_sugerido_cr} · puedes cambiarlo si no es correcto")
            with cr2:
                cr_ref = st.text_input("Referencia:", value=pdir, key="cr_ref")

            # ── OBSERVACIONES — igual que en Reportar Residuo ───────────
            cr_obs = st.text_area(
                "📝 Observaciones (opcional):",
                placeholder="Describe la acumulación: hace cuánto está ahí, si genera "
                            "olores, si bloquea el paso, riesgos para la salud, etc.",
                key="cr_obs", height=80,
            )
            _widget_dictado("Describe la acumulación", "dictado_cr")

            cr_img = st.file_uploader("📷 Foto del punto crítico:",
                                      type=["jpg","jpeg","png"], key="cr_img")
            if cr_img:
                img2 = Image.open(cr_img)

                if st.button("🔍 Evaluar con IA", type="primary",
                             use_container_width=True, key="cr_analizar"):
                    with st.spinner("Analizando con YOLOv8 (alta resolución)..."):
                        res2 = analizar(img2, imgsz=960)
                    st.session_state.cache_foto_b64 = img_a_b64(img2)

                    co2, cd2 = st.columns(2)
                    with co2:
                        st.markdown("**📷 Original**")
                        st.image(img2, use_container_width=True)
                    with cd2:
                        st.markdown("**🤖 Detecciones IA**")
                        st.image(res2[0].plot(), use_container_width=True)

                    tabla2, res2_r, peso2, tipo2, nivel2, total2 = procesar(res2)

                    if tabla2:
                        df_si2 = pd.DataFrame(tabla2)
                        df_si2 = df_si2[df_si2["♻️"] == "✅ Sí"]
                        if not df_si2.empty:
                            st.dataframe(df_si2, use_container_width=True, hide_index=True)

                    st.session_state.cache_critico = {
                        "residuos":    res2_r,
                        "peso":        peso2,
                        "tipo":        tipo2,
                        "nivel":       nivel2,
                        "total":       total2,
                        "ia_detecto":  total2 > 0,
                        "Lat":         plat,
                        "Lon":         plon,
                    }

                if st.session_state.get("cache_critico"):
                    cc = st.session_state.cache_critico

                    if not cc["ia_detecto"]:
                        st.warning(
                            "⚠️ La IA no reconoció objetos específicos "
                            "(escombros, bolsas oscuras, basura mezclada). "
                            "Clasifica manualmente:"
                        )
                        OPCIONES_MC = [
                            "🏗️ Escombros / Residuos de construcción",
                            "🗑️ Basura doméstica mezclada / bolsas",
                            "🧹 Residuos orgánicos (comida, vegetación)",
                            "⚠️ Mezcla de varios tipos",
                        ]
                        tipo_mc = st.selectbox("¿Qué ves en la imagen?",
                                               OPCIONES_MC, key="cr_tipo_manual")
                        cant_mc = st.slider("Cantidad aproximada de residuos:", 1, 30, 8,
                                            key="cr_cant_manual")
                        MAP_MC = {
                            "🏗️ Escombros / Residuos de construcción":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Escombros", round(cant_mc * 5.0, 1)),
                            "🗑️ Basura doméstica mezclada / bolsas":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Residuo mixto", round(cant_mc * 0.8, 1)),
                            "🧹 Residuos orgánicos (comida, vegetación)":
                                ("🟡 Punto amarillo — Residuos mixtos",
                                 "Orgánico", round(cant_mc * 0.3, 1)),
                            "⚠️ Mezcla de varios tipos":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Mixto", round(cant_mc * 1.5, 1)),
                        }
                        nivel_f, tipo_f, peso_f = MAP_MC[tipo_mc]
                        total_f = cant_mc
                        residuos_f = 0
                    else:
                        nivel_f   = cc["nivel"]
                        tipo_f    = cc["tipo"]
                        peso_f    = cc["peso"]
                        total_f   = cc["total"]
                        residuos_f= cc["residuos"]

                    metricas(residuos_f, peso_f, nivel_f)
                    if cr_obs.strip():
                        st.markdown(f"**📝 Observaciones:** {cr_obs.strip()}")

                    st.markdown("")
                    cr_pub, cr_can = st.columns(2)
                    with cr_pub:
                        if st.button("🚨 REGISTRAR ALERTA EN EL MAPA",
                                     type="primary", use_container_width=True,
                                     key="cr_registrar"):
                            nuevo = {
                                "Código":        f"CRIT-{len(st.session_state.reportes)+500}",
                                "Sector":        cr_barrio,
                                "Referencia":    cr_ref,
                                "Objetos":       total_f,
                                "Peso (Kg)":     round(peso_f, 2),
                                "Predominante":  tipo_f or "Mixto",
                                "Clasificación": nivel_f,
                                "Lat":           cc["Lat"],
                                "Lon":           cc["Lon"],
                                "Fecha":         datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "Estado":        "🔴 Pendiente",
                                "FotoB64": st.session_state.get("cache_foto_b64", ""),
                                "Observaciones": cr_obs.strip(),
                            }
                            st.session_state.reportes.append(nuevo)
                            st.session_state.mis_codigos.append(nuevo["Código"])
                            st.session_state.mis_estados_vistos[nuevo["Código"]] = nuevo["Estado"]
                            guardar_reportes_disco(st.session_state.reportes)
                            st.session_state.cache_critico = None
                            st.session_state.seccion = "historial"
                            for k in ["click_lat","click_lon","click_dir","click_barrio"]:
                                st.session_state.pop(k, None)
                            st.success("✅ ¡Alerta registrada permanentemente!")
                            st.rerun()
                    with cr_can:
                        if st.button("❌ Cancelar", use_container_width=True,
                                     key="cr_cancelar"):
                            st.session_state.cache_critico = None
                            st.rerun()

    # ── SECCIÓN: Historial ─────────────────────────────────────────────
    elif seccion == "historial":
        st.markdown("### 📋 Historial de Reportes")

        mis_reportes_actuales = [
            r for r in st.session_state.reportes
            if r["Código"] in st.session_state.mis_codigos
        ]
        avisos_cambio = []
        for r in mis_reportes_actuales:
            cod = r["Código"]
            estado_actual = r.get("Estado", "")
            estado_previo = st.session_state.mis_estados_vistos.get(cod)
            if estado_previo is not None and estado_previo != estado_actual:
                avisos_cambio.append((cod, estado_previo, estado_actual, r))
            st.session_state.mis_estados_vistos[cod] = estado_actual

        if avisos_cambio:
            for cod, previo, actual, r in avisos_cambio:
                if "Resuelto" in actual:
                    st.success(
                        f"🎉 ¡Tu reporte **{cod}** ({r.get('Sector','')}) fue **resuelto**! "
                        f"Gracias por reportarlo — tu acción ayudó a limpiar tu barrio."
                    )
                elif "proceso" in actual:
                    st.info(
                        f"🚚 Tu reporte **{cod}** ({r.get('Sector','')}) pasó a "
                        f"**en proceso de recolección**. Ya está siendo atendido."
                    )

        if mis_reportes_actuales:
            n_total_mios = len(mis_reportes_actuales)
            n_resueltos_mios = sum(1 for r in mis_reportes_actuales if "Resuelto" in r.get("Estado",""))
            n_proceso_mios   = sum(1 for r in mis_reportes_actuales if "proceso"  in r.get("Estado",""))
            n_pend_mios      = n_total_mios - n_resueltos_mios - n_proceso_mios
            st.markdown(
                f'<div style="background:rgba(74,222,128,0.08);border:1px solid #4ade80;'
                f'border-radius:10px;padding:10px 16px;margin-bottom:10px;font-size:13px;">'
                f'👤 <b>Tus reportes en esta sesión:</b> {n_total_mios} total · '
                f'🔴 {n_pend_mios} pendientes · 🟡 {n_proceso_mios} en proceso · '
                f'✅ {n_resueltos_mios} resueltos'
                f'</div>', unsafe_allow_html=True)

        solo_mios = st.checkbox(
            "📍 Mostrar solo mis reportes",
            value=False,
            help=("Reportes publicados en ESTA sesión del navegador. La app "
                  "todavía no tiene cuentas de usuario, así que esta lista se "
                  "reinicia si cierras o refrescas la página.")
        )
        reportes_mostrar = (
            [r for r in st.session_state.reportes if r["Código"] in st.session_state.mis_codigos]
            if solo_mios else st.session_state.reportes
        )

        if not reportes_mostrar:
            if solo_mios:
                st.info("Aún no has publicado ningún reporte en esta sesión.")
            else:
                st.info("Sin reportes aún. Toca el mapa y usa '📸 Reportar Residuo' para el primero.")
        else:
            df = pd.DataFrame(reportes_mostrar)

            h1, h2, h3, h4 = st.columns(4)
            pendientes = df.get("Estado", pd.Series([])).str.contains("Pendiente", na=False).sum() if "Estado" in df.columns else len(df)
            resueltos  = df.get("Estado", pd.Series([])).str.contains("Resuelto",  na=False).sum() if "Estado" in df.columns else 0
            crit = df["Clasificación"].str.contains("crítico", case=False, na=False).sum()
            with h1:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2><p>Total</p></div>', unsafe_allow_html=True)
            with h2:
                st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{crit}</h2><p>Críticos 🔴</p></div>', unsafe_allow_html=True)
            with h3:
                st.markdown(f'<div class="metric-card"><h2 style="color:#fbbf24">{pendientes}</h2><p>Pendientes</p></div>', unsafe_allow_html=True)
            with h4:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{resueltos}</h2><p>Resueltos ✅</p></div>', unsafe_allow_html=True)

            st.markdown("")

            COLS = ["Código","Fecha","Estado","Sector","Referencia",
                    "Objetos","Peso (Kg)","Clasificación","Observaciones"]
            cols_ok = [c for c in COLS if c in df.columns]
            st.dataframe(df[cols_ok], use_container_width=True, hide_index=True)

            csv_data = df[cols_ok].to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exportar como CSV",
                data=csv_data,
                file_name=f"ecocom2_reportes_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

# ====================================================================
# 8.5 COMUNA EN CIFRAS — Panel público, sin contraseña
# ====================================================================
elif menu == "📊 Comuna en Cifras":
    st.title("📊 Comuna 2 en Cifras")
    st.caption("Panel público — visible para cualquier persona, sin contraseña. "
               "Estos datos se actualizan en tiempo real con cada reporte y cada "
               "cambio de estado que hace la administración.")

    reportes_pub = st.session_state.reportes

    if not reportes_pub:
        st.info("Todavía no hay reportes publicados. Sé el primero en reportar un "
                "punto crítico desde 🏠 Inicio y Mapa.")
    else:
        df_pub = pd.DataFrame(reportes_pub)

        total_pub      = len(df_pub)
        criticos_pub   = int(df_pub["Clasificación"].str.contains("crítico",  case=False, na=False).sum())
        amarillos_pub  = int(df_pub["Clasificación"].str.contains("amarillo", case=False, na=False).sum())
        verdes_pub     = int(df_pub["Clasificación"].str.contains("verde",    case=False, na=False).sum())
        peso_pub       = float(df_pub["Peso (Kg)"].sum()) if "Peso (Kg)" in df_pub.columns else 0.0
        pendientes_pub = int(df_pub["Estado"].str.contains("Pendiente", na=False).sum()) if "Estado" in df_pub.columns else total_pub
        proceso_pub    = int(df_pub["Estado"].str.contains("proceso",   na=False).sum()) if "Estado" in df_pub.columns else 0
        resueltos_pub  = int(df_pub["Estado"].str.contains("Resuelto",  na=False).sum()) if "Estado" in df_pub.columns else 0

        try:
            df_pub["_fecha_dt"] = pd.to_datetime(df_pub["Fecha"], errors="coerce")
            hoy = datetime.now()
            df_mes = df_pub[
                (df_pub["_fecha_dt"].dt.month == hoy.month) &
                (df_pub["_fecha_dt"].dt.year == hoy.year)
            ]
            resueltos_mes = int(df_mes["Estado"].str.contains("Resuelto", na=False).sum()) if "Estado" in df_mes.columns else 0
            nuevos_mes    = len(df_mes)
        except Exception:
            resueltos_mes, nuevos_mes = 0, 0

        st.markdown(
            f'<div style="background:linear-gradient(135deg,rgba(74,222,128,0.15),rgba(22,163,74,0.10));'
            f'border:1px solid #4ade80;border-radius:14px;padding:18px 22px;margin-bottom:16px;">'
            f'<span style="font-size:16px;font-weight:700;color:#166534;">'
            f'🙌 Gracias a los reportes de la comunidad, este mes se han resuelto '
            f'<span style="color:#16a34a;">{resueltos_mes}</span> punto(s) crítico(s) '
            f'y se registraron <span style="color:#16a34a;">{nuevos_mes}</span> reporte(s) nuevo(s).'
            f'</span></div>', unsafe_allow_html=True)

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        for col, val, label, color in [
            (k1, total_pub,     "Total reportes",  "#4ade80"),
            (k2, criticos_pub,  "🔴 Críticos",      "#f87171"),
            (k3, amarillos_pub, "🟡 Mixtos",        "#fbbf24"),
            (k4, verdes_pub,    "🟢 Reciclables",   "#4ade80"),
            (k5, proceso_pub,   "🚚 En proceso",    "#fb923c"),
            (k6, resueltos_pub, "✅ Resueltos",     "#34d399"),
        ]:
            with col:
                st.markdown(
                    f'<div class="metric-card"><h2 style="color:{color};margin:0">{val}</h2>'
                    f'<p style="font-size:11px;margin:4px 0 0 0;">{label}</p></div>',
                    unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:rgba(167,139,250,0.10);border:1px solid #a78bfa;'
            f'border-radius:8px;padding:10px 16px;margin-top:14px;font-size:14px;">'
            f'⚖️ <b style="color:#7c3aed">Carga total estimada reportada: {peso_pub:.1f} kg</b> '
            f'en {total_pub} reportes desde el inicio del proyecto.'
            f'</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### 🏘️ Puntos críticos activos por barrio")
        st.caption("Barrios con reportes 🔴/🟡 que aún no han sido marcados como resueltos — "
                   "útil para priorizar dónde enfocar la limpieza y la sensibilización.")

        if "Sector" in df_pub.columns and "Estado" in df_pub.columns:
            df_activos = df_pub[~df_pub["Estado"].str.contains("Resuelto", na=False)]
            if not df_activos.empty:
                ranking = (df_activos.groupby("Sector").size()
                           .reset_index(name="Puntos activos")
                           .sort_values("Puntos activos", ascending=False))
                ranking.insert(0, "Puesto", range(1, len(ranking) + 1))
                st.dataframe(ranking, use_container_width=True, hide_index=True)
            else:
                st.success("🎉 ¡No hay puntos activos pendientes! Todos los reportes están resueltos.")

        st.markdown("---")
        st.markdown("#### 📈 Reportes acumulados en el tiempo")
        try:
            df_evol = df_pub.dropna(subset=["_fecha_dt"]).sort_values("_fecha_dt")
            if not df_evol.empty:
                df_evol["Acumulado"] = range(1, len(df_evol) + 1)
                st.line_chart(df_evol.set_index("_fecha_dt")["Acumulado"])
            else:
                st.caption("Sin fechas suficientes para mostrar la evolución todavía.")
        except Exception:
            st.caption("Sin datos suficientes para mostrar la evolución todavía.")

        st.markdown("---")
        st.caption(
            "💡 Este panel es de solo lectura: los cambios de estado (Pendiente → En proceso → "
            "Resuelto) los hace la administración desde el 🛡️ Panel Admin. Si tú publicaste un "
            "reporte, puedes ver su seguimiento personal en 🏠 Inicio y Mapa → 📋 Historial."
        )

# ====================================================================
# 9. PANEL ADMINISTRADOR — Gestión completa de reportes
# ====================================================================
elif menu == "🛡️ Panel Admin":

    if not st.session_state.get("admin_ok"):
        st.markdown("")
        col_login = st.columns([1, 2, 1])[1]
        with col_login:
            st.markdown("""
<div style="background:rgba(16,185,129,0.08);border:1px solid #4ade80;
border-radius:14px;padding:32px 28px;text-align:center;">
<h2 style="color:#4ade80;margin-bottom:4px;">🛡️ Panel Admin</h2>
<p style="color:#9ca3af;font-size:14px;margin-bottom:20px;">
EcoCom2 Circular IA · ITM Medellín</p>
</div>""", unsafe_allow_html=True)
            st.markdown("")
            pwd_input = st.text_input("Contraseña de administrador:",
                                      type="password", key="login_pwd",
                                      placeholder="Ingresa tu contraseña")
            if st.button("🔐 Iniciar sesión", type="primary",
                         use_container_width=True, key="login_btn"):
                if pwd_input == "ecocom2admin2026":
                    st.session_state.admin_ok = True
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")
        st.stop()

    st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;
margin-bottom:8px;">
<div>
  <h1 style="color:#4ade80;margin:0;">🛡️ Panel de Administración</h1>
  <p style="color:#9ca3af;margin:0;font-size:13px;">
  EcoCom2 Circular IA · Comuna 2 Santa Cruz · ITM Medellín</p>
</div>
</div>""", unsafe_allow_html=True)

    accion = st.session_state.pop("adm_accion_pendiente", None)
    if accion:
        cod_obj = accion["codigo"]
        tipo_acc = accion["tipo"]
        if tipo_acc == "estado":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj:
                    r["Estado"] = accion["valor"]
                    break
            guardar_reportes_disco(st.session_state.reportes)
        elif tipo_acc == "resuelto":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj:
                    r["Estado"] = "✅ Resuelto"
                    break
            guardar_reportes_disco(st.session_state.reportes)
        elif tipo_acc == "eliminar":
            st.session_state.reportes = [
                r for r in st.session_state.reportes if r["Código"] != cod_obj
            ]
            guardar_reportes_disco(st.session_state.reportes)
        elif tipo_acc == "en_proceso":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj:
                    r["Estado"] = "🟡 En proceso de recolección"
                    break
            guardar_reportes_disco(st.session_state.reportes)
        st.rerun()

    reportes = st.session_state.reportes

    tab_dash, tab_mapa, tab_lista, tab_export = st.tabs([
        "📊 Dashboard",
        "🗺️ Mapa de control",
        "🗂️ Gestión de reportes",
        "📥 Exportar / Limpiar"
    ])

    # ════════════════════════════════════════════════════════════════
    # TAB 1: DASHBOARD
    # ════════════════════════════════════════════════════════════════
    with tab_dash:
        if not reportes:
            st.info("Sin reportes aún. Los reportes de los residentes aparecerán aquí.")
        else:
            df_a = pd.DataFrame(reportes)

            total    = len(df_a)
            criticos = int(df_a["Clasificación"].str.contains("crítico",  case=False, na=False).sum())
            amarillos= int(df_a["Clasificación"].str.contains("amarillo", case=False, na=False).sum())
            verdes   = int(df_a["Clasificación"].str.contains("verde",    case=False, na=False).sum())
            peso_t   = float(df_a["Peso (Kg)"].sum())
            pendientes = int(df_a["Estado"].str.contains("Pendiente",  na=False).sum()) if "Estado" in df_a.columns else total
            en_proceso = int(df_a["Estado"].str.contains("proceso",    na=False).sum()) if "Estado" in df_a.columns else 0
            resueltos  = int(df_a["Estado"].str.contains("Resuelto",   na=False).sum()) if "Estado" in df_a.columns else 0

            k1,k2,k3,k4,k5,k6 = st.columns(6)
            for col, val, label, color in [
                (k1, total,       "Total",         "#4ade80"),
                (k2, criticos,    "🔴 Críticos",   "#f87171"),
                (k3, amarillos,   "🟡 Mixtos",     "#fbbf24"),
                (k4, verdes,      "🟢 Reciclables","#4ade80"),
                (k5, pendientes,  "⏳ Pendientes", "#fb923c"),
                (k6, resueltos,   "✅ Resueltos",  "#34d399"),
            ]:
                with col:
                    st.markdown(
                        f'<div class="metric-card"><h2 style="color:{color};margin:0">{val}</h2>'
                        f'<p style="font-size:11px;margin:4px 0 0 0;color:#9ca3af">{label}</p></div>',
                        unsafe_allow_html=True)

            st.markdown(f"""
<div style="background:rgba(167,139,250,0.1);border:1px solid #a78bfa;border-radius:8px;
padding:10px 16px;margin-top:12px;font-size:14px;">
⚖️ <b style="color:#a78bfa">Carga total acumulada: {peso_t:.1f} kg</b> en {total} reportes
</div>""", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("#### 📍 Reportes por Barrio")
            if "Sector" in df_a.columns:
                conteo_barrio = df_a["Sector"].value_counts().reset_index()
                conteo_barrio.columns = ["Barrio", "Reportes"]
                st.dataframe(conteo_barrio, use_container_width=True,
                             hide_index=True)

            st.markdown("#### 🕐 Últimos reportes registrados")
            COLS_DASH = ["Código","Fecha","Estado","Sector","Clasificación","Peso (Kg)","Observaciones"]
            cols_ok = [c for c in COLS_DASH if c in df_a.columns]
            st.dataframe(df_a[cols_ok].tail(5).iloc[::-1],
                         use_container_width=True, hide_index=True)

    # ════════════════════════════════════════════════════════════════
    # TAB 2: MAPA DE CONTROL
    # ════════════════════════════════════════════════════════════════
    with tab_mapa:
        st.markdown("#### 🗺️ Todos los puntos reportados — mapa de control")

        if not reportes:
            st.info("Sin reportes aún.")
        else:
            fm1, fm2 = st.columns(2)
            with fm1:
                f_estado = st.selectbox("Filtrar por estado:",
                    ["Todos","🔴 Pendiente","🟡 En proceso","✅ Resuelto"],
                    key="adm_f_estado")
            with fm2:
                f_nivel = st.selectbox("Filtrar por criticidad:",
                    ["Todos","🔴 Crítico","🟡 Amarillo","🟢 Verde"],
                    key="adm_f_nivel")

            mapa_adm = folium.Map(location=[LAT_C, LON_C],
                                  zoom_start=14, tiles="CartoDB positron")

            coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
            folium.Polygon(locations=coords_p, color="#4ade80", weight=2,
                           fill=True, fill_color="#4ade80", fill_opacity=0.06).add_to(mapa_adm)

            total_mostrados = 0
            for rep in reportes:
                est = rep.get("Estado", "")
                niv = rep.get("Clasificación", "")
                if f_estado != "Todos":
                    if f_estado == "🔴 Pendiente"     and "Pendiente" not in est: continue
                    if f_estado == "🟡 En proceso"    and "proceso"   not in est: continue
                    if f_estado == "✅ Resuelto"      and "Resuelto"  not in est: continue
                if f_nivel != "Todos":
                    if f_nivel == "🔴 Crítico"  and "crítico"  not in niv.lower(): continue
                    if f_nivel == "🟡 Amarillo" and "amarillo" not in niv.lower(): continue
                    if f_nivel == "🟢 Verde"    and "verde"    not in niv.lower(): continue

                col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
                if "Resuelto" in est:
                    col = "gray"

                foto_b64 = rep.get("FotoB64", "")
                img_html  = (f'<br><img src="data:image/jpeg;base64,{foto_b64}" '
                              f'style="width:160px;border-radius:4px;margin-top:4px;">'
                              if foto_b64 else "")
                obs_txt_adm = rep.get("Observaciones", "")
                obs_html_adm = f"📝 {obs_txt_adm[:100]}<br>" if obs_txt_adm else ""
                popup_adm = (
                    f"<div style='font-family:sans-serif;min-width:190px;'>"
                    f"<b style='color:{col}'>{niv}</b><br>"
                    f"<b>{rep['Código']}</b><br>"
                    f"📍 {rep.get('Sector','')} · {rep.get('Referencia','')[:35]}<br>"
                    f"{obs_html_adm}"
                    f"♻️ {rep.get('Objetos',0)} obj | ⚖️ {rep.get('Peso (Kg)',0)} kg<br>"
                    f"🕐 {rep.get('Fecha','')} | 🔖 {est}"
                    f"{img_html}</div>"
                )
                folium.CircleMarker(
                    location=[rep["Lat"], rep["Lon"]], radius=13,
                    color=col, fill=True, fill_color=col, fill_opacity=0.85,
                    popup=folium.Popup(popup_adm, max_width=220),
                    tooltip=f"{rep['Código']} | {est}"
                ).add_to(mapa_adm)
                total_mostrados += 1

            st_folium(mapa_adm, width="100%", height=480, returned_objects=[])
            st.caption(f"Mostrando {total_mostrados} de {len(reportes)} reportes")

    # ════════════════════════════════════════════════════════════════
    # TAB 3: GESTIÓN DE REPORTES
    # ════════════════════════════════════════════════════════════════
    with tab_lista:
        st.markdown("#### 🗂️ Gestión individual de reportes")

        if not reportes:
            st.info("Sin reportes aún.")
        else:
            g1, g2, g3 = st.columns(3)
            with g1:
                g_sector = st.selectbox("Barrio:", ["Todos"]+BARRIOS, key="adm_g_sector")
            with g2:
                g_estado = st.selectbox("Estado:",
                    ["Todos","🔴 Pendiente","🟡 En proceso","✅ Resuelto"],
                    key="adm_g_estado")
            with g3:
                g_tipo = st.selectbox("Tipo:",
                    ["Todos","🔴 Crítico","🟡 Mixto","🟢 Verde"],
                    key="adm_g_tipo")

            ESTADOS = ["🔴 Pendiente","🟡 En proceso de recolección","✅ Resuelto"]

            for rep in list(reportes):
                codigo   = rep["Código"]
                key_safe = codigo.replace(" ","_").replace("/","_").replace("-","_")
                estado   = rep.get("Estado","🔴 Pendiente")
                nivel    = rep.get("Clasificación","")

                if g_sector != "Todos" and rep.get("Sector") != g_sector: continue
                if g_estado != "Todos":
                    if g_estado == "🔴 Pendiente"  and "Pendiente" not in estado: continue
                    if g_estado == "🟡 En proceso" and "proceso"   not in estado: continue
                    if g_estado == "✅ Resuelto"   and "Resuelto"  not in estado: continue
                if g_tipo != "Todos":
                    if g_tipo == "🔴 Crítico" and "crítico"  not in nivel.lower(): continue
                    if g_tipo == "🟡 Mixto"   and "amarillo" not in nivel.lower(): continue
                    if g_tipo == "🟢 Verde"   and "verde"    not in nivel.lower(): continue

                icono = "🔴" if "crítico" in nivel.lower() else ("🟡" if "amarillo" in nivel.lower() else "🟢")
                if "Resuelto" in estado: icono = "✅"
                if "proceso"  in estado: icono = "🟡"

                with st.expander(
                    f"{icono} {codigo} · {rep.get('Sector','?')} · "
                    f"{rep.get('Referencia','')[:30]} · {estado}",
                    expanded=False
                ):
                    foto_b64 = rep.get("FotoB64","")
                    if foto_b64:
                        st.markdown("**📷 Foto del reporte:**")
                        st.markdown(
                            f'<img src="data:image/jpeg;base64,{foto_b64}" '
                            f'style="max-width:320px;border-radius:8px;margin-bottom:10px;">',
                            unsafe_allow_html=True)

                    i1, i2 = st.columns(2)
                    with i1:
                        st.markdown(
                            f"**Código:** {codigo}  \n"
                            f"**Barrio:** {rep.get('Sector','—')}  \n"
                            f"**Referencia:** {rep.get('Referencia','—')}  \n"
                            f"**Fecha:** {rep.get('Fecha','Sin fecha')}"
                        )
                    with i2:
                        st.markdown(
                            f"**Clasificación:** {nivel}  \n"
                            f"**Objetos:** {rep.get('Objetos',0)}  \n"
                            f"**Peso:** {rep.get('Peso (Kg)',0)} kg  \n"
                            f"**Material:** {rep.get('Predominante','—')}"
                        )
                    st.markdown(
                        f"📍 Coordenadas: `{rep.get('Lat',0):.5f}, {rep.get('Lon',0):.5f}`"
                    )

                    # ── Observaciones del ciudadano ─────────────────────
                    obs_rep = rep.get("Observaciones", "")
                    if obs_rep:
                        st.markdown(
                            f'<div style="background:rgba(74,222,128,0.08);border-left:3px solid #4ade80;'
                            f'border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px;">'
                            f'📝 <b>Observaciones del ciudadano:</b><br>{obs_rep}</div>',
                            unsafe_allow_html=True)

                    st.markdown("**Cambiar estado:**")
                    idx_est = ESTADOS.index(estado) if estado in ESTADOS else 0
                    nuevo_estado = st.selectbox("",ESTADOS,index=idx_est,
                                                label_visibility="collapsed",
                                                key=f"sel_{key_safe}")
                    b1,b2,b3,b4 = st.columns(4)
                    with b1:
                        if st.button("💾 Guardar",key=f"grd_{key_safe}",
                                     use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"estado","valor":nuevo_estado}
                            st.rerun()
                    with b2:
                        if st.button("🚚 En proceso",key=f"proc_{key_safe}",
                                     use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"en_proceso"}
                            st.rerun()
                    with b3:
                        if st.button("✅ Resuelto",key=f"res_{key_safe}",
                                     type="primary",use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"resuelto"}
                            st.rerun()
                    with b4:
                        if st.button("🗑️ Eliminar",key=f"del_{key_safe}",
                                     use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"eliminar"}
                            st.rerun()

    # ════════════════════════════════════════════════════════════════
    # TAB 4: EXPORTAR / LIMPIAR
    # ════════════════════════════════════════════════════════════════
    with tab_export:
        st.markdown("#### 📥 Exportar datos")

        if reportes:
            df_exp = pd.DataFrame(reportes)
            cols_exp = [c for c in df_exp.columns if c != "FotoB64"]

            csv_bytes = df_exp[cols_exp].to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Descargar CSV — todos los reportes",
                data=csv_bytes,
                file_name=f"ecocom2_reportes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            df_pend = df_exp[df_exp.get("Estado","").str.contains("Pendiente",na=False)] if "Estado" in df_exp.columns else df_exp
            if len(df_pend) > 0:
                csv_pend = df_pend[cols_exp].to_csv(index=False).encode("utf-8")
                st.download_button(
                    f"⏳ Descargar solo PENDIENTES ({len(df_pend)})",
                    data=csv_pend,
                    file_name=f"ecocom2_pendientes_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        st.markdown("---")
        st.markdown("#### ⚠️ Operaciones en lote")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("🟡 Marcar TODOS pendientes como En Proceso",
                         use_container_width=True, key="adm_todos_proceso"):
                cambios = 0
                for r in st.session_state.reportes:
                    if "Pendiente" in r.get("Estado",""):
                        r["Estado"] = "🟡 En proceso de recolección"
                        cambios += 1
                guardar_reportes_disco(st.session_state.reportes)
                st.success(f"✅ {cambios} reporte(s) marcados como En proceso.")
                st.rerun()

        with col_b2:
            if st.button("✅ Marcar TODOS como Resueltos",
                         use_container_width=True, key="adm_todos_resuelto"):
                for r in st.session_state.reportes:
                    r["Estado"] = "✅ Resuelto"
                guardar_reportes_disco(st.session_state.reportes)
                st.success(f"✅ {len(st.session_state.reportes)} reportes marcados como resueltos.")
                st.rerun()

        st.markdown("")
        st.markdown("**🗑️ Eliminar reportes resueltos** (libera espacio del mapa):")
        if st.button("🗑️ ELIMINAR todos los ✅ Resueltos del mapa",
                     use_container_width=True, key="adm_limpiar_resueltos"):
            antes = len(st.session_state.reportes)
            st.session_state.reportes = [
                r for r in st.session_state.reportes
                if "Resuelto" not in r.get("Estado","")
            ]
            guardar_reportes_disco(st.session_state.reportes)
            eliminados = antes - len(st.session_state.reportes)
            st.success(f"✅ {eliminados} reporte(s) resuelto(s) eliminados del mapa.")
            st.rerun()

        st.markdown("")
        with st.expander("🔴 ZONA DE PELIGRO — Eliminar todo"):
            st.warning("Esta acción elimina TODOS los reportes permanentemente. No se puede deshacer.")
            confirm = st.text_input("Escribe CONFIRMAR para continuar:",
                                    key="adm_confirm_borrar_todo")
            if st.button("🗑️ BORRAR TODOS LOS REPORTES",
                         use_container_width=True, key="adm_borrar_todo"):
                if confirm == "CONFIRMAR":
                    st.session_state.reportes = []
                    guardar_reportes_disco([])
                    st.success("✅ Todos los reportes eliminados.")
                    st.rerun()
                else:
                    st.error("Escribe exactamente CONFIRMAR para continuar.")

elif menu == "ℹ️ Información":
    st.title("♻️ EcoCom2 Circular IA")
    st.markdown(
        '<div style="background:rgba(16,185,129,0.1);border:1px solid #4ade80;'
        'border-radius:10px;padding:16px;margin-bottom:20px;font-size:15px;">'
        '🌱 <b style="color:#4ade80">Plataforma de Gestión Inteligente de Residuos</b><br>'
        'Tecnología IA al servicio de una <b>Comuna 2 más limpia y sostenible</b>.'
        '</div>', unsafe_allow_html=True)

    st.markdown("## 🔄 ¿Qué es la Economía Circular?")
    st.markdown("""
La **economía circular** es un modelo de producción y consumo que busca **eliminar los residuos
desde el diseño**, manteniendo los materiales en uso el mayor tiempo posible. A diferencia de la
economía lineal (fabricar → usar → tirar), la economía circular propone:

- **Reducir** el consumo de recursos y la generación de residuos
- **Reutilizar** materiales y productos antes de descartarlos
- **Reciclar** lo que ya no puede ser reutilizado para crear nuevos materiales
- **Recuperar** energía de los residuos que no pueden reciclarse
""")

    i1, i2, i3 = st.columns(3)
    with i1:
        st.markdown("""
<div style="background:rgba(16,185,129,0.1);border:1px solid #4ade80;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#4ade80">♻️</h2>
<b style="color:#4ade80">Reciclar</b><br>
<span style="font-size:13px;color:#9ca3af">Papel, plástico, vidrio,<br>
aluminio y electrónicos</span>
</div>""", unsafe_allow_html=True)
    with i2:
        st.markdown("""
<div style="background:rgba(251,191,36,0.1);border:1px solid #fbbf24;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#fbbf24">🔁</h2>
<b style="color:#fbbf24">Reutilizar</b><br>
<span style="font-size:13px;color:#9ca3af">Muebles, ropa, aparatos<br>
que aún sirven</span>
</div>""", unsafe_allow_html=True)
    with i3:
        st.markdown("""
<div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#ef4444">🌱</h2>
<b style="color:#ef4444">Compostar</b><br>
<span style="font-size:13px;color:#9ca3af">Residuos orgánicos que<br>
se convierten en abono</span>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 🗺️ ¿Qué es un Punto Crítico de Residuos?")
    st.markdown("""
Un **punto crítico** es una zona donde se acumulan residuos de forma irregular, afectando la
salud pública, el medio ambiente y la calidad de vida del barrio. En la **Comuna 2 — Santa Cruz**
existen zonas donde los residuos se depositan en espacios públicos sin recolección oportuna.

### 🟢 🟡 🔴 Sistema de Clasificación EcoCom2

La clasificación combina **dos factores**: qué tan reciclable es el material, y **qué tan grande**
es la acumulación. Un montón grande de material 100% reciclable (ej. 40 botellas) también cuenta
como punto crítico — el volumen es un problema aunque el material tenga valor.

| Color | Significado | Acción recomendada |
|---|---|---|
| 🟢 **Verde** | ≥60% objetos reciclables y volumen pequeño | Ruta de reciclaje |
| 🟡 **Amarillo** | 30-60% mixto, o buen material pero volumen considerable | Separación en origen |
| 🔴 **Rojo** | <30% reciclable, o una acumulación grande sin importar el material | Recolección urgente |
""")

    st.markdown("---")
    st.markdown("## 🤖 ¿Cómo funciona la IA?")
    st.markdown("""
EcoCom2 usa **YOLOv8** (You Only Look Once), un modelo de visión artificial que analiza imágenes
en tiempo real para detectar y clasificar objetos. El sistema:

1. **Detecta** todos los objetos visibles en la fotografía
2. **Clasifica** cada objeto en su tipo de material (Plástico, Papel, Vidrio, Metal, Electrónico, Orgánico)
3. **Calcula** el peso estimado y el ratio reciclable/no-reciclable
4. **Clasifica** el punto como Verde 🟢, Amarillo 🟡 o Rojo 🔴

### 📦 Materiales que detecta la IA
""")

    mat_cols = st.columns(3)
    categorias = {
        "🧴 Plástico": ["Botellas", "Vasos", "Bolsas", "Baldes", "Sillas", "Juguetes"],
        "📄 Papel/Cartón": ["Libros", "Periódicos", "Cajas", "Cuadernos"],
        "🍶 Vidrio": ["Botellas", "Frascos", "Jarrones", "Copas"],
        "🥫 Metal/Aluminio": ["Latas", "Cuchillos", "Tijeras", "Utensilios"],
        "💻 Electrónicos": ["Celulares", "Portátiles", "Teclados", "Televisores", "Relojes"],
        "🌿 Orgánico": ["Frutas", "Verduras", "Comida", "Plantas"],
        "👕 Textil": ["Ropa", "Mochilas", "Bolsos", "Maletas"],
        "🪵 Madera/Mixto": ["Mesas", "Sofás", "Camas", "Colchones"],
    }
    cat_items = list(categorias.items())
    for i, col in enumerate(mat_cols):
        with col:
            for cat, items in cat_items[i*3:(i+1)*3]:
                st.markdown(
                    f'<div style="background:rgba(16,185,129,0.06);border-radius:8px;'
                    f'padding:10px;margin-bottom:8px;font-size:13px;">'
                    f'<b style="color:#4ade80">{cat}</b><br>'
                    f'<span style="color:#9ca3af">{" · ".join(items)}</span></div>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 📍 Cómo usar EcoCom2")
    st.markdown("""
1. **Verifica tu dirección** en 🏠 Inicio y Mapa — escribe tu dirección y presiona 🔍 Verificar
2. **Toca el mapa** en el punto exacto donde están los residuos
3. **Presiona el botón** "📸 Ir a Reportar Residuo" o "🚨 Ir a Punto Crítico"
4. **Sube una foto** del residuo y deja que la IA lo analice
5. **Agrega observaciones** si quieres contar detalles que la foto no muestra
6. **Publica el reporte** — quedará guardado en el mapa comunitario

> Solo residentes **dentro del polígono de la Comuna 2** pueden publicar reportes.
> Cualquier persona puede analizar imágenes con la IA.
""")

    st.markdown("---")
    st.markdown("## 📍 Los 11 barrios de la Comuna 2 — Santa Cruz")
    bc1, bc2 = st.columns(2)
    mitad = len(BARRIOS) // 2
    with bc1:
        for b in BARRIOS[:mitad+1]:
            st.markdown(f"- 📍 **{b}**")
    with bc2:
        for b in BARRIOS[mitad+1:]:
            st.markdown(f"- 📍 **{b}**")

    st.markdown("---")
    st.markdown("""
<div style="background:rgba(16,185,129,0.06);border:1px solid rgba(74,222,128,0.2);
border-radius:10px;padding:16px;text-align:center;color:#9ca3af;font-size:13px;">
⚙️ <b style="color:#4ade80">EcoCom2 Circular IA v5.0</b><br>
Proyecto <b style="color:#4ade80">Territorio INN 2026</b> · Instituto Tecnológico Metropolitano (ITM) · Medellín<br>
Desarrollado por: <b style="color:#4ade80">Brandon Duque</b> · Comuna 2 Santa Cruz
</div>
""", unsafe_allow_html=True)
