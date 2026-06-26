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

# --- 1. CONFIGURACIÓN Y ESTADO (PROTEGIDO CONTRA ERRORES) ---
st.set_page_config(page_title="EcoCom2 Circular IA", layout="wide")

if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
if "gps_lat" not in st.session_state: st.session_state.gps_lat = 6.2982
if "gps_lon" not in st.session_state: st.session_state.gps_lon = -75.5521
if "fuera_de_rango" not in st.session_state: st.session_state.fuera_de_rango = False

BARRIOS_HABILITADOS = ["Andalucía", "La Francia", "Villa del Socorro", "Moscú", "Villa Niza"]

GUIA_RECICLAJE = {
    "Papel y Cartón": "Cajas, cuadernos, revistas, papel periódico.",
    "Plástico": "Botellas PET, baldes, juguetes, sillas plásticas.",
    "Vidrio": "Frascos de conservas, botellas de vidrio.",
    "Aluminio": "Latas de gaseosa, latas de alimentos."
}

# Carga modelo
@st.cache_resource
def cargar_modelo():
    try: return YOLO("yolov8m.pt")
    except: return None
modelo = cargar_modelo()

# --- 2. MENÚ LATERAL ---
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar Residuo", "Guía de Reciclaje", "Información"])

# --- 3. LÓGICA POR SECCIONES ---

if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Bienvenido, habitante de la Comuna 2.")
    
    # Mapa
    mapa = folium.Map(location=[6.2982, -75.5521], zoom_start=15)
    st_folium(mapa, width=1000, height=400)
    
    st.subheader("Historial de Reportes")
    if st.session_state.registro_reportes:
        st.dataframe(pd.DataFrame(st.session_state.registro_reportes))
    else:
        st.info("Aún no hay reportes en el mapa.")

elif menu == "Reportar Residuo":
    st.header("♻️ Reportar Residuo")
    barrio = st.selectbox("Selecciona tu barrio en Comuna 2:", BARRIOS_HABILITADOS)
    
    # FORZADO: Si selecciona un barrio, habilitamos reporte
    st.session_state.fuera_de_rango = False 
    
    st.success(f"✅ Estás reportando desde **{barrio}**. El sistema está listo.")
    
    referencia = st.text_input("Referencia del lugar:")
    img_file = st.file_uploader("Sube una foto:", type=["jpg", "png"])
    
    if img_file and st.button("🚀 ENVIAR REPORTE DEFINITIVO"):
        st.session_state.registro_reportes.append({
            "Barrio": barrio, "Referencia": referencia, "Estado": "Registrado"
        })
        st.success("¡Reporte enviado exitosamente a la comunidad!")
        st.balloons()

elif menu == "Guía de Reciclaje":
    st.header("🔍 ¿Qué puedo reciclar?")
    st.write("Consulta aquí qué materiales son aprovechables:")
    for mat, desc in GUIA_RECICLAJE.items():
        with st.expander(f"📦 {mat}"):
            st.write(desc)

elif menu == "Información":
    st.header("Acerca de EcoCom2")
    st.write("Proyecto ITM - Comuna 2. Gestión inteligente de residuos.")
