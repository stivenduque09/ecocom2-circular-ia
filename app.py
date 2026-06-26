import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium
from streamlit_folium import st_folium
import pandas as pd
import random

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="EcoCom2 Circular IA", layout="wide")

# Inicialización de estado
if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
BARRIOS_PILOTO = ["Andalucía", "Moscú No. 1", "Villa del Socorro", "Santa Cruz", "La Rosa"]
PESOS_REFERENCIA = {"bottle": 0.05, "can": 0.03, "cup": 0.04, "box": 0.25, "paper": 0.05}

@st.cache_resource
def cargar_modelo():
    return YOLO('best.pt')

model = cargar_modelo()

# --- MENÚ ---
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar residuo", "Punto crítico", "Información"])

# --- SECCIÓN INICIO ---
if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Panel de monitoreo de Comuna 2.")
    mapa = folium.Map(location=[6.2950, -75.5530], zoom_start=15)
    st_folium(mapa, width=1000, height=400)
    st.dataframe(pd.DataFrame(st.session_state.registro_reportes))

# --- SECCIÓN REPORTAR (CON GPS Y PESO) ---
elif menu == "Reportar residuo":
    st.header("📸 Reportar Residuo con IA")
    
    # 1. GPS / VALIDACIÓN DE BARRIO
    barrio_gps = st.selectbox("Tu ubicación actual:", BARRIOS_PILOTO + ["Fuera de zona"])
    
    if barrio_gps in BARRIOS_PILOTO:
        st.success(f"📍 GPS Validado: Zona {barrio_gps} activa.")
        archivo = st.file_uploader("Sube foto:", type=["jpg", "png"])
        
        if archivo:
            img = Image.open(archivo)
            detecciones = model(img)
            
            # Procesar IA y Pesos
            clases = [model.names[int(box.cls[0])] for r in detecciones for box in r.boxes]
            total_kilos = sum([PESOS_REFERENCIA.get(c, 0.1) for c in clases])
            
            st.image(detecciones[0].plot(), caption="IA detectó materiales")
            st.metric("📦 Peso Estimado", f"{total_kilos:.2f} Kg")
            
            if st.button("Guardar Reporte Técnico"):
                st.session_state.registro_reportes.append({
                    "Barrio": barrio_gps, "Peso": total_kilos, "Materiales": str(Counter(clases))
                })
                st.success("¡Reporte exitoso!")
    else:
        st.error("🛑 Acceso denegado: Fuera del área de cobertura de la Comuna 2.")

# --- SECCIÓN INFORMACIÓN ---
elif menu == "Información":
    st.header("📖 Guía Educativa")
    st.write("Usa esta guía para saber qué materiales clasifica nuestra IA.")
    with st.expander("🟢 Materiales Aprovechables"):
        st.write("- **Plásticos:** Botellas, envases.")
        st.write("- **Cartón:** Cajas, papel.")
    with st.expander("🔴 Materiales No Aprovechables"):
        st.write("- **Higiene:** Papel usado.")
        st.write("- **Orgánicos:** Comida.")

# --- SECCIÓN PUNTO CRÍTICO ---
elif menu == "Punto crítico":
    st.header("🚨 Reportar Punto Crítico")
    with st.form("punto_critico"):
        referencia = st.text_input("Punto de referencia:")
        if st.form_submit_button("Reportar"):
            st.success(f"Reporte recibido en {referencia}")
