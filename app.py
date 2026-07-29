import streamlit as st
from ultralytics import YOLO, YOLOE
from PIL import Image, ImageFilter
import tempfile
from collections import Counter
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import pandas as pd
from shapely.geometry import Point, Polygon
import json, os
from urllib.parse import quote as url_quote
import sqlite3
import unicodedata
import difflib
from pathlib import Path
from datetime import datetime
import base64
from io import BytesIO
from streamlit_js_eval import get_geolocation
import imagehash
from math import radians, sin, cos, sqrt, atan2

# ====================================================================
# PERSISTENCIA — SQLite en vez de JSON en /tmp
# ====================================================================
DB_PATH = Path(__file__).resolve().parent / "data" / "ecocom2.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_CAMPOS    = ["Código","Sector","Referencia","Objetos","Peso (Kg)",
              "Predominante","Clasificación","Lat","Lon","Fecha","Estado","FotoB64",
              "Observaciones","NotaVozB64","FotosExtraB64","CodigoResidente","PHash",
              "Confirmaciones"]
_COLUMNAS  = ["codigo","sector","referencia","objetos","peso_kg",
              "predominante","clasificacion","lat","lon","fecha","estado","foto_b64",
              "observaciones","nota_voz_b64","fotos_extra_b64","residente_codigo","phash",
              "confirmaciones"]

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
            # Migración suave: agregar columnas nuevas si la tabla ya
            # existía de una versión anterior. SQLite no soporta
            # "ADD COLUMN IF NOT EXISTS", así que intentamos y
            # silenciamos el error si la columna ya existe.
            for col_sql in ["observaciones TEXT", "nota_voz_b64 TEXT",
                            "fotos_extra_b64 TEXT", "residente_codigo TEXT",
                            "phash TEXT", "confirmaciones INTEGER DEFAULT 0"]:
                try:
                    conn.execute(f"ALTER TABLE reportes ADD COLUMN {col_sql}")
                except Exception:
                    pass
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
    .stApp {
        background-color: #f0fdf4;
        color: #1a2e1a;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    .block-container { padding-top: 1rem; max-width: 1200px; }

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
    /* Placeholder del campo "Pregunta:" del chatbot — antes heredaba
       el gris muy claro por defecto del navegador, casi invisible
       sobre el fondo crema del campo. */
    [data-testid="stSidebar"] input[type="text"]::placeholder {
        color: #6b7280 !important;
        opacity: 1 !important;
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
    div[data-testid="stTextInput"] label,
    div[data-testid="stTextArea"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stFileUploader"] label {
        color: #14532d !important;
        font-weight: 600 !important;
    }

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
    /* Texto del valor seleccionado (ej. "La Frontera") — heredaba el
       color claro del tema, invisible sobre el fondo blanco de arriba.
       El "*" cubre el value-container y cualquier span interno que
       use BaseWeb (la librería de componentes de Streamlit). */
    div[data-testid="stSelectbox"] * {
        color: #14532d !important;
    }
    /* La flecha del desplegable es un ícono SVG, no texto — se pinta
       con "fill", no con "color", así que necesita su propia regla. */
    div[data-testid="stSelectbox"] svg {
        fill: #14532d !important;
    }
    /* La LISTA de opciones (al hacer clic para desplegar) se pinta en
       un popover aparte, fuera del contenedor del selectbox — por eso
       necesita su propia regla, si no, tendría el mismo problema de
       texto invisible en cuanto el usuario la abriera. */
    div[data-baseweb="popover"] li,
    div[data-baseweb="menu"] * {
        color: #14532d !important;
        background: #ffffff !important;
    }

    [data-baseweb="tab-list"] {
        background: #dcfce7 !important; border-radius: 10px !important; padding: 4px !important;
        gap: 4px !important;
    }
    [data-baseweb="tab"] {
        background: transparent !important; border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 8px 14px !important;
    }
    /* El texto de cada pestaña vive en un <p> anidado dentro del botón,
       no directamente en el botón — por eso el "color" de arriba no
       alcanzaba a pintarlo. El "*" cubre ese <p> y cualquier otro hijo. */
    [data-baseweb="tab"] * {
        color: #166534 !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        background: #16a34a !important;
        border-radius: 8px !important;
    }
    [data-baseweb="tab"][aria-selected="true"] * {
        color: #ffffff !important;
    }

    div[data-testid="stExpander"] {
        border: 1px solid #bbf7d0 !important;
        border-radius: 10px !important;
        background: #ffffff !important;
        margin-bottom: 8px !important;
    }
    /* El encabezado clickeable (el "summary") es un elemento aparte
       dentro del expander — no heredaba el fondo blanco de arriba,
       por eso se veía con el fondo oscuro del tema por defecto y el
       texto casi invisible encima. */
    div[data-testid="stExpander"] summary {
        background: #ffffff !important;
    }
    div[data-testid="stExpander"] summary * {
        color: #14532d !important;
    }

    div[data-testid="stDataFrameContainer"] {
        border: 2px solid #bbf7d0;
        border-radius: 10px; overflow: hidden;
    }

    div[data-testid="stInfo"] {
        background: #eff6ff !important; border-left: 4px solid #3b82f6 !important;
        color: #1e3a5f !important; border-radius: 8px !important;
    }
    div[data-testid="stInfo"] * { color: #1e3a5f !important; }
    div[data-testid="stWarning"] {
        background: #fefce8 !important; border-left: 4px solid #f59e0b !important;
        color: #713f12 !important; border-radius: 8px !important;
    }
    div[data-testid="stWarning"] * { color: #713f12 !important; }
    div[data-testid="stSuccess"] {
        background: #f0fdf4 !important; border-left: 4px solid #16a34a !important;
        color: #14532d !important; border-radius: 8px !important;
    }
    div[data-testid="stSuccess"] * { color: #14532d !important; }
    div[data-testid="stError"] {
        background: #fef2f2 !important; border-left: 4px solid #dc2626 !important;
        color: #7f1d1d !important; border-radius: 8px !important;
    }
    div[data-testid="stError"] * { color: #7f1d1d !important; }

    div[data-testid="stFileUploader"] {
        background: #f0fdf4 !important; border: 2px dashed #4ade80 !important;
        border-radius: 12px !important; padding: 16px !important;
    }
    /* "Drag and drop file here / Limit 200MB per file..." es texto
       técnico de Streamlit que no le sirve a alguien reportando desde
       el celular — lo ocultamos y dejamos solo el botón "Browse files"
       junto con la instrucción propia que ya ponemos en cada campo. */
    div[data-testid="stFileUploaderDropzoneInstructions"] div span,
    div[data-testid="stFileUploaderDropzoneInstructions"] small {
        display: none !important;
    }
    div[data-testid="stFileUploaderDropzoneInstructions"]::before {
        content: "📷 Toca para tomar o subir una foto";
        color: #14532d;
        font-size: 14px;
        font-weight: 600;
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

/* Burbujas del chat EcoBot — usamos [data-testid="stSidebar"] + clase
   (más específico que el "[data-testid=stSidebar] *" de arriba) para
   garantizar que el texto SIEMPRE gane esa pelea de especificidad y
   no vuelva a quedar invisible sobre el fondo. */
[data-testid="stSidebar"] .ecobot-bubble-bot,
[data-testid="stSidebar"] .ecobot-bubble-bot * {
    color: #14532d !important;
    background: #f0fdf4 !important;
}
[data-testid="stSidebar"] .ecobot-bubble-user,
[data-testid="stSidebar"] .ecobot-bubble-user * {
    color: #166534 !important;
    background: #dcfce7 !important;
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
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    (-75.5613, 6.2933),
    (-75.5608, 6.2965),
    (-75.5598, 6.3005),
    (-75.5585, 6.3055),
    (-75.5560, 6.3098),
    (-75.5540, 6.3100),
    (-75.5500, 6.3032),
    (-75.5498, 6.2980),
    (-75.5500, 6.2935),
    (-75.5500, 6.2895),
    (-75.5555, 6.2890),
    (-75.5590, 6.2895),
    (-75.5613, 6.2933)
])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

LAT_C = 6.3104
LON_C = -75.5552

# ====================================================================
# 3. SESIÓN
# ====================================================================
for k, v in {
    "lat": None, "lon": None, "validado": False, "fuera": True,
    "direccion": "", "reporte_ok": False, "cache": None,
    "seccion": "info",
    "click_barrio": None,
    "mis_codigos": [],
    "gps_procesado": None,
    "gps_lat": None, "gps_lon": None,
    "gps_solicitado": False,
    "tutorial_visto": False,
    "tutorial_paso": 0,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()

if "mis_estados_vistos" not in st.session_state:
    st.session_state.mis_estados_vistos = {}

# ====================================================================
# 4. MODELO YOLO — YOLOE (vocabulario abierto)
# ====================================================================
# YOLOE es la evolución de YOLO-World dentro de Ultralytics: mismo
# concepto (darle las clases EN TEXTO LIBRE sin reentrenar nada), pero
# usa un codificador de texto que se descarga desde GitHub — no depende
# de un servidor externo de OpenAI/Microsoft que en algunos entornos
# de despliegue puede estar bloqueado. Gracias a esto reconoce objetos
# que YOLOv8 "clásico" (80 clases fijas de COCO) no podía: sillas y
# muebles de madera artesanales, colchones, escombros, chatarra, etc.
#
# ⚠️ Primera ejecución: descarga el modelo (~26MB) una sola vez, se
# queda en caché para arranques siguientes. Requiere `ultralytics`
# actualizado (`pip install -U ultralytics`, versión con soporte YOLOE).
CLASES_DETECCION = [
    # ── Reciclables típicos (equivalentes a lo que ya cubría COCO) ──
    "plastic bottle", "plastic cup", "plastic chair", "plastic bench",
    "plastic bucket", "plastic bowl", "plastic toy", "frisbee",
    "garbage bag", "backpack", "suitcase", "book", "newspaper",
    "cardboard box", "glass bottle", "glass jar", "aluminum can",
    "knife", "fork", "spoon", "scissors", "cell phone", "laptop",
    "keyboard", "computer mouse", "remote control", "television",
    "clock", "banana", "apple", "orange", "broccoli", "carrot",
    "potted plant", "food waste", "wooden table", "couch", "bed",
    "umbrella", "tie",
    # ── Objetos que YOLOv8 clásico NO reconocía y son comunes en la comuna ──
    "wooden chair", "wooden stool", "broken wooden furniture",
    "mattress", "construction rubble", "pile of rubble",
    "pile of garbage bags", "scrap metal", "old tire",
    "broken appliance", "styrofoam waste", "pile of plastic bags",
    "wood planks", "broken glass", "electronic waste",
    "abandoned furniture", "cardboard boxes pile",
    # ── Distractores — para que NO se confundan con residuos ──
    "person", "dog", "cat", "car", "bus", "truck", "bicycle",
    "motorcycle", "traffic light", "stop sign", "bird", "toothbrush",
]

@st.cache_resource
def cargar_modelo():
    m = YOLOE("yoloe-11s-seg.pt")
    embeddings = m.get_text_pe(CLASES_DETECCION)
    m.set_classes(CLASES_DETECCION, embeddings)
    return m
modelo = cargar_modelo()

# ====================================================================
# 5. MATERIALES
# ====================================================================
MAT = {
    # ── Reciclables típicos ──
    "plastic bottle":        ("Botella plástica",           "Plástico",    0.05, True),
    "plastic cup":           ("Vaso / Recipiente plástico", "Plástico",    0.03, True),
    "plastic chair":         ("Silla plástica",             "Plástico",    2.00, True),
    "plastic bench":         ("Banco plástico",             "Plástico",    2.50, True),
    "plastic bucket":        ("Balde plástico",             "Plástico",    0.50, True),
    "plastic bowl":          ("Recipiente plástico",        "Plástico",    0.15, True),
    "plastic toy":           ("Juguete plástico",           "Plástico",    0.50, True),
    "frisbee":               ("Disco plástico",             "Plástico",    0.10, True),
    "garbage bag":           ("Bolsa de basura",            "Plástico",    0.40, True),
    "backpack":              ("Bolsa / Mochila",            "Textil",      0.50, True),
    "suitcase":              ("Bolsa grande / Maleta",      "Textil",      1.00, True),
    "book":                  ("Libro / Cuaderno",           "Papel",       0.30, True),
    "newspaper":             ("Periódico / Papel",          "Papel",       0.10, True),
    "cardboard box":         ("Caja de cartón",             "Cartón",      0.30, True),
    "glass bottle":          ("Botella de vidrio",          "Vidrio",      0.20, True),
    "glass jar":             ("Frasco de vidrio",           "Vidrio",      0.80, True),
    "aluminum can":          ("Lata de aluminio",           "Aluminio",    0.02, True),
    "knife":                 ("Cuchillo / Utensilio metal", "Metal",       0.10, True),
    "fork":                  ("Tenedor / Utensilio metal",  "Metal",       0.05, True),
    "spoon":                 ("Cuchara / Utensilio metal",  "Metal",       0.05, True),
    "scissors":              ("Tijeras",                    "Metal",       0.10, True),
    "cell phone":            ("Celular",                    "Electrónico", 0.20, True),
    "laptop":                ("Portátil",                   "Electrónico", 2.50, True),
    "keyboard":              ("Teclado",                    "Electrónico", 0.60, True),
    "computer mouse":        ("Ratón de computador",        "Electrónico", 0.10, True),
    "remote control":        ("Control remoto",             "Electrónico", 0.20, True),
    "television":            ("Televisor",                  "Electrónico", 8.00, True),
    "clock":                 ("Reloj",                      "Electrónico", 0.30, True),
    "banana":                ("Banano",                     "Orgánico",    0.10, True),
    "apple":                 ("Manzana",                    "Orgánico",    0.15, True),
    "orange":                ("Naranja",                    "Orgánico",    0.20, True),
    "broccoli":              ("Brócoli",                    "Orgánico",    0.25, True),
    "carrot":                ("Zanahoria",                  "Orgánico",    0.10, True),
    "potted plant":          ("Planta / Matero",            "Orgánico",    1.00, True),
    "food waste":            ("Residuo de comida",          "Orgánico",    0.25, True),
    "wooden table":          ("Mesa / Madera",              "Madera",     12.00, True),
    "couch":                 ("Sofá / Mueble",               "Mixto",     15.00, True),
    "bed":                   ("Cama / Colchón",             "Mixto",      20.00, True),
    "umbrella":              ("Paraguas",                   "Mixto",       0.50, True),
    "tie":                   ("Corbata / Textil",           "Textil",      0.10, True),
    # ── Antes invisibles para la IA — ahora reconocidos por texto libre ──
    "wooden chair":          ("Silla de madera",            "Madera",      3.00, True),
    "wooden stool":          ("Banco / Taburete de madera",  "Madera",     2.00, True),
    "broken wooden furniture":("Mueble de madera roto",      "Madera",     8.00, True),
    "mattress":              ("Colchón",                    "Mixto",      20.00, True),
    "construction rubble":   ("Escombros de construcción",  "Escombros",  15.00, False),
    "pile of rubble":        ("Montón de escombros",        "Escombros",  20.00, False),
    "pile of garbage bags":  ("Montón de bolsas de basura",  "Residuo mixto",5.00, False),
    "scrap metal":           ("Chatarra metálica",          "Metal",       2.00, True),
    "old tire":              ("Llanta usada",               "Caucho",      8.00, False),
    "broken appliance":      ("Electrodoméstico dañado",     "Electrónico",10.00, True),
    "styrofoam waste":       ("Icopor / Poliestireno",       "Plástico",   0.20, True),
    "pile of plastic bags":  ("Montón de bolsas plásticas",  "Plástico",   1.00, True),
    "wood planks":           ("Tablas / Madera suelta",      "Madera",     4.00, True),
    "broken glass":          ("Vidrio roto",                "Vidrio",      0.50, False),
    "electronic waste":      ("Chatarra electrónica",       "Electrónico", 3.00, True),
    "abandoned furniture":   ("Mueble abandonado",          "Mixto",      15.00, True),
    "cardboard boxes pile":  ("Montón de cajas de cartón",   "Cartón",     2.00, True),
    # ── Distractores (no cuentan como residuo) ──
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
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode("ascii")
    return txt.lower().strip()


def adivinar_barrio(texto_nominatim: str):
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


def marcar_zona_critica(img_pil, texto="🚨 ZONA CRÍTICA — revisar acumulación completa"):
    """Cuando la IA no logra separar objetos individuales (0 detecciones)
    pero el punto igual queda clasificado como 🔴 crítico por la
    clasificación manual, resaltamos la foto COMPLETA con un marco y
    una etiqueta — así quien la vea en el mapa (residente o admin)
    entiende de inmediato que hay que revisar toda la zona, sin
    depender de cajas de detección que en estos casos no existen."""
    from PIL import ImageDraw, ImageFont
    img = img_pil.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size
    grosor = max(6, int(min(w, h) * 0.02))
    for i in range(grosor):
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=(220, 38, 38))
    alto_franja = max(30, int(h * 0.09))
    draw.rectangle([0, h - alto_franja, w, h], fill=(220, 38, 38))
    try:
        fuente = ImageFont.load_default(size=max(14, int(alto_franja * 0.45)))
    except TypeError:
        fuente = ImageFont.load_default()
    draw.text((12, h - alto_franja + alto_franja * 0.25), texto,
              fill=(255, 255, 255), font=fuente)
    return img


def img_a_b64(img_pil, max_px=200) -> str:
    try:
        thumb = img_pil.copy()
        thumb.thumbnail((max_px, max_px))
        buf = BytesIO()
        thumb.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def fotos_extra_a_json(imgs_pil: list, max_px=200) -> str:
    """Convierte una lista de imágenes PIL (las fotos de APOYO, no la
    principal) a un JSON con sus miniaturas en base64. Se guardan solo
    como evidencia visual — nunca se les corre YOLO, por eso no cuentan
    para el conteo de objetos ni el peso."""
    try:
        if not imgs_pil:
            return ""
        miniaturas = [img_a_b64(img, max_px=max_px) for img in imgs_pil]
        miniaturas = [m for m in miniaturas if m]
        return json.dumps(miniaturas) if miniaturas else ""
    except Exception:
        return ""


def json_a_fotos_extra(fotos_json: str) -> list:
    """Decodifica el JSON guardado de vuelta a una lista de strings
    base64. Tolerante a valores vacíos, None o JSON corrupto."""
    try:
        if not fotos_json:
            return []
        datos = json.loads(fotos_json)
        return datos if isinstance(datos, list) else []
    except Exception:
        return []


def galeria_html(fotos_extra_json: str, ancho_px: int = 90) -> str:
    """HTML de una fila de miniaturas para las fotos de apoyo — se usa
    tanto en los popups del mapa como en el historial/panel admin."""
    fotos = json_a_fotos_extra(fotos_extra_json)
    if not fotos:
        return ""
    imgs = "".join(
        f'<img src="data:image/jpeg;base64,{f}" '
        f'style="width:{ancho_px}px;height:{ancho_px}px;object-fit:cover;'
        f'border-radius:6px;margin:3px 3px 0 0;">'
        for f in fotos
    )
    return (f'<div style="margin-top:6px;">'
            f'<span style="font-size:11px;color:#9ca3af;">📎 Fotos de apoyo:</span><br>'
            f'{imgs}</div>')


def audio_a_b64(audio_uploadedfile) -> str:
    """Convierte el audio grabado por st.audio_input (WAV) a base64 para
    guardarlo junto al reporte. Es un widget NATIVO de Streamlit — a
    diferencia del truco anterior de "dictado por voz" (que manipulaba
    el DOM del navegador vía JavaScript y fallaba silenciosamente en
    producción), este graba el audio real y Streamlit lo entrega
    directo a Python de forma confiable, igual que un file_uploader."""
    try:
        if audio_uploadedfile is None:
            return ""
        return base64.b64encode(audio_uploadedfile.getvalue()).decode("utf-8")
    except Exception:
        return ""


def campo_codigo_residente(key: str) -> str:
    """Campo opcional de código o teléfono del residente — NO es un
    login real ni una contraseña, solo un identificador que la persona
    puede volver a escribir después (en otro navegador o sesión) para
    encontrar sus propios reportes en el Historial. Se guarda en
    session_state para no tener que reescribirlo en cada reporte
    dentro de la misma visita."""
    valor = st.text_input(
        "📱 Tu código o teléfono (opcional):",
        value=st.session_state.get("mi_codigo_residente", ""),
        placeholder="Ej. tu número de celular — para recuperar tus reportes después",
        key=key,
        help="No es una contraseña: sirve para que más adelante puedas buscar "
             "tus propios reportes en el Historial, incluso si cierras el "
             "navegador. Cualquiera que conozca este código podría ver esos "
             "reportes, así que no escribas datos sensibles."
    )
    if valor.strip():
        st.session_state.mi_codigo_residente = valor.strip()
    st.caption("🔒 Ver el aviso completo de tratamiento de datos en "
               "ℹ️ Información → 'Aviso de Tratamiento de Datos Personales'.")
    return valor.strip()


def verificar_api_key() -> bool:
    """Chequea si la API key de Anthropic está configurada en
    st.secrets. Se usa para avisarle al ADMIN (no a los residentes)
    si el chatbot EcoBot va a funcionar en modo 'sin conexión'."""
    try:
        return bool(st.secrets.get("ANTHROPIC_API_KEY", "").strip())
    except Exception:
        return False


def tamano_bd_mb() -> float:
    """Tamaño actual del archivo SQLite en MB — como las fotos y notas
    de voz van codificadas dentro de la misma base de datos (no en
    archivos externos tipo S3), esto ayuda a vigilar que no crezca sin
    control con hosting gratuito de espacio limitado."""
    try:
        return round(DB_PATH.stat().st_size / (1024 * 1024), 2)
    except Exception:
        return 0.0


def difuminar_personas(img_pil, resultados_yolo, nombre_clase="person"):
    """Difumina automáticamente cualquier persona detectada en la foto
    antes de guardarla — protege a vecinos o menores que puedan quedar
    de fondo sin querer en un reporte que va a quedar público en el
    mapa. No corre un modelo aparte: reutiliza la MISMA detección que
    ya se calculó para clasificar el residuo, así no cuesta tiempo
    extra ni una segunda pasada de IA."""
    try:
        img = img_pil.convert("RGB").copy()
        hubo_personas = False
        for r in resultados_yolo:
            nombres = r.names if hasattr(r, "names") else modelo.names
            for box in r.boxes:
                idx = int(box.cls[0])
                if nombres.get(idx) != nombre_clase:
                    continue
                hubo_personas = True
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img.width, x2), min(img.height, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                region = img.crop((x1, y1, x2, y2))
                radio = max(10, (x2 - x1) // 5)
                region = region.filter(ImageFilter.GaussianBlur(radius=radio))
                img.paste(region, (x1, y1))
        return img, hubo_personas
    except Exception:
        return img_pil, False


def calcular_phash(img_pil) -> str:
    """Hash perceptual de la imagen — a diferencia de un hash normal,
    dos fotos casi idénticas (misma foto recomprimida, con un poco más
    de brillo, etc.) dan un hash muy parecido, mientras que fotos de
    sitios distintos dan hashes muy diferentes. No usa IA, es pura
    comparación matemática de la estructura de la imagen."""
    try:
        return str(imagehash.phash(img_pil.convert("RGB")))
    except Exception:
        return ""


def distancia_hash(hash_a: str, hash_b: str) -> int:
    """Distancia de Hamming entre dos phash — entre más bajo, más se
    parecen las fotos. 0 = prácticamente idénticas; 20+ = distintas."""
    try:
        return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)
    except Exception:
        return 999


def distancia_metros(lat1, lon1, lat2, lon2) -> float:
    """Distancia aproximada en metros entre dos coordenadas (fórmula
    de Haversine) — para saber si dos reportes están en el mismo punto
    físico del barrio."""
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


LIMITE_REPORTES_DIA = 8

def contar_reportes_hoy(codigo_residente: str) -> int:
    """Cuenta reportes de HOY para aplicar el límite anti-spam. Con
    código/teléfono, el conteo es real (persiste en la base de datos).
    Sin código, usamos un contador de la sesión actual — más débil
    (se reinicia si cierra el navegador), pero evita al menos el clic
    repetido en cadena sin necesidad de pedir datos a nadie."""
    hoy = datetime.now().strftime("%Y-%m-%d")
    if codigo_residente.strip():
        return sum(
            1 for r in st.session_state.reportes
            if r.get("CodigoResidente", "").strip().lower() == codigo_residente.strip().lower()
            and r.get("Fecha", "").startswith(hoy)
        )
    return st.session_state.get("reportes_hoy_sesion", 0)


def verificar_limite_reportes(codigo_residente: str) -> bool:
    """Protección simple contra spam/inundación de reportes falsos:
    máximo LIMITE_REPORTES_DIA reportes por día."""
    n = contar_reportes_hoy(codigo_residente)
    if n >= LIMITE_REPORTES_DIA:
        if codigo_residente.strip():
            st.error(
                f"🚫 Ya alcanzaste el límite de {LIMITE_REPORTES_DIA} reportes hoy "
                f"con este código/teléfono. Si es una emergencia real, contacta "
                f"directamente a la administración."
            )
        else:
            st.error(
                f"🚫 Ya publicaste {LIMITE_REPORTES_DIA} reportes en esta sesión. "
                f"Espera a mañana, o escribe tu código/teléfono arriba para un "
                f"conteo más preciso en vez de por sesión del navegador."
            )
        return False
    return True


def verificar_fecha_exif(img_pil, dias_max=20):
    """Revisa la fecha EXIF de la foto (cuándo la tomó la cámara/celular
    realmente), si el archivo la trae. Muchas fotos NO tienen este dato
    (capturas de pantalla, reenvíos de WhatsApp que lo borran, etc.),
    así que si no está disponible simplemente no decimos nada — esto
    es un aviso adicional, no una verificación garantizada."""
    try:
        exif = img_pil._getexif()
        if not exif:
            return None
        fecha_str = exif.get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
        if not fecha_str:
            return None
        fecha_foto = datetime.strptime(fecha_str, "%Y:%m:%d %H:%M:%S")
        dias = (datetime.now() - fecha_foto).days
        if dias > dias_max:
            return fecha_foto, dias
        return None
    except Exception:
        return None


def buscar_foto_reciclada(lat, lon, phash_nuevo, radio_max_valido_m=40, umbral_hash=6):
    """A diferencia de buscar_posible_duplicado (que busca CERCANÍA +
    parecido para pescar el mismo reporte hecho 2 veces en el mismo
    punto), esta busca la MISMA foto usada en un punto LEJANO del
    mapa. Una foto casi idéntica a más de 40m no puede ser el mismo
    montón de basura real — es señal de que alguien está reciclando
    la misma imagen (o una bajada de internet) para inflar reportes
    falsos en varios puntos. Por eso el umbral de parecido es más
    estricto (6, no 10) y no revisa solo los reportes activos: incluso
    si el otro reporte ya está resuelto, la misma foto en otro lugar
    sigue siendo sospechosa."""
    if not phash_nuevo or lat is None or lon is None:
        return None
    for r in st.session_state.reportes:
        if not r.get("PHash") or r.get("Lat") is None:
            continue
        d_hash = distancia_hash(phash_nuevo, r["PHash"])
        if d_hash > umbral_hash:
            continue
        try:
            d_m = distancia_metros(lat, lon, r["Lat"], r["Lon"])
        except Exception:
            continue
        if d_m > radio_max_valido_m:
            return r, round(d_m, 1), d_hash
    return None


def buscar_posible_duplicado(lat, lon, phash_nuevo, radio_m=30, umbral_hash=10):
    """Busca entre los reportes ACTIVOS (no resueltos) uno que esté muy
    cerca en el mapa Y tenga una foto muy parecida — esa combinación es
    la señal de que probablemente sea el mismo residuo reportado dos
    veces, no dos residuos distintos que por casualidad se ven similar
    (ej. dos montones de cartón en barrios distintos)."""
    if not phash_nuevo or lat is None or lon is None:
        return None
    mejor = None
    for r in st.session_state.reportes:
        if "Resuelto" in r.get("Estado", ""):
            continue
        if not r.get("PHash") or r.get("Lat") is None:
            continue
        try:
            d_m = distancia_metros(lat, lon, r["Lat"], r["Lon"])
        except Exception:
            continue
        if d_m > radio_m:
            continue
        d_hash = distancia_hash(phash_nuevo, r["PHash"])
        if d_hash <= umbral_hash and (mejor is None or d_hash < mejor[2]):
            mejor = (r, round(d_m, 1), d_hash)
    return mejor


def aviso_foto_reciclada(resultado) -> bool:
    """A diferencia de aviso_duplicado, esta NO deja opción de publicar
    de todas formas — si la misma foto ya se usó en un punto lejano,
    algo no cuadra, y forzamos a subir una foto real de este punto."""
    if not resultado:
        return True
    rep_existente, d_m, _ = resultado
    st.error(
        f"🚫 **Esta foto ya se usó en el reporte {rep_existente['Código']}, "
        f"a {d_m}m de aquí** ({rep_existente.get('Sector','')}, "
        f"{rep_existente.get('Fecha','')}). Un mismo residuo no puede estar "
        f"en dos puntos distintos del mapa — sube una foto tomada en ESTE "
        f"punto para poder publicar."
    )
    return False


def aviso_duplicado(resultado, key_confirmar: str) -> bool:
    """Muestra el aviso de posible duplicado y devuelve True si está
    bien publicar (no hay duplicado, o el usuario confirmó que quiere
    publicar de todas formas)."""
    if not resultado:
        return True
    rep_existente, d_m, d_hash = resultado
    st.warning(
        f"⚠️ **Posible reporte duplicado.** Encontré el reporte "
        f"**{rep_existente['Código']}** a solo {d_m}m de aquí, publicado el "
        f"{rep_existente.get('Fecha','')} ({rep_existente.get('Estado','')}), "
        f"con una foto muy parecida a la que acabas de subir."
    )
    return st.checkbox(
        "Sé que es un punto o residuo distinto — publicar de todas formas",
        key=key_confirmar
    )



def extraer_telefono_whatsapp(codigo_residente: str):
    """Si lo que el residente dejó en 'código/teléfono' parece un
    número de celular real, lo devuelve limpio y listo para wa.me
    (con indicativo de Colombia si hace falta). Si parece un código
    inventado (letras, muy corto, etc.), devuelve None — no forzamos
    nada, es una detección simple por conveniencia."""
    if not codigo_residente:
        return None
    digitos = "".join(c for c in codigo_residente if c.isdigit())
    if len(digitos) == 10 and digitos.startswith(("3",)):
        return "57" + digitos
    if len(digitos) == 12 and digitos.startswith("57"):
        return digitos
    return None


def link_whatsapp(telefono: str, mensaje: str) -> str:
    return f"https://wa.me/{telefono}?text={url_quote(mensaje)}"


def boton_whatsapp_html(url: str, texto: str) -> str:
    return (f'<a href="{url}" target="_blank" style="display:inline-block;'
            f'background:#25D366;color:white !important;text-decoration:none;'
            f'padding:10px 16px;border-radius:8px;font-weight:700;font-size:14px;'
            f'text-align:center;width:100%;box-sizing:border-box;">{texto}</a>')


def es_residente():
    return st.session_state.validado and not st.session_state.fuera


def set_ubicacion(lat, lon, direccion=""):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.validado = True
    st.session_state.fuera = not POLIGONO_COMUNA2.contains(Point(lon, lat))
    st.session_state.direccion = direccion


def _abrir_img_subida(uploaded_file) -> Image.Image:
    """Abre un UploadedFile de Streamlit como imagen PIL leyendo los
    bytes directamente — evita problemas si el mismo archivo se
    necesita abrir más de una vez (ej. para mostrar miniaturas y luego
    volver a abrirlo tras elegir la foto principal)."""
    return Image.open(BytesIO(uploaded_file.getvalue()))


def analizar(img, imgsz=640):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            img.save(tmp.name)
            tmp_path = tmp.name
        return modelo(tmp_path, conf=0.25, imgsz=imgsz)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _iou(caja_a, caja_b):
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
    ordenados = sorted(objetos, key=lambda o: o[1], reverse=True)
    conservados = []
    for nombre, conf, caja in ordenados:
        if any(_iou(caja, c[2]) >= iou_umbral for c in conservados):
            continue
        conservados.append((nombre, conf, caja))
    return conservados


def procesar(resultados):
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

    ESCALA_ALERTA_OBJ, ESCALA_CRITICA_OBJ = 15, 30
    PESO_ALERTA_KG,    PESO_CRITICA_KG    = 20.0, 50.0
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


def _img_tutorial(b64: str) -> str:
    return (f'<img src="data:image/jpeg;base64,{b64}" '
            f'style="max-width:100%;border-radius:12px;border:2px solid #4ade80;'
            f'box-shadow:0 4px 14px rgba(22,163,74,0.20);">')


B64_TUT_MAPA = "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osB0VFYF5a6hNrnl2zzrFHFCVlMpCL8z78j+IkAD24NQPp2vzxRb7hogCoZUmy3EajdngfeDHHv36UWA6TenmeXuG/G7bnnHrinVyj6LrRnkmEpEhASR/PJMo8xidvI2DBHAI6Y96vQ2GqxR3yefI7S222OWSX5hJtwCMcAZ56Zz60WA3aK5a/07V7YXMsVzcvGEURLHKST90EHnOc7jnHfr2qdNN1hZUPnOF3gxg3BPkr5hJDf38pgc5x+tFgOizzjvRXMf2NqcMYKF5Z5baKKWQ3T5DBmLkcjrkY+h/G1badqyaVeCW6Zr6SNEjbzSQMRqDjsCWDc475osBtLNE8hRZEZxnKhgSMdeKfXMW+iakkvys1vBJMXdBcEvtMikgt1J2gjrTodL1mNy09xLcJ52XjWcoJF+bBU5yMZXI46fmWA6UEHpzRXNLpGqQyFYXdE853VvtLYUtLu3EfxDadu31z65ro4mdolaRBG56qG3Y/GkA6iiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigApaSigYtFJRQFxaKSigLi0cUlFAXClpKKACiiigQUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFc74h8Y2ug3aWYt5by7cbvKi/hHvXRVxmvaTrVh4tXxBotvHeM8flvE/VeMeo4wB0rKq5KPunpZbSoVa3LX2s7Xdk30TfQ3fD3iO08RWbzWyvHJEdskT/AHlP9RRr/iOz8Ow273Su5uJPLRUx16kkngAVmeDNDv8ATmv9Q1MLHdX77zEmMKMk9uOp6Vsa3o1prdgLa7to7hVdXUP2IPOD24zTpuTinLceIhhaWMcY+9TXZ+Wtn1sy1ZXcWoWMN3ASYplDqT6Gp6bFFHBEkUSKkcYCqqjAAHQCn5rQ8+XK2+XYSilzRmgnQSiilzQGglFLmigNBKKXNGaA0Erh/GHxf8J+CNXTS9UubiS8KhnjtovMMQPQtyMeuOvtXcV87fFj4JeJ9e8fXeuaCkN7b6gVd1eZY2hYKFOd3VeM8flTVuoI990jVrHXdIttT024S5s7lN8Ui9CP6Htiq+reItO0WaCK7lxJMyqFUZIBONx9hWV8NvCUvgjwDYaHcTrPcQ7pJXT7u9mLELnsM4p2t+FpNS15b9fLkQxiMo5xtIzz9Oa5sVOpTpuVKPM+x14SFGdW1d2idOORkcg0VFawm3tIYS24xoFz64GKmzW61WpytK9kxKKXNFMWglFLmjNAaCUUuaSgAooooEFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUZoAKKKKACiiigAooooAKKKKACiiigAoooyPWgAoozRQAUUZozzQAUUdelFABRRQSAMk4FABRRketFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUiufMKEdsg0tMkTcRk8E4B7qf8KEXHcY10CP3cczA9GWMkUnn+WvEE7E/wDTM1JZyxxaPDNK6xxpCGZnOAoA5JPasDSviFomreK9S0WK+sQbTyBDKLxG+1GRScIPUEY4z1pmhuQTb5WUq6MRnDqRVioZ9/8AaEYX/nk381p/lZOWbNAD6CQBk9Kj/wBUfVTTwwPQ0AN80Y4Vj9FNHnL0w27+7jmn0UAMIaQ4YbV9O5p9FFADHYqyn+HvTlYN0NDEBSSMioujByMAnjFAExOBk9qgkwWyD1qeoHXDkAE+gFAmMprOqnBPPoBRl+yY+ppVXaPUnqaQhpZm4Clc9z2pwAUYAwKWigAooooAsRtuX3FOqCNtr+xqemNEZG2TI7/40/hB2ApkpwyH3pijzHIPI60DJGYAggZY9KRY+dzYzRsK8g5NMwC2D87UATnOOBmoTgDGR+J60jKB2waQ42E8gDqR1+goAfHkMue42n6iqzja7D0NWFIKY2FRnIKnJBqNigb/AFTO5OBvPf6UCYlujGQPjA2nBPc0vm9EBI2jBAGcUuzEu9iWcNxgc8fyFKxDNlVxuGcHsc4oAQbiCScD0IPNVrxpIUSWPaJA3UgnAwfYmrJ5B49/Wo7zIsmdAxYEcBiv8qaBkkQBjVARs7YGKnRNmec5qvAT5KZBB46nJHAqyrh847Uhg5IXjqeBWdqTl5orVOg6+9aPWRB+NZcLebqksp5CZb8ulNCZfgiVAFUALGNox69zU1Ii7Y1HoKWkMCMjBqJsxfMDx6VLUTtub5T0+UH3P+AoAZK7Bh2Y9P8AZH+NJuOwDt6VK8aBOABj9ai/gIzwe9AE0T71yBgdqfTYyNgx+NOJAGScCgAqJELLuBwakAdug2j1PX8qTbGnHmEe2aAE8sn7zE0/hR6AU3Kdnk/75/8ArUhZV52lj6v/AIUAO3g9Mt9BS/OeifmaiMzH+I/hxSgKULMM49TmgB+WHWNvw5pPMXOM8/SoVdlPDED060/zFc4kjDD1A5FAriyndGAOdxApYiNuO9RupjlQA5BOVP4U8KxcMRtoGSUUUUAFFFBOAT6UARPKVYjFSB1PGRmgZQjGN7DJJ7UHfjBKuPRhQAtFN+Uf3o/1FKA5HylGHrmgB0X8Y9/6VC3+pXjNSZ2qUQ5Y9T6UuBtx26UARnl0wfxqSoxG2Rk8CpKAGFSp3J+IpRIO4wadQVBOSAaAE3r/AHh+PFG9f7w/OjYuc4FRyAKcAHPr6UASnpTaUDC49KSkZzCiiiggKKKKACmNuZsDkjpxwPen04dKEXDcZZIp0yBCAymIAg85GKytN8I6fpvifVNajRGk1EQjyzEoWHy1IBXjPOcn6VqWUKGxgJB5QfxH0qbyU9G/76NUaEMv/IQj/wCuTfzWpKidFTUExnmNupz3WpaQBSBFByAM0tFABRRRQAVEzOHC5AB71LUMuWfB4A6UANz8xy2R9aC/7s9xnikGRg5xz1oI3EgZ59Ox9KAJ42LLz1psn3lx96iIg5HXHOaUf645/CgBJU/iH41DVqoGjYE4HFITGUUqqWzjnFJ0oEFFFFABU6SAqMkA1BRQBK53nHG0dxSbWR/lGaSIgSYyOlPeVVGAwz060xkbysTjpQcAA4xjoe9D4AGMH6UqxMwznFACMct1yTQVYkr6gj9OP5UMFjI+cbj2pu9DKrZz8wwQDQMFyU39gM5ojJaTfkAY4JobLKIdvAPzE/Wl3gjhKBDm4OCN+TnIJHb2pOuPlAAGOM0gbqcY5pRyp9PT1oGLjjPbOMfhUdyjSWb+WqEjGFbkHpT8fKfbiorgf6PJnPQn5etMB8ELxosTqq4AJC9B7CrKqFGBWbYEKkuw5OQSwbcCe5BxWkhygNJghC20u3ZV/wA/yrM05dwmc/xEL+Zq9dNts7hvXiq+mpi2T/aYt+Qx/Wn0F1L9DMFUknAFNZwBxyc4A9TURPzKdwJP8XX8u1IYOxbO4c/3ew+v+FNR9rhid3GPQD6VMm0goAcDnnvTJIsDI6fyoASR95A7dqQqu4BTz7d6QnvkYBwTT41yxxx7nsKAJBtjAHf270jNswzDn+Ff60q5/g+Uf3jyTQYlI759T1oAgMjsfmbPt2oU7CCO1I6FDTc5/wA/pQIsCdcDg0jyKycc1Fjik6UguOJzUn/LCowCxwKlkXCADtQJEJ460o5IpVGACRweKeI+6sPbFFh2EBVswyfcJ4PoaVGaN/LkOfQ+tRtyee9PH75PLY4cfdb1pgTUVHHLu+VxtcdQf6VJQMKST/Vn6UtNyD85+6DwPU0AOb/XH6CikAPJPU9aWgApCik5Kg/hS0UAAAAwBiiiigAooooAKKKKACkZA/WlooARQVXBOaSnHpTaRnMKKKKCAooooAKcOlNpw6UFw3I7dGk0iNElaFmiAEigEocdRkEZHuKzLbQdVguopZfFmqXMaMGaKSG1CuPQlYgcH2INaMX2mGJYkELKg2gkkEj8qd5l3/cg/wC+j/hVGgS/8hCP/rk381qSolWVpxLLsBClQFJPUj/CpaQBRRRQAUhYL1NLSFVJyRk+9ACeYvrn8KiZt/GMMD3pZAu8AKOPTihmby87cJQBGQfT6nj+dPV9o6c+tN3EY9x3FADdGA4PTPJpgL5p38ce3rT8neC4xiosBj8owPpk05mYnn06envSAnVgwyKU8D3qBHKcYyP50YOMZweozQABtiljwCPypplQcHGRxmnhGZBjpTHJVdmR17c0ANdxuGCGz/d5ppZznauO2TTxnAGQc8jmhgc9s9KBDAgIy3zE+tLsAGAWA9M06ikIfDEm05UHPrzTxbxDog/KnRjCCklfYvvTGRtt8zA6d8VOTtXPpVUetSXD/ucA/MaBkIO+RnI6nAqXKlCMfMemOKjUYUDj8/zp457Hn0oBC7nwdq7g/wA2QOPfk0wlRjLrk9lBY05x8mGj3lWxzk4yM9KQO2MDKAdgu2gBQrMuRHKcHuAP50qqeMoRzyDIP6VHk475+tLgYB/z0oAewCqpwmTnOZD/AJNRAKenkf8AjzVIvyqCBxlhz74puffJ9M0wJnAd0A6FO31FPTAXAOQKrtcQwG2WWRVZlIAJ69P/AK1BuIkt3dpVVAeWJ4GaQEeotiwUd5GzUtsBFGgPRUHP15qpqEqS3McSOpEZw2D0IqwbiHDsJEZAT34OMKP1piJGZiwOCCf/AB0f4mmgcYGAcdqRGjmAKSK+75uDgn3xTiCDz1680DAkLjOR6Ggs6gsPxz60gPIzkUpVgeobPPrmkAu35AxPzDoBT1x5Rx3YKfpSQ/PluuOKdjCMB0Dj+lAD6KKKAEZQ4wahaIryDmp6KAKtKq7mAp0gwx4wKWJSWz2FIkFxE+MgilbdIM4wBSiL5yT0qSmUQRnnaeh7U9hsO5encVEeG+lWF+ZOe4pCREyYGRyppAm0BhyP5VJGeCh6ilRdqYNMY1wJYy38S9cfzp0bll56jg02PKSjPTpmkQbLhk9Rx/n8aAJHOI2I9KCMSAdlXikk/wBW30pzf63/AICKACiiigAooooAKKKKACiiigAooooAKaxbcFX86dRQA1GLKc9RRTSCj5HIanUjOYUUUUEBRRRQAUnmIvDHH1FLTh0oLjuIHU9GH50F1UZJAFBRD1RT+FII0U5CKD6gUzQQM7fdTA/2jRtkPVwB/sj/ABpGYv8AKv51IBigBmx+0rfkKA5HDI24eg4NPooAZ5mfuox9eMfzpHlwMYKk/wB7j9aeXUHBNBK9CR+NAEW6MJ94Z65PSgSqsWOv4U+QZG4dqjOMDDHnqDQAigyZIxwfpipGiyny9ah4Xnbgn8KfjK5KksemWoAcMRjBG5qjzuzuJ59BSx78ll5x60oK7uVKn6UANIG75c5oJBwq9u/WjOWyMAfpRkbgRQBIrlOGBxUcgDMSuAPUU5iCNuMkcimAYB7sePTH+f8AGgACjbnPUUAg0o3OcEjjjNP2rt2jqBnNAmR0qruYCkqaFcDd60hEhIUZ7Co1XflmHXpRMeBk8ZqQkKuewplEEkYUA9agXn52J9hmnyyM52jknoMZxT0ISAsFQndxlf8ACgQ3Py9jj3FKr4I5x+IoDnptjAP+xRvccYjGP9imMWRx853YG4DIbHamxujMIy4YMcYJP6VJ5j+WMFQSxH3cdqTzJFIJcYzzwKAI1cYxlSR1x/8AXpwHA7/rTmd9zAlGAJHK00lWAzFG3HbigA6oOnL+ntUyxqUHHb1qMlAkfyOBz0Of505ZAnysc8Aj1x9KQFa4sorgRySbiVYoMHAAyf8A61EelWq+ZGFbYQCwJ7Zzj+dW04hyf7+f1pQQTJj+7/jTuKyMQabavqHl7W2quSd2SOM96mXR7UMTtbcduee5OTT4P+P65Pfaf5Vb3Akn0Cn8j/8AXp3YkkNg0y2t5hKinepJBJ9iMfqasuTwB1NKTjtxikjyVyeT61JQ0xcElu9NETqcgg+xp7sVIGM0CUdwQfpQAsabF560H7sn1FI0g2/KeaBnyxnku2fw/wAigCSkoooAKKKKADGRzRRRQAUUUUANMalskU6io+ZGIBwooAV/lkDYOO9PByMioyhXkZI7g0kcgU7T06igCVhuUj1qNwz7XQZdfvL608MpOAaCoJz0PqKADDSDbtIB6k8UwtuuAV5GMUjk7mBZiMDAzUiDCAd6AFooooAKKKaylsfNgUAOoqP5oyeCVp6urHA60ALRRRQAUjttUmlpkhGQDj1Oew70AOQHb8xJPvSkgdSBUIZgOC3/AAJMn9KUIzHJ492AJ/LoKAFkI3rzxTqaIipyCo+iAGnUmZzCiiiggKKKKACnDpTaaznoo59aC4bj2YKOaYZCwwqnNKqHdljmn0zQaqBVx3p1FFABRRQeAcc0ARnAlbcODTHCcBDj1Oaa77jnuPYkUoV2HCnHvxQAhHzH5h69sUuccAjn8x9aPLfptP8A31SZcHJRsexzTAUHCnHC55pOduGGKUEkAjPPT/Cg47Z+hpAJyAMEgjuacx34yMkd6QEN0I9CaOwP6npQAmxS24AKfU9PpS7mA5YD0AUUfrx3pM8tg5/SgAKs7bsA49sGhmGeFOOKOQAO2KUrjKk8jpgUAIQQCB9M0/KmIYIz/OojvzkbcZ9/50iuCcdCM8GgQ4datDgcVTWVN3OcCpGuhtwqsSenFAIbIXkm2rgcZ5ppZ0GHBH0FOiBEgZuvQDtT5hhs5oAiRSSWJwccCpUJaBlxgqdwzmot3zYUEn0A/pUiBo5wQAB9QOKYxucjj+tLz6c/jzTmjcMdoyueDuFIYn7Lx/vDigAJzCRgghh3PNNGcncSAOvJz+FPEb7H+UAnGPm96BGxVsgZ4I+YdqAGFmclgODzyT/hSkHH0pdj+in/AIEKHikJJ2sfoRQA7Yd21cfKoGfrSg5wxztIx0zgjtSMxWR/mKZPcdaT5SJAWDDG8kHoRQA/ev2cZ6FiOB70sRDO4Gfu0yRQkMSjgZJ/z+dLbf6xvpSEUrcf8TGUeuP1FTJ80bH0TH5//qqG3OdTc/7o/lVxQFgDjAIHPoR6GmwRK4yhANNSRdoB4/CmBWJcA8Z6dKeqkcMqketIY1mHmKc9KdJ80fHOeKVY1XPcGmhFLEg4QdaAAKr9BhR1PSnj5m3YwMYA9qZ5itjPCjouKkoAKKKKACiiigAooooAKYZBnABP0p5GQRTIyApB4I60AIzlxtUHmnqoUYFN830UkUCUZwwK/WgB9NaNW9jQJAX2inUARrGQwORgelSUUUARyKPMU9j8p/pSxkglD2pzrvQr09/SowxJVjwehFAEtFFFABRRRQAU1kBHHBp1FADA5Xh+PejzARwrn/gJpzoHXBqIBHbLDO8ZxnpQAYaQ9jj15UfQd6csXPIUDOcAk5P+e1SAADAGBRQAUUUUAB6U2nHpTaRnMKKKKCAooooAKUEdO9JTNu52IPzDtQXDclopiuSQrDBp9M0Cimszg/cyPY80nmg/dDE+mMUAPJCgknAFR8ynkEJ796UIzEFyOP4R0p9ABwB6AUAgjIOajmBxnPHpQC6rgLxQA8uqnBNAGCaYI8jLck0bXTlTkelACOgQ7l4JprK5bazFvYYoZtx6mhQcFgcYoAQAYweMDgCmgsByDwetP5CHjhu5o+U4/Ik0AIGDE8jON2TxigAjB4X0PajAwf4snr7D/wCvTSpyu0gADJGO55oAd0Geg9e57UHGCR+A9aRQzbgcA9aME4Yc4HX/APVQA0tkcf59KfkNEVZQQTxQF3AgA4pU25+bj6UANBVVPy8dAcUinO7jH4EUpGQSBwfWkwEz+XH1oAPpjPWlXpuc/L0+vtSry6qScHjrTXkPBAAzwFzxQAucx7QFQZ5CEimsq7RkKMeo/wAaUmQ8AIc9+eKeLZQpLEs35CgCJBHggbcH0FO2DGNo9elMKKzEYx7jrS/OgwVJHqOtMQ8INjjaOSvb3o2Afwj8RTQ58uQhW428dM80nmN2ib35pDH7AOdvT2pAqg8HBz2OKTeR1hb86bvkJyFx6ZoFcnJdVDK7ZYfWhHkLhTtbd1+WoiZMYWI59e1PVmihMjfffhQB+tMZO8gY7VXcQeSRwKaZdkEjtjCDqOKbEV27YmyT3I6VXumE8gtIzhF5kb0oAh09HKvMerthfr6/hzV5iAAgGVTHHqewpFQsm0YVR0QrkAUqY8xRtC4BGB2P/wCqgCRF2rgnJ6k+ppaKKQCNzhf7xxSMN529FWl58zj+EfqaYZAsj/WgBcxq2OAaeDnpVY5Jye9Km/quaQrliikUsR8wxS0xhRRRQAUUUUAFRvhZMnoRg1JQSAOelADIs7Oac23+LH40xph/DURJPWgVyUAedxwAO1SVXiOJR71YoGFFFFACMwUZNQFsOewJyPY1MULPkngdqSYZhbjPegBysGXIBH1paBjAx07UUAFFFFABRSMwUZNJ5g/uv/3yaAHEZBHrVdVLHcOu0fpxT3fIxgqD7cn2Ap6LtBJGCe3oPSgBw6DPWiiigAooooAD0ptOPSm0jOYUUUUEBRRRQAUzcDKvGCDtPvkZp9RvwxPsG/I//XoRcNxy8yHP8NSUxxtYMPoacGBGc0zQWijrRQAUEgDniioiQ53MdqD1oAXmR/8AZFSVH5hxiONvYkYFIzyocfKfwxQBKCD0NRSORJgE03zWDfMh+q0Aq2d5Oc9qAF38HKg5pvBUH+L3pxUBMhsjPNG4M+WGB04oACG3Bc7scikLclmGTjGB60AYDEHaR0Heml+Ni/Nu7DrQA4j5wjdeF6dR3NBYhCxIVXOeaQCRW+XsOUHOfrTdgVN6rg/3ep+oz29qYCyNG6gIpz7jAFMwxb/V78DJKjkClzlcjBz0/wA+lSoCAp3Al2yTnqKAIslM7dyevHFHmEkAEsD/AHhkVIR5gxkb+g9TUbZIB5yOoxQACaM8Zw3oO9PQryWO3HY9T6U3+MMCcdT/AJzSkbgpyuRwAeOnvQARvulX5CvVs02NCxUtwTwB6U45WM7xt3HHPpUc10lpF5rAkZwAMc0ASnLcd+nFCllX7xP4VVTUraXBD8nnaVOfyo/tC0BK+byMjGDz9KLCuido243feI+uKdhsAAfUf5FMW9hXays8iFA5YD5VU9CfypiarZrIwaXb3yQfUj8Px9aLBdE/PlBQoJY5PPpx6UL8oOV/Cq66rZK+TPgYP8J9fpVxSGmyDkEf4UDITjeemOfSlQbjg9P8+9HDH72DShfkPc9B9aQE6qSRyQFyeD15obbIBnaW/hpmNvyKfkQc+5p6ABfMPYUwILqQ28YSJcyy8DFJb2whQJncc5c+ppbW5eZGZ1yA5UYHIqvJfzGeSC0tjc+SdrSGQKA3p70m7Gc5xhqy7uYlgMcGmKcuD6tnP0HWqTS6o5/49bWNfRpic/ktOsr0zTSw3ESC5ix0J2lT0Iz+VSpIlVotpa6+RobweFyx9qDu7kIPzNNLtvClgB/s8UqqjDOB+NUbCGVUT5ATnuarnnk9zk09kO/bnpzSMpGM0CHMflC96BmPBHI7ikyu0EE7velLZwMcntQMnByMjvRVcSsoC+lSpKH9jQA+iiigBquCxXoRTqa67hkdRQj7h796AEeXacAc1EzlutLIP3hplIkKesTN14FM71Zz8oIGfpQCGNGBGcDkd6BMu3vmnM20/N0PFV+hIpjJTN6LSGZvao6KQrk0cmThjUlVasq25QaBobF8u6P+70+lPpjcTqf7wIp5pjCiiigBrqTgjqPXvUIUIcHdgdQScj396sUyQAlPc4/A9aAFVFU5A/GnU2IkxKT6U6gAooooAa7EYA6mk8tuoc5of5XV+3Sn0ANRtyc9R1opo+WUjs1OpGcwooooICiiigAqKUgsVBy2xuKlpj7yRtX7pzyevsKEXHcR3DDHOMZ+tNG0vjPHucYpjNghAmeMq+e1WEjUKMjcTySRzTNBqSIuQXAHbmnedH2bcfQc0jLtYMq5HpSo5LkYxQAjGRlwEwPc0RxgKGbLN79qkooAKKKCQoJPQUABAYYNVjGiyEY3DqecVN5jN91c+9R4zubOMfzoAaIQwJC4x15PNAUbsBtmfT0oY7AOce3rQpOS2Bj0PemAqIr8M4IHYDGaVmRGUqMKvpSsqKo4BYj1/WmGQDHzLxyAM5J7UgBzvdQcjcdzeoUdKJAxAkPB6jHan+Wu5Vz1U5PrxTs7osH72dpHvQBGygkKpUP3Uccn0pWG4nLYA+7QxxK7YBxkj9BTSgXO0ZHQ88GmAjYYbs/X39f50qvN2LY//V/gaTG04yRz3FHzFSpz7ZoAUtIAejHGOgNDY3nOOAF4H5/1pD8oGRk9ev5CnMMOwz0J70AJyOFYjHHHIokhWRQ0kSMByOxH9KAMHk5HuKeJCo6gqPWkBnXSQQL5qW5eXcFGfU5Pb8arG7tGVVNqwIPK7RkHpxz1yuO1bBGMDoT8xx69qTAznHX261VxWM03tnlRJatwu0BlA+XOPXBx6VC1zp5CPNayAg7lVRwc+v4itg7QMnGKVQIjhlLbuinkD3ouKxU+x2zLH/o6gFQ2CORycVYPQexP9PanSNuKvjGVHek79akewmAQOnXr7flUyYBBP3Y13H61Fj3P50+PmADJ+eTH4D/9VAXHAOqFy3JGSPepGHKx/wAIGT70ORsIJ6ikzl1b+8v+f50DMiW+ayiuYo/9e0m2IHuT/gOamhtBZWyxp8/qT1LHqfxNUYJFvdfluhzEiskfvxgt+NavVoR7g1O7uckHzy5+my9P+D+VhjY3HGCFG0Ee3/16p3qOhS8hG6S3zle7J/EP6/UVaRSoHy57nBpRyMnnHHNDVy5x5lYkjmWVEmjbcjruU+oqQMWYGsy1b7DdPaNnyZMvBnkD+8v9fzrSGQckAjPv0pp3Lpz54679R0hy49R6U1iT3/KkPI6cc96cGXPT8aZqNGCxzkDtxS4B6fePfinsvBwOajwQDkUAHBB4464pf6dhR+uPyoHBGecUATx8IB6U6mp3p1ABTWjB5HBp1FADFIdcMORTHixyCMe9PkGPnBwf51A7HdkGgB2xvSpIgynBHFRozhQu7Bp+0yclvwoFYRyX3cjA9KjIxjnI7e1ByhI64pXccZIGBigBKKKKQgp6JvBGcU0DJp0eQwPb1oBCsWLrGeTnOam5zUDsPNVwSAOtSs+G2hSx68Uyh1DEKpJ6CkVgy5B4pkjBkwp3EnjHtQA0lnOCM4/hHAH1NKImz2HbO4n8vSnRHO4DkZzn+dPoAAMDAo7UUUAFFFR8u5wxAHpQAOdxCD8akpFUKOKWgBkgyAfQ0tOIyKbSM5hRRRQQFFFFABSFNxySSOwHFLSiguO5G6CMZUAqOdp/pTowQW+bIBwKSVsEf7ILf4fzp6LtQL6UzQWo0/1retSZpj/LIrdqAH0UUUAICT2x9aG3Y+XqfWlozQAzys9SSabKAkeF+tSMSBkDNQt8z5wQewoAZnDE/lSooIPYgUzBJODk96Vm2r07cUAPA+Xrglcn3/8ArUnU/gSOeTT2A+YnjB2jFNQ/OuT1OMevFMAB+63zYBzgEGhdzvv+6QCDz0PY/lTFLBAVXHH1ApdoOCSMDmgABbGB2RqljA5fGBTVycDlcgdPQf40KTsIA+UdqQDnKuhI61HhgpbBH/6qczqVG2lRwv3mAHvQIY33Aox6f5/Klf779evpTiVyrAEKpySeB+FRqSRnbg5PvQMcELKcChRz83AHJ4pQ22M4ODmkySjEkZJA75xQAZzknGT1o4AzxSHI7Y47cU5F3Ef3ep56UAA+TaTjeemegH+NMDZYlmBz/n1pS+6Que9NAHUk/SmArgeWjdvu5H1+tGc81IIm2k8ZPUEcEelREbSMZ2npnqPY0mJi1InEMR9GOf1qOqiSZu1gL7gpd8AHj2JoQkXvNbqV/SqWpXG+GCyhk2zzkrkHBRB94/lxVkD5TwMH2NY1gkk1296IBiaTcG/uoOB347mlLsZVm3aC6/l1/wAi9DCsOoNFGoVUjAUdsYxirGQjZYN8qkj5sj0pk3yalC3ZlK05hkOCeAAOnvQCVtEG6PoS6cd+RSiL5vkdTj04pB0z6H86acHqAaBkN5befAQreXOhDxHrhh/TtUlpMl3arKFKNkq65+6w6j86kLEAg/MOmG/xqm/+g6gswYGG6ISQE42P2Offp+VTs7mbfJLn6Pf9H/X6GhjgBcHj/PNSxyKw2sAGFRt12sCD6EU3bkjBIIHG30rQ6i1s460FAU2mq2+VeVfPs1S+c7fdQfQkmkA5oztwB9KhO4HkdOKkWZvMAbAU8fSiQZl9DigBYmJbBFS02NQo4p1ABTJWKgY6dzT6ikk6rigBjYIyCSfem/Tinp8ylfxFIDg4x+FIkaqnI4696fuIJG4cHBwpOKkEYAIJyD2qInY+c8+vr9f8aZQjbh+PcdD+NDfI5VDgjgt1/ClPH3CynuAabt2jpigQnqQMEclR0PuP8KXrTs4VSByDmmBR/CJcfUUAKG2kU4ksQqnGT37Ui/LkqCp9ScmlLFwRgAkY3Y5IoBDdwaM/6zafcHNN++gwNqHnA6/iaep+Q/Q8fhTUHyLj0oBjg2cZVSe7EVL5RzyQQevy4J9qjRPnANWKBgAAMCiiigAooooACcKT6U2IYT60kp+THqaeBgAelABRRRQAHpTacelNpGcwooooICiiigApw6U2kKbuSSR/d6ChFx3I5SMsByQhOB9RTvP/ANg/nTWALEKAP4Bj9al2L0AH5UzQj81icgAe/WmkuSASSD7VOEUds/Wh1DqQf/1UANEhyAy4z3p29d2M81AZSJBvXDD9feh+W3DoaBFjNMlGUz6UkaHGT+AqSgZFG+Djk5qQqGxkdKXAz0ooAhljIJZcYxUZG4hMZHTjvU7sOVPHvTCm1iEIyy4BzQA5QrZJ6Fsj3prv++4AwAcn8KTJwG6DHHtSDhWPfAHJ9etACKpIA9B19Kcq7mUjk4yMj7o9aRFBYr6nn3oBV4uVYsfmOOKAHshQMwOc8mmFk28ZVV6nFZhk1VY8yRsykAkHHy89MipFl1BolCQAKFztII55469ff3p2FcugBs+XliOx6ilGF+4R/vY5JqGyluJDKJ4hHuGFHr14z/Wn7WXByxXHK98UAOPLfNu+p7UEhVXryaRGGcZz/T2p31pDF6Y4P5UDOHAz0zwPQ0hO0E8cetCENIhz14oAX6fypVI+c+iGlWMNGjHjjn3pSv8ArQOgUCgCDGOvepI9qvhqaVKkZp0YAIY9BQBKzMucDJPSohGWj3FgMtnn6YqbcdxGOOxqtLdon7uIh5BlQq9uM4P5GgBXHl5LkY657VWhjbzRN56yIwO0LzjJ6H9acFu7l13xgRjaynHXOCQfbrVmK2S3QpCnUknPJNPYRT1OUw6bMyj5tuF4P3jwP51XMBhit4UeRQgA+UHBxjqKn1Q7rizthj5pPNbjsoz/ADIqNkWe+UE52Y6Ngj6j0+lQtZHM/eqN9rL9f8ie6Um5tcddxqQ5YfKOSc49ugpkrbtQQAZ8tST+NP3bAvbKAE9aZoDAg89/Wm+5yRSsx9cU1cFv1OP/AK1AC5GPT1pk0Ec8LQyj924wfpinA5OfxNKQRkdMikJpNWZDplw7xvb3GXmhO1xn7w7MPqP1q4VI3KTkKeTWZe5tpY75eqERyDH3kJx+h5rTmID8/KCBz2P40RfQKMnrB7r8ugE4OQfwo4BGeMUdCFwST2pwXY4D7eRnj+VUbgGUZJHXr6U0sdo24YDoSecUuMtwCF9ewpwUDJbIK96AHxSBht6MDjHr71IGBOAQSO1VH2/ICTjPHBH5U8RpsDBSpHcUAWKhkRslscU4OyffGR/eH9akPK/WgCsMjnOKfuU43Ak+tSqgUAYquylWIpCJFKA5LEn3qOTGSwPWnhdqEkc9s0zcRyR+PrTAB97Oc596TdkjJzSt1zkdelIoOS3BPvQMexGwc01Ax5FN54/M5qcEBVA4BoEMKEd+aVFwfU0KN45PSmsSr5BoGOkGGUZqOFSyKM4OKDk/Ng5zxSQsVkIPY5/A0CJmO11J698VLVd23S5FTI4YYzzQMdRTGJZ9gP1oEWMfMaAH0EjOKKR2UD5u9ADZOqn3p9RoNzluSB0zUlABRRRQAHpTacelNpGcwooooICiiigAprvgEA4x1Pp/9enUgXdJkjhen19aC4biRLj5sY4wB6CpO/Sio5N4YFc0zQkoqMO6/eHFPLgLnNACSKrL84yKhtycFSMHpzT0Jdid2PanSr8uR1FAh5IHU4oqq7ljtOc/56VLFJ8pDHkUDJcgdTUDylsAAjn160hbOWNN7ehPrQA47iA+M889qQscA/3cfpSH+EClfb5bfxMeP/r0AOYqGZTzycfzpnHlNgngg4I7ZpZMCR+mcA9qUkfPkLgrjr3NMBhVyvykLJn5TjPPTNUzb6hGgjR1TK/Nubfz0ycj9Kvn5Sw6s3ygDqv1qrdxyzJGEfYW2sx57Z9D7ChCZXntb4gKLoEI2R0GME4HA+lPVNTIwboLwcAAH6dvpUR0ybYyNfSPu4JbPI/PrTjp04LeTdO7YA2sxABzzn2qidSRVv1ibMimUsNuMceuOP55p9lBdozxzzIzKAFGOvqc1HBp8iOhe6aVU5wSTu9+vrV7Ge3UUmNIRkxLyCrdBu6Ggh4z84yMZ+U5/SnBiF2nDr/db/Gl2rIPkJDA/dY8/hSKGKyuMqcilwdpwMFuB7DuR/KmeX+9AwVf8uPf1qQOnzYIB6KCe1AEsQxHz096iLDIbkjcT7EdKkV/l+QZA7ngVG4QIvHmkDoDheeaQCbTv2YLkccdKkBZPvRkL3PWklYl9uSAAOBwKUrtwEyJD6f1oAZcI9wmYipWMhtp6P7VHDagS+ZIP3smWYjj6Y9qtfekwPup19zShFUkgYJpgMaJQpKLhhyCKQSYBC8ljlc+h5/xqWoeBF2ByVB9Bnn9KQGUzrLq1zOWYrbxiMHjqfmPH5VNaJm7aTzvMUIDjOQpPam6WgltRMRzcSNN+GeP0AqS4cRRMsQVPMbaMDH1NTHY5KWsebvr94RHck9x/fOB9BUpUB2GBxgc/SgRxxBVHROW9hTA4ZgMgk9TnvTNR3GQcYB9DQDgZxn8abu4HFKFyMhhyeB0z9KQB3zjJPSlJJ4I5o9Vx81Lk9voKYFLVeNMm47qf/HhWjnYdw+7nlex/Cs/VudJuT2C1okHhlOOmKS+JkU/4svRfqOYt825ycEjAOBTCFG1QH4GOMAdaMZd/wDeOPzpc+vf9f8AOao6ReQAOdoGMHqfWk3g4UscA/c6k/Q9xShdwGUyME9evpSL1HlqFbuck/lTAX5iCHOZSAQnof8AGlZzgEqVXtxilWFQMMSfWmuFTfgkjHOTzntSAGkJXA4z2HWmJIUyVBI9KVckgZqRQMGgCVGDqGHQ1FI/z8DkVHvMJYZwrcg+lIG3Hv8AjQK5M5B2jOc0sgIGQKjRNx9xSMxDEHgenpQMfjIB9aFX5s4qMH5uCOakR+2eaAGMPm4H+BpdpzkHn8qGlPcAGkUHjNACls8jg0qnew9qUkbCMfQUxR1IoAV1AbpxSOqj5x1H8qUkHp83HORSeWTjFABjjjkGk3du/rmkBKjYQOpx64pyD5ufqaBE6LtXpgmnUAgjIooGFR/fk9VFDDdKFPQCpAAowBQAUUUUAFFFIWwcAZPpQAp6U2glh1K0UjOYUUUUEBRRRQAUo579KSmsdpLr1X7w9RQi47klFAORkUUzQKhkTDDHANTUEA9aAI0BQ4K596QsX+XGOalprIG56GgAZMgYOCOh9KauCWVlAbvjvSD925znBpWKyr1KnsaAI+Ax6kUmcew70uMrkYyDg+9ICOcjgDnNACKRuJOfcjtTzHhgB0YjilRV3Z/hHrTS2ZN393n+gFACMw+Zg7HLYPHr6UBN5aNmODgZI7g8UqpgbdyjaeST7UbUaRVXcPcY7d6YCnBdmUlmycYGaQ4xgFTgAdfz/nTdwabO7ghvwGKDnAIB7Dj19KQCrjJPZcZ9/alLMwGSePTigr8vyD5Qe/c+tIME4HNAAenpSEhTyOlI6kjKttI6EcUm4g8xtn25FAD8jbnPFNbBAHUD1/oacpQMSc57gDrSF1AO2Nh+VMLj1kYKVYbh056+/NIrKudseP8AeOaYDlscgn1707APXnHP40ABYMvzZdh1z0/CiPDyKuOpyfpTSnAww99wxz9aFIjSV3yCox7gmgBZJQpLFgCxJGTgUlrO0qHhg5A3yFdvPoKqNAZ2z58c1uxGRnOCB0/z71oxALGEVRtAxQIlVQqgDoKKTcAmegFKDkZFIYtZmpyPFpkjJ96RCi/7zNj+taDybeAMmsq+YyX9jaDnBEh/AcfqR+VTLYxru1N266ffoW4kEFsEQcKojX8OKpzESXqx4ysI/M1cmlWFSf4Y1/Wq1lEciV+rZc/0pit0Q69u7bS7Bprp0ihiXzJJHYKo+tcd/wALc8Li5Ef2m625x5xtvkP9cfhWH8Zr64LaVp29vs0pkmkXPDsuAAfpk15BM5kmYnoDgD0ry8TjJU58sFsfe5Nw5h8ThI4jEN3leyTtZJ27PXQ+ndM8SaNrLFdO1GzunXkqhG4fh1rTI5BPPH4fQV8radPNaXH2m1kaG4gIkjkU4INfS+gai+q+HbC+Zdv2mBJSPQkc/hW+FxPt7pqzPjMww7wWOqYNu/LZp900mvnrqaWeACNyjoO4/GgFQR8zdO681JhXG5efpTDgNgKQO9dhzFTVF3aRcgOD+6Y9x2zV9MmJHKEAKDz3PaqWp4/s66Uc/um/lVqAf6JCEYFdi9ehJFC+ImH8V+i/UeudwPzc9yaP4M//AFv89KMfN05PQGhsbSBg5OMDnirOgMkIWIIL4VSOpFSwgjJIphXJcgcA4x6jpUsYO0HORikBEzMGPPTtQ3LsBj+8M+oHP6VI5G4KRwe9Rsuxg3JwcjFADVIyD2pVPPJJFBAUkY4B4+lGF3Ejn0oAc2OMkH1xTHPzlwDtIx9KdsPpn27UqjYT60CsNyT3pOjUi8FhjgHge1LnAxgknjpQCA85IBPTmkBLHCjvgmnNCFVWckj+LHapVUKMIPloGRDI4cbCe/r+NSAYwPSpCAy4IBB7GomjaP5oySB1U0AJJgDHeiNDnPakJEh3Ic8d6VCdwz3oEJyHIUe1OVXxkHGe1PK45A5pC+3IGAaBjJBu+WQc9j6UwEjKk5x39RT8GTGSPcE0jR7WHPynj6GgTHRNhsetSs4UVGISDnNOP+uX6UAhI+WLHr6VJTXjDc9DUe5ozg80ATUU0SqTjpQ8gQep7CgYrttHHU9KjEiqOOSepqMsTnJ60lIVx2dzg+9TVAv3h9anoM5BRRRQSFFFFABTGby33Ag54Ip9McbsgLn1NCLjuNSQK5Cj5PT0NTggjIqCJwFIZeR39aFk2nI+4f0pmhPRRRQAUUUUABx0NMeMEZA5pFQ7tzHkdKc7hBz3oAhKkDK8igxoU3KdrD070n8WScUqkED5cjrzQAm5VbD5Ve3pSsVcnYQRlQMH8aXb8pI6scAUz5GRl2gqD94/xN7UAP3AIRtyegPqaa+1MoeBjH1NBA2kjpjH+RSspL8D5lXB+uKYABkPjH3eMn+tK29DvfA9ADnn39KjWN/Kfqwb5R3I9acp5ypwT6UASMv7lQrZA7im7DyoAz1Pakzg5xk+q8E/0pyvtb5TnPZuCfxpAM6HuDRgY56e9PLgt+8Qr6Z/xprbVJA60AN70DPej6D60nUcd6RLHom/nOMcg+lNLHdyAC3THHNLkY/+vTWBzjkf0NMY8jA5H157VDezLFYAOxyxyDjoO2aeFdmUNyrHBPTFV7ts6kEZvm7BWwQPyx0zTQMfbRqIchQPM+bI4+h56CpgcHGcN6etAHGOvH5UEBhjbmgZKXyoUcHvmnLKuDz0/WoiwUgFSy9j3H+NSosZXKjIpAMwSh9ZDis+3/e61eXDLzHiBB+p/mK08qCZWOEjBrIs5fK0o3TH95cs0gH+8eP0xUvdI56usox+f9feSS5u7gQKfkQ5c+pq1tKsq49QPpio7WIW9sN/3j8x+tLI/DZ+90xnp/8AXplHN+MfCkPi3SFgaX7Pd27b4ZduQrY5B9jXjWp/DfxTp/my/wBm/aYweTbMJPx2jn9K+iFJAGDkgdMdKQZc8Lk98da5K2EhWfM9Ge7gc+xeApOjSs49Lq9vTVfdsfPfh/wFrusTi3+wXFlASPOubiMoFHsDyT6CvfrG0i07T7aztxiK3jWNPoBjmrJHzFC2SOSfeowScnBHaqoYeNFaHgzc6taeIrS5py3f9bIUj5tynaw5z61J5gY7SpDY/Omdeg/Ck6nfuC4PBIzk10jI71gun3LNgYiYYHqQamtBjT7dewjXP/fNVdRcf2VdKMFRGe3JOOtW4QBbRcYPljr9BSXxEQ/iv0JN2RjHfOaHeC22tNcwxEj5PMYL9etBxk9MdR9KwvF3hlPEX2Jnhlk8lWxsYLjOPX6UTqwox56ibS/lV38kdNpS0ja/nobkM1tK3lw3sEjnnargk/gDVqExyKRHIj7Dsbac4I6g+9cX4a8ExaLr0N8tvOhQMNzOCORjtWiTqcVnrFjaWd1FdTzTSQXG0eXzyDuzwf61VGpSxK5qXMl/eXK/u7GdRzpfGr+mp0bwlnyGxVf7RatdGy+1Q/asZMW4b8Yz069K5Kax1t7LykS+8l3cooLK0Z2AL1l3YLZOS2Ae3Ipv9iayPMureKWO+lDMZWfJ3G2Rc9eDu3DtzXSqMesjneIn0gdo6L5ihpFDsMAHqSPSkjWJzIiSI5jbDgHOw4zg+nBz+Nczpmm3o1SxuriG6aKKaQIH3Dyg0YHIMjEqSD1PU9MVdFtJeL4kt4ceZJcqACcBv3MXyk+h6fjWU4qLsnc3pzc021Y1LO9s7x3jtb2C4ZPvLG4Yj8qVr2yiu1s5LyAXJ+7EZAHPpxnNc9ollftqFs09hLbfZmLPPJKW3/KwKhc4Gdy8Lx8vsKkubC7/ALN1LSxp8ks95O8kd0Nuwbmyrsc5BQYGMfwjFEIqW4VJuK0R0j24cgnIPqOKRbbbzuyS2TXGeRrF3FdPppvVmEtyksskxKSKJSFVBu4OAcYxjnnmpotK1WaFxI16sSw3DQoJGiKvhNg++xPIYjJ9e2K09ilvIxWIb2idS97Y/bfsLXkAumH+pMg3n8OtTQohiDRuHRhkEHIIrlWsL86goSyuQ0s8csqyeW9u+AoaTdw6OADwO4HY1WtdG1SHRXS3juoJYbeCJEaVuzt520BhyR3yO2CKPZRtuHt53+Hudts96hNzbeekBuYvNk3BE3jc2372B3x39K42XT/EBiiCyXfk4k8kBW3xOWG0kebyMdNxPoRTn0W/t78XlvYyvPZzXNwmW4lLOhwpJ43JvH1pqjH+YTxE+kTroPJllmEE8cgRikiqc7H9D6HBHFPEDDBDdPauIn0XWbaC5ghhuMzSSTGSFvvSmKPBwHX+LfySQMdKvaONQn1cOVvPOiusTyPLmLy/JGU25xneQenXJzSdFWumOOIk3yuJ1rRk9DimfZjnJauS1ay1l77UTbxaibx3Jtp4rjZCIfLA2YLY3Z3ds5IOcVCuj6jeXjKsep22l4laGGS6YSK3loBkhicF9xAJ6gnvWB1nYKiMXUSKxjOGwfunGefwINMgaG7hcQXMcy8ZKHdjIBH6EH8a5DTdC1E6orXMF7H5kouLhxOyrI32ZAM4btIG4+naq1no2uBiFt9Qhv5fJLXDXH7rYLdFkDDdy24EZxnODnigDvyQioJJFVmO0Z43H0H5UpiJfcD244rg3sda1Ceznmsb6M2n2UJ5snSVY5ld8BuQGZMnuPWpbXSdXuJ7OJ4tTgtd0IvRLdNukkAfeykMTtPGcYB4wOKAO5CHHJ5qn9ssp702sd9btcLkGIOCwx14rC8OWerQapqMdyl0sMiNtnnkJYPuOABvZWGD94BeAARVOx0rUlnSzk054zHIjC5Mx8tArKcqvT+FsEcndzjJoA6e6uLOydEur2CBpPuCRwpb6ZNSYiFyLc3EfnspcR5+YrnBOOuMmsu6intdV1KVtMk1BL6JEjC7SowpBjbJ4XJznpyao/2ZrA1RdYEUKNBMka2yoS5hA2MFbdjB3M4BHYVqqcWtzmdWSdrf8Ma6appUhYJqtmxRSzASqcAdT17UQ6rpNwkjw6rZyLEN0jLKpCDpk88VkaTo2o2i6I1351xBCW3QEIPszkMFfIGWXBIIJPUGpxpt3HbJKbRpRBqk100AxmRCX2kZOCRuDAH09ap04LRMiNSo1dr+tDatngu4RPbXMU8WfvRsGHHuKnrO0qCZtS1G/e3e1iufLCRPgMSoILkAnGcgeuFFaNYTSTsjVNtXYUUUVIBRRRQAUdM+9FFACMobGRnHSk2Lzx1p1FA7sFG1QB0FLk0lFAXYuTSZoooC7AcAAdBQeRg0UUBdjSikYI4pdgz060tFAXYmxcjjpSBFAAA6dKdRQF2IFAIIHTpSCNR2p1FAXY3YvHGMDAwaVlDDkZ9+9LRQF2JsX0o2L6UtFAXY0RqAABwOlHlpn7tOooC7ECKAQB160hjUnOOadRQF2IVBOTSbF9KdRQF2IEUAcdDmmNbxO4dkBYZw3epKKAuxojUDGKNi+lOooC7EKg446UbQCccZ60tFAXYjqJI9jD5cYx0qEWcAWJRH8sQAQZPFT0UC3dxvlqWDEcjpSGGM/wAI9afRQAzykHQY+lKI1HTPr1p1FAEfkR/3c/U04RoO1OooAZ5Kf3f1pPJj4+Xp05qSigCGW0hmiaN0yjjaRkjin+UmANvSn0UBs7jSitjIzin7jSUUDuxdxpd7etNooC7Hb29aN59abRQF2O3H1pASDkYGfakooC7F3H1pdx9abRQF2KCQMDj6Uu8+tNooC7Hbz60m4+tJRQF2O3n1o3t602igLsdvb1pAxGcY55pKKAux29vWjeabRQF2O3t60b29abRQF2LuNLvb1ptFAXY7e3rRvPrTaKAux24+tG4+tNooC7Hbj60bj602igLsXcfWkoooAKKKKBBRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFGaACikyKMigBaKTIoyKAFopMijIoAWikyKMigBaKTIoyKAFopMijIoAWikyKMigBaKTIoyKAFopMijIoAWikyKMigBaKTIoyKAFoozRQAUUUUAFFFFABVC4vbl742WnwxyzIoeWSViI4gegOOSTjp+tX6paR/wAhPWD/ANPKf+iY6TJd20u43yde/wCemm/98Sf40eTr3/PTTf8AviT/ABrXop8pfsl3ZkeTr3/PTTf++JP8aPJ17/nppv8A3xJ/jWvRRyh7Jd2ZHk69/wA9NN/74k/xo8nXv+emm/8AfEn+Na9FHKHsl3ZkeTr3/PTTf++JP8aPJ17/AJ6ab/3xJ/jV291G105YzdTJEJG2ruYDNNtdWsL6cw213FLIF3FVbJx60rJuw/Yruyp5Ovf89NN/74k/xo8nXv8Anppv/fEn+NRxeKbFr2e3kDReSzpuyGyVcIRtUlgSSMAjmrI8RaUWwLxMbd24ghR8u7k4xnbk468UWRHJDv8AiReTr3/PTTf++JP8aPJ17/nppv8A3xJ/jS3HibTLe2eYzO5RHcxrExcBcZyuMjqOuOoqaXXdOhd0lnMboFJVo2BO4gDAxzyQOO5p2QckO/4kHk69/wA9NN/74k/xo8nXv+emm/8AfEn+NJdeJLSz1cWEqsDhCXLKMbs4O0nOBtOTjipR4h050PlT+Y4Rn27GBAUZJOR8o5HJ9aVkHJDv+JH5Ovf89NN/74k/xo8nXv8Anppv/fEn+NL/AMJJY/borbfnehZnAO1CNg25xgnLjp071Y/tnT/tCQfaVMjtsAAOAdxXBOMDLKQM9SOKdkPkj3/EreTr3/PTTf8AviT/ABo8nXv+emm/98Sf41r0Uco/ZLuzI8nXv+emm/8AfEn+NHk69/z003/viT/GteijlD2S7syPJ17/AJ6ab/3xJ/jR5Ovf89NN/wC+JP8AGteijlD2S7sxJbvUdNAl1GK2ktcgPLblgYs8ZKnqvqQePStOq/iD/kWdT/69Zf8A0A1NF/qU/wB0fypbOxFuWTjcpTXl1PeyWmnQxO8IHnSzMQiEjIUAcs2Oe2ARzR5Ovf8APTTf++JP8adof+u1X/r9b/0BK1aEr6jhDnXM2ZHk69/z003/AL4k/wAaPJ17/nppv/fEn+Na9FPlK9ku7Mjyde/56ab/AN8Sf40eTr3/AD003/viT/GteijlD2S7syPJ17/nppv/AHxJ/jR5Ovf89NN/74k/xrXoo5Q9ku7Mjyde/wCemm/98Sf40eTr3/PTTf8AviT/ABq7qWowaVp8t7dOEt4Rl29B9O/OOKTTNQi1Swju4GDRSDKsD19fpzS0vY0+rPk59bbXKfk69/z003/viT/Gjyde/wCemm/98Sf403T/ABNZ38/lFXhY/c3FTu5YdicH5TwcVJN4l0uGGVxcGTy4jKQiMcgIHwOMZ2kHHXFFkY8kLXv+I3yde/56ab/3xJ/jR5Ovf89NN/74k/xq1Dq9jcXBgjn/AHoUsVZSvQAkcjqMjI6jPNQW+uQywRTzQy28VywW2L4YzZBIwq5I4Gee1OyH7OPf8Rnk69/z003/AL4k/wAaPJ17/nppv/fEn+NNt/E1nMuWIjAZQzsSEAMZkBDEYPyjmrSa3p8k0UQnIeXG0NGy9c4zkcZwcZ644pWQlCD6/iV/J17/AJ6ab/3xJ/jR5Ovf89NN/wC+JP8AGteinyleyXdmR5Ovf89NN/74k/xo8nXv+emm/wDfEn+Na9FHKHsl3ZkeTr3/AD003/viT/Gjyde/56ab/wB8Sf41r0UcoeyXdmR5Ovf89NN/74k/xpj3d/p8kZ1KK3a3kYJ59uWHlsTgblPYnAyD36VtVleJv+RYv/8ArkTSasrkzhyxck9i4xwK4XxZ8R49B1BrCztRdXKY8wu2FQntx1NdvOcBq+e/FZLeL9VJ/wCfh/51jWm4rQ8zMsROhTXs9G2dX/wt7Uv+gZa/99tSf8Le1L/oGWv/AH21efUlcvtZ9zwfr+I/n/I9C/4W/qX/AEDLX/vtqT/hb+pf9Ay1/wC+2rz0mko9rPuH17Efz/kehf8AC4NT/wCgZaf99tR/wuHU/wDoGWn/AH21eeZpM0/az7j+vYj+b8j0P/hcOp/9Au0/77aj/hcWp/8AQLtP++2rzukzR7Sfcr69iP5vyPRP+Fxan/0C7T/vtqP+Fx6n/wBAu0/77avL7e+E91JFs2hSQD64re07w/f6tbLPaKjK1ylry2CGYZBPt71rNVab5Zep0TrYyElCTd2r9Dsf+Fyan/0C7T/vtqP+Fyan/wBAq0/77auNbQbwXjWq7XlWB5yAG5VSQQOOT8pxilm8OalEFAhMjkBiqg/KCivySABwwGM9ajnmR9ZxXdnYf8Ll1P8A6BVp/wB9tR/wuXVP+gVaf99tXF3Hh7VLfcWs3dUjWVmT5gFZdw/HHb2NDeHtUVY91pIJZGKrEVIboDn07+uaOeY/rOK7v7js/wDhc2qf9Aq0/wC+3o/4XNqn/QKtP++3rgr/AE+bT/s/n4DTxebtwQV+ZlwffKmqmaPaT7kvF4haOR6P/wALn1T/AKBVp/329J/wujVP+gVaf99vXnFITR7SXcf1yv8AzHpH/C6NU/6BVn/329J/wunVP+gVZ/8Afb15vSUe0l3D65X/AJj0n/hdOqf9Amz/AO+3pP8AhdWqf9Amz/77evNqTNP2ku5X1yv/ADHtXhL4rx63q0enajZpaSznbFJG5KM3ZTnpmvSFORXy3oTEeI9NI4xdRf8AoYr6ghORW9KTktT18DXnVi1PoS0UUVseiFFFFABVLSP+QprA7/aEP4eTH/hV2qNzYzfbPttjcC3uCoRw6b45QOm4ZByMnBB70mS7pproa1FZH/E+/wCfnTf/AAHk/wDi6P8Aiff8/Om/+A8n/wAXT5i/a+TNeisj/iff8/Om/wDgPJ/8XR/xPv8An503/wAB5P8A4ujmD2vkzXorI/4n3/Pzpv8A4Dyf/F0f8T7/AJ+dN/8AAeT/AOLo5g9r5MqeL/CEHi+2tYZ7qS2+zSGRSgBzkYxzVHwl8PLTwlqH2qC+muCITAFkUDgsDnP4Vs/8T7/n503/AMB5P/i6P+J9/wA/Om/+A8n/AMXT53awe18mJP4X02fzN0bAysXcgj5mMnmAnIwcNnGexIqFfClq01x58jyW8mNkK4RVIj8vPAHOM9MDnpU//E+/5+dN/wDAeT/4uj/iff8APzpv/gPJ/wDF1N12I5o/yscPDtmROZHmlkuI3jlkZ/mYNjJ4GM/KoH0pieGbJb03TPPJMWDlmYdQyv2Hqo/kMCl/4n3/AD86b/4Dyf8AxdH/ABPv+fnTf/AeT/4ui67D5o/yslu9AsL66kuJ4y0kgCsQcfKAykfQh2Bqv/wi1h9nihJk2RbsBQik5GOSFB6fn3zT/wDiff8APzpv/gPJ/wDF0f8AE+/5+dN/8B5P/i6LrsHPH+VjT4XscnElwFwwVQ/CElSWHHXKA857+tPi8OWcUiOJJzhg7gvkSsHLgtx2ZieMUn/E+/5+dN/8B5P/AIuj/iff8/Om/wDgPJ/8XRddg5o/ys16KyP+J9/z86b/AOA8n/xdH/E+/wCfnTf/AAHk/wDi6fMV7XyZr0Vkf8T7/n503/wHk/8Ai6P+J9/z86b/AOA8n/xdHMHtfJmvRWR/xPv+fnTf/AeT/wCLo/4n3/Pzpv8A4Dyf/F0cwe18mTeISB4Z1PP/AD6y/wDoBqePiFP90fyrPksL6/KpqV3C9urBjDbxFBIQcjcSxJGewxnvWlS3dyLuUnKxS0P/AF2qjv8AbW/9AStWsiexuEvWvNPuVt5pABKkib45MdCQCCCBxkHp1o/4n3/Pzpv/AIDyf/F0J20CE3BcrRr0Vkf8T7/n503/AMB5P/i6P+J9/wA/Om/+A8n/AMXT5i/a+TNeisj/AIn3/Pzpv/gPJ/8AF0f8T7/n503/AMB5P/i6OYPa+TNeisj/AIn3/Pzpv/gPJ/8AF0f8T7/n503/AMB5P/i6OYPa+THeItEXxDpf2CScxQs4ZwBncByB1HfH5VJoejRaFpws4G3RBiwHPGevUmof+J9/z86b/wCA8n/xdH/E+/5+dN/8B5P/AIujm8jT61Pk9lry726X+8l/sGzWwjtYvMhWKTzVeMgPu55zjn7xH41GPDWni2MGJdhG37/OPKEX/oI/Ok/4n3/Pzpv/AIDyf/F0f8T7/n503/wHk/8Ai6V/Ix54/wArJrbRLa2uxceZNK43EB2BUM2NzYA6nH064xmkttDt7ZrfbNcOls26FHfKxjay4HHTDHrntUX/ABPv+fnTf/AeT/4uj/iff8/Om/8AgPJ/8XRfyDnX8rG/8ItpxgEB85oQqjyy/HEZjz652nH4CpV0G3+0xzyT3MzqUZt7jEhQkoWwB0J7Y980z/iff8/Om/8AgPJ/8XR/xPv+fnTf/AeT/wCLouuwc8f5Wa9FZH/E+/5+dN/8B5P/AIuj/iff8/Om/wDgPJ/8XT5iva+TNeisj/iff8/Om/8AgPJ/8XR/xPv+fnTf/AeT/wCLo5g9r5M16KyP+J9/z86b/wCA8n/xdH/E+/5+dN/8B5P/AIujmD2vkzXrK8T/APIsX/vEQPrTf+J9/wA/Om/+A8n/AMXTTY3t5LG2pXcUkUTBxBBEUVmHILEkk4POOBn1pN3ViJzcouKW5cufutXz34q/5G3VP+vl/wCdfQsq5U15f4x8AXV/q0moaa0ZaY5kic7fm9QfesK0XJaHlZpRnVguRXszzOkNdOfh74g/54Qf9/hSf8K98Qf88IP+/wAK5eSXY+f+rVv5X9xzFJXT/wDCvfEH/PCD/v8ACj/hXniH/nhB/wB/hRyS7D+rVf5X9xy9JXUf8K88Q/8APCD/AL/Ck/4V34h/54Qf9/hRyS7D+rVf5X9xy5NI2dp24B7Zrqf+Fd+If+eEH/f4Un/CuvEX/PCD/v8ACnyS7FLD1f5X9xxNvZTQXDSmdXZz83y4zXRaX4jv9GtXgtCirI+9iVyTwBj9K0/+FdeIv+eEH/f4Uf8ACufEX/PCD/v8K1qTqVHeX5HRN4mpJTad1porfkZkniS9e+N2FjSU272wKZGFYsSRz1+Y1YTxfeh42khhl8vB+Yt82EVPm5+YEIMg8HJq1/wrnxF/zwg/7/Cj/hXHiL/nhB/3+FRaZKjiF0ZSPiy58tQLO2Doo2OAw2t5fl7gM4+5gY6cZoi8XXcdxJK1rbOXlabkMNrFVXIIORwo/M1c/wCFceI/+eEH/f4Un/Ct/Ef/ADwg/wC/wp2mVy4js/uMTWNYn1q4jnuI40kRWX5M4OXZ+/uxrPrqv+Fb+I/+eEH/AH+FH/CtvEf/ADwg/wC/wpcsmQ6NWTu4s5Q0hrq/+FbeJP8AnhB/3+FH/CtfEn/PCD/v8KOV9g9hU/lZydJXWf8ACtfEn/PC3/7/AApP+Fa+JP8An3t/+/wo5X2H7Cp/KzkzSGut/wCFaeJf+fe3/wC/wpP+FZ+Jf+fe3/7/AAo5X2H7Cp/KzB0P/kYtN/6+ov8A0MV9PwdK8g8H/DK+tdagv9XaJUt2DpDG24sw6ZPQAda9hhXCiuikmlqexl9KUItyVrktFFFbnqBRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUABGaheEN2qajvSC1yr9lX0o+yr6VaopE8qKv2VfSj7KvpVqigOVFX7KvpR9lX0q1RQHKir9lX0o+yr6VaooDlRV+yr6UfZV9KtUUByoq/ZV9KPsq+lWqKA5UVfsq+lH2VfSrVFAcqKv2VfSj7KvpVqigOVFX7KvpR9lX0q1RQHKir9lX0o+yr6VaooDlRV+yr6UfZV9KtUUByohSBV7VKBilopjSsFFFFMZ//9k="
B64_TUT_GPS = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAcFBQYFBAcGBgYIBwcICxILCwoKCxYPEA0SGhYbGhkWGRgcICgiHB4mHhgZIzAkJiorLS4tGyIyNTEsNSgsLSz/2wBDAQcICAsJCxULCxUsHRkdLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCwsLCz/wAARCABkAoADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD6JoooqTAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAoopCcCgALYqB763jYq9xErDqC4Brk/iPrtzpHh5Vs5DFNdSeV5i9VXBJx79q8WYl2LMSzHkk8k1z1K3K7WPJxeZLDz5FG7PpP+0bT/AJ+oP+/g/wAaP7RtP+fqD/v4P8a+asD0FGB6Cs/rHkcf9sy/k/H/AIB9K/2jaf8AP1B/38H+NH9o2n/P1B/38H+NfNWB6CjA9BR9YfYP7Zl/J+P/AAD6V/tG0/5+oP8Av4P8aP7RtP8An6g/7+D/ABr5pwPQUYHoKPrD7B/bMv5Px/4B9Lf2jaf8/UH/AH8H+NH9o2n/AD9Qf9/B/jXzRtHoKNo9BR9YfYP7Yl/J+P8AwD6X/tG0/wCfqD/v4P8AGj+0bT/n6g/7+D/GvmjaPQUYHoKPrD7B/bEv5Px/4B9L/wBo2n/P1B/38X/Gj+0bT/n6g/7+L/jXzPgegowPQU/rHkP+2Jfyfj/wD6Y/tK0/5+oP+/i/40f2laf8/UH/AH8X/GvmbA9BRgego+seQf2xL+T8f+AfTP8AaVp/z9Qf9/F/xo/tK0/5+oP+/i/418zbR6CjA9BR9Y8g/tiX8n4/8A+mf7StP+fqD/v4v+NH9pWn/P1B/wB/F/xr5lwPQUYHoKPb+Q/7Xl/J+P8AwD6a/tK0/wCfqD/v4v8AjR/aVp/z9Qf9/F/xr5kwPQUYHoKPb+Qf2vL+T8f+AfTX9pWn/P1B/wB/F/xo/tK0/wCfqD/v4v8AjXzLtHoKTA9BR7fyD+15fyfj/wAA+m/7StP+fqD/AL+L/jR/aVp/z9Qf9/F/xr5k2j0FJtHoKPb+Qf2vL+T8f+AfTn9pWn/P1B/38X/Gj+0rT/n6g/7+L/jXzHgegowPQUe38h/2vL+T8f8AgH05/aVp/wA/UH/fxf8AGj+0rT/n6g/7+L/jXzFtHoKMD0FHt/IP7Xl/J+P/AAD6d/tK0/5+oP8Av4v+NH9pWn/P1B/38X/GvmLavoKTA9BR7fyD+1pfyfj/AMA+nv7StP8An6g/7+L/AI0f2laf8/UH/fxf8a+YcL6CjC+gp+38g/taX8n4/wDAPp7+0rT/AJ+oP+/i/wCNH9pWn/P1B/38X/GvmHC+gpNo9BR7fyD+1pfyfj/wD6f/ALStP+fqD/v4v+NH9pWn/P1B/wB/F/xr5gwPQUmB6Cj2/kP+1pfy/j/wD6g/tK0/5+oP+/i/40f2laf8/UH/AH8X/Gvl/aPQUYX0FHt/IP7Wl/L+P/APqD+0rT/n7g/7+L/jR/aVn/z9wf8Afxf8a+X8L6Ck2j0FHt/IP7Vl/L+P/APqH+0rP/n7g/7+L/jR/aVn/wA/cH/fxf8AGvl7aPQUmB6Cj2/kP+1X/L+P/APqL+0rP/n7g/7+L/jR/adn/wA/cH/fxf8AGvl3aPQUbR6Cj277B/asv5fx/wCAfUX9p2f/AD9wf9/F/wAaP7Ts/wDn7g/7+L/jXy5tHoKNq+go9t5B/ar/AJfx/wCAfUf9p2f/AD9wf9/F/wAaP7Ts/wDn7g/7+L/jXy3hfQUYHoKPbPsH9qy/l/H/AIB9Sf2nZ/8AP3B/38X/ABo/tOz/AOfuD/v4v+NfLe0ego2j0FHtvIP7Vf8AL+J9Sf2nZ/8AP3B/38X/ABo/tOz/AOfuD/v4v+NfLW0egowvoKPbeQ/7Uf8AL+J9S/2nZ/8AP3B/38X/ABo/tOz/AOfuD/v4v+NfLO0egowPQUe28g/tR/y/ifU39p2f/P3B/wB/F/xo/tOz/wCfuD/v4v8AjXyxtHoKNo9BT9t5B/akv5fxPqf+07P/AJ+4P+/i/wCNH9p2f/P3B/38X/GvljaPQUYHoKPbeQf2o/5fxPqf+07P/n7g/wC/i/40f2nZ/wDP3B/38X/GvlfaPQUbR6Cj23kP+1H/AC/ifVH9p2f/AD9wf9/F/wAaP7Ts/wDn7g/7+L/jXyvtHoKNq+go9t5B/ab/AJfxPqj+07P/AJ+4P+/i/wCNH9p2f/P3B/38X/GvlbaPQUm0ego9t5B/ab/l/E+qv7Ts/wDn7g/7+L/jR/adn/z9wf8Afxf8a+VcD0FG0ego9t5D/tN/y/ifVX9p2f8Az92//fxf8aliuoZ8+VLHJjrsYHH5V8obR6Crml6reaJfx3thO0E0ZyNp4b2I7ij23kNZnrrH8T6pBzRVHSb4ahpdreBdouIklx6bgDj9avV0I9hO6ugooopjCiiigAooooAKRulLSN0oA81+LRzpNj/18H/0E15ZXqfxZB/smyOOPtB/9BNeWV59b4z4/Mv94fyCkoorE88KKKSmAUUUUDCiiigApKKKACkoopjCiikpAFFFJTGFFFJQMKWkooAKKKSgYUUUlABRRRTGFWruSJoLdVgWJ1XJYfxg9Caq0ruz7dxztAUfSqUrJo76ONlRw9TDqKanbVrVW7PobukaNbX0GlPIsjfab9reXaeiBVP4Hk81Jb+FUuRbSR3jvbypukmSNSkR+X5SS4wRuA5x7ZzWJb6heWkMsVtdzQxyjDqjlQ31xUqazqcYQJqFyojXYuJSNo44H5D8hTTXUwjOnZc0TRu/DIs7+wsXvN1zeTGLAj+VAJWjznPPK5xirkPhK2aaAxX5n3MrGN4SgK+eIW5DZ+8fy9DXNveXUkyTPcytJGco5ckqc5yD25JP1pVv7xCCt1OpHTEh4+bd/wChc/Xmi67DU6Sfwmla+HnvpG2TCMfa5LbG0nG1GfP/AI7itd/C1nLcNJbP8kVuhlhkVgAzWxkBVgcnlSe2MjqK5eDUr61WVbe8nhWY5kCSFd59/XqaV9W1GSOON765ZIgVQGU4UEYIH4cfShNdhxnSS1ibMPhOOXWW037bIHh2pPL5IEaOxAABLDIyfqccA0g8NR2t2LW4n826NrLcGPyyI1ARyPnByT8vTGKyk1vVY9uzUrpdi7FxKwwvHHX2H5VGdV1AwCE31wYhu+TzDjnOfzyfzNF49g56X8p0Vx4UgEDj7UsS6csi3cghJZ3VQ525bDDBwOnT3qlHoMNvqep2k8qyC2VESQjaMyOihyM9g2cetZMup38yKkt7cOqoYwrSEgKeo+nA/KkTULlGuGMhkNzGYpTJ824cfqMDH0ouuw3Om3pE6qPw5YSXtwPsYjt7X7RGTJdkMzxrkb+PkzjPHGDVSTS9FlguxpoN1cRhpFV5mVdqxhm8s7cPg7s5wSAMVhTatqM8apLf3MiopQBpSQFIwR+XFMh1K9t7V7aK6mS3kOXiDkI3rke9PmXYp1Yfyk2uWsVnrVxDANsXyui5ztDKGA/DOPwqhUt3dS3t5LczEGWVizEDA/D2qKoe5zyabbQUlFFAgpKKKACiikpjCiiigApKKKBgaSiigAoopKBhRRRTAKKKSgYUUUlABRRRQMKKKSgApD0paQ9DQB9M+FD/AMUvpf8A16Rf+gCt0dKwvCqlfDOmAjBFrFkf8AFbo6V3R2PraXwIKKKKo0CiiigAooooAKQjIpaKAMLxFodvrumSWdyDtblWXqjDoRXms3wv1FZCI763ZOxZWB/LmvZWQNULQpnkisp01LVnDiMFSrvmmtTxz/hWWqf8/lr/AOPf4Uf8Ky1T/n8tf/Hv8K9h8iP1FHkR+oqPYxOX+y6P9M8d/wCFZap/z+Wv5N/hR/wrLVP+fy1/Jv8ACvYvIj9RR5EfqKPYxH/ZdH+meO/8Ky1T/n8tfyb/AAo/4Vlqn/P5a/8Aj3+FexeRH6ijyI/UUexiH9mUf6Z47/wrHVP+fy1/8e/wo/4Vjqn/AD+Wv5N/hXsXkR+oo8iP1FHsYh/ZlH+meOf8Kx1T/n9tfyb/AAo/4Vhqn/P5a/8Aj3+Fex+RH6ijyI/UUexiH9mUf6Z45/wrDVP+fy1/8e/wo/4Vhqn/AD+Wv/j3+Fex+RH6ijyI/UUexiH9mUf6Z45/wrDVP+f21/Jv8KT/AIVhqn/P7a/k3+FeyeRH6ijyI/UUexiH9mUf6Z43/wAKv1T/AJ/bX8m/wo/4Vfqn/P7a/k3+FeyeRH6ijyI/UUexiH9mUf6Z41/wq/VP+f21/Jv8KP8AhV+q/wDP7af+Pf4V7L5EfqKPIj9RR7GI/wCzKP8ATPGv+FX6r/z+2n/j3+FH/Cr9V/5/bT8m/wAK9l8iP1FHkR+oo9jEP7No/wBM8a/4Vdqv/P7afk3+FJ/wq7Vf+f20/Jv8K9m8iP1FHkR+oo9jEP7NonjP/CrdV/5/bT8m/wAKP+FW6r/z+2n/AI9/hXs3kR+oo8iP1FHsYh/ZtH+meM/8Kt1X/n9tPyb/AAo/4Vbqv/P7afk3+FezeRH6ijyI/UUexiH9m0Txj/hVuq/8/tp+Tf4Uf8Kt1X/n9tPyb/CvZ/Ij9RR5EfqKPYxD+zaJ4x/wq3Vf+f20/Jv8KP8AhVuq/wDP7afk3+Fez+RH6ijyI/UU/YxD+zaJ4x/wqzVf+f20/Jv8KT/hVmq/8/tp+Tf4V7R5EfqKPIj9RR7GI/7NpHi//Cq9V/5/bT8m/wAKP+FV6r/z+2n5N/hXtHkR+oo8iP1FHsoh/Z1I8X/4VXqv/P7afk3+FH/Cq9V/5/bT8m/wr2jyI/UUeRH6ij2UQ/s6keLf8Kr1X/n+tPyb/Cj/AIVXq3/P7afk3+Fe0+RH6ijyI/UUeyiH9nUjxb/hVWrf8/1p+Tf4Uf8ACqtW/wCf60/Jv8K9p8iP1FHkR+oo9lEP7OpHiv8AwqrVv+f60/Jv8KP+FVat/wA/1p/49/hXtXkR+oo8iP1FHsoh/Z1I8V/4VVq3/P8AWn5N/hR/wqnVv+f60/Jv8K9q8iP1FHkR+oo9lEP7OpHiv/CqdW/5/rT8m/wo/wCFU6t/z/Wn5N/hXtXkR+oo8iP1FHsoj/s+keKf8Kp1b/n+tPyb/Cj/AIVTq3/P9afk3+Fe1+RH6ijyI/UUeyiH9n0jxT/hVGrf8/1p+Tf4Un/CqNW/5/rP8n/wr2zyI/UUeRH6ij2UQ/s+keJ/8Ko1b/n+tPyb/Cj/AIVRq3/P9afk3+Fe2eRH6ijyI/UUeyiH9n0jxP8A4VPq3/P9afk3+FH/AAqfVv8An+s/yf8Awr2zyI/UUeRH6ij2UQ/s+keJ/wDCp9W/5/rP8n/wpP8AhU+rf8/1n+T/AOFe2+RH6ijyI/UUeyQf2fSPEv8AhU+rf8/1n+T/AOFH/Cp9X/5/rP8A8f8A8K9t8iP1FHkR+oo9kg/s+keJf8Km1f8A5/rP8n/wo/4VNq//AD/Wf5P/AIV7b5EfqKPIj9RR7JB9QpHiP/CptX/5/rP8n/wo/wCFS6v/AM/1n+T/AOFe3eRH6ijyI/UUeyQ/qFI8R/4VLq//AD/Wf5P/AIUf8Kl1f/n+s/yf/CvbvIj9RR5EfqKPZIPqFM8R/wCFS6v/AM/1n+T/AOFJ/wAKl1f/AJ/7P8n/AMK9v8iP1FHkR+oo9kg+oUzxD/hUmrn/AJf7P8n/AMK0tF+EUi30cmq3scsCHJihU/P7EnoK9d8iP1H509IVHTFNU0VHA0k72G20QjjVVAAAwAOwqzSAYpa1R6CVgooopjCiiigAooooAKKKKAFA3OFPQ9amCqBwo/KoU/1q/Q1PTRpATaPQUbR6Csyy1WW517UNPaJXjtgrLPHnaMj/AFbZ/jHXjsR0rRmlSCB5ZGVERSzMxwAB3NMpNMdtHoKNo9BXG6z4l1Kx33KlEtv7OjkYBM+VK5fa/wAwB25UKQR3B9a17HxBJd6x9kMEaxu0yJiTMimJgpLrjgHOR+HrSuSppuxt7R6CjaPQVxkPi28gsYLi6jWaaSJ/lib5AfPWMEjGeN3P/wBersfim8adFk09I1UwrKDId+ZHdBtGP9kHk96Li54nTbR6CjaPQVycHjC6m05L5tPWG3Yq5kdyQkZUkkgDJIwAcDHOexqzqmsS22szLJdy29vbJC4ihWMtMHYgsd/VRgDC88/Si4+dbnR7R6CjaPQVxsOoeILi2up4rkxxCSaMPceUiZWfaqxEDOdoYZcEZxWlFrzjR7F4SZZrid7cyXjKgRl3ltxQbT9wgbeDxRcFJM6DaPQUbR6Cucu/FUkWm2F1Dbwqbu2kuSJ5toUIqkqDjnO7g/jVefxfdKCYtOB3ztBGC5zlY953ccHnAHsTRcOeJ1e0ego2j0FcWfEl5YXd9dXSSSKGlKQLIMIqRxkKRjrlzkg+vXirUvi68ggeSXTVHkwSTv8AOQWCsFG0Y6HOeemD1ouhc8Tqto9BRtHoK5628R3T3NnHdWaW8c7mMyFictnCgAcjPqeO1RSeKb1ry+httM8xLZ2iDM+35lZQSc9cgkgDk4HrRcfNE6baPQUbR6CuZPi13sby8gjtpYbSJW2mUq8rFFbIBHC/NjJ54PHFVb7X9QtdWKB4FMDyiVJJdsbbYI34O3I+8evufai4nOJ2G0ego2j0Fc5pniGe+1GO2jt8CaSRmMz8xqqxHAAHX950Pp1qIeKJ7SW9F4tuUjuLhIyH24WNNwByOpouPnidRtHoKNo9BXLeIvEVzb6bttPKglks/tRkkkwV5AwnHJ5/l602XxZPapcsLXzkt1mkctJ82FnaMAAL04Bz2HrRcXPG51e0ego2j0Fc3D4numfZLZxwtFC08gd8GRQxA8sY5Jx0PTIHeopvE08MNtcOkDGe3aVVhmzGuWiVdxK548zJPTAPHoXHzxOp2j0FG0egrko/FN1bR+QLeOc2obz5WnJ3gSBCVO3n72e2CCK29KN213f+dcPNbrKEi37dwIHzfdA4yQADzwfWi4KSexpbR6CjaPQUtFMsTaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUbR6ClooATaPQUjRqw6AHsadRQKyKwOVBpaRfuD6UtQYoKKKKYBRRRQAUUUUAFFFFACp/rV/Gp6r0u9/7w/KhMqMrEwUDOABnk4qK8tIb+yltbhS0UylGAJBwfcUm+T+8Pyo3yf3h+VO5XMghs4orcQtumGNpaY72YdeSevWnrBCkzzLEiyvwzhQGb6nvTN8n94flRvk/vD8qLhzIX7JbbXH2eLD53DYPmz1z65pyW0EahUhjVRjACgAY6flTN8n94flRvk/vD8qLhzIT+z7Pn/RIOX8z/AFY+9/e+vvT5baCd0eWGORozlGZQSp9vSm75P7w/KjfJ/eH5UXDmQ9oIXhaJ4kaNs5QqCDnk8UjWlu1sLdreIwDgRlBt/LpTd8n94flRvk/vD8qLhzIjuNMtLu6t7ieFZHtgwjDDKjdjPH/ARU0lrbzRlJYIpEZtxVkBBPr9abvk/vD8qN8n94flRcOZdiTyIiSfKTnP8I78H+VNjtbeFNkcESIAV2qgAweopu+T+8Pyo3yf3h+VFw5kCWNpEYzHawoYs7CsYG3PXHpRJZWsru8ltC7SDa5ZASw9D60b5P7w/KjfJ/eH5UXDmQps7YuHNtEWC7AdgyF9Pp7US2ltP/rbeKTnd8yA8+v6Ck3yf3h+VG+T+8PyouHMiURRq+8RqG55A556/wAh+VRvZWsrM0ltC5YhiWQHJHAP1pN8n94flRvk/vD8qLhzIdLa282zzYI5PL+7uQHb9PSneRF837pPmBB+Ucg8mo98n94flRvk/vD8qLhzIFsrVREFtoQITmMBB8h9vSlSztY0KpbQorZyFQAHPX86TfJ/eH5Ub5P7w/Ki4cyHLa26IEWCNUA2hQgAA64p6RpHu2Iq7juOBjJ9ai3yf3h+VG+T+8PyouHMieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6Kg3yf3h+VG+T+8PyouHOieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6Kg3yf3h+VG+T+8PyouHOieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6Kg3yf3h+VG+T+8PyouHOieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6Kg3yf3h+VG+T+8PyouHOieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6Kg3yf3h+VG+T+8PyouHOieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6Kg3yf3h+VG+T+8PyouHOieioN8n94flRvk/vD8qLhzonoqDfJ/eH5Ub5P7w/Ki4c6J6OlQb5P7w/KgszDDNx6AUXDnGr9wfSloopGYUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFAH/2Q=="
B64_TUT_REPORTAR = "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x8nP3jg0vlLzzjj1qIHByOtJRZ9xcsu5K0ahWIJ46e9L5aEA5I4Gef1qGiiz7hyvuS+WnQMc0SRqi5ySfSoqKLPuNRfckZAAME8mneUu7rwPeoaKLPuHK+5N5aZPOP8AJpioGUnOMZ/lTKKLPuJRa6kwiUtgMcdKRFVo/wDayaioosw5X3JvLTAwScZ6HrUTDDEA5x3pKKaVhxTW7CiiimWFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAW9K/5Ddh/18x/+hivuQ/eNfDelf8AIbsP+vmP/wBDFfch+8azmRISiiisyAooooAKKKKACq8LKby6AQKVKZYdW+WiipfQiW8fX9GeT/tF6TLd+EdN1NJECWFwVdDnLeYABj6bf1r5xooreGxvHYKKKKsoKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooA2/BukS67400nToZEiea5T5nzgAHcf0Ffah5JoorKZEj/2Q=="

SVG_CONFIRMAR = """<svg viewBox="0 0 160 160" width="120" height="120" xmlns="http://www.w3.org/2000/svg">
<circle cx="80" cy="80" r="78" fill="#dcfce7" stroke="#4ade80" stroke-width="3"/>
<circle cx="58" cy="70" r="20" fill="#16a34a"/>
<circle cx="102" cy="70" r="20" fill="#4ade80"/>
<path d="M80 100 C55 100 45 120 45 132 L115 132 C115 120 105 100 80 100 Z" fill="#166534"/>
<circle cx="118" cy="55" r="24" fill="#fbbf24"/>
<path d="M110 55 L116 61 L128 47" fill="none" stroke="#78350f" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

PASOS_TUTORIAL = [
    {
        "visual_html": _img_tutorial(B64_TUT_MAPA),
        "titulo": "¡Bienvenido a EcoCom2 Circular IA!",
        "texto": "Entre todos podemos mantener la Comuna 2 más limpia. Te mostramos "
                 "en 4 pasos rápidos cómo funciona — toma 30 segundos.",
    },
    {
        "visual_html": _img_tutorial(B64_TUT_GPS),
        "titulo": "1. Verifica tu dirección",
        "texto": "Usa el botón grande de GPS, o escribe tu dirección si prefieres. "
                 "Solo residentes DENTRO de la Comuna 2 pueden publicar reportes — "
                 "cualquiera puede ver el mapa.",
    },
    {
        "visual_html": _img_tutorial(B64_TUT_REPORTAR),
        "titulo": "2. Reporta un residuo",
        "texto": "Toca el mapa donde está el residuo, sube una foto, y la IA la "
                 "analiza sola — te dice si es reciclable y qué tan urgente es "
                 "(🟢 🟡 🔴).",
    },
    {
        "visual_html": SVG_CONFIRMAR,
        "titulo": "3. Confirma los reportes de tus vecinos",
        "texto": "Si pasas por un punto ya reportado y el residuo sigue ahí, "
                 "confírmalo desde '👤 Mi Historial' — ayuda a la administración "
                 "a priorizar dónde actuar primero.",
    },
]


def mostrar_tutorial():
    paso = st.session_state.get("tutorial_paso", 0)
    paso = max(0, min(paso, len(PASOS_TUTORIAL) - 1))
    info = PASOS_TUTORIAL[paso]

    st.markdown(
        f'<div style="background:linear-gradient(135deg,rgba(74,222,128,0.15),rgba(22,163,74,0.08));'
        f'border:2px solid #4ade80;border-radius:16px;padding:28px 24px;'
        f'text-align:center;margin-bottom:10px;">'
        f'<div style="margin-bottom:10px;">{info["visual_html"]}</div>'
        f'<div style="font-size:19px;font-weight:800;color:#166534;margin-bottom:8px;">'
        f'{info["titulo"]}</div>'
        f'<div style="font-size:14px;color:#374151;max-width:480px;margin:0 auto;'
        f'line-height:1.5;">{info["texto"]}</div>'
        f'</div>', unsafe_allow_html=True)

    puntos = "".join(
        "●" if i == paso else "○" for i in range(len(PASOS_TUTORIAL))
    )
    st.markdown(
        f'<div style="text-align:center;color:#4ade80;font-size:16px;'
        f'letter-spacing:6px;margin-bottom:10px;">{puntos}</div>',
        unsafe_allow_html=True)

    tb1, tb2, tb3 = st.columns([1, 1, 1])
    with tb1:
        if paso > 0:
            if st.button("⬅️ Anterior", use_container_width=True, key="tut_prev"):
                st.session_state.tutorial_paso = paso - 1
                st.rerun()
    with tb2:
        if st.button("Saltar tutorial", use_container_width=True, key="tut_skip"):
            st.session_state.tutorial_visto = True
            st.rerun()
    with tb3:
        if paso < len(PASOS_TUTORIAL) - 1:
            if st.button("Siguiente ➡️", type="primary",
                         use_container_width=True, key="tut_next"):
                st.session_state.tutorial_paso = paso + 1
                st.rerun()
        else:
            if st.button("✅ ¡Entendido, empezar!", type="primary",
                         use_container_width=True, key="tut_finish"):
                st.session_state.tutorial_visto = True
                st.rerun()
    st.markdown("---")


def nav_tabs(seccion_actual):
    SECCIONES = [
        ("residuo",   "📸 Reportar Residuo"),
        ("critico",   "🚨 Punto Crítico"),
        ("historial", "👤 Mi Historial"),
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

PAGINAS = ["🏠 Reportar y Ver Mapa", "ℹ️ Información"]
menu_elegido = st.sidebar.radio("Menú", PAGINAS)

with st.sidebar.expander("⚙️ Más opciones"):
    st.caption("Estadísticas públicas y gestión — para curiosos y administración.")
    if st.button("📊 Comuna en Cifras", use_container_width=True, key="ir_cifras"):
        st.session_state.menu_extra = "📊 Comuna en Cifras"
        st.rerun()
    if st.button("🛡️ Panel Admin", use_container_width=True, key="ir_admin"):
        st.session_state.menu_extra = "🛡️ Panel Admin"
        st.rerun()
    if st.session_state.get("menu_extra") and st.button(
            "⬅️ Volver al inicio", use_container_width=True, key="ir_inicio"):
        st.session_state.menu_extra = None
        st.rerun()

menu = st.session_state.get("menu_extra") or menu_elegido
if menu == "🏠 Reportar y Ver Mapa":
    menu = "🏠 Inicio y Mapa"  # nombre interno sin cambiar el resto de la lógica

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

if st.sidebar.button("🎬 Ver tutorial de nuevo", use_container_width=True, key="ver_tutorial_de_nuevo"):
    st.session_state.tutorial_visto = False
    st.session_state.tutorial_paso = 0
    st.session_state.menu_extra = None
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div class="ecocom2-footer" style="font-size:11px;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#16a34a">EcoCom2 v7.0</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#16a34a">Brandon Duque</b>
</div>""", unsafe_allow_html=True)

# ====================================================================
# 8. INICIO Y MAPA
# ====================================================================
if menu == "🏠 Inicio y Mapa":
    st.title("♻️ EcoCom2 Circular IA")
    st.caption("Gestión inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    if not st.session_state.get("tutorial_visto", False):
        mostrar_tutorial()

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
        if not verificar_api_key():
            return ("🤖 El asistente con IA no está disponible en este momento "
                    "(falta configuración del administrador). Aquí va la ayuda "
                    "rápida: 1️⃣ Verifica dirección 2️⃣ Toca el mapa "
                    "3️⃣ Sube foto 4️⃣ Publica.")
        try:
            import requests
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")

            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }

            mensajes_api = [
                {"role": m["role"], "content": m["content"]}
                for m in mensajes_historial
            ]
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json={
                    "model": "claude-haiku-4-5-20251001",
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
            # Convertimos saltos de línea reales a <br> — dentro de HTML,
            # un "\n" normal se ignora visualmente; sin este cambio el
            # saludo de bienvenida (que tiene un salto doble) se veía
            # todo pegado en una sola línea.
            contenido_html = msg["content"].replace("\n", "<br>")
            if msg["role"] == "assistant":
                st.markdown(
                    f'<div class="ecobot-bubble-bot" style="border:1px solid #bbf7d0;'
                    f'border-radius:10px;padding:10px;font-size:13px;'
                    f'margin-bottom:6px;">'
                    f'🤖 {contenido_html}</div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div class="ecobot-bubble-user" style="border-radius:10px;'
                    f'padding:8px 10px;font-size:13px;'
                    f'text-align:right;margin-bottom:6px;">'
                    f'👤 {contenido_html}</div>',
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

    if st.button("📍 Usar mi ubicación (GPS)", key="btn_gps",
                 type="primary", use_container_width=True):
        st.session_state.gps_solicitado = True

    with st.expander("¿No tienes GPS o prefieres escribir tu dirección?"):
        with st.form(key="form_direccion", clear_on_submit=False):
            c_inp, c_btn = st.columns([5, 1])
            with c_inp:
                dir_inp = st.text_input(
                    "📍 Dirección:",
                    value=dir_auto,
                    placeholder="Ej. Cra 50 #107-62, Andalucía",
                    label_visibility="collapsed",
                    key="dir_campo",
                )
            with c_btn:
                verificar_clicked = st.form_submit_button(
                    "🔍 Verificar", type="primary", use_container_width=True)
            st.caption("También puedes tocar directamente el mapa de abajo.")

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

    if st.session_state.get("gps_solicitado"):
        with st.spinner("📡 Obteniendo tu ubicación (acepta el permiso del navegador)..."):
            loc = get_geolocation()

        if loc is None:
            pass
        elif loc.get("error"):
            st.session_state.gps_solicitado = False
            cod_err = loc["error"].get("code")
            msg = "⚠️ No pudimos obtener tu ubicación."
            if cod_err == 1:
                msg = "⚠️ Permiso de ubicación denegado. Actívalo en tu navegador si quieres usar esta opción."
            elif cod_err == 2:
                msg = "⚠️ Ubicación no disponible en este dispositivo."
            elif cod_err == 3:
                msg = "⚠️ Se agotó el tiempo de espera obteniendo tu ubicación."
            st.warning(msg + " Busca tu dirección manualmente o toca el mapa.")
        else:
            coords = loc.get("coords", {})
            glat, glon = coords.get("latitude"), coords.get("longitude")
            clave_gps = f"{glat:.6f},{glon:.6f}" if glat is not None else None
            if clave_gps and clave_gps != st.session_state.get("gps_procesado"):
                st.session_state.gps_procesado = clave_gps
                st.session_state.gps_lat = glat
                st.session_state.gps_lon = glon
                st.session_state.gps_solicitado = False
                dentro_gps = POLIGONO_COMUNA2.contains(Point(glon, glat))
                if dentro_gps:
                    with st.spinner("📍 Estás dentro de la Comuna 2 — verificando dirección..."):
                        dir_gps, barrio_gps = geocodificar_inversa(glat, glon)
                    set_ubicacion(glat, glon, dir_gps)
                    st.session_state.click_barrio = barrio_gps
                    st.session_state.click_lat = glat
                    st.session_state.click_lon = glon
                    st.session_state.click_dir = dir_gps
                    st.success(f"✅ ¡Verificado por GPS! Estás en: {dir_gps}")
                else:
                    st.warning(
                        "🛑 Tu GPS indica que estás **fuera** de la Comuna 2. "
                        "Puedes ver tu posición en el mapa (pin morado), pero para "
                        "reportar necesitas buscar tu dirección o tocar el punto "
                        "manualmente dentro del área piloto."
                    )
                st.rerun()

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
                      "gps_lat","gps_lon","gps_procesado","gps_solicitado"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")
    st.markdown("### 🗺️ Toca el punto exacto del residuo en el mapa")
    st.caption("Al tocar, la dirección aparece automáticamente arriba y puedes reportar directo.")

    vista_mapa = st.radio(
        "Vista del mapa:", ["📍 Puntos individuales", "🔥 Mapa de calor"],
        horizontal=True, key="vista_mapa_principal",
        help="El mapa de calor te ayuda a ver de un vistazo las zonas con más "
             "problemas, sin tener que contar puntos uno por uno."
    )

    lat_c = st.session_state.get("lat") or st.session_state.get("gps_lat") or LAT_C
    lon_c = st.session_state.get("lon") or st.session_state.get("gps_lon") or LON_C

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=14, tiles="CartoDB positron")

    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_p, color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        tooltip="📍 Área piloto — Comuna 2 Santa Cruz (Acevedo → Villa del Socorro)"
    ).add_to(mapa)

    def _mismo_punto(a, b, tol=0.00003):
        return (a[0] is not None and b[0] is not None
                and abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol)

    _lat_home = st.session_state.get("lat")
    _lon_home = st.session_state.get("lon")
    _clat_ss  = st.session_state.get("click_lat")
    _clon_ss  = st.session_state.get("click_lon")
    _glat_ss  = st.session_state.get("gps_lat")
    _glon_ss  = st.session_state.get("gps_lon")

    if st.session_state.get("validado") and _lat_home:
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker(
            location=[_lat_home, _lon_home],
            popup=f"🏠 {st.session_state.direccion}",
            tooltip="🏠 Tu dirección verificada",
            icon=folium.Icon(color=col_pin, icon="home", prefix="fa")
        ).add_to(mapa)

    if _clat_ss and not _mismo_punto((_clat_ss, _clon_ss), (_lat_home, _lon_home)):
        folium.Marker(
            location=[_clat_ss, _clon_ss],
            popup=f"📌 {st.session_state.get('click_dir','Punto seleccionado')}",
            tooltip="📌 Punto seleccionado",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(mapa)

    if (_glat_ss
            and not _mismo_punto((_glat_ss, _glon_ss), (_lat_home, _lon_home))
            and not _mismo_punto((_glat_ss, _glon_ss), (_clat_ss, _clon_ss))):
        folium.Marker(
            location=[_glat_ss, _glon_ss],
            popup="📍 Tu posición GPS actual",
            tooltip="📍 Tu ubicación en tiempo real",
            icon=folium.Icon(color="purple", icon="crosshairs", prefix="fa")
        ).add_to(mapa)

    if vista_mapa == "🔥 Mapa de calor":
        PESO_CALOR = {"🔴": 1.0, "🟡": 0.6, "🟢": 0.3}
        datos_calor = []
        for rep in st.session_state.reportes:
            niv = rep.get("Clasificación", "")
            p = PESO_CALOR["🔴"] if "🔴" in niv else (PESO_CALOR["🟡"] if "🟡" in niv else PESO_CALOR["🟢"])
            if "Resuelto" in rep.get("Estado", ""):
                p *= 0.25  # los resueltos casi no pesan, pero no desaparecen del mapa
            if rep.get("Lat") is not None and rep.get("Lon") is not None:
                datos_calor.append([rep["Lat"], rep["Lon"], p])
        if datos_calor:
            HeatMap(datos_calor, radius=24, blur=20, max_zoom=16,
                    gradient={0.2: "#4ade80", 0.5: "#fbbf24", 0.8: "#f87171", 1.0: "#dc2626"}
                    ).add_to(mapa)
        else:
            st.info("Aún no hay reportes para mostrar en el mapa de calor.")
        st.caption("🔴 Zonas rojas = más puntos críticos concentrados. Los reportes "
                   "ya resueltos pesan mucho menos, así que no distorsionan el mapa.")
    else:
        for rep in st.session_state.reportes:
            niv = rep.get("Clasificación", "🟢")
            col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
            foto_b64 = rep.get("FotoB64", "")
            img_html = (f'<br><img src="data:image/jpeg;base64,{foto_b64}" '
                        f'style="width:180px;border-radius:6px;margin-top:6px;">'
                        if foto_b64 else "")
            obs_txt = rep.get("Observaciones", "")
            obs_html = f"📝 {obs_txt[:80]}<br>" if obs_txt else ""
            audio_b64 = rep.get("NotaVozB64", "")
            audio_html = (f'<br><audio controls style="width:180px;margin-top:4px;">'
                          f'<source src="data:audio/wav;base64,{audio_b64}"></audio>'
                          if audio_b64 else "")
            galeria_extra_html = galeria_html(rep.get("FotosExtraB64", ""), ancho_px=60)
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
                f"{img_html}{audio_html}{galeria_extra_html}</div>"
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
            st.session_state.punto_para_reporte = {
                "lat": clat, "lon": clon, "dir": cdir
            }
            if st.button("✖ Quitar punto seleccionado", key="btn_quit"):
                for k in ["click_lat","click_lon","click_dir","click_barrio",
                           "cache","punto_para_reporte"]:
                    st.session_state.pop(k, None)
                st.rerun()
        elif clat and not es_residente():
            badge("⚠️ Verifica tu dirección arriba para reportar en este punto.", "warn")

    st.markdown("")
    st.markdown("")
    seccion = st.session_state.get("seccion", "info")

    nav_tabs(seccion)
    st.markdown("")

    if seccion == "info":
        if not clat:
            st.info("👆 Toca cualquier punto del mapa y luego usa los botones de arriba para reportar.")

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
                r_codigo = campo_codigo_residente("r_codigo_residente")

            # ── OBSERVACIONES: texto o solo voz ──────────────────────────
            # Dos formas independientes de contar lo que ves — usa una,
            # la otra, o ambas. La nota de voz es un widget nativo de
            # Streamlit (st.audio_input): graba el audio real y queda
            # guardado tal cual con el reporte, sin depender de que el
            # navegador transcriba nada.
            r_obs = st.text_area(
                "📝 Observaciones por texto (opcional):",
                placeholder="Describe lo que ves en la foto: hace cuánto está ahí, "
                            "si bloquea el paso, olores, riesgos, etc.",
                key="r_obs", height=80,
            )
            r_audio = st.audio_input("🎙️ O deja solo una nota de voz:", key="r_audio")
            if r_audio:
                st.caption("✅ Nota de voz grabada — se guardará junto con el reporte.")

            r_imgs = st.file_uploader(
                "📷 Foto(s) del residuo (hasta 3, ej. distintos ángulos):",
                type=["jpg","jpeg","png"], key="r_imgs",
                accept_multiple_files=True)
            st.caption("🙈 Evita incluir personas en la foto. Si aparecen, las "
                       "difuminamos automáticamente antes de publicar.")

            img = None
            r_imgs_extra_pil = []
            if r_imgs:
                if len(r_imgs) > 3:
                    st.warning("⚠️ Solo se usarán las primeras 3 fotos que subiste.")
                    r_imgs = r_imgs[:3]

                if len(r_imgs) == 1:
                    img = _abrir_img_subida(r_imgs[0])
                else:
                    st.caption("📌 Son varias fotos del mismo residuo — elige la que lo "
                               "muestre MEJOR completo. Solo esa la analiza la IA; las "
                               "demás quedan guardadas como evidencia adicional.")
                    cols_mini = st.columns(len(r_imgs))
                    for i, (col_m, f) in enumerate(zip(cols_mini, r_imgs)):
                        with col_m:
                            st.image(_abrir_img_subida(f), use_container_width=True,
                                     caption=f"Foto {i+1}")
                    opciones_ppal = [f"Foto {i+1}" for i in range(len(r_imgs))]
                    sel_ppal = st.radio("📸 Foto principal (la que analiza la IA):",
                                        opciones_ppal, horizontal=True, key="r_sel_ppal")
                    idx_ppal = opciones_ppal.index(sel_ppal)
                    img = _abrir_img_subida(r_imgs[idx_ppal])
                    r_imgs_extra_pil = [_abrir_img_subida(f) for i, f in enumerate(r_imgs)
                                        if i != idx_ppal]

                if img is not None:
                    exif_r = verificar_fecha_exif(img)
                    if exif_r:
                        fecha_foto_r, dias_r = exif_r
                        st.warning(f"📅 Esta foto parece haber sido tomada el "
                                   f"{fecha_foto_r:%d/%m/%Y} — hace {dias_r} días. "
                                   f"Si el residuo ya cambió, sube una foto más reciente.")

            if img is not None:
                if st.button("🔍 Analizar con IA", type="primary",
                             use_container_width=True, key="r_analizar"):
                    with st.spinner("Analizando imagen (conf ≥ 25%)..."):
                        res = analizar(img)
                    tabla, residuos, peso, tipo, nivel, _ = procesar(res)
                    img_blur, hubo_personas_r = difuminar_personas(img, res)
                    st.session_state.cache_analisis_r = {
                        "res_plot": res[0].plot(),
                        "tabla": tabla,
                        "residuos": residuos,
                        "peso": peso,
                        "tipo": tipo,
                        "nivel": nivel,
                        "ia_detecto": not (residuos == 0 and len(tabla) == 0),
                        "img_blur": img_blur,
                        "hubo_personas": hubo_personas_r,
                    }

                # ── Este bloque va FUERA del botón a propósito: si estuviera
                # adentro, en cuanto tocas el selectbox o el slider de abajo
                # Streamlit vuelve a correr todo el script con el botón en
                # False y este bloque completo desaparecería, guardando el
                # reporte con los valores por defecto de la primera corrida
                # en vez de con lo que realmente elegiste.
                if st.session_state.get("cache_analisis_r"):
                    ca = st.session_state.cache_analisis_r
                    img_mostrar = ca.get("img_blur", img)
                    if ca.get("hubo_personas"):
                        st.info("🙈 Detectamos personas en la foto y las difuminamos "
                                 "automáticamente antes de guardarla, para proteger su privacidad.")
                    co, cd = st.columns(2)
                    with co:
                        st.markdown("**📷 Original**")
                        st.image(img_mostrar, use_container_width=True)
                    with cd:
                        st.markdown("**🤖 Detecciones IA**")
                        st.image(ca["res_plot"], use_container_width=True)

                    if ca["tabla"]:
                        df_t = pd.DataFrame(ca["tabla"])
                        df_si = df_t[df_t["♻️"] == "✅ Sí"]
                        df_no = df_t[df_t["♻️"] == "❌ No"]
                        if not df_si.empty:
                            st.markdown("**♻️ Reciclables:**")
                            st.dataframe(df_si, use_container_width=True, hide_index=True)
                        if not df_no.empty:
                            st.markdown("**⚠️ No aprovechables:**")
                            st.dataframe(df_no, use_container_width=True, hide_index=True)

                    img_foto_final = img_mostrar
                    residuos_f, peso_f, tipo_f, nivel_f = (
                        ca["residuos"], ca["peso"], ca["tipo"], ca["nivel"])

                    if not ca["ia_detecto"]:
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
                        nivel_f, tipo_f, peso_f = MAP_MANUAL[tipo_manual]
                        residuos_f = cant_manual if "reciclable" in tipo_manual.lower() else 0
                        if "🔴" in nivel_f:
                            img_foto_final = marcar_zona_critica(img_mostrar)
                            st.caption("🚨 La foto se marcará con un aviso de zona crítica "
                                       "para que el administrador la identifique fácil en el mapa.")
                        metricas(residuos_f, peso_f, nivel_f)
                    else:
                        metricas(residuos_f, peso_f, nivel_f)

                    st.session_state.cache = {
                        "Código":        f"REP-{len(st.session_state.reportes)+200}",
                        "Sector":        r_barrio,
                        "Referencia":    r_ref,
                        "Objetos":       residuos_f,
                        "Peso (Kg)":     peso_f,
                        "Predominante":  tipo_f,
                        "Clasificación": nivel_f,
                        "Lat": plat, "Lon": plon,
                        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Estado": "🔴 Pendiente",
                        "FotoB64": img_a_b64(img_foto_final),
                        "Observaciones": r_obs.strip(),
                        "NotaVozB64": audio_a_b64(r_audio),
                        "FotosExtraB64": fotos_extra_a_json(r_imgs_extra_pil),
                        "CodigoResidente": r_codigo,
                        "PHash": calcular_phash(img_mostrar),
                        "Confirmaciones": 0,
                    }

            if st.session_state.get("cache"):
                r = st.session_state.cache
                st.markdown(f"**Listo:** {r['Clasificación']} · {r['Objetos']} reciclables · {r['Peso (Kg)']} kg")
                if r.get("Observaciones"):
                    st.markdown(f"**📝 Observaciones:** {r['Observaciones']}")
                if r.get("NotaVozB64"):
                    st.markdown("**🎙️ Nota de voz adjunta:**")
                    st.audio(base64.b64decode(r["NotaVozB64"]), format="audio/wav")
                if r.get("FotosExtraB64"):
                    st.markdown(galeria_html(r["FotosExtraB64"]), unsafe_allow_html=True)

                ok_limite_r = verificar_limite_reportes(r_codigo)
                foto_recic_r = buscar_foto_reciclada(r["Lat"], r["Lon"], r.get("PHash", ""))
                if foto_recic_r:
                    ok_publicar_r = aviso_foto_reciclada(foto_recic_r)
                else:
                    dup_r = buscar_posible_duplicado(r["Lat"], r["Lon"], r.get("PHash", ""))
                    ok_publicar_r = aviso_duplicado(dup_r, "r_confirmar_duplicado")
                ok_publicar_r = ok_publicar_r and ok_limite_r

                cp, cc = st.columns(2)
                with cp:
                    if st.button("🚀 PUBLICAR EN EL MAPA", type="primary",
                                 use_container_width=True, key="r_publicar",
                                 disabled=not ok_publicar_r):
                        st.session_state.reportes.append(r)
                        st.session_state.mis_codigos.append(r["Código"])
                        st.session_state.mis_estados_vistos[r["Código"]] = r["Estado"]
                        st.session_state.reportes_hoy_sesion = st.session_state.get("reportes_hoy_sesion", 0) + 1
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache = None
                        st.session_state.cache_analisis_r = None
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir","click_barrio"]:
                            st.session_state.pop(k, None)
                        st.success("✅ ¡Publicado! Guardado permanentemente en el mapa.")
                        st.rerun()
                with cc:
                    if st.button("❌ Cancelar", use_container_width=True, key="r_cancelar"):
                        st.session_state.cache = None
                        st.session_state.cache_analisis_r = None
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
                cr_codigo = campo_codigo_residente("cr_codigo_residente")

            # ── OBSERVACIONES: texto o solo voz (igual que Reportar Residuo) ──
            cr_obs = st.text_area(
                "📝 Observaciones por texto (opcional):",
                placeholder="Describe la acumulación: hace cuánto está ahí, si genera "
                            "olores, si bloquea el paso, riesgos para la salud, etc.",
                key="cr_obs", height=80,
            )
            cr_audio = st.audio_input("🎙️ O deja solo una nota de voz:", key="cr_audio")
            if cr_audio:
                st.caption("✅ Nota de voz grabada — se guardará junto con la alerta.")

            cr_imgs = st.file_uploader(
                "📷 Foto(s) del punto crítico (hasta 3 ángulos del mismo montón):",
                type=["jpg","jpeg","png"], key="cr_imgs",
                accept_multiple_files=True)
            st.caption("🙈 Evita incluir personas en la foto. Si aparecen, las "
                       "difuminamos automáticamente antes de publicar.")

            img2 = None
            cr_imgs_extra_pil = []
            if cr_imgs:
                if len(cr_imgs) > 3:
                    st.warning("⚠️ Solo se usarán las primeras 3 fotos que subiste.")
                    cr_imgs = cr_imgs[:3]

                if len(cr_imgs) == 1:
                    img2 = _abrir_img_subida(cr_imgs[0])
                else:
                    st.caption("📌 Son varios ángulos del MISMO montón — elige la foto "
                               "que mejor muestre toda la acumulación completa. Solo esa "
                               "la analiza la IA (así no se cuentan los mismos objetos "
                               "varias veces); las demás quedan como evidencia adicional.")
                    cols_mini2 = st.columns(len(cr_imgs))
                    for i, (col_m, f) in enumerate(zip(cols_mini2, cr_imgs)):
                        with col_m:
                            st.image(_abrir_img_subida(f), use_container_width=True,
                                     caption=f"Foto {i+1}")
                    opciones_ppal2 = [f"Foto {i+1}" for i in range(len(cr_imgs))]
                    sel_ppal2 = st.radio("📸 Foto principal (la que analiza la IA):",
                                         opciones_ppal2, horizontal=True, key="cr_sel_ppal")
                    idx_ppal2 = opciones_ppal2.index(sel_ppal2)
                    img2 = _abrir_img_subida(cr_imgs[idx_ppal2])
                    cr_imgs_extra_pil = [_abrir_img_subida(f) for i, f in enumerate(cr_imgs)
                                         if i != idx_ppal2]

                if img2 is not None:
                    exif_cr = verificar_fecha_exif(img2)
                    if exif_cr:
                        fecha_foto_cr, dias_cr = exif_cr
                        st.warning(f"📅 Esta foto parece haber sido tomada el "
                                   f"{fecha_foto_cr:%d/%m/%Y} — hace {dias_cr} días. "
                                   f"Si la acumulación ya cambió, sube una foto más reciente.")

            if img2 is not None:

                if st.button("🔍 Evaluar con IA", type="primary",
                             use_container_width=True, key="cr_analizar"):
                    with st.spinner("Analizando con YOLOv8 (alta resolución)..."):
                        res2 = analizar(img2, imgsz=960)
                    img2_blur, hubo_personas_cr = difuminar_personas(img2, res2)
                    st.session_state.cache_img_blur = img2_blur
                    st.session_state.hubo_personas_cr = hubo_personas_cr
                    st.session_state.cache_foto_b64 = img_a_b64(img2_blur)
                    st.session_state.cache_phash = calcular_phash(img2_blur)
                    st.session_state.cache_fotos_extra_b64 = fotos_extra_a_json(cr_imgs_extra_pil)

                    if hubo_personas_cr:
                        st.info("🙈 Detectamos personas en la foto y las difuminamos "
                                 "automáticamente antes de guardarla, para proteger su privacidad.")

                    co2, cd2 = st.columns(2)
                    with co2:
                        st.markdown("**📷 Original**")
                        st.image(img2_blur, use_container_width=True)
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
                        if "🔴" in nivel_f:
                            st.session_state.cache_foto_b64 = img_a_b64(
                                marcar_zona_critica(st.session_state.get("cache_img_blur", img2)))
                            st.caption("🚨 La foto se marcará con un aviso de zona crítica "
                                       "para que el administrador la identifique fácil en el mapa.")
                    else:
                        nivel_f   = cc["nivel"]
                        tipo_f    = cc["tipo"]
                        peso_f    = cc["peso"]
                        total_f   = cc["total"]
                        residuos_f= cc["residuos"]

                    metricas(residuos_f, peso_f, nivel_f)
                    if cr_obs.strip():
                        st.markdown(f"**📝 Observaciones:** {cr_obs.strip()}")
                    if cr_audio:
                        st.markdown("**🎙️ Nota de voz adjunta:**")
                        st.audio(cr_audio)
                    if st.session_state.get("cache_fotos_extra_b64"):
                        st.markdown(galeria_html(st.session_state["cache_fotos_extra_b64"]),
                                    unsafe_allow_html=True)

                    ok_limite_cr = verificar_limite_reportes(cr_codigo)
                    foto_recic_cr = buscar_foto_reciclada(
                        cc["Lat"], cc["Lon"], st.session_state.get("cache_phash", ""))
                    if foto_recic_cr:
                        ok_publicar_cr = aviso_foto_reciclada(foto_recic_cr)
                    else:
                        dup_cr = buscar_posible_duplicado(
                            cc["Lat"], cc["Lon"], st.session_state.get("cache_phash", ""))
                        ok_publicar_cr = aviso_duplicado(dup_cr, "cr_confirmar_duplicado")
                    ok_publicar_cr = ok_publicar_cr and ok_limite_cr

                    st.markdown("")
                    cr_pub, cr_can = st.columns(2)
                    with cr_pub:
                        if st.button("🚨 REGISTRAR ALERTA EN EL MAPA",
                                     type="primary", use_container_width=True,
                                     key="cr_registrar", disabled=not ok_publicar_cr):
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
                                "NotaVozB64": audio_a_b64(cr_audio),
                                "FotosExtraB64": st.session_state.get("cache_fotos_extra_b64", ""),
                                "CodigoResidente": cr_codigo,
                                "PHash": st.session_state.get("cache_phash", ""),
                                "Confirmaciones": 0,
                            }
                            st.session_state.reportes.append(nuevo)
                            st.session_state.mis_codigos.append(nuevo["Código"])
                            st.session_state.mis_estados_vistos[nuevo["Código"]] = nuevo["Estado"]
                            st.session_state.reportes_hoy_sesion = st.session_state.get("reportes_hoy_sesion", 0) + 1
                            guardar_reportes_disco(st.session_state.reportes)
                            st.session_state.cache_critico = None
                            st.session_state.cache_fotos_extra_b64 = None
                            st.session_state.cache_phash = None
                            st.session_state.cache_img_blur = None
                            st.session_state.seccion = "historial"
                            for k in ["click_lat","click_lon","click_dir","click_barrio"]:
                                st.session_state.pop(k, None)
                            st.success("✅ ¡Alerta registrada permanentemente!")
                            st.rerun()
                    with cr_can:
                        if st.button("❌ Cancelar", use_container_width=True,
                                     key="cr_cancelar"):
                            st.session_state.cache_critico = None
                            st.session_state.cache_fotos_extra_b64 = None
                            st.session_state.cache_phash = None
                            st.session_state.cache_img_blur = None
                            st.rerun()

    # ── SECCIÓN: Historial ─────────────────────────────────────────────
    elif seccion == "historial":
        st.markdown("### 👤 Mi Historial")
        st.caption("Tus propios reportes. Para ver estadísticas de toda la Comuna 2, "
                   "usa la página **📊 Comuna en Cifras** en el menú de la izquierda.")

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
                    msg_logro = (
                        f"🎉 ¡Reporté un punto de residuos en {r.get('Sector','')} - Comuna 2 "
                        f"con EcoCom2 Circular IA y ya lo resolvieron! Tú también puedes "
                        f"reportar en tu cuadra 🌱♻️"
                    )
                    st.markdown(
                        boton_whatsapp_html(link_whatsapp("", msg_logro),
                                             "📲 Compartir este logro"),
                        unsafe_allow_html=True)
                elif "proceso" in actual:
                    st.info(
                        f"🚚 Tu reporte **{cod}** ({r.get('Sector','')}) pasó a "
                        f"**en proceso de recolección**. Ya está siendo atendido."
                    )

        busq_codigo = st.text_input(
            "🔎 Si reportaste desde otro navegador o dispositivo, busca por "
            "código/teléfono (si lo escribiste al reportar):",
            value=st.session_state.get("mi_codigo_residente", ""),
            key="hist_busqueda_codigo",
            placeholder="Escribe el mismo código/teléfono que usaste al reportar"
        )

        if busq_codigo.strip():
            reportes_mostrar = [
                r for r in st.session_state.reportes
                if r.get("CodigoResidente", "").strip().lower() == busq_codigo.strip().lower()
            ]
        else:
            reportes_mostrar = mis_reportes_actuales

        if reportes_mostrar:
            n_total_mios = len(reportes_mostrar)
            n_resueltos_mios = sum(1 for r in reportes_mostrar if "Resuelto" in r.get("Estado",""))
            n_proceso_mios   = sum(1 for r in reportes_mostrar if "proceso"  in r.get("Estado",""))
            n_pend_mios      = n_total_mios - n_resueltos_mios - n_proceso_mios
            st.markdown(
                f'<div style="background:rgba(74,222,128,0.08);border:1px solid #4ade80;'
                f'border-radius:10px;padding:10px 16px;margin-bottom:10px;font-size:13px;">'
                f'👤 <b>Tus reportes:</b> {n_total_mios} total · '
                f'🔴 {n_pend_mios} pendientes · 🟡 {n_proceso_mios} en proceso · '
                f'✅ {n_resueltos_mios} resueltos'
                f'</div>', unsafe_allow_html=True)

        if not reportes_mostrar:
            if busq_codigo.strip():
                st.info("No encontré reportes con ese código/teléfono. Revisa que esté "
                        "escrito igual a como lo pusiste al reportar.")
            else:
                st.info("Aún no has publicado ningún reporte. Toca el mapa y usa "
                        "'📸 Reportar Residuo' para el primero.")
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

        st.markdown("---")
        with st.expander("👍 Confirmar reportes activos de la comunidad"):
            st.caption(
                "Si pasaste por alguno de estos puntos y el residuo sigue ahí, "
                "confírmalo — ayuda a la administración a priorizar. Cada persona "
                "solo puede confirmar un reporte una vez por sesión."
            )
            activos = [r for r in st.session_state.reportes if "Resuelto" not in r.get("Estado", "")]
            if "confirmados_sesion" not in st.session_state:
                st.session_state.confirmados_sesion = set()
            if not activos:
                st.info("No hay reportes activos en este momento.")
            for r in activos[-15:][::-1]:
                cod = r["Código"]
                c_info, c_btn = st.columns([4, 1])
                with c_info:
                    st.markdown(
                        f"**{cod}** · {r.get('Sector','')} · {r.get('Clasificación','')} · "
                        f"👍 {r.get('Confirmaciones', 0)} confirmaciones"
                    )
                with c_btn:
                    ya_confirmado = cod in st.session_state.confirmados_sesion
                    if st.button("👍 Confirmar", key=f"confirmar_{cod}",
                                 disabled=ya_confirmado, use_container_width=True):
                        for rep in st.session_state.reportes:
                            if rep["Código"] == cod:
                                rep["Confirmaciones"] = rep.get("Confirmaciones", 0) + 1
                                break
                        st.session_state.confirmados_sesion.add(cod)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.rerun()

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

        msg_compartir = (
            f"♻️ ¡La Comuna 2 - Santa Cruz está actuando! Entre todos hemos reportado "
            f"{total_pub} puntos de residuos y ya resolvimos {resueltos_pub}, con "
            f"{peso_pub:.0f} kg de carga identificada. Súmate en EcoCom2 Circular IA 🌱"
        )
        st.markdown(
            boton_whatsapp_html(link_whatsapp("", msg_compartir),
                                 "📲 Compartir estas cifras por WhatsApp"),
            unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### 🏆 Barrios más comprometidos")
        st.caption("Ranking por reportes ✅ RESUELTOS — el reconocimiento va para los "
                   "barrios que más han logrado limpiar, no solo reportar.")
        if "Sector" in df_pub.columns and "Estado" in df_pub.columns:
            df_resueltos_barrio = df_pub[df_pub["Estado"].str.contains("Resuelto", na=False)]
            if not df_resueltos_barrio.empty:
                ranking_pos = (df_resueltos_barrio.groupby("Sector").size()
                               .reset_index(name="Puntos resueltos ✅")
                               .sort_values("Puntos resueltos ✅", ascending=False))
                ranking_pos.insert(0, "🏆", ["🥇","🥈","🥉"] + [""] * max(0, len(ranking_pos) - 3))
                st.dataframe(ranking_pos, use_container_width=True, hide_index=True)
            else:
                st.info("Todavía no hay puntos resueltos — ¡el primer barrio en lograrlo "
                        "aparecerá aquí como líder!")

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

    with tab_dash:
        st.markdown("#### ⚙️ Estado del sistema")
        est1, est2 = st.columns(2)
        with est1:
            if verificar_api_key():
                st.markdown(
                    '<div class="badge-ok" style="font-size:13px;">'
                    '✅ API key de Anthropic configurada<br>'
                    '<span style="font-weight:normal">EcoBot puede responder con IA.</span></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div class="badge-err" style="font-size:13px;">'
                    '⚠️ ANTHROPIC_API_KEY no configurada<br>'
                    '<span style="font-weight:normal">EcoBot está en modo "sin conexión" — '
                    'configúrala en Settings → Secrets de tu hosting.</span></div>',
                    unsafe_allow_html=True)
        with est2:
            tam_mb = tamano_bd_mb()
            color_tam = "badge-ok" if tam_mb < 200 else ("badge-warn" if tam_mb < 500 else "badge-err")
            st.markdown(
                f'<div class="{color_tam}" style="font-size:13px;">'
                f'💾 Base de datos: {tam_mb} MB<br>'
                f'<span style="font-weight:normal">Fotos y audio van codificados aquí adentro — '
                f'usa "Eliminar resueltos" si crece mucho.</span></div>',
                unsafe_allow_html=True)
        st.markdown("")

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

    with tab_mapa:
        st.markdown("#### 🗺️ Todos los puntos reportados — mapa de control")

        if not reportes:
            st.info("Sin reportes aún.")
        else:
            fm1, fm2, fm3 = st.columns(3)
            with fm1:
                f_estado = st.selectbox("Filtrar por estado:",
                    ["Todos","🔴 Pendiente","🟡 En proceso","✅ Resuelto"],
                    key="adm_f_estado")
            with fm2:
                f_nivel = st.selectbox("Filtrar por criticidad:",
                    ["Todos","🔴 Crítico","🟡 Amarillo","🟢 Verde"],
                    key="adm_f_nivel")
            with fm3:
                vista_mapa_adm = st.radio(
                    "Vista:", ["📍 Puntos", "🔥 Mapa de calor"],
                    key="vista_mapa_admin", horizontal=True)

            mapa_adm = folium.Map(location=[LAT_C, LON_C],
                                  zoom_start=14, tiles="CartoDB positron")

            coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
            folium.Polygon(locations=coords_p, color="#4ade80", weight=2,
                           fill=True, fill_color="#4ade80", fill_opacity=0.06).add_to(mapa_adm)

            reportes_filtrados = []
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
                reportes_filtrados.append(rep)

            total_mostrados = 0
            if vista_mapa_adm == "🔥 Mapa de calor":
                PESO_CALOR_ADM = {"🔴": 1.0, "🟡": 0.6, "🟢": 0.3}
                datos_calor_adm = []
                for rep in reportes_filtrados:
                    niv = rep.get("Clasificación", "")
                    p = (PESO_CALOR_ADM["🔴"] if "🔴" in niv else
                         PESO_CALOR_ADM["🟡"] if "🟡" in niv else PESO_CALOR_ADM["🟢"])
                    if "Resuelto" in rep.get("Estado", ""):
                        p *= 0.25
                    if rep.get("Lat") is not None and rep.get("Lon") is not None:
                        datos_calor_adm.append([rep["Lat"], rep["Lon"], p])
                        total_mostrados += 1
                if datos_calor_adm:
                    HeatMap(datos_calor_adm, radius=24, blur=20, max_zoom=16,
                            gradient={0.2: "#4ade80", 0.5: "#fbbf24", 0.8: "#f87171", 1.0: "#dc2626"}
                            ).add_to(mapa_adm)
            else:
                for rep in reportes_filtrados:
                    est = rep.get("Estado", "")
                    niv = rep.get("Clasificación", "")
                    col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
                    if "Resuelto" in est:
                        col = "gray"

                    foto_b64 = rep.get("FotoB64", "")
                    img_html  = (f'<br><img src="data:image/jpeg;base64,{foto_b64}" '
                                  f'style="width:160px;border-radius:4px;margin-top:4px;">'
                                  if foto_b64 else "")
                    obs_txt_adm = rep.get("Observaciones", "")
                    obs_html_adm = f"📝 {obs_txt_adm[:100]}<br>" if obs_txt_adm else ""
                    audio_b64_adm = rep.get("NotaVozB64", "")
                    audio_html_adm = (f'<br><audio controls style="width:160px;margin-top:4px;">'
                                      f'<source src="data:audio/wav;base64,{audio_b64_adm}"></audio>'
                                      if audio_b64_adm else "")
                    galeria_adm_html = galeria_html(rep.get("FotosExtraB64", ""), ancho_px=55)
                    popup_adm = (
                        f"<div style='font-family:sans-serif;min-width:190px;'>"
                        f"<b style='color:{col}'>{niv}</b><br>"
                        f"<b>{rep['Código']}</b><br>"
                        f"📍 {rep.get('Sector','')} · {rep.get('Referencia','')[:35]}<br>"
                        f"{obs_html_adm}"
                        f"♻️ {rep.get('Objetos',0)} obj | ⚖️ {rep.get('Peso (Kg)',0)} kg<br>"
                        f"🕐 {rep.get('Fecha','')} | 🔖 {est}"
                        f"{img_html}{audio_html_adm}{galeria_adm_html}</div>"
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
                        st.markdown("**📷 Foto analizada por la IA:**")
                        st.markdown(
                            f'<img src="data:image/jpeg;base64,{foto_b64}" '
                            f'style="max-width:320px;border-radius:8px;margin-bottom:10px;">',
                            unsafe_allow_html=True)
                    if rep.get("FotosExtraB64"):
                        st.markdown(galeria_html(rep["FotosExtraB64"], ancho_px=100),
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

                    obs_rep = rep.get("Observaciones", "")
                    if obs_rep:
                        st.markdown(
                            f'<div style="background:rgba(74,222,128,0.08);border-left:3px solid #4ade80;'
                            f'border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px;">'
                            f'📝 <b>Observaciones del ciudadano:</b><br>{obs_rep}</div>',
                            unsafe_allow_html=True)

                    audio_rep = rep.get("NotaVozB64", "")
                    if audio_rep:
                        st.markdown("**🎙️ Nota de voz del ciudadano:**")
                        try:
                            st.audio(base64.b64decode(audio_rep), format="audio/wav")
                        except Exception:
                            st.caption("⚠️ No se pudo reproducir la nota de voz.")

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

                    tel_wa = extraer_telefono_whatsapp(rep.get("CodigoResidente", ""))
                    if tel_wa:
                        msg_wa = (
                            f"Hola! Tu reporte {codigo} en {rep.get('Sector','')} "
                            f"({rep.get('Referencia','')[:40]}) está ahora: {estado}. "
                            f"— EcoCom2 Circular IA"
                        )
                        st.markdown(
                            boton_whatsapp_html(link_whatsapp(tel_wa, msg_wa),
                                                 "📲 Notificar al residente por WhatsApp"),
                            unsafe_allow_html=True)
                    else:
                        st.caption("📲 Este residente no dejó un teléfono válido para notificar.")

    with tab_export:
        st.markdown("#### 📥 Exportar datos")

        if reportes:
            df_exp = pd.DataFrame(reportes)
            cols_exp = [c for c in df_exp.columns if c not in ("FotoB64", "NotaVozB64")]

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
1. **Verifica tu dirección** en 🏠 Inicio y Mapa — usa tu GPS o escribe tu dirección y presiona 🔍 Verificar
2. **Toca el mapa** en el punto exacto donde están los residuos (si no usaste el GPS)
3. **Presiona el botón** "📸 Ir a Reportar Residuo" o "🚨 Ir a Punto Crítico"
4. **Sube una foto** del residuo y deja que la IA lo analice
5. **Agrega observaciones** por texto o deja una nota de voz si quieres contar detalles que la foto no muestra
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
    st.markdown("## 🔒 Aviso de Tratamiento de Datos Personales")
    st.markdown("""
En cumplimiento de la **Ley 1581 de 2012 (Habeas Data)** y sus decretos reglamentarios,
EcoCom2 Circular IA informa lo siguiente sobre los datos que recoge:

**¿Qué datos recogemos?**
- Fotos que subes al reportar un residuo (pueden mostrar el sitio, objetos y, si no
  tienes cuidado, personas — por eso difuminamos automáticamente cualquier rostro/persona
  que la IA detecte antes de publicar la foto).
- Ubicación aproximada del punto reportado (coordenadas del mapa o la dirección que escribas).
- Código o teléfono, **solo si tú decides escribirlo** — es opcional.
- Observaciones de texto o notas de voz que agregues voluntariamente.

**¿Para qué los usamos?**
- Mostrar el reporte en el mapa comunitario, para que la administración y otros
  residentes puedan verlo y darle seguimiento.
- Si dejaste un teléfono, permitir que la administración te notifique por WhatsApp
  cuando el estado de tu reporte cambie, y que tú mismo puedas buscar tus reportes
  después desde otro dispositivo.

**¿Quién puede ver estos datos?**
La foto, el sector, la clasificación y el estado del reporte son **públicos** — cualquiera
que entre a la app puede verlos en el mapa. El código/teléfono que dejes **no se muestra
públicamente** en el mapa ni en las estadísticas, pero técnicamente cualquiera que lo
supiera podría usarlo para buscar tus reportes en "Mi Historial" — por eso te
recomendamos no usar información sensible ahí.

**¿Cuánto tiempo se guardan?**
Mientras el proyecto piloto esté activo. Puedes pedir que se elimine un reporte tuyo
(foto incluida) contactando a la administración.

**Tus derechos como titular de los datos**
Puedes conocer, actualizar, rectificar o solicitar la eliminación de tus datos en
cualquier momento, contactando al desarrollador del proyecto.

*Este es un aviso informativo básico para un proyecto piloto académico
(Territorio INN 2026, ITM Medellín) y no reemplaza una política de datos formal
revisada por un abogado — si el proyecto crece más allá de la fase piloto, se
recomienda formalizarla.*
""")

    st.markdown("---")
    st.markdown("""
<div style="background:rgba(16,185,129,0.06);border:1px solid rgba(74,222,128,0.2);
border-radius:10px;padding:16px;text-align:center;color:#9ca3af;font-size:13px;">
⚙️ <b style="color:#4ade80">EcoCom2 Circular IA v7.0</b><br>
Proyecto <b style="color:#4ade80">Territorio INN 2026</b> · Instituto Tecnológico Metropolitano (ITM) · Medellín<br>
Desarrollado por: <b style="color:#4ade80">Brandon Duque</b> · Comuna 2 Santa Cruz
</div>
""", unsafe_allow_html=True)
