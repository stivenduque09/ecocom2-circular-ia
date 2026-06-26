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

# 1. INICIALIZACIÓN SEGURA (Evita el AttributeError)
st.set_page_config(page_title="EcoCom2", layout="wide")

if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
if "gps_lat" not in st.session_state: st.session_state.gps_lat = None
if "gps_lon" not in st.session_state: st.session_state.gps_lon = None
if "fuera_de_rango" not in st.session_state: st.session_state.fuera_de_rango = False

BARRIOS_HABILITADOS = ["Andalucía", "Villa del Socorro", "Moscú", "La Francia", "Villa Niza"]

# 2. PROCESAMIENTO DE QUERY PARAMS
query_params = st.query_params
if "lat" in query_params and "lon" in query_params:
    st.session_state.gps_lat = float(query_params["lat"])
    st.session_state.gps_lon = float(query_params["lon"])
    st.query_params.clear()

# 3. LÓGICA DE VALIDACIÓN
def verificar_zona(lat, lon):
    try:
        geolocator = Nominatim(user_agent="ecocom2_app")
        loc = geolocator.reverse(f"{lat}, {lon}")
        direccion = loc.address.lower() if loc else ""
        return any(b.lower() in direccion for b in BARRIOS_HABILITADOS)
    except:
        return False

# 4. INTERFAZ
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar residuo"])

if menu == "Inicio":
    st.title("EcoCom2 Circular IA")
    
    # Verificación segura
    lat = st.session_state.gps_lat
    lon = st.session_state.gps_lon
    
    if lat and lon:
        if verificar_zona(lat, lon):
            st.success("✅ Estás en un sector autorizado.")
            st.session_state.fuera_de_rango = False
        else:
            st.error("🛑 Estás fuera de los barrios permitidos.")
            st.session_state.fuera_de_rango = True
    else:
        st.info("Presiona el botón de GPS para validar tu zona.")
        # [Aquí iría tu botón de JavaScript para obtener GPS]

elif menu == "Reportar residuo":
    st.header("Reportar residuo")
    # ... (Carga de imagen y lógica de IA)
    
    if st.button("ENVIAR REPORTE"):
        if st.session_state.fuera_de_rango:
            st.error(f"❌ Solo puedes reportar si estás en: {', '.join(BARRIOS_HABILITADOS)}")
        else:
            st.success("✅ Reporte enviado con éxito.")
