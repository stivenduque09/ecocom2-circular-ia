import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
import os
import numpy as np
from collections import Counter
import folium
from streamlit_folium import st_folium
import pandas as pd
import streamlit.components.v1 as components
from shapely.geometry import Point, Polygon
from geopy.geocoders import Nominatim

# --------------------------------------------------------------------
# 1. CONFIGURACIÓN DE LA PÁGINA
# --------------------------------------------------------------------
st.set_page_config(
    page_title="EcoCom2 Circular IA",
    page_icon="♻️",
    layout="wide"
)

# CSS personalizado
st.markdown("""
<style>
    .stApp { background-color: #0f1f17; color: #e8f5e9; }
    .block-container { padding-top: 1.5rem; }
    h1, h2, h3 { color: #4ade80 !important; }
    .metric-card {
        background: rgba(16, 185, 129, 0.1);
        border: 1px solid rgba(74, 222, 128, 0.3);
        border-radius: 10px;
        padding: 16px;
        text-align: center;
    }
    .gps-ok {
        background: rgba(16, 185, 129, 0.15);
        border: 1px solid #4ade80;
        border-radius: 8px;
        padding: 12px 16px;
        color: #4ade80;
        font-weight: bold;
    }
    .gps-error {
        background: rgba(239, 68, 68, 0.15);
        border: 1px solid #ef4444;
        border-radius: 8px;
        padding: 12px 16px;
        color: #ef4444;
        font-weight: bold;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg, #10b981, #059669);
        border: none;
        font-weight: bold;
        font-size: 16px;
    }
</style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------
# 2. POLÍGONO REAL COMUNA 2 - SANTA CRUZ, MEDELLÍN
# --------------------------------------------------------------------
POLIGONO_COMUNA2 = Polygon([
    (-75.5650, 6.2850),
    (-75.5480, 6.2850),
    (-75.5400, 6.2950),
    (-75.5380, 6.3100),
    (-75.5450, 6.3200),
    (-75.5600, 6.3180),
    (-75.5700, 6.3080),
    (-75.5680, 6.2950),
    (-75.5650, 6.2850),
])

BARRIOS_PILOTO = ["Andalucía", "Villa del Socorro", "Moscú", "Santa Cruz", "La Francia", "Palermo"]
LAT_CRA50 = 6.2982
LON_CRA50 = -75.5521

# --------------------------------------------------------------------
# 3. ESTADO DE SESIÓN
# --------------------------------------------------------------------
defaults = {
    "registro_reportes": [],
    "gps_lat": None,
    "gps_lon": None,
    "gps_validado": False,
    "fuera_de_rango": True,
    "reporte_enviado": False,
    "direccion": "No disponible",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --------------------------------------------------------------------
# 4. CARGAR MODELO
# --------------------------------------------------------------------
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# --------------------------------------------------------------------
# 5. DICCIONARIO DE MATERIALES
# --------------------------------------------------------------------
materiales = {
    "book": ("Libro/Cuaderno", "Papel", 0.30, True),
    "paper": ("Papel", "Papel", 0.05, True),
    "newspaper": ("Periódico", "Papel", 0.10, True),
    "box": ("Caja", "Cartón", 0.30, True),
    "toy": ("Juguete", "Plástico", 0.50, True),
    "bucket": ("Balde", "Plástico", 0.50, True),
    "laptop": ("Portátil", "Electrónico", 2.50, True),
    "remote": ("Control remoto", "Electrónico", 0.20, True),
    "bottle": ("Botella", "Plástico", 0.05, True),
    "cup": ("Vaso", "Plástico", 0.03, True),
    "chair": ("Silla", "Plástico", 2.00,
