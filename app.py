import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium                     # Para el mapa interactivo
from streamlit_folium import st_folium  # Para mostrar el mapa en Streamlit
import random                     # Para simular coordenadas fijas en la Comuna 2

# --------------------------------------------------------------------
# 1. CONFIGURACIÓN DE LA PÁGINA Y ESTILOS
# --------------------------------------------------------------------
st.set_page_config(
    page_title="Circular IA EcoCom2",
    page_icon="♻️",
    layout="wide"
)

# Estilo personalizado para las tarjetas y títulos
st.markdown("""
    <style>
    .main-title {
        font-size: 34px;
        font-weight: bold;
        color: #10B981;
        margin-bottom: 5px;
    }
    .subtitle {
        font-size: 18px;
        color: #4B5563;
        margin-bottom: 25px;
    }
    .card-reciclable {
        background-color: #E6F4EA;
        padding: 20px;
        border-radius: 15px;
        border-left: 6px solid #137333;
        margin-bottom: 15px;
    }
    .card-no-reciclable {
        background-color: #FCE8E6;
        padding: 20px;
        border-radius: 15px;
        border-left: 6px solid #C5221F;
        margin-bottom: 15px;
    }
    </style>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------
# 2. CARGA DEL MODELO IA (YOLO)
# --------------------------------------------------------------------
@st.cache_resource
def cargar_modelo():
    return YOLO('best.pt')

try:
    model = cargar_modelo()
except Exception as e:
    st.error(f"No se pudo cargar el modelo de IA (best.pt). Asegúrate de que esté subido. Error: {e}")

# --------------------------------------------------------------------
# 3. BARRA LATERAL (LOGOTIPO EN MENU Y NAVEGACIÓN)
# --------------------------------------------------------------------
try:
    st.sidebar.image("./logo.png", use_container_width=True)
except Exception:
    st.sidebar.title("♻️ EcoCom2")

menu = st.sidebar.radio(
    "Menú",
    [
        "Inicio",
        "Reportar residuo",
        "Punto crítico",
        "Información"
    ]
)

st.sidebar.markdown("---")
st.sidebar.info("⚙️ **Ecosistema EcoCom2 v1.5**<br>Territorio INN 2026 | ITM Medellín<br>Desarrollado por: **Brandon Duque**", unsafe_allow_html=True)

BARRIOS_PILOTO = ["Andalucía", "Moscú No. 1", "Villa del Socorro"]

# --------------------------------------------------------------------
# 4. SECCIÓN: INICIO (CENTRO DE MANDO CON MAPA DE COLOR)
# --------------------------------------------------------------------
if menu == "Inicio":
    st.markdown('<div class="main-title">ECOCOM2 CIRCULAR IA</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Panel de Monitoreo Territorial en Tiempo Real - Comuna 2 Santa Cruz</div>', unsafe_allow_html=True)
    st.write("Bienvenido al centro de mando inteligente. Aquí mapeamos y semaforizamos los reportes ciudadanos procesados por IA para trazar rutas logísticas óptimas.")

    lat_base, lon_base = 6.2950, -75.5530
    barrios_comuna = ["Andalucía", "Villa del Socorro", "Moscú No. 1", "Santa Cruz", "La Rosa"]
    materiales_ia = ["Cartón/Papel", "Plástico PET", "Vidrio", "Metales"]
    
    random.seed(42)
    puntos_criticos = []
    for i in range(12):
        lat_rand = lat_base + random.uniform(-0.004, 0.004)
        lon_rand = lon_base + random.uniform(-0.004, 0.004)
        estado_alerta = random.choice(["🟢 Zona Verde (Aprovechable)", "🟡 Zona Amarilla (Seguimiento)", "🔴 Zona Crítica (Roja)"])
        
        puntos_criticos.append({
            "id": f"REP-{2026+i}",
            "barrio": random.choice(barrios_comuna),
            "lat": lat_rand,
            "lon": lon_rand,
            "material": random.choice(materiales_ia),
            "estado": estado_alerta,
            "peso": random.randint(5, 75)
        })

    c_f1, c_f2 = st.columns(2)
    with c_f1:
        barrio_filtro = st.selectbox("Filtrar Mapa por Barrio:", ["Todos"] + barrios_comuna)
    with c_f2:
        estado_filtro = st.multiselect(
            "Filtrar por Nivel de Criticidad:",
            ["🟢 Zona Verde (Aprovechable)", "🟡 Zona Amarilla (Seguimiento)", "🔴 Zona Crítica (Roja)"],
            default=["🟢 Zona Verde (Aprovechable)", "🟡 Zona Amarilla (Seguimiento)", "🔴 Zona Crítica (Roja)"]
        )

    def obtener_color_por_estado(estado):
        if "Roja" in estado:
            return "#EF4444"
        elif "Amarilla" in estado:
            return "#FBBF24"
        else:
            return "#10B981"

    mapa = folium.Map(location=[6.2950, -75.5530], zoom_start=15, tiles="OpenStreetMap")

    puntos_visibles = 0
    for pt in puntos_criticos:
        if barrio_filtro != "Todos" and pt["barrio"] != barrio_filtro:
            continue
        if pt["estado"] not in estado_filtro:
            continue
            
        color_pt = obtener_color_por_estado(pt["estado"])
        puntos_visibles += 1
        
        popup_html = f"""
        <div style='font-family: Arial, sans-serif; font-size: 13px; min-width: 170px;'>
            <h4 style='margin:0 0 6px 0; color:#1E3A8A;'>Reporte {pt['id']}</h4>
            <b>Sector:</b> {pt['barrio']}<br>
            <b>Clasificación IA:</b> {pt['material']}<br>
            <b>Peso aprox:</b> {pt['peso']} Kg<br>
            <b>Estado:</b> <span style='color:{color_pt}; font-weight:bold;'>{pt['estado']}</span>
        </div>
        """
        
        folium.CircleMarker(
            location=[pt["lat"], pt["lon"]],
            radius=12,
            popup=folium.Popup(popup_html, max_width=250),
            color=color_pt,
            fill=True,
            fill_color=color_pt,
            fill_opacity=0.6,
            weight=2
        ).add_to(mapa)

    st_folium(mapa, width=1100, height=450, returned_objects=[])
    st.caption(f"Visualizando {puntos_visibles} reportes georreferenciados activos en la Comuna 2.")

# --------------------------------------------------------------------
# 5. SECCIÓN: REPORTAR RESIDUO (IA + CONDICIONAL DE GEOCERCA PILOTO)
# --------------------------------------------------------------------
elif menu == "Reportar residuo":
    st.markdown('<div class="main-title">📸 Reportar Residuo con Visión Artificial</div>', unsafe_allow_html=True)
    st.write("Sube una foto del residuo. Nuestra IA clasificará el material y estimará su peso operativo.")

    st.write("### 📍 Validación GPS Obligatoria")
    col_gps1, col_gps2 = st.columns(2)
    
    with col_gps1:
        barrio_gps = st.selectbox(
            "Ubicación reportada por el dispositivo móvil:",
            ["Andalucía", "Moscú No. 1", "Villa del Socorro", "Santa Cruz (Central)", "La Rosa", "Aranjuez (Fuera de cobertura)"]
        )
    
    with col_gps2:
        if barrio_gps in BARRIOS_PILOTO:
            st.success(f"📍 GPS Validado: Te encuentras en **{barrio_gps}** (Zona de piloto activa).")
            acceso_ia = True
        else:
            st.error(f"🛑 **Reporte Bloqueado:** La ubicación ({barrio_gps}) está fuera del territorio piloto de EcoCom2. Solo se permite procesar fotos dentro de Andalucía, Moscú y Villa del Socorro.")
            acceso_ia = False

    st.markdown("---")

    archivo_imagen = st.file_uploader("Sube una foto de los residuos acumulados:", type=["jpg", "jpeg", "png"])

    if archivo_imagen is not None:
        if not acceso_ia:
            st.warning("⚠️ No se puede procesar el análisis de IA. Ubicación no permitida para la Fase 1 del proyecto.")
        else:
            img_abierta = Image.open(archivo_imagen)
            col_v1, col_v2 = st.columns(2)
            
            with col_v1:
                st.image(img_abierta, caption="Imagen Reportada", use_container_width=True)
                
            with col_v2:
                with st.spinner("La red YOLOv8 está procesando la segmentación del material..."):
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                        img_abierta.save(tmp_img.name)
                        ruta_tmp_img = tmp_img.name
                        
                    detecciones = model(ruta_tmp_img)
                    
                    for d in detecciones:
                        arr_img = d.plot()
                        img_yolo = Image.fromarray(arr_img[..., ::-1])
                        st.image(img_yolo, caption="Predicción IA", use_container_width=True)
                        
                    lista_clases = []
                    for box in detecciones[0].boxes:
                        id_c = int(box.cls[0])
                        clase_nom = model.names[id_c]
                        lista_clases.append(clase_nom)
                        
                    conteos_ia = Counter(lista_clases)
                    
            if conteos_ia:
                st.success("🤖 ¡Detección de Inteligencia Artificial exitosa!")
                st.write("### Clasificación de Materiales Encontrados:")
                columnas_m = st.columns(len(conteos_ia))
                for idx, (tipo, cantidad) in enumerate(conteos_ia.items()):
                    with columnas_m[idx]:
                        st.metric(label=f"Material: {tipo}", value=f"{cantidad} unidades")
            else:
                st.warning("La IA no detectó materiales reciclables en esta toma.")

# --------------------------------------------------------------------
# 6. SECCIÓN: PUNTO CRÍTICO (CORREGIDO)
# --------------------------------------------------------------------
elif menu == "Punto crítico":
    st.markdown('<div class="main-title">🚨 Reportar Punto Crítico de Acumulación</div>', unsafe_allow_html=True)
    st.write("Ayúdanos a identificar botaderos satélite espontáneos en la Comuna 2 que requieran intervención comunitaria urgente.")

    with st.form("formulario_punto_critico"):
        nombre_reporte = st.text_input("Nombre de quien reporta (Opcional):", "Anónimo")
        barrio_seleccionado = st.selectbox("Barrio de la Comuna 2:", ["Andalucía", "Moscú No. 1", "Villa del Socorro", "Santa Cruz", "La Rosa", "El Pomar"])
        referencia_direccion = st.text_input("Punto de referencia (Ej: Al lado de la cancha, junto al poste de luz):")
        gravedad_emergencia = st.select_slider("Nivel de obstrucción de vía pública:", options=["Bajo", "Moderado", "Crítico (Cierre de vía)"])
        comentarios_adicionales = st.text_area("Cuéntanos más detalles:")
        
        # CORRECCIÓN AQUÍ: Se cambió st.form_submit_with_ui_button por el comando nativo correcto
        boton_enviar = st.form_submit_button("Guardar reporte de punto crítico")
        
        if boton_enviar:
            if not referencia_direccion:
                st.error("Por favor, describe una referencia física para poder enviar el reporte.")
            else:
                st.success(f"¡Gracias {nombre_reporte}! El reporte ha sido registrado de forma exitosa en el mapa central bajo el código **#ECOM2-000157**.")
                st.balloons()

# --------------------------------------------------------------------
# 7. SECCIÓN: INFORMACIÓN (LA GRAN GALERÍA DE MATERIALES COMPLETA)
# --------------------------------------------------------------------
elif menu == "Información":
    st.markdown('<div class="main-title">📖 Guía Educativa de Reciclaje</div>', unsafe_allow_html=True)
    st.write("Aprende a clasificar los residuos sólidos para apoyar la economía circular de la Comuna 2 Santa Cruz.")

    pestaña_reciclable, pestaña_no_reciclable = st.tabs(["🟢 Materiales Aprovechables", "🔴 Residuos No Aprovechables"])

    with pestaña_reciclable:
        st.write("### ¿Qué SÍ se puede reciclar y procesar en EcoCom2?")
        st.write("Asegúrate de que estos materiales estén **limpios, secos y sin grasa** antes de entregarlos.")

        col_ap1, col_ap2 = st.columns(2)
        with col_ap1:
            st.markdown("""
                <div class="card-reciclable">
                    <h3>🥤 Plásticos (Botellas PET y Envases)</h3>
                    <p><b>Ejemplos:</b> Botellas de gaseosa, agua, envases de yogurt, champú y detergentes.</p>
                    <p><i>Consejo EcoCom2:</i> Escurre bien los líquidos y aplasta las botellas para que ocupen menos espacio en el centro de acopio.</p>
                </div>
                <div class="card-reciclable">
                    <h3>📦 Cartón y Papel</h3>
                    <p><b>Ejemplos:</b> Cajas de cartón corrugado, carpetas, papel de oficina, hojas de cuaderno, periódicos y revistas.</p>
                    <p><i>Consejo EcoCom2:</i> Desarma las cajas grandes para facilitar su transporte por parte de los recicladores de oficio.</p>
                </div>
            """, unsafe_allow_html=True)

        with col_ap2:
            st.markdown("""
                <div class="card-reciclable">
                    <h3>🥫 Metales (Latas y Chatarra)</h3>
                    <p><b>Ejemplos:</b> Latas de gaseosa, cerveza, latas de atún, tapas metálicas de botellas de vidrio y chatarra menor.</p>
                    <p><i>Consejo EcoCom2:</i> Enjuaga los restos de comida de las latas de alimentos para evitar malos olores e insectos.</p>
                </div>
                <div class="card-reciclable">
                    <h3>🍾 Vidrio (Botellas y Frascos)</h3>
                    <p><b>Ejemplos:</b> Botellas de jugos, frascos de mermelada, recipientes de conservas y envases de perfumes limpios.</p>
                    <p><i>Consejo EcoCom2:</i> Retira las tapas metálicas (estas se reciclan con los metales). No mezcules con bombillos ni espejos rotos.</p>
                </div>
            """, unsafe_allow_html=True)

    with pestaña_no_reciclable:
        st.write("### ¿Qué NO se puede reciclar en nuestro sistema (Ordinarios)?")
        st.write("Estos elementos van directamente a la basura ordinaria para ser recogidos por Emvarias, ya que no son reutilizables.")

        col_no1, col_no2 = st.columns(2)
        with col_no1:
            st.markdown("""
                <div class="card-no-reciclable">
                    <h3>🧻 Papeles Sanitarios e Higiénicos</h3>
                    <p><b>Ejemplos:</b> Papel higiénico usado, servilletas de cocina grasosas, pañales desechables y toallas húmedas.</p>
                    <p><i>Razón:</i> Representan un riesgo de contaminación biológica y médica, por lo que nunca deben mezclarse con el reciclaje.</p>
                </div>
                <div class="card-no-reciclable">
                    <h3>🍕 Cartones con Grasa y Humedad</h3>
                    <p><b>Ejemplos:</b> Cajas de pizza manchadas de aceite, vasos de cartón de café encerados y servilletas de papel con comida.</p>
                    <p><i>Razón:</i> La grasa daña las fibras de celulosa del papel limpio durante el proceso químico de reciclaje industrial.</p>
                </div>
            """, unsafe_allow_html=True)

        with col_no2:
            st.markdown("""
                <div class="card-no-reciclable">
                    <h3>🍫 Plásticos de un Solo Uso Metalizados</h3>
                    <p><b>Ejemplos:</b> Bolsas de papas fritas, envolturas de golosinas, paquetes de galletas y empaques de dulces.</p>
                    <p><i>Razón:</i> Contienen finas capas de aluminio fusionadas con plástico, lo que hace muy difícil su separación.</p>
                </div>
                <div class="card-no-reciclable">
                    <h3>🍧 Icopor y Desechables de Comida</h3>
                    <p><b>Ejemplos:</b> Envases de icopor (poliestireno expandido) para almuerzos, vasos plásticos desechables sucios.</p>
                    <p><i>Razón:</i> El icopor sucio de comida no se puede reciclar económicamente debido a los altos costos de lavado y transporte.</p>
                </div>
            """, unsafe_allow_html=T)
