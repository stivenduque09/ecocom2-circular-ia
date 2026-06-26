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
#    (Coordenadas aproximadas del límite oficial)
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
    "chair": ("Silla", "Plástico", 2.00, True),
    "wine glass": ("Copa de vidrio", "Vidrio", 0.20, True),
    "vase": ("Jarrón", "Vidrio", 0.80, True),
    "can": ("Lata", "Aluminio", 0.02, True),
    "cell phone": ("Celular", "Electrónico", 0.20, True),
    "keyboard": ("Teclado", "Electrónico", 0.60, True),
    "mouse": ("Ratón", "Electrónico", 0.10, True),
    "tv": ("Televisor", "Electrónico", 8.00, True),
    "backpack": ("Mochila", "Textil", 0.50, True),
    "handbag": ("Bolso", "Textil", 0.40, True),
    "suitcase": ("Maleta", "Textil", 2.50, True),
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
    "car": ("Vehículo", "No aplica", 0, False),
    "bus": ("Bus", "No aplica", 0, False),
    "truck": ("Camión", "No aplica", 0, False),
    "bicycle": ("Bicicleta", "No aplica", 0, False),
}

COLOR_NIVEL = {
    "🔴": "red",
    "🟡": "orange",
    "🟢": "green",
}

# --------------------------------------------------------------------
# 6. LEER PARAMS GPS (desde JS → query params)
# --------------------------------------------------------------------
query_params = st.query_params
if "lat" in query_params and "lon" in query_params:
    try:
        lat = float(query_params["lat"])
        lon = float(query_params["lon"])
        st.session_state.gps_lat = lat
        st.session_state.gps_lon = lon
        # Validar si está dentro del polígono
        punto = Point(lon, lat)
        st.session_state.gps_validado = True
        st.session_state.fuera_de_rango = not POLIGONO_COMUNA2.contains(punto)
        st.query_params.clear()
    except Exception:
        pass

# --------------------------------------------------------------------
# 7. BARRA LATERAL
# --------------------------------------------------------------------
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## ♻️ EcoCom2")

menu = st.sidebar.radio("Menú", ["🏠 Inicio", "📸 Reportar Residuo", "🚨 Punto Crítico", "ℹ️ Información"])

# Badge GPS en sidebar
if st.session_state.gps_validado:
    if not st.session_state.fuera_de_rango:
        st.sidebar.markdown('<div class="gps-ok">✅ GPS: Dentro de Comuna 2</div>', unsafe_allow_html=True)
    else:
        st.sidebar.markdown('<div class="gps-error">🛑 GPS: Fuera de Comuna 2</div>', unsafe_allow_html=True)
else:
    st.sidebar.warning("⚠️ GPS no verificado")

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="background:rgba(16,185,129,0.1);padding:10px;border-radius:8px;border:1px solid rgba(74,222,128,0.2);font-size:12px;color:#9ca3af;">
    ⚙️ <b style="color:#4ade80">EcoCom2 v3.0</b><br>
    Territorio INN 2026 | ITM Medellín<br>
    Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>
""", unsafe_allow_html=True)

# ====================================================================
# 8. SECCIÓN: INICIO
# ====================================================================
if menu == "🏠 Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Sistema inteligente de gestión de residuos — **Solo residentes de la Comuna 2 pueden reportar.**")

    # ------------------------------------------------------------------
    # BOTÓN GPS CON JS → redirige con lat/lon en query params
    # ------------------------------------------------------------------
    st.markdown("### 📡 Verificar mi ubicación")

    gps_html = """
    <div style="font-family:sans-serif; margin-bottom:8px;">
        <button onclick="verificarGPS()" style="
            background: linear-gradient(135deg,#10b981,#059669);
            color:white; border:none; padding:14px 28px;
            font-size:15px; font-weight:bold; border-radius:8px;
            cursor:pointer; width:100%; letter-spacing:0.5px;">
            📡 VALIDAR MI UBICACIÓN GPS
        </button>
        <p id="msg" style="color:#9ca3af; margin-top:8px; font-size:13px;"></p>
    </div>
    <script>
    function verificarGPS() {
        var msg = document.getElementById('msg');
        msg.textContent = '⏳ Obteniendo coordenadas satelitales...';
        if (!navigator.geolocation) {
            msg.textContent = '❌ Tu dispositivo no soporta GPS.';
            return;
        }
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                var lat = pos.coords.latitude.toFixed(6);
                var lon = pos.coords.longitude.toFixed(6);
                msg.textContent = '✅ GPS obtenido: ' + lat + ', ' + lon + ' — redirigiendo...';
                setTimeout(function() {
                    window.parent.location.search = '?lat=' + lat + '&lon=' + lon;
                }, 800);
            },
            function(err) {
                msg.textContent = '❌ Error GPS: ' + err.message + '. Verifica los permisos del navegador.';
            },
            { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
        );
    }
    </script>
    """
    components.html(gps_html, height=90)

    # ------------------------------------------------------------------
    # ESTADO GPS
    # ------------------------------------------------------------------
    if st.session_state.gps_validado:
        lat_u = st.session_state.gps_lat
        lon_u = st.session_state.gps_lon
        if not st.session_state.fuera_de_rango:
            st.markdown(f'<div class="gps-ok">✅ Ubicación validada: {lat_u:.5f}, {lon_u:.5f} — Dentro de la Comuna 2. Puedes reportar residuos.</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="gps-error">🛑 Ubicación detectada: {lat_u:.5f}, {lon_u:.5f} — Fuera de la Comuna 2. Solo puedes visualizar el mapa.</div>', unsafe_allow_html=True)
    else:
        st.info("👆 Presiona el botón para validar tu ubicación y habilitar los reportes.")

    st.markdown("---")

    # ------------------------------------------------------------------
    # MAPA COMUNITARIO
    # ------------------------------------------------------------------
    st.markdown("### 🗺️ Mapa de Congestión en Tiempo Real — Comuna 2")

    barrio_filtro = st.selectbox("Filtrar por barrio:", ["Todos"] + BARRIOS_PILOTO)

    lat_centro = st.session_state.gps_lat if st.session_state.gps_lat else LAT_CRA50
    lon_centro = st.session_state.gps_lon if st.session_state.gps_lon else LON_CRA50

    mapa = folium.Map(location=[lat_centro, lon_centro], zoom_start=16, tiles="CartoDB dark_matter")

    # Dibujar límite de la Comuna 2
    coords_poligono = [(lat, lon) for lon, lat in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_poligono,
        color="#4ade80",
        weight=2,
        fill=True,
        fill_color="#4ade80",
        fill_opacity=0.05,
        popup="Límite Comuna 2 — Santa Cruz, Medellín",
        tooltip="📍 Área piloto EcoCom2"
    ).add_to(mapa)

    # Pin del usuario (posición real GPS)
    if st.session_state.gps_validado:
        color_usuario = "blue" if not st.session_state.fuera_de_rango else "gray"
        folium.Marker(
            location=[st.session_state.gps_lat, st.session_state.gps_lon],
            popup=f"📍 Tu ubicación GPS\n{st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}",
            tooltip="📍 Tú estás aquí",
            icon=folium.Icon(color=color_usuario, icon="user", prefix="fa")
        ).add_to(mapa)

    # Reportes registrados en sus coordenadas REALES
    for rep in st.session_state.registro_reportes:
        if barrio_filtro != "Todos" and rep.get("Sector") != barrio_filtro:
            continue

        lat_r = rep.get("Lat", LAT_CRA50)
        lon_r = rep.get("Lon", LON_CRA50)
        nivel = rep.get("Clasificación", "🟢")
        color = "red" if "🔴" in nivel else ("orange" if "🟡" in nivel else "green")

        popup_html = f"""
        <div style="font-family:sans-serif; min-width:160px;">
            <b>{rep['Código']}</b><br>
            📍 {rep['Sector']}<br>
            📌 {rep['Referencia']}<br>
            ♻️ {rep['Objetos']} objetos | ⚖️ {rep['Peso (Kg)']} kg<br>
            🏷️ {rep['Predominante']}<br>
            <span style="color:{color}">● {nivel}</span>
        </div>
        """
        folium.CircleMarker(
            location=[lat_r, lon_r],
            radius=12,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"Reporte {rep['Código']}"
        ).add_to(mapa)

    st_folium(mapa, width=1100, height=480, returned_objects=[])

    # ------------------------------------------------------------------
    # HISTORIAL
    # ------------------------------------------------------------------
    st.markdown("---")
    st.markdown("### 📋 Historial de Reportes Comunitarios")

    if st.session_state.registro_reportes:
        df = pd.DataFrame(st.session_state.registro_reportes)
        # Mostrar columnas relevantes sin lat/lon crudas
        cols_mostrar = [c for c in ["Código", "Sector", "Referencia", "Objetos", "Peso (Kg)", "Predominante", "Clasificación", "Lat", "Lon"] if c in df.columns]
        st.dataframe(df[cols_mostrar], use_container_width=True)

        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2><p>Puntos registrados</p></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{df["Peso (Kg)"].sum():.1f} kg</h2><p>Carga acumulada</p></div>', unsafe_allow_html=True)
        with c3:
            criticos = len(df[df["Clasificación"].str.contains("crítico", case=False, na=False)])
            st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{criticos}</h2><p>Puntos críticos</p></div>', unsafe_allow_html=True)
    else:
        st.info("💡 Sin reportes aún. Usa '📸 Reportar Residuo' para agregar el primer reporte.")

# ====================================================================
# 10. SECCIÓN: PUNTO CRÍTICO
# ====================================================================
elif menu == "🚨 Punto Crítico":eporte_enviado = True
        st.rerun()

# ====================================================================
# 10. SECCIÓN: PUNTO CRÍTICO
# ====================================================================
elif menu == "🚨 Punto Crítico":
    st.header("🚨 Registrar Punto Crítico")

    if not st.session_state.gps_validado:
        st.warning("⚠️ Valida tu ubicación GPS desde **🏠 Inicio** primero.")
        st.stop()

    if st.session_state.fuera_de_rango:
        st.markdown('<div class="gps-error">🛑 Acceso denegado — Fuera de la Comuna 2.</div>', unsafe_allow_html=True)
        st.stop()

    st.markdown(f'<div class="gps-ok">✅ Residente verificado — {st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}</div>', unsafe_allow_html=True)
    st.markdown("")

    col_a, col_b = st.columns(2)
    with col_a:
        barrio = st.selectbox("Barrio:", BARRIOS_PILOTO, key="barrio_critico")
    with col_b:
        referencia = st.text_input("Referencia del punto:", key="ref_critico")

    imagen = st.file_uploader("📷 Foto del punto crítico:", type=["jpg", "jpeg", "png"], key="img_critico")

    if imagen is not None:
        img = Image.open(imagen)

        if st.button("🔍 Evaluar con IA", type="primary", use_container_width=True):
            with st.spinner("Analizando..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp.name)
                    resultados = modelo(tmp.name, conf=0.10)

            # Comparación
            st.markdown("### 🔬 Original vs Detecciones")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**📷 Original**")
                st.image(img, use_container_width=True)
            with c2:
                st.markdown("**🤖 Detecciones**")
                st.image(resultados[0].plot(), caption="Detecciones IA", use_container_width=True)

            cantidad = sum(len(r.boxes) for r in resultados)
            nivel = (
                "🔴 Punto crítico alto" if cantidad >= 8
                else "🟡 Punto crítico medio" if cantidad >= 4
                else "🟢 Punto crítico bajo"
            )

            st.markdown(f"**Objetos detectados:** {cantidad} → **{nivel}**")

            nuevo = {
                "Código": f"CRIT-{len(st.session_state.registro_reportes) + 500}",
                "Sector": barrio,
                "Referencia": referencia if referencia else "Punto crítico manual",
                "Objetos": cantidad,
                "Peso (Kg)": round(cantidad * 0.4, 2),
                "Predominante": "Mixto",
                "Clasificación": nivel,
                "Lat": st.session_state.gps_lat,
                "Lon": st.session_state.gps_lon,
            }

            st.markdown(f"📍 **Se registrará en:** {st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}")

            if st.button("🚨 REGISTRAR ALERTA", type="primary", use_container_width=True):
                st.session_state.registro_reportes.append(nuevo)
                st.success("✅ Alerta registrada en el mapa de congestión.")

# ====================================================================
# 11. SECCIÓN: INFORMACIÓN
# ====================================================================
elif menu == "ℹ️ Información":
    st.header("ℹ️ ¿Qué es EcoCom2 Circular IA?")

    st.markdown("""
    **EcoCom2 Circular IA** es una plataforma de gestión inteligente de residuos sólidos desarrollada para la **Comuna 2 — Santa Cruz, Medellín**.

    ### 🔐 Sistema de Validación Territorial
    - El acceso para **reportar** está **exclusivamente** habilitado para residentes dentro del polígono oficial de la Comuna 2.
    - La validación se realiza en tiempo real mediante **GPS satelital del dispositivo**.
    - Observadores externos pueden **ver el mapa** pero no enviar reportes.

    ### 🤖 Inteligencia Artificial (YOLOv8)
    - Detecta automáticamente objetos en fotografías.
    - Clasifica materiales: Plástico, Papel, Vidrio, Aluminio, Electrónico, Orgánico, Textil.
    - Estima el peso y la criticidad del punto.

    ### 🗺️ Mapa Comunitario
    - Cada reporte se ubica en el **punto GPS exacto** donde fue tomada la foto.
    - El límite verde muestra el **perímetro oficial** de la zona piloto.

    ### 📍 Barrios del Prototipo
    """)

    for b in BARRIOS_PILOTO:
        st.write(f"- 📍 **{b}**")

    st.markdown("""
    ---
    **Versión:** 3.0 | **Proyecto:** Territorio INN 2026 | **Institución:** ITM Medellín  
    **Desarrollador:** Brandon Duque
    """)
