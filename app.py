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

# 1. CONFIGURACIÓN Y ESTADO (SIEMPRE AL PRINCIPIO)
st.set_page_config(page_title="EcoCom2 Circular IA", layout="wide")

if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
if "gps_lat" not in st.session_state: st.session_state.gps_lat = 6.2982
if "gps_lon" not in st.session_state: st.session_state.gps_lon = -75.5521
if "fuera_de_rango" not in st.session_state: st.session_state.fuera_de_rango = False

BARRIOS_HABILITADOS = ["Andalucía", "Villa del Socorro", "Moscú", "La Francia", "Villa Niza"]

# 2. INTERFAZ
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar residuo", "Punto crítico", "Información"])

if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    # Lógica de Mapa
    mapa = folium.Map(location=[6.2982, -75.5521], zoom_start=17)
    st_folium(mapa, width=1100, height=450)

elif menu == "Reportar residuo":
    st.header("♻️ Reporte de residuos")
    
    # Aquí debe ir tu formulario de subida de imagen y análisis IA
    barrio = st.selectbox("Seleccione el sector del reporte:", BARRIOS_HABILITADOS)
    
    # --- LÓGICA DE VALIDACIÓN (Aquí sí funciona porque 'barrio' ya fue definido arriba) ---
    if barrio in BARRIOS_HABILITADOS:
        st.session_state.fuera_de_rango = False 
    
    # Solo mostramos el botón si la lógica permite el reporte
    if st.session_state.fuera_de_rango:
        st.error(f"🛑 Acceso Denegado: Debes estar en {', '.join(BARRIOS_HABILITADOS)}.")
    else:
        # Aquí iría tu botón: st.button("🚀 ENVIAR REPORTE DEFINITIVO", ...)
        st.write("Botón habilitado para barrios autorizados.")

elif menu == "Información":
    st.header("Acerca de EcoCom2")
    st.write(f"Barrios habilitados: {', '.join(BARRIOS_HABILITADOS)}")
