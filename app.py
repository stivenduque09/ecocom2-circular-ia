import streamlit as st
from ultralytics import YOLO, YOLOE
from PIL import Image, ImageFilter
import tempfile
from collections import Counter
import folium
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
