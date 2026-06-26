import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium                     
from streamlit_folium import st_folium  
import pandas as pd               
import streamlit.components.v1 as components

# --------------------------------------------------------------------
# 1. CONFIGURACIÓN Y BARRIOS AMPLIADOS
# --------------------------------------------------------------------
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon="♻️", layout="wide")

if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
if "fuera_de_rango" not in st.session_state: st.session_state.fuera_de_rango = False

# NUEVA LISTA DE BARRIOS HABILITADOS
BARRIOS_PILOTO = ["Andalucía", "Villa del Socorro", "Moscú", "La Francia", "Villa Niza"]

@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# --------------------------------------------------------------------
# 2. LÓGICA DE VALIDACIÓN (Función para verificar si está en la zona)
# --------------------------------------------------------------------
def es_zona_valida(texto_ubicacion):
    texto = texto_ubicacion.lower()
    # Verifica si alguno de los barrios está en la dirección o si es Comuna 2
    return any(b.lower() in texto for b in BARRIOS_PILOTO) or "comuna 2" in texto

# --------------------------------------------------------------------
# 3. INTERFAZ (Fragmento de validación en Inicio)
# --------------------------------------------------------------------
# ... (Mantener configuración de menú lateral anterior)

# Dentro del bloque de validación (Inicio), ajusta la lógica así:
if st.session_state.gps_lat and st.session_state.gps_lon:
    # ... (código de geolocalización)
    direccion_detectada = location.address if location else "Medellín, Comuna 2"
    
    if es_zona_valida(direccion_detectada):
        st.success(f"✅ **Zona autorizada:** {direccion_detectada}")
        st.session_state.fuera_de_rango = False
    else:
        st.error(f"🛑 **Fuera de rango:** {direccion_detectada}. No estás en los barrios habilitados.")
        st.session_state.fuera_de_rango = True

# --------------------------------------------------------------------
# 4. CORRECCIÓN EN SECCIÓN "REPORTAR RESIDUO"
# --------------------------------------------------------------------
# Asegúrate de usar esta lógica al final del reporte:

if "cache_nuevo_reporte" in st.session_state:
    st.write("---")
    # AQUÍ ESTÁ LA CLAVE: El usuario puede reportar si está en la lista de barrios
    if st.session_state.fuera_de_rango:
        st.error("🛑 **Acceso Denegado:** Tu ubicación no corresponde a: " + ", ".join(BARRIOS_PILOTO))
    else:
        if st.button("🚀 ENVIAR REPORTE DEFINITIVO", type="primary", use_container_width=True):
            st.session_state.registro_reportes.append(st.session_state.cache_nuevo_reporte)
            del st.session_state.cache_nuevo_reporte  
            st.session_state.reporte_enviado = True
            st.rerun()
