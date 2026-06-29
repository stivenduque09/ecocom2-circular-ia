import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium
from streamlit_folium import st_folium
import pandas as pd
import streamlit.components.v1 as components
from shapely.geometry import Point, Polygon

# ====================================================================
# 1. CONFIGURACIÓN DE LA PÁGINA
# ====================================================================
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon="♻️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0f1f17; color: #e8f5e9; }
    .block-container { padding-top: 1.5rem; }
    h1, h2, h3 { color: #4ade80 !important; }
    .metric-card {
        background: rgba(16,185,129,0.1);
        border: 1px solid rgba(74,222,128,0.3);
        border-radius: 10px; padding: 16px; text-align: center;
    }
    .gps-ok {
        background: rgba(16,185,129,0.15); border: 1px solid #4ade80;
        border-radius: 8px; padding: 12px 16px; color: #4ade80; font-weight: bold;
    }
    .gps-warn {
        background: rgba(251,191,36,0.12); border: 1px solid #fbbf24;
        border-radius: 8px; padding: 12px 16px; color: #fbbf24; font-weight: bold;
    }
    .gps-error {
        background: rgba(239,68,68,0.12); border: 1px solid #ef4444;
        border-radius: 8px; padding: 12px 16px; color: #ef4444; font-weight: bold;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg,#10b981,#059669);
        border: none; font-weight: bold; font-size: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO REAL COMUNA 2 — SANTA CRUZ, MEDELLÍN
#
#  Límites oficiales verificados:
#   Norte  → Quebrada Negra/Seca (límite con Bello)
#   Oeste  → Río Medellín (límite con Comuna 5 Castilla)
#   Sur    → Quebrada La Rosa (límite con Comuna 4 Aranjuez)
#   Oriente→ Límite con Comuna 1 Popular (ladera)
#
#  Coordenadas WGS84 (lon, lat) del perímetro real ~220 ha
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    # Vértice SW — cerca del río Medellín, altura de Acevedo
    (-75.5720, 6.2960),
    # Borde oeste — siguiendo el río Medellín hacia el norte
    (-75.5710, 6.3020),
    (-75.5705, 6.3080),
    # Vértice NW — quebrada Negra, límite con Bello
    (-75.5700, 6.3130),
    (-75.5660, 6.3160),
    (-75.5610, 6.3170),
    # Vértice NE — ladera alta, límite con Bello/Comuna 1
    (-75.5560, 6.3155),
    (-75.5510, 6.3120),
    # Borde oriente — ladera hacia el sur, límite con Comuna 1
    (-75.5490, 6.3060),
    (-75.5480, 6.2990),
    (-75.5500, 6.2940),
    # Vértice SE — quebrada La Rosa, límite con Comuna 4
    (-75.5540, 6.2910),
    (-75.5600, 6.2920),
    # Cierre SW
    (-75.5660, 6.2940),
    (-75.5720, 6.2960),
])

# Los 11 barrios oficiales de la Comuna 2
BARRIOS_PILOTO = [
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

# Centro geográfico aproximado de la Comuna 2
LAT_CENTRO = 6.3040
LON_CENTRO = -75.5590

# ====================================================================
# 3. ESTADO DE SESIÓN
# ====================================================================
for k, v in {
    "registro_reportes": [],
    "gps_lat": None,
    "gps_lon": None,
    "gps_validado": False,
    "fuera_de_rango": True,
    "reporte_enviado": False,
    "cache_reporte": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ====================================================================
# 4. LEER GPS DESDE QUERY PARAMS  (JS → ?lat=…&lon=… → Streamlit)
# ====================================================================
qp = st.query_params
if "lat" in qp and "lon" in qp:
    try:
        lat_qp = float(qp["lat"])
        lon_qp = float(qp["lon"])
        st.session_state.gps_lat = lat_qp
        st.session_state.gps_lon = lon_qp
        st.session_state.gps_validado = True
        st.session_state.fuera_de_rango = not POLIGONO_COMUNA2.contains(Point(lon_qp, lat_qp))
        st.query_params.clear()
    except Exception:
        pass

# ====================================================================
# 5. MODELO YOLO — conf=0.08 para detectar más objetos en basura real
# ====================================================================
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# ====================================================================
# 6. DICCIONARIO MATERIALES  (clave=nombre YOLO en inglés)
#    Formato: (nombre_español, tipo_material, peso_kg_unidad, reciclable)
# ====================================================================
MATERIALES = {
    # Plástico
    "bottle":           ("Botella plástica",      "Plástico",    0.05,  True),
    "cup":              ("Vaso plástico",          "Plástico",    0.03,  True),
    "chair":            ("Silla plástica",         "Plástico",    2.00,  True),
    "bench":            ("Banco plástico",         "Plástico",    2.50,  True),
    "bucket":           ("Balde plástico",         "Plástico",    0.50,  True),
    "toy":              ("Juguete",                "Plástico",    0.50,  True),
    # Papel / Cartón
    "book":             ("Libro / Cuaderno",       "Papel",       0.30,  True),
    "newspaper":        ("Periódico",              "Papel",       0.10,  True),
    "box":              ("Caja de cartón",         "Cartón",      0.30,  True),
    # Vidrio
    "wine glass":       ("Copa de vidrio",         "Vidrio",      0.20,  True),
    "vase":             ("Jarrón / Matero vidrio", "Vidrio",      0.80,  True),
    # Aluminio
    "can":              ("Lata de aluminio",       "Aluminio",    0.02,  True),
    # Electrónico (RAEE)
    "cell phone":       ("Celular",                "Electrónico", 0.20,  True),
    "laptop":           ("Portátil",               "Electrónico", 2.50,  True),
    "keyboard":         ("Teclado",                "Electrónico", 0.60,  True),
    "mouse":            ("Ratón de computador",    "Electrónico", 0.10,  True),
    "remote":           ("Control remoto",         "Electrónico", 0.20,  True),
    "tv":               ("Televisor",              "Electrónico", 8.00,  True),
    "clock":            ("Reloj",                  "Electrónico", 0.30,  True),
    # Textil
    "backpack":         ("Mochila",                "Textil",      0.50,  True),
    "handbag":          ("Bolso",                  "Textil",      0.40,  True),
    "suitcase":         ("Maleta",                 "Textil",      2.50,  True),
    "tie":              ("Corbata",                "Textil",      0.10,  True),
    "umbrella":         ("Paraguas",               "Textil",      0.50,  True),
    # Orgánico
    "banana":           ("Banano",                 "Orgánico",    0.10,  True),
    "apple":            ("Manzana",                "Orgánico",    0.15,  True),
    "orange":           ("Naranja",                "Orgánico",    0.20,  True),
    "broccoli":         ("Brócoli",                "Orgánico",    0.25,  True),
    "carrot":           ("Zanahoria",              "Orgánico",    0.10,  True),
    "potted plant":     ("Planta / Matero",        "Orgánico",    1.00,  True),
    "bowl":             ("Recipiente / Tazón",     "Plástico",    0.15,  True),
    # Madera / Mixto
    "dining table":     ("Mesa de comedor",        "Madera",      12.00, True),
    "couch":            ("Sofá",                   "Mixto",       15.00, True),
    "bed":              ("Cama",                   "Mixto",       20.00, True),
    # No reciclables / no aplica
    "person":           ("Persona",                "No aplica",   0,     False),
    "dog":              ("Perro",                  "No aplica",   0,     False),
    "cat":              ("Gato",                   "No aplica",   0,     False),
    "car":              ("Vehículo",               "No aplica",   0,     False),
    "bus":              ("Bus",                    "No aplica",   0,     False),
    "truck":            ("Camión",                 "No aplica",   0,     False),
    "bicycle":          ("Bicicleta",              "No aplica",   0,     False),
    "motorcycle":       ("Motocicleta",            "No aplica",   0,     False),
    "traffic light":    ("Semáforo",               "No aplica",   0,     False),
    "stop sign":        ("Señal de tráfico",       "No aplica",   0,     False),
}

# ====================================================================
# 7. BARRA LATERAL
# ====================================================================
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## ♻️ EcoCom2")

menu = st.sidebar.radio(
    "Menú",
    ["🏠 Inicio", "📸 Reportar Residuo", "🚨 Punto Crítico", "ℹ️ Información"]
)

if st.session_state.gps_validado:
    if not st.session_state.fuera_de_rango:
        st.sidebar.markdown(
            f'<div class="gps-ok">✅ Dentro de la Comuna 2<br>'
            f'<small style="font-weight:normal">'
            f'Lat {st.session_state.gps_lat:.5f}<br>'
            f'Lon {st.session_state.gps_lon:.5f}</small></div>',
            unsafe_allow_html=True
        )
    else:
        st.sidebar.markdown(
            f'<div class="gps-error">🛑 Fuera de la Comuna 2<br>'
            f'<small style="font-weight:normal">'
            f'Lat {st.session_state.gps_lat:.5f}<br>'
            f'Lon {st.session_state.gps_lon:.5f}</small></div>',
            unsafe_allow_html=True
        )
else:
    st.sidebar.markdown(
        '<div class="gps-warn">⚠️ GPS no verificado<br>'
        '<small style="font-weight:normal">Ve a 🏠 Inicio para validar</small></div>',
        unsafe_allow_html=True
    )

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="background:rgba(16,185,129,0.08);padding:10px;border-radius:8px;
border:1px solid rgba(74,222,128,0.2);font-size:12px;color:#9ca3af;">
    ⚙️ <b style="color:#4ade80">EcoCom2 v3.2</b><br>
    Territorio INN 2026 | ITM Medellín<br>
    Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>
""", unsafe_allow_html=True)
