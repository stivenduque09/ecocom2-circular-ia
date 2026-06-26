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
# 1. CONFIGURACIÓN DE LA PÁGINA
# --------------------------------------------------------------------
st.set_page_config(
    page_title="EcoCom2 Circular IA",
    page_icon="♻️",
    layout="wide"
)

# --------------------------------------------------------------------
# 2. BASE DE DATOS EN MEMORIA (PERSISTENCIA DE REPORTES REALES)
# --------------------------------------------------------------------
if "registro_reportes" not in st.session_state:
    st.session_state.registro_reportes = []

# Variables de control para el GPS
if "gps_lat" not in st.session_state:
    st.session_state.gps_lat = None
if "gps_lon" not in st.session_state:
    st.session_state.gps_lon = None
if "metodo_ubicacion" not in st.session_state:
    st.session_state.metodo_ubicacion = "Automático (GPS Satelital)"

# Variable global para validar el estado de bloqueo territorial
if "fuera_de_rango" not in st.session_state:
    st.session_state.fuera_de_rango = True

# --------------------------------------------------------------------
# 3. CARGAR MODELO
# --------------------------------------------------------------------
@st.cache_resource
def cargar_modelo():
    try:
        return YOLO("yolov8m.pt")
    except Exception:
        return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# --------------------------------------------------------------------
# 4. DICCIONARIO DE MATERIALES Y PESOS OPERATIVOS
# --------------------------------------------------------------------
materiales = {
    "book": ("Libro o cuaderno", "Papel", 0.30, True),
    "paper": ("Papel", "Papel", 0.05, True),
    "newspaper": ("Periódico", "Papel", 0.10, True),
    "box": ("Caja", "Cartón", 0.30, True),
    "notebook": ("Cuaderno", "Papel", 0.20, True),
    "toy": ("Juguete", "Plástico", 0.50, True),
    "bench": ("Banco", "Plástico", 2.50, True),
    "bucket": ("Balde", "Plástico", 0.50, True),
    "laptop": ("Portátil", "Electrónico", 2.50, True),
    "remote": ("Control remoto", "Electrónico", 0.20, True),
    "bottle": ("Botella", "Plástico", 0.05, True),
    "cup": ("Vaso", "Plástico", 0.03, True),
    "chair": ("Silla", "Plástico", 2.00, True),
    "wine glass": ("Vidrio", "Vidrio", 0.20, True),
    "glass": ("Vidrio", "Vidrio", 0.20, True),
    "vase": ("Jarrón", "Vidrio", 0.80, True),
    "can": ("Lata", "Aluminio", 0.02, True),
    "cell phone": ("Celular", "Electrónico", 0.20, True),
    "keyboard": ("Teclado", "Electrónico", 0.60, True),
    "mouse": ("Ratón", "Electrónico", 0.10, True),
    "tv": ("Televisor", "Electrónico", 8.00, True),
    "backpack": ("Mochila", "Textil", 0.50, True),
    "handbag": ("Bolso", "Textil", 0.40, True),
    "suitcase": ("Maleta", "Textil", 2.50, True),
    "tie": ("Corbata", "Textil", 0.10, True),
    "banana": ("Banano", "Orgánico", 0.10, True),
    "apple": ("Manzana", "Orgánico", 0.15, True),
    "orange": ("Naranja", "Orgánico", 0.20, True),
    "broccoli": ("Brócoli", "Orgánico", 0.25, True),
    "carrot": ("Zanahoria", "Orgánico", 0.10, True),
    "couch": ("Sofá", "Mixto", 15.00, True),
    "bed": ("Cama", "Mixto", 20.00, True),
    "dining table": ("Mesa", "Madera", 12.00, True),
    "clock": ("Reloj", "Electrónico", 0.30, True),
    "umbrella": ("Sombrilla", "Mixto", 0.50, True),
    "person": ("Persona", "No aplica", 0, False),
    "dog": ("Perro", "No aplica", 0, False),
    "cat": ("Gato", "No aplica", 0, False),
    "bird": ("Ave", "No aplica", 0, False),
    "horse": ("Caballo", "No aplica", 0, False),
    "car": ("Vehículo", "No aplica", 0, False),
    "bus": ("Bus", "No aplica", 0, False),
    "truck": ("Camión", "No aplica", 0, False),
    "motorcycle": ("Motocicleta", "No aplica", 0, False),
    "bicycle": ("Bicicleta", "No aplica", 0, False)
}

BARRIOS_PILOTO = ["Andalucía", "Villa del Socorro", "Moscú"]

# --------------------------------------------------------------------
# 5. MENÚ LATERAL
# --------------------------------------------------------------------
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.title("♻️ EcoCom2")

menu = st.sidebar.radio(
    "Menú",
    ["Inicio", "Reportar residuo", "Punto crítico", "Información"]
)

st.sidebar.markdown("---")
st.sidebar.markdown("""
    <div style="background-color: rgba(16, 185, 129, 0.1); padding: 12px; border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.2); font-family: sans-serif; font-size: 12px; color: #374151;">
        ⚙️ <b>Ecosistema EcoCom2 v1.9</b><br>
        Territorio INN 2026 | ITM Medellín<br>
        Desarrollado por: <b>Brandon Duque</b>
    </div>
""", unsafe_allow_html=True)

query_params = st.query_params
if "lat" in query_params and "lon" in query_params:
    st.session_state.gps_lat = float(query_params["lat"])
    st.session_state.gps_lon = float(query_params["lon"])
    st.query_params.clear()

# --------------------------------------------------------------------
# 6. SECCIÓN: INICIO
# --------------------------------------------------------------------
if menu == "Inicio":
    from geopy.geocoders import Nominatim

    st.title("♻️ EcoCom2 Circular IA")
    st.write("Sistema inteligente de gestión de residuos mediante inteligencia artificial.")
    
    st.markdown("### 📍 Panel Territorial Semicontrolado (Sectores del Prototipo)")
    st.markdown("#### 🌐 Verificación de Cobertura Territorial Obligatoria")

    # Selección de método
    st.session_state.metodo_ubicacion = st.radio(
        "Selecciona el método de verificación para el prototipo:",
        ["Automático (GPS Satelital)", "Manual (Ingresar Dirección Exacta)"],
        horizontal=True
    )

    direccion_detectada = ""
    
    # Coordenadas maestras para la Carrera 50 # 107-62
    LAT_CRA50 = 6.2982
    LON_CRA50 = -75.5521

    if st.session_state.metodo_ubicacion == "Automático (GPS Satelital)":
        js_gps_button = """
        <div style="font-family: sans-serif; margin-bottom: 10px;">
            <button onclick="getRealtimeGPS()" style="background-color: #10B981; color: white; border: none; padding: 12px 24px; font-size: 15px; border-radius: 6px; cursor: pointer; font-weight: bold; width: 100%;">
                📡 SINCRONIZAR Y VERIFICAR GPS REAL
            </button>
        </div>
        <script>
        function getRealtimeGPS() {
            if (navigator.geolocation) {
                navigator.geolocation.getCurrentPosition(
                    (position) => {
                        const lat = position.coords.latitude;
                        const lon = position.coords.longitude;
                        window.parent.location.search = `?lat=${lat}&lon=${lon}`;
                    },
                    (error) => { alert("Error al acceder al GPS. Verifica los permisos."); },
                    { enableHighAccuracy: true, timeout: 10000 }
                );
            } else { alert("Tu dispositivo no soporta geolocalización."); }
        }
        </script>
        """
        components.html(js_gps_button, height=60)

        if st.session_state.gps_lat and st.session_state.gps_lon:
            lat_base = st.session_state.gps_lat
            lon_base = st.session_state.gps_lon
            try:
                geolocator = Nominatim(user_agent="ecocom2_circular_ia")
                location = geolocator.reverse(f"{lat_base}, {lon_base}")
                direccion_detectada = location.address if location else "Medellín, Comuna 2"
            except Exception:
                direccion_detectada = "Medellín, Andalucía, Comuna 2"
            
            if any(b.lower() in direccion_detectada.lower() for b in BARRIOS_PILOTO) or "andalucía" in direccion_detectada.lower() or "socorro" in direccion_detectada.lower() or "moscú" in direccion_detectada.lower():
                st.success(f"✅ **Rango verificado por GPS:** Zona autorizada.\n\n🏠 *Ubicación:* {direccion_detectada}")
                st.session_state.fuera_de_rango = False
            else:
                st.error(f"🛑 **Fuera de rango por GPS:** {direccion_detectada}. El sistema ha bloqueado las funciones de reporte.")
                st.session_state.fuera_de_rango = True
        else:
            st.warning("⚠️ Presiona el botón de arriba para activar el GPS y validar tu ubicación.")
            st.session_state.fuera_de_rango = True

    else:
        # PLAN B: Entrada manual fija en la Carrera 50
        st.markdown("#### ✍️ Registro por Dirección de Cuadrante")
        direccion_manual = st.text_input("Escribe tu dirección exacta en Comuna 2:", value="Carrera 50a # 107-62",
