import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium                     
from streamlit_folium import st_folium  
import pandas as pd               
import streamlit.components.v1 as components  # Para inyección directa de JS Nativo

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

# Variables de control para el GPS nativo
if "gps_lat" not in st.session_state:
    st.session_state.gps_lat = None
if "gps_lon" not in st.session_state:
    st.session_state.gps_lon = None
if "gps_error" not in st.session_state:
    st.session_state.gps_error = None

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
# 5. MENÚ LATERAL CON LOGO Y MARCA DE AUTOR
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
        ⚙️ <b>Ecosistema EcoCom2 v1.6</b><br>
        Territorio INN 2026 | ITM Medellín<br>
        Desarrollado por: <b>Brandon Duque</b>
    </div>
""", unsafe_allow_html=True)

# Capturar parámetros enviados por la URL desde el script inyectado de JS de manera limpia
query_params = st.query_params
if "lat" in query_params and "lon" in query_params:
    st.session_state.gps_lat = float(query_params["lat"])
    st.session_state.gps_lon = float(query_params["lon"])
    st.session_state.gps_error = None
    st.query_params.clear()  # Limpiar la URL de residuos visuales de parámetros

# --------------------------------------------------------------------
# 6. SECCIÓN: INICIO (CON CORRECCIÓN DE GPS ASÍNCRONO NATIVO)
# --------------------------------------------------------------------
if menu == "Inicio":
    from geopy.geocoders import Nominatim

    st.title("♻️ EcoCom2 Circular IA")
    st.write("Sistema inteligente de gestión de residuos mediante inteligencia artificial.")
    
    st.markdown("### 📍 Panel Territorial Semicontrolado (Sectores del Prototipo)")
    st.markdown("#### 🌐 Verificación de Cobertura GPS Obligatoria")

    # Botón HTML/JS nativo insertado de forma transparente para forzar la petición de coordenadas al navegador web móvil
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
                    // Enviar variables de vuelta a Streamlit recargando sutilmente con parámetros limpios
                    window.parent.location.search = `?lat=${lat}&lon=${lon}`;
                },
                (error) => {
                    alert("Error al obtener acceso al satélite GPS. Verifica los permisos de tu navegador móvil.");
                },
                { enableHighAccuracy: true, timeout: 10000 }
            );
        } else {
            alert("Tu dispositivo móvil no soporta geolocalización HTML5.");
        }
    }
    </script>
    """
    components.html(js_gps_button, height=60)

    fuera_de_rango = False
    direccion_detectada = ""
    
    # Coordenadas por defecto (Centro de Comuna 2 Medellín)
    lat_base, lon_base = 6.2950, -75.5530

    if st.session_state.gps_lat and st.session_state.gps_lon:
        lat_base = st.session_state.gps_lat
        lon_base = st.session_state.gps_lon
        
        try:
            geolocator = Nominatim(user_agent="ecocom2_circular_ia")
            location = geolocator.reverse(f"{lat_base}, {lon_base}")
            if location:
                direccion_detectada = location.address
            else:
                direccion_detectada = ""
        except Exception:
            # Respaldo seguro en caso de fallas de timeout del servidor de reversión Nominatim
            direccion_detectada = "Medellín, Andalucía, Comuna 2"

        if any(b.lower() in direccion_detectada.lower() for b in BARRIOS_PILOTO) or "andalucía" in direccion_detectada.lower() or "socorro" in direccion_detectada.lower() or "moscú" in direccion_detectada.lower():
            st.success(f"✅ **Rango verificado con éxito:** Te encuentras dentro de la Comuna 2.\n\n🏠 *Ubicación detectada:* {direccion_detectada}")
            fuera_de_rango = False
        else:
            st.error(f"🛑 **Fuera de rango:** Tu ubicación actual ({direccion_detectada}) no pertenece a Andalucía, Villa del Socorro ni Moscú. Las funciones de recolección están bloqueadas.")
            fuera_de_rango = True
    else:
        st.warning("⚠️ Debes presionar el botón superior 'SINCRONIZAR Y VERIFICAR GPS REAL' para corroborar tu geocerca territorial.")

    barrio_seleccionado = st.selectbox("Filtrar visualización del mapa:", ["Todos"] + BARRIOS_PILOTO)

    # Generación y pintado del mapa reactivo
    mapa_centro = folium.Map(location=[lat_base, lon_base], zoom_start=16, tiles="OpenStreetMap")

    # Colocar marcador azul de la posición del usuario si el GPS está activo
    if st.session_state.gps_lat and st.session_state.gps_lon:
        folium.Marker(
            location=[st.session_state.gps_lat, st.session_state.gps_lon],
            popup="Mi Ubicación Real",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(mapa_centro)

    # Solo recorremos los registros que existan en el historial real generado por el usuario
    for idx, rep in enumerate(st.session_state.registro_reportes):
        if barrio_seleccionado != "Todos" and rep["Sector"] != barrio_seleccionado:
            continue
            
        color_dinamico = "green" if "individual" in rep["Clasificación"].lower() else ("orange" if "posible" in rep["Clasificación"].lower() else "red")
        popup_dinamico = f"<b>{rep['Código']}</b><br>Sector: {rep['Sector']}<br>Ref: {rep['Referencia']}<br>Peso: {rep['Peso (Kg)']} kg"
        
        lat_b = lat_base + (idx * 0.0003) 
        lon_b = lon_base - (idx * 0.0003)
        
        folium.CircleMarker(
            location=[lat_b, lon_b],
            radius=13,
            color=color_dinamico,
            fill=True,
            fill_color=color_dinamico,
            fill_opacity=0.7,
            popup=folium.Popup(popup_dinamico, max_width=200)
        ).add_to(mapa_centro)

    st_folium(mapa_centro, width=1100, height=450, returned_objects=[])

    st.markdown("---")
    st.markdown("### 📋 Historial de Reportes Guardados")
    
    if fuera_de_rango:
        st.error("❌ Sección bloqueada. No se pueden procesar ni visualizar datos si estás fuera del rango geográfico establecido.")
    else:
        if len(st.session_state.registro_reportes) > 0:
            df_datos = pd.DataFrame(st.session_state.registro_reportes)
            st.dataframe(df_datos, use_container_width=True)
            c_m1, c_m2 = st.columns(2)
            with c_m1:
                st.metric("Total Reportes Guardados", len(df_datos))
            with c_m2:
                st.metric("Material Recuperado Acumulado", f"{df_datos['Peso (Kg)'].sum():.2f} kg")
        else:
            st.info("💡 El sistema de base de datos está actualmente vacío. Los marcadores aparecerán de forma automática en el mapa tan pronto como registres un elemento en el formulario.")

# --------------------------------------------------------------------
# 7. SECCIÓN: INFORMACIÓN
# --------------------------------------------------------------------
elif menu == "Información":
    st.header("¿Qué es EcoCom2 Circular IA?")
    st.write("EcoCom2 Circular IA identifica residuos y puntos críticos mediante fotografías e inteligencia artificial.")
    st.header("Sectores del Prototipo")
    st.write("Este despliegue experimental opera de manera exclusiva en:")
    for b in BARRIOS_PILOTO:
        st.write(f"📍 Barrio **{b}**")

# --------------------------------------------------------------------
# 8. SECCIÓN: REPORTAR RESIDUO
# --------------------------------------------------------------------
elif menu == "Reportar residuo":
    st.header("♻️ Reporte de residuos")

    if "reporte_enviado" not in st.session_state:
        st.session_state.reporte_enviado = False

    if st.session_state.reporte_enviado:
        st.success("🎉 ¡Tu reporte ha sido enviado y registrado con éxito!")
        col_otro, col_salir = st.columns(2)
        with col_otro:
            if st.button("🔄 Hacer otro reporte", use_container_width=True, type="primary"):
                st.session_state.reporte_enviado = False
                st.rerun()
        with col_salir:
            if st.button("🚪 Ir al Panel de Inicio", use_container_width=True):
                st.session_state.reporte_enviado = False
                st.rerun()
    else:
        barrio = st.selectbox("Seleccione el sector del reporte:", BARRIOS_PILOTO)
        referencia = st.text_input("Ingrese una referencia")

        if referencia and len(referencia) < 8:
            st.warning("Ingrese una referencia más específica.")

        imagen = st.file_uploader("Seleccione una fotografía", type=["jpg", "jpeg", "png"])

        if imagen is not None:
            img = Image.open(imagen)
            st.image(img, caption="Imagen cargada", use_container_width=True)

            if st.button("Analizar imagen con IA", use_container_width=True):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    img.save(tmp.name)
                    resultados = modelo(tmp.name, conf=0.10)

                imagen_resultado = resultados[0].plot()
                st.image(imagen_resultado, caption="Objetos detectados por la IA", use_container_width=True)

                objetos = []
                for r in resultados:
                    for box in r.boxes:
                        clase = int(box.cls[0])
                        nombre = modelo.names[clase]
                        objetos.append(nombre)

                if len(objetos) > 0:
                    st.success("✅ Análisis completado")
                    peso_total = 0
                    residuos = 0
                    conteo = Counter(objetos)
                    tipo_predominante = "Varios"

                    for obj, cantidad_obj in conteo.items():
                        if obj in materiales:
                            nombre_es, material, peso, reciclable = materiales[obj]
                            if reciclable:
                                residuos += cantidad_obj
                                st.success(f"♻️ {nombre_es}: {cantidad_obj} unidad(es)")
                                peso_total += peso * cantidad_obj
                                tipo_predominante = material
                            else:
                                st.warning(f"⚠️ {nombre_es} no corresponde a un residuo aprovechable.")

                    nivel = "🔴 Punto crítico confirmado" if residuos >= 10 else ("🟡 Posible punto crítico" if residuos >= 5 else "🟢 Residuo individual")

                    st.markdown("### 📊 Resumen del Reporte")
                    st.write(f"📍 **Barrio:** {barrio}")
                    st.write(f"📌 **Referencia:** {referencia}")
                    st.write(f"🗑️ **Objetos totales detectados:** {len(objetos)}")
                    st.write(f"♻️ **Residuos reciclables:** {residuos}")
                    st.write(f"⚖️ **Peso aproximado total:** {peso_total:.2f} kg")
                    st.write(f"🚨 **Clasificación operativa:** {nivel}")

                    st.session_state.cache_nuevo_reporte = {
                        "Código": f"REP-{len(st.session_state.registro_reportes) + 200}",
                        "Sector": barrio,
                        "Referencia": referencia if referencia else "Sin referencia",
                        "Objetos": residuos,
                        "Peso (Kg)": round(peso_total, 2),
                        "Predominante": tipo_predominante,
                        "Clasificación": nivel
                    }
                else:
                    st.error("❌ No se detectaron objetos.")

            if "cache_nuevo_reporte" in st.session_state:
                st.write("---")
                if st.button("🚀 ENVIAR REPORTE DEFINITIVO", type="primary", use_container_width=True):
                    st.session_state.registro_reportes.append(st.session_state.cache_nuevo_reporte)
                    del st.session_state.cache_nuevo_reporte  
                    st.session_state.reporte_enviado = True
                    st.rerun()

# --------------------------------------------------------------------
# 9. SECCIÓN: PUNTO CRÍTICO
# --------------------------------------------------------------------
elif menu == "Punto crítico":
    st.header("🚨 Punto crítico")
    barrio = st.selectbox("Seleccione el barrio del prototipo:", BARRIOS_PILOTO, key="barrio2")
    referencia = st.text_input("Referencia", key="referencia2")
    imagen = st.file_uploader("Suba una fotografía", type=["jpg", "jpeg", "png"], key="imagen2")

    if imagen is not None:
        img = Image.open(imagen)
        st.image(img, use_container_width=True)

        if st.button("Evaluar punto crítico"):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                img.save(tmp.name)
                resultados = modelo(tmp.name, conf=0.10)

            cantidad = 0
            for r in resultados:
                cantidad += len(r.boxes)

            nivel = "🔴 Punto crítico alto" if cantidad >= 8 else ("🟡 Punto crítico medio" if cantidad >= 4 else "🟢 Punto crítico bajo")
            st.warning(nivel)
            
            st.session_state.registro_reportes.append({
                "Código": f"CRIT-{len(st.session_state.registro_reportes) + 500}",
                "Sector": barrio,
                "Referencia": referencia if referencia else "Punto crítico manual",
                "Objetos": cantidad,
                "Peso (Kg)": round(cantidad * 0.4, 2),
                "Predominante": "Mixto Satélite",
                "Clasificación": nivel
            })
            st.success("¡Alerta registrada con éxito en el mapa de control de Inicio!")
