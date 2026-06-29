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
from datetime import datetime
import base64
from io import BytesIO

# ====================================================================
# PERSISTENCIA
# ====================================================================
REPORTES_FILE = "/tmp/ecocom2_reportes.json"

def cargar_reportes_disco():
    if os.path.exists(REPORTES_FILE):
        try:
            with open(REPORTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_reportes_disco(reportes):
    try:
        with open(REPORTES_FILE, "w", encoding="utf-8") as f:
            json.dump(reportes, f, ensure_ascii=False, indent=2)
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

    /* Sidebar verde moderno */
[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #166534 0%, #15803d 100%) !important;
        border-right: 3px solid #86efac;
    }
    border-right: 3px solid #86efac;
}
    [data-testid="stSidebar"] * { color: #f0fdf4 !important; }
    [data-testid="stSidebar"] .stRadio label { font-size: 15px !important; font-weight: 600 !important; }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
        background: rgba(255,255,255,0.08);
        border-radius: 8px; padding: 8px 12px; margin: 3px 0;
        transition: background 0.2s;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
        background: rgba(255,255,255,0.18);
    }

    /* ── Títulos ─────────────────────────────────────────────────── */
    h1 { color: #166534 !important; font-size: 2rem !important; font-weight: 800 !important; }
    h2 { color: #15803d !important; font-weight: 700 !important; }
    h3 { color: #16a34a !important; font-weight: 600 !important; }

    /* ── Header de Streamlit oculto ──────────────────────────────── */
  /* ── Ocultar fondo del header pero mantener el botón visible ── */
    header { 
        background-color: transparent !important; 
    }
    
    /* Ocultar solo el menú de los 3 puntitos de Streamlit (opcional) */
    [data-testid="stHeader"] > div > div:nth-child(2) {
        visibility: hidden !important;
    }

    /* ── Badges de estado ────────────────────────────────────────── */
  /* Ajuste para mayor contraste en Badges */
  .badge-ok {
        background: #dcfce7 !important; 
        border: 2px solid #16a34a !important;
        border-radius: 10px; padding: 12px 16px;
        color: #064e3b !important; /* Verde muy oscuro forzado */
        font-weight: 800 !important; font-size: 14px;
    }
   .badge-warn {
        background: #fefce8 !important; 
        border: 2px solid #ca8a04 !important;
        border-radius: 10px; padding: 12px 16px;
        color: #854d0e !important; /* Ámbar muy oscuro forzado */
        font-weight: 800 !important; font-size: 14px;
    }
   .badge-err {
        background: #fef2f2 !important; 
        border: 2px solid #dc2626 !important;
        border-radius: 10px; padding: 12px 16px;
        color: #7f1d1d !important; /* Rojo muy oscuro forzado */
        font-weight: 800 !important; font-size: 14px;
    }

    /* ── Cards de métricas ───────────────────────────────────────── */
.metric-card {
        background: #ffffff;
        border: 2px solid #86efac; /* Un verde un poco más marcado */
        /* ... resto de tu código ... */
    }
    .metric-card h2, .metric-card h3 { 
        color: #064e3b !important; /* Verde muy oscuro */
        font-weight: 900 !important; 
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-card h2, .metric-card h3 { margin: 0 0 4px 0 !important; }
    .metric-card p { color: #4b5563 !important; font-size: 13px !important; margin: 0; }

    /* ── Botones primarios ───────────────────────────────────────── */
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

    /* ── Botones secundarios ─────────────────────────────────────── */
    div[data-testid="stButton"] button[kind="secondary"] {
        background: #ffffff !important; color: #166534 !important;
        border: 2px solid #16a34a !important;
        font-weight: 600 !important; border-radius: 10px !important;
    }

    /* ── Inputs ──────────────────────────────────────────────────── */
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

    /* ── Selectbox ───────────────────────────────────────────────── */
    div[data-testid="stSelectbox"] > div > div {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; background: #ffffff !important;
    }

    /* ── Tabs ────────────────────────────────────────────────────── */
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

    /* ── Expanders ───────────────────────────────────────────────── */
    div[data-testid="stExpander"] {
        border: 1px solid #bbf7d0 !important;
        border-radius: 10px !important;
        background: #ffffff !important;
        margin-bottom: 8px !important;
    }

    /* ── Dataframes ──────────────────────────────────────────────── */
    div[data-testid="stDataFrameContainer"] {
        border: 2px solid #bbf7d0;
        border-radius: 10px; overflow: hidden;
    }

    /* ── Info / Warning / Error boxes ───────────────────────────── */
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

    /* ── File uploader ───────────────────────────────────────────── */
    div[data-testid="stFileUploader"] {
        background: #f0fdf4 !important; border: 2px dashed #4ade80 !important;
        border-radius: 12px !important; padding: 16px !important;
    }

    /* ── Chat del agente ─────────────────────────────────────────── */
/* ── Chat del agente (Corregido para máxima visibilidad) ─────── */
    .chat-burbuja-user {
        background: #dcfce7 !important; 
        border-radius: 16px 16px 4px 16px !important;
        padding: 12px 16px !important; 
        margin: 8px 0 !important; 
        color: #064e3b !important; /* Verde muy oscuro forzado */
        font-size: 15px !important; 
        font-weight: 600 !important;
        max-width: 80% !important; 
        margin-left: auto !important;
        text-align: right !important;
    }
    .chat-burbuja-bot {
        background: #ffffff !important; 
        border: 2px solid #bbf7d0 !important;
        border-radius: 16px 16px 16px 4px !important;
        padding: 12px 16px !important; 
        margin: 8px 0 !important; 
        color: #0f172a !important; /* Azul oscuro casi negro forzado */
        font-size: 15px !important; 
        font-weight: 600 !important;
        max-width: 85% !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
    }
    .chat-agente-header {
        background: linear-gradient(135deg, #16a34a, #15803d) !important;
        border-radius: 14px 14px 0 0 !important; 
        padding: 14px 18px !important;
        color: #ffffff !important; /* Blanco garantizado */
        font-weight: 700 !important; 
        font-size: 16px !important;
    }
    .chat-container {
        background: #f8fff8 !important; 
        border: 2px solid #bbf7d0 !important;
        border-radius: 0 0 14px 14px !important; 
        padding: 16px !important;
        max-height: 350px !important; 
        overflow-y: auto !important;
    }
    
    /* Por si acaso usas el input de chat nativo de Streamlit */
    [data-testid="stChatInput"] textarea {
        color: #0f172a !important;
        background-color: #ffffff !important;
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
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()

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


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar_inversa(lat: float, lon: float) -> str:
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4_rev", timeout=6)
        r = geo.reverse(f"{lat}, {lon}", language="es")
        if r and r.raw.get("address"):
            a = r.raw["address"]
            partes = []
            calle  = a.get("road") or a.get("pedestrian") or a.get("path") or ""
            num    = a.get("house_number", "")
            barrio = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
            if calle:
                partes.append(calle + (f" #{num}" if num else ""))
            if barrio:
                partes.append(barrio)
            partes.append("Medellín")
            return ", ".join(partes) if partes else r.address
        return f"{lat:.5f}, {lon:.5f}"
    except Exception:
        return f"{lat:.5f}, {lon:.5f}"


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


def analizar(img):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        img.save(tmp.name)
        # conf=0.05 detecta más objetos en imágenes de basura real
        return modelo(tmp.name, conf=0.05)


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
            objetos.append((modelo.names[int(box.cls[0])], float(box.conf[0])))

    if not objetos:
        return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados"

    conteo = Counter(o[0] for o in objetos)
    mejor  = {n: max(c for nn, c in objetos if nn == n) for n in conteo}

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

    if total <= 2:
        nivel = "🟢 Residuo puntual"
    elif ratio >= 0.60:
        nivel = "🟢 Punto verde — Alta valorización reciclable"
    elif ratio >= 0.30:
        nivel = "🟡 Punto amarillo — Residuos mixtos"
    else:
        nivel = "🔴 Punto crítico — Acumulación sin valorización"

    return tabla, residuos, round(peso_total, 2), tipo, nivel


def badge(txt, tipo="ok"):
    cls = {"ok":"badge-ok","warn":"badge-warn","err":"badge-err"}[tipo]
    st.markdown(f'<div class="{cls}">{txt}</div><br>', unsafe_allow_html=True)


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
            # Botón resaltado si es la sección activa
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

# SOLUCIÓN Python 3.10: menú SIEMPRE con las mismas 3 opciones (no cambiar dinámicamente)
# El contenido del panel admin está protegido por contraseña dentro de la página
PAGINAS = ["🏠 Inicio y Mapa", "🛡️ Panel Admin", "ℹ️ Información"]
menu = st.sidebar.radio("Menú", PAGINAS)   # sin key → sin conflicto de estado

st.sidebar.markdown("---")
es_admin = st.session_state.get("admin_ok", False)

# ── Login / logout de administrador ──────────────────────────────
if not es_admin:
    with st.sidebar.expander("🔐 Acceso Administrador"):
        pwd = st.text_input("Contraseña:", type="password", key="adm_pwd",
                            placeholder="Ingresa la contraseña")
        if st.button("Ingresar", key="adm_login", type="primary",
                     use_container_width=True):
            if pwd == "ecocom2admin2026":          # ← cambia esta contraseña
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
<div style="font-size:11px;color:#6b7280;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#4ade80">EcoCom2 v5.0</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>""", unsafe_allow_html=True)


# ====================================================================
# 8. INICIO Y MAPA
# ====================================================================
if menu == "🏠 Inicio y Mapa":
    st.title("♻️ EcoCom2 Circular IA")
    st.caption("Gestión inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    # ── AGENTE DE AYUDA IA (sidebar expandible) ───────────────────────
    with st.sidebar.expander("🤖 Asistente EcoCom2", expanded=False):
        st.markdown("""
<div style="background:linear-gradient(135deg,#4ade80,#16a34a);
border-radius:10px;padding:10px 14px;color:white;font-weight:700;
font-size:14px;text-align:center;margin-bottom:10px;">
🤖 Hola, soy EcoBot<br>
<span style="font-weight:400;font-size:12px">Te ayudo a reportar residuos</span>
</div>""", unsafe_allow_html=True)

        # Historial del chat del agente
        if "agente_msgs" not in st.session_state:
            st.session_state.agente_msgs = [
                {"role": "assistant",
                 "content": "¡Hola! 👋 Soy **EcoBot**, tu asistente de EcoCom2.\n\nPuedo ayudarte a:\n- 📍 Verificar tu dirección\n- 📸 Saber cómo reportar residuos\n- 🚨 Reportar puntos críticos\n- ♻️ Entender cómo funciona la IA\n\n¿En qué te ayudo hoy?"}
            ]

        # Mostrar historial
        for msg in st.session_state.agente_msgs[-6:]:   # últimos 6 mensajes
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

        # Input del usuario
        pregunta = st.text_input("Escribe tu pregunta:",
                                  placeholder="¿Cómo reporto basura?",
                                  key="agente_input",
                                  label_visibility="collapsed")
        col_send, col_clear = st.columns([3,1])
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

            # Llamar a la API de Claude
            try:
                import requests
                SISTEMA_AGENTE = """Eres EcoBot, el asistente amigable de EcoCom2 Circular IA,
una app para reportar residuos en la Comuna 2 - Santa Cruz de Medellín, Colombia.

Responde en español, de forma CORTA (máximo 3 oraciones), amigable y clara.
Usa emojis para hacer la respuesta más visual.
Eres accesible para niños, adultos y personas mayores.

Lo que hace la app:
- Verificar si el usuario vive en la Comuna 2 por dirección
- Tocar el mapa para seleccionar el punto exacto del residuo
- La IA (YOLOv8) detecta materiales en la foto
- 🟢 Verde: muchos reciclables | 🟡 Amarillo: mezcla | 🔴 Rojo: basura sin valorizar
- El reporte queda guardado en el mapa comunitario

Pasos para reportar:
1. Verificar dirección en el campo de arriba
2. Tocar el mapa en el punto del residuo
3. Presionar "Reportar Residuo" o "Punto Crítico"
4. Subir una foto
5. La IA analiza y clasifica automáticamente
6. Presionar Publicar

Si preguntan algo fuera de EcoCom2, redirige amablemente al tema de residuos."""

                mensajes_api = [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.agente_msgs
                ]

                resp = requests.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 200,
                        "system": SISTEMA_AGENTE,
                        "messages": mensajes_api,
                    },
                    timeout=15
                )
                if resp.status_code == 200:
                    data = resp.json()
                    respuesta = data["content"][0]["text"]
                else:
                    respuesta = "⚠️ No pude conectarme en este momento. Para reportar: verifica tu dirección, toca el mapa y sube una foto."
            except Exception:
                respuesta = "⚠️ Sin conexión al asistente. Pasos: 1️⃣ Verifica dirección 2️⃣ Toca el mapa 3️⃣ Sube foto 4️⃣ Publica."

            st.session_state.agente_msgs.append(
                {"role": "assistant", "content": respuesta})
            st.rerun()

        # Preguntas rápidas de acceso rápido
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
                st.session_state.agente_msgs.append({"role":"user","content":pq})
                st.session_state["agente_input"] = pq
                st.rerun()

    # ── CAMPO DE DIRECCIÓN (se auto-rellena al hacer clic en el mapa) ─
    dir_auto = st.session_state.get("click_dir") or st.session_state.get("direccion") or ""

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
        if st.button("🔍 Verificar", type="primary", use_container_width=True):
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

    # Badge de estado
    if st.session_state.validado:
        if not st.session_state.fuera:
            badge(f"✅ <b>Dentro de la Comuna 2</b> — {st.session_state.direccion[:80]}", "ok")
        else:
            badge(f"🛑 Fuera de la Comuna 2 — {st.session_state.direccion[:70]}<br>"
                  f"<span style='font-weight:normal;font-size:12px'>"
                  f"Puedes usar el analizador de materiales, pero no publicar reportes.</span>", "err")
        if st.button("🔄 Cambiar dirección", key="cambiar_dir"):
            for k in ["validado","lat","lon","fuera","direccion",
                      "click_lat","click_lon","click_dir",
                      "punto_lat","punto_lon","cache"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")
    st.markdown("### 🗺️ Toca el punto exacto del residuo en el mapa")
    st.caption("Al tocar, la dirección aparece automáticamente arriba y puedes reportar directo.")

    lat_c = st.session_state.get("lat") or LAT_C
    lon_c = st.session_state.get("lon") or LON_C

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=14, tiles="CartoDB positron")

    # Polígono oficial
    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_p, color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        tooltip="📍 Área piloto — Comuna 2 Santa Cruz (Acevedo → Villa del Socorro)"
    ).add_to(mapa)

    # Pin hogar
    if st.session_state.get("validado") and st.session_state.get("lat"):
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker(
            location=[st.session_state.lat, st.session_state.lon],
            popup=f"🏠 {st.session_state.direccion}",
            tooltip="🏠 Tu dirección verificada",
            icon=folium.Icon(color=col_pin, icon="home", prefix="fa")
        ).add_to(mapa)

    # Pin punto seleccionado
    if st.session_state.get("click_lat"):
        folium.Marker(
            location=[st.session_state.click_lat, st.session_state.click_lon],
            popup=f"📌 {st.session_state.get('click_dir','Punto seleccionado')}",
            tooltip="📌 Punto seleccionado",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(mapa)

    # Reportes guardados
    for rep in st.session_state.reportes:
        niv = rep.get("Clasificación", "🟢")
        col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
        # Construir popup con foto si está disponible
        foto_b64 = rep.get("FotoB64", "")
        img_html = (f'<br><img src="data:image/jpeg;base64,{foto_b64}" '
                    f'style="width:180px;border-radius:6px;margin-top:6px;">'
                    if foto_b64 else "")
        popup_html = (
            f"<div style='font-family:sans-serif;min-width:190px;'>"
            f"<b style='color:{col}'>{niv}</b><br>"
            f"<b>{rep['Código']}</b><br>"
            f"📍 {rep['Sector']}<br>"
            f"📌 {rep.get('Referencia','')[:40]}<br>"
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

    # ── Click en el mapa → dirección automática en el campo de arriba ─
    if mapa_data and mapa_data.get("last_clicked"):
        clk = mapa_data["last_clicked"]
        lat_clk = round(clk["lat"], 7)
        lon_clk = round(clk["lng"], 7)
        if (lat_clk != st.session_state.get("click_lat") or
                lon_clk != st.session_state.get("click_lon")):
            st.session_state.click_lat = lat_clk
            st.session_state.click_lon = lon_clk
            with st.spinner("📍 Detectando dirección..."):
                dir_obtenida = geocodificar_inversa(lat_clk, lon_clk)
            st.session_state.click_dir = dir_obtenida
            # Si aún no estaba verificado, validar automáticamente
            if not st.session_state.get("validado"):
                set_ubicacion(lat_clk, lon_clk, dir_obtenida)
            st.rerun()  # ← recarga y el campo de dirección muestra la nueva

    # ====================================================================
    # PANEL DE ACCIÓN — aparece cuando hay punto seleccionado
    # ====================================================================
    clat       = st.session_state.get("click_lat")
    clon       = st.session_state.get("click_lon")
    cdir       = st.session_state.get("click_dir", "")
    dentro_clk = POLIGONO_COMUNA2.contains(Point(clon, clat)) if clat else False

    if clat:
        st.markdown("")
        # Tarjeta de dirección del punto
        color_card = "#4ade80" if dentro_clk else "#ef4444"
        estado_txt = "✅ Dentro de la Comuna 2" if dentro_clk else "🛑 Fuera del área piloto"
        st.markdown(
            f'<div style="background:rgba(16,185,129,0.08);border:1px solid {color_card};'
            f'border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
            f'<span style="color:{color_card};font-weight:bold;font-size:14px;">📌 {cdir}</span><br>'
            f'<span style="color:#9ca3af;font-size:12px;">{estado_txt} · {clat:.5f}, {clon:.5f}</span>'
            f'</div>',
            unsafe_allow_html=True)

        # ── BOTONES DE ACCIÓN — redirigen al menú lateral ───────────
        if dentro_clk and es_residente():
            st.markdown("")
            # Guardar el punto seleccionado para que lo use la página de reporte
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
                    for k in ["click_lat","click_lon","click_dir",
                               "cache","punto_para_reporte"]:
                        st.session_state.pop(k, None)
                    st.rerun()
        elif clat and not es_residente():
            badge("⚠️ Verifica tu dirección arriba para reportar en este punto.", "warn")

    st.markdown("")

    st.markdown("")
    seccion = st.session_state.get("seccion", "info")

    # ── Indicador de sección activa (compacto, sin duplicar botones) ──
    if seccion != "info":
        iconos = {"residuo": "📸 Reportar Residuo", "critico": "🚨 Punto Crítico",
                  "historial": "📋 Historial"}
        st.markdown(
            f'<div style="border-bottom:2px solid #4ade80;padding:6px 0 4px 0;'
            f'color:#4ade80;font-weight:bold;font-size:15px;margin-bottom:12px;">'
            f'{iconos.get(seccion,"")}</div>',
            unsafe_allow_html=True)

    # ── SECCIÓN: Punto en el mapa ──────────────────────────────────────
    if seccion == "info":
        if not clat:
            st.info("👆 Toca cualquier punto del mapa y usa los botones que aparecen para reportar.")

    # ── SECCIÓN: Reportar Residuo ──────────────────────────────────────
    elif seccion == "residuo":
        st.markdown("### 📸 Reportar Residuo")

        if not es_residente():
            badge("⚠️ Verifica tu dirección para reportar.", "warn")
        elif not clat or not dentro_clk:
            badge("⚠️ Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"📌 {pdir}", "ok")

            r1, r2 = st.columns(2)
            with r1:
                r_barrio = st.selectbox("Barrio:", BARRIOS, key="r_barrio")
            with r2:
                r_ref = st.text_input("Referencia (edita si quieres):",
                                      value=pdir, key="r_ref")

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

                    tabla, residuos, peso, tipo, nivel = procesar(res)
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

                    # ── Fallback manual si YOLO no detecta nada ──────
                    # (escombros, basura genérica, plástico oscuro, etc.)
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
                        # Clasificar según selección
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
                        "FotoB64": img_a_b64(img),   # ← miniatura para popup del mapa
                    }

            if st.session_state.get("cache"):
                r = st.session_state.cache
                st.markdown(f"**Listo:** {r['Clasificación']} · {r['Objetos']} reciclables · {r['Peso (Kg)']} kg")
                cp, cc = st.columns(2)
                with cp:
                    if st.button("🚀 PUBLICAR EN EL MAPA", type="primary",
                                 use_container_width=True, key="r_publicar"):
                        st.session_state.reportes.append(r)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache = None
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir"]:
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

        if not es_residente():
            badge("⚠️ Verifica tu dirección para registrar alertas.", "warn")
        elif not clat or not dentro_clk:
            badge("⚠️ Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"🚨 {pdir}", "err")

            cr1, cr2 = st.columns(2)
            with cr1:
                cr_barrio = st.selectbox("Barrio:", BARRIOS, key="cr_barrio")
            with cr2:
                cr_ref = st.text_input("Referencia:", value=pdir, key="cr_ref")

            cr_img = st.file_uploader("📷 Foto del punto crítico:",
                                      type=["jpg","jpeg","png"], key="cr_img")
            if cr_img:
                img2 = Image.open(cr_img)

                # ── Botón de análisis — guarda resultados en cache_critico ──
                if st.button("🔍 Evaluar con IA", type="primary",
                             use_container_width=True, key="cr_analizar"):
                    with st.spinner("Analizando con YOLOv8..."):
                        res2 = analizar(img2)
                    st.session_state.cache_foto_b64 = img_a_b64(img2)

                    co2, cd2 = st.columns(2)
                    with co2:
                        st.markdown("**📷 Original**")
                        st.image(img2, use_container_width=True)
                    with cd2:
                        st.markdown("**🤖 Detecciones IA**")
                        st.image(res2[0].plot(), use_container_width=True)

                    tabla2, res2_r, peso2, tipo2, nivel2 = procesar(res2)
                    total2 = sum(len(r.boxes) for r in res2)

                    if tabla2:
                        df_si2 = pd.DataFrame(tabla2)
                        df_si2 = df_si2[df_si2["♻️"] == "✅ Sí"]
                        if not df_si2.empty:
                            st.dataframe(df_si2, use_container_width=True, hide_index=True)

                    # Guardar en session_state para que persista entre reruns
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

                # ── Resultados y botón REGISTRAR — FUERA del bloque analizar ──
                # (esto persiste entre reruns gracias a cache_critico)
                if st.session_state.get("cache_critico"):
                    cc = st.session_state.cache_critico

                    # Si la IA no detectó nada → selector manual
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

                    # Botón REGISTRAR fuera del bloque analizar → siempre visible
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
                            }
                            st.session_state.reportes.append(nuevo)
                            guardar_reportes_disco(st.session_state.reportes)
                            st.session_state.cache_critico = None
                            st.session_state.seccion = "historial"
                            for k in ["click_lat","click_lon","click_dir"]:
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
        if not st.session_state.reportes:
            st.info("Sin reportes aún. Toca el mapa y usa '📸 Reportar Residuo' para el primero.")
        else:
            df = pd.DataFrame(st.session_state.reportes)

            # Métricas resumen
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

            # Tabla con columnas relevantes
            COLS = ["Código","Fecha","Estado","Sector","Referencia",
                    "Objetos","Peso (Kg)","Clasificación"]
            cols_ok = [c for c in COLS if c in df.columns]
            st.dataframe(df[cols_ok], use_container_width=True, hide_index=True)

            # Exportar CSV
            csv_data = df[cols_ok].to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exportar como CSV",
                data=csv_data,
                file_name=f"ecocom2_reportes_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

# ====================================================================
# 9. PANEL ADMINISTRADOR — Gestión completa de reportes
# ====================================================================
elif menu == "🛡️ Panel Admin":

    # ── Pantalla de login si no está autenticado ───────────────────────
    if not st.session_state.get("admin_ok"):
        st.markdown("")
        col_login = st.columns([1, 2, 1])[1]   # centrado
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

    # ── ADMIN AUTENTICADO ─────────────────────────────────────────────
    st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;
margin-bottom:8px;">
<div>
  <h1 style="color:#4ade80;margin:0;">🛡️ Panel de Administración</h1>
  <p style="color:#9ca3af;margin:0;font-size:13px;">
  EcoCom2 Circular IA · Comuna 2 Santa Cruz · ITM Medellín</p>
</div>
</div>""", unsafe_allow_html=True)

    # Procesar acción pendiente ANTES de renderizar (evita removeChild)
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

    # ── PESTAÑAS DEL ADMIN ────────────────────────────────────────────
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

            # ── KPIs principales ─────────────────────────────────────
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

            # ── Reportes por barrio ───────────────────────────────────
            st.markdown("---")
            st.markdown("#### 📍 Reportes por Barrio")
            if "Sector" in df_a.columns:
                conteo_barrio = df_a["Sector"].value_counts().reset_index()
                conteo_barrio.columns = ["Barrio", "Reportes"]
                st.dataframe(conteo_barrio, use_container_width=True,
                             hide_index=True)

            # ── Últimos 5 reportes ────────────────────────────────────
            st.markdown("#### 🕐 Últimos reportes registrados")
            COLS_DASH = ["Código","Fecha","Estado","Sector","Clasificación","Peso (Kg)"]
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
            # Filtros rápidos
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

            # Polígono
            coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
            folium.Polygon(locations=coords_p, color="#4ade80", weight=2,
                           fill=True, fill_color="#4ade80", fill_opacity=0.06).add_to(mapa_adm)

            total_mostrados = 0
            for rep in reportes:
                # Filtrar
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
                popup_adm = (
                    f"<div style='font-family:sans-serif;min-width:190px;'>"
                    f"<b style='color:{col}'>{niv}</b><br>"
                    f"<b>{rep['Código']}</b><br>"
                    f"📍 {rep.get('Sector','')} · {rep.get('Referencia','')[:35]}<br>"
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
            # Filtros
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

                # Aplicar filtros
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
                    # Foto si existe
                    foto_b64 = rep.get("FotoB64","")
                    if foto_b64:
                        st.markdown("**📷 Foto del reporte:**")
                        st.markdown(
                            f'<img src="data:image/jpeg;base64,{foto_b64}" '
                            f'style="max-width:320px;border-radius:8px;margin-bottom:10px;">',
                            unsafe_allow_html=True)

                    # Detalles
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
            # CSV sin la columna de foto (es muy grande)
            cols_exp = [c for c in df_exp.columns if c != "FotoB64"]

            csv_bytes = df_exp[cols_exp].to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Descargar CSV — todos los reportes",
                data=csv_bytes,
                file_name=f"ecocom2_reportes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

            # Solo pendientes
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

| Color | Significado | Acción recomendada |
|---|---|---|
| 🟢 **Verde** | ≥60% objetos reciclables. Punto de **alta valorización** | Ruta de reciclaje |
| 🟡 **Amarillo** | 30-60% mixto: reciclables + basura | Separación en origen |
| 🔴 **Rojo** | <30% reciclable. Acumulación crítica sin valor | Recolección urgente |
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
5. **Publica el reporte** — quedará guardado en el mapa comunitario

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
