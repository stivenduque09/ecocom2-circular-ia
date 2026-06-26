import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium                     
from streamlit_folium import st_folium  
import pandas as pd               
import streamlit.components.v1 as components
from geopy.geocoders import Nominatim

# --------------------------------------------------------------------
# 1. CONFIGURACIÓN Y ESTADO INICIAL
# --------------------------------------------------------------------
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon="♻️", layout="wide")

# Inicialización segura de variables de estado
if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
if "gps_lat" not in st.session_state: st.session_state.gps_lat = None
if "gps_lon" not in st.session_state: st.session_state.gps_lon = None
if "fuera_de_rango" not in st.session_state: st.session_state.fuera_de_rango = False

BARRIOS_PILOTO = ["Andalucía", "Villa del Socorro", "Moscú", "La Francia", "Villa Niza"]

@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# --------------------------------------------------------------------
# 2. FUNCIÓN DE VALIDACIÓN DE BARRIO
# --------------------------------------------------------------------
def es_zona_valida(texto):
    texto = texto.lower()
    return any(b.lower() in texto for b in BARRIOS_PILOTO) or "comuna 2" in texto

# --------------------------------------------------------------------
# 3. INTERFAZ Y LÓGICA (Inicio)
# --------------------------------------------------------------------
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar residuo", "Punto crítico", "Información"])

query_params = st.query_params
if "lat" in query_params and "lon" in query_params:
    st.session_state.gps_lat = float(query_params["lat"])
    st.session_state.gps_lon = float(query_params["lon"])
    st.query_params.clear()

if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    
    # Manejo seguro con .get() para evitar el AttributeError
    lat = st.session_state.get("gps_lat")
    lon = st.session_state.get("gps_lon")

    if lat and lon:
        try:
            geolocator = Nominatim(user_agent="ecocom2_app")
            location = geolocator.reverse(f"{lat}, {lon}")
            dir_text = location.address if location else "Ubicación detectada"
            
            if es_zona_valida(dir_text):
                st.success(f"✅ Zona autorizada: {dir_text}")
                st.session_state.fuera_de_rango = False
            else:
                st.error(f"🛑 Fuera de rango: {dir_text}")
                st.session_state.fuera_de_rango = True
        except:
            st.warning("No se pudo verificar la dirección exacta, pero GPS activo.")
    else:
        st.info("Presiona el botón de GPS para validar tu zona.")

    # [Aquí incluirías tu mapa, igual que antes]
    st.write("Mapa activo...")

# --------------------------------------------------------------------
# 4. REPORTAR RESIDUO (RESTRICCIÓN EN EL BOTÓN)
# --------------------------------------------------------------------
elif menu == "Reportar residuo":
    st.header("♻️ Reporte")
    # ... (código de carga de imagen)
    
    # El bloqueo solo ocurre al intentar enviar
    if st.button("🚀 ENVIAR REPORTE"):
        if st.session_state.fuera_de_rango:
            st.error("❌ Acceso denegado: Debes estar en Andalucía, Socorro, Moscú, La Francia o Villa Niza.")
        else:
            st.success("✅ Reporte enviado con éxito.")
