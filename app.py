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

# 1. CONFIGURACIÓN INICIAL (PROTEGIDA)
st.set_page_config(page_title="EcoCom2 Circular IA", layout="wide")

# Inicialización segura de todas las variables
if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
if "gps_lat" not in st.session_state: st.session_state.gps_lat = None
if "gps_lon" not in st.session_state: st.session_state.gps_lon = None
if "fuera_de_rango" not in st.session_state: st.session_state.fuera_de_rango = False

BARRIOS_HABILITADOS = ["Andalucía", "Villa del Socorro", "Moscú", "La Francia", "Villa Niza"]

# Carga de modelo
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")
modelo = cargar_modelo()

# 2. PROCESAMIENTO DE GPS
query_params = st.query_params
if "lat" in query_params and "lon" in query_params:
    st.session_state.gps_lat = float(query_params["lat"])
    st.session_state.gps_lon = float(query_params["lon"])
    st.query_params.clear()

# 3. INTERFAZ
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar residuo", "Punto crítico", "Información"])

if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    
    # Verificación de ubicación
    lat = st.session_state.gps_lat
    lon = st.session_state.gps_lon
    
    if lat and lon:
        st.success(f"📍 GPS Activo: {lat}, {lon}")
        # Aquí va tu lógica de validación de barrio original
        st.session_state.fuera_de_rango = False # Ajusta esto según tu lógica de validación
    else:
        st.warning("Presiona el botón de GPS para validar tu sector.")
        # Aquí iría tu botón de JavaScript para capturar GPS

    # MAPA COMPLETO (Aquí recuperamos el mapa)
    mapa = folium.Map(location=[6.2982, -75.5521], zoom_start=17)
    # [Insertar aquí el resto de tu lógica original para añadir marcadores al mapa]
    st_folium(mapa, width=1100, height=450)

    # HISTORIAL
    st.write("### Historial de Reportes")
    if st.session_state.registro_reportes:
        st.dataframe(pd.DataFrame(st.session_state.registro_reportes))

elif menu == "Reportar residuo":
    st.header("♻️ Reporte de residuos")
    # [Aquí pegas toda tu lógica original de carga de archivo, IA y formulario]
    # Recuerda mantener la condición: if st.session_state.fuera_de_rango: st.error("...") else: st.button("ENVIAR")

# 4. PUNTO CRÍTICO E INFORMACIÓN
elif menu == "Punto crítico":
    st.header("🚨 Punto crítico")
    # [Aquí pegas tu lógica original]
elif menu == "Información":
    st.header("Acerca de EcoCom2")
    st.write(f"Barrios habilitados: {', '.join(BARRIOS_HABILITADOS)}")
