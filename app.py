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

# --- 1. CONFIGURACIÓN Y ESTADO ---
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

# Carga modelo IA
@st.cache_resource
def cargar_modelo():
    try: return YOLO("yolov8m.pt")
    except: return None
modelo = cargar_modelo()

# --- 2. MENÚ LATERAL ---
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar Residuo", "Guía de Reciclaje", "Información"])

# --- 3. LÓGICA DE SECCIONES ---

if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Bienvenido, habitante de la Comuna 2.")
    mapa = folium.Map(location=[6.2982, -75.5521], zoom_start=15)
    st_folium(mapa, width=1000, height=400)
    
    st.subheader("Historial de Reportes")
    if st.session_state.registro_reportes:
        st.dataframe(pd.DataFrame(st.session_state.registro_reportes))

elif menu == "Reportar Residuo":
    st.header("♻️ Reportar Residuo con IA")
    barrio = st.selectbox("Selecciona tu barrio en Comuna 2:", BARRIOS_HABILITADOS)
    st.session_state.fuera_de_rango = False # Forzamos permiso para Comuna 2
    
    img_file = st.file_uploader("Sube la foto del residuo:", type=["jpg", "png", "jpeg"])
    
    if img_file:
        img = Image.open(img_file)
        st.image(img, caption="Foto cargada", use_container_width=True)
        
        if st.button("🔍 ANALIZAR MATERIALES"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                img.save(tmp.name)
                resultados = modelo(tmp.name, conf=0.25)
            
            res_plotted = resultados[0].plot()
            st.image(res_plotted, caption="IA detectó estos objetos", use_container_width=True)
            
            objetos_detectados = [modelo.names[int(box.cls[0])] for r in resultados for box in r.boxes]
            
            if objetos_detectados:
                conteo = Counter(objetos_detectados)
                st.write("### Objetos detectados:")
                for obj, cant in conteo.items():
                    st.write(f"- **{obj}**: {cant} unidades")
                st.session_state.temp_analisis = {"objetos": conteo, "barrio": barrio}
                st.success("✅ Análisis exitoso.")
            else:
                st.warning("La IA no detectó materiales.")

    if "temp_analisis" in st.session_state:
        if st.button("🚀 ENVIAR REPORTE DEFINITIVO"):
            st.session_state.registro_reportes.append({
                "Barrio": st.session_state.temp_analisis["barrio"], 
                "Residuos": str(dict(st.session_state.temp_analisis["objetos"]))
            })
            del st.session_state.temp_analisis
            st.success("¡Reporte enviado exitosamente!")
            st.rerun()

elif menu == "Guía de Reciclaje":
    st.header("🔍 ¿Qué puedo reciclar?")
    for mat, desc in GUIA_RECICLAJE.items():
        with st.expander(f"📦 {mat}"):
            st.write(desc)

elif menu == "Información":
    st.header("Acerca de EcoCom2")
    st.write("Proyecto ITM - Comuna 2. Gestión inteligente de residuos.")
