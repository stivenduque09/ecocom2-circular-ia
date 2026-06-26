
import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium                     # Para crear el mapa interactivo
from streamlit_folium import st_folium  # Para mostrar el mapa en Streamlit
import random
import pandas as pd               # Para estructurar el historial en tablas

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

# --------------------------------------------------------------------
# 3. CARGAR MODELO (CON RESPALDO SEGURO ANTE EL ERROR DE DISCO)
# --------------------------------------------------------------------
@st.cache_resource
def cargar_modelo():
    try:
        return YOLO("best.pt")
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

# LAS ÚNICAS TRES ZONAS OFICIALES APROBADAS PARA EL PROTOTIPO
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
    [
        "Inicio",
        "Reportar residuo",
        "Punto crítico",
        "Información"
    ]
)

st.sidebar.markdown("---")
st.sidebar.markdown("""
    <div style="background-color: rgba(16, 185, 129, 0.1); padding: 12px; border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.2); font-family: sans-serif; font-size: 12px; color: #374151;">
        ⚙️ <b>Ecosistema EcoCom2 v1.5</b><br>
        Territorio INN 2026 | ITM Medellín<br>
        Desarrollado por: <b>Brandon Duque</b>
    </div>
""", unsafe_allow_html=True)

# --------------------------------------------------------------------
# 6. SECCIÓN: INICIO (MAPA CON FILTROS DE LOS TRES BARRIOS)
# --------------------------------------------------------------------
if menu == "Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Sistema inteligente de gestión de residuos mediante inteligencia artificial.")
    st.markdown("### 📍 Panel Territorial Semicontrolado (Sectores del Prototipo)")

    # Selector para filtrar los puntos del mapa basándose exclusivamente en tus 3 opciones
    barrio_seleccionado = st.selectbox("Filtrar visualización del mapa:", ["Todos"] + BARRIOS_PILOTO)

    # Configuración de coordenadas base de la Comuna 2
    lat_base, lon_base = 6.2950, -75.5530
    
    # Generación controlada de puntos fijos de muestra inicial dentro de los 3 sectores
    random.seed(15)
    puntos_simulados = []
    for i in range(6):
        puntos_simulados.append({
            "id": f"REP-{2026+i}",
            "barrio": random.choice(BARRIOS_PILOTO),
            "lat": lat_base + random.uniform(-0.002, 0.002),
            "lon": lon_base + random.uniform(-0.002, 0.002),
            "residuos": random.randint(2, 11),
            "peso": round(random.uniform(1.2, 18.5), 2)
        })

    # Crear el objeto Mapa de Folium centrado
    mapa_centro = folium.Map(location=[lat_base, lon_base], zoom_start=15.5, tiles="OpenStreetMap")

    # Dibujar puntos de muestra que coincidan con la selección
    for p in puntos_simulados:
        if barrio_seleccionado != "Todos" and p["barrio"] != barrio_seleccionado:
            continue
            
        color_marker = "green" if p["residuos"] < 5 else ("orange" if p["residuos"] < 9 else "red")
        popup_text = f"<b>{p['id']}</b><br>Sector: {p['barrio']}<br>Objetos: {p['residuos']}<br>Peso: {p['peso']} kg"
        
        folium.CircleMarker(
            location=[p["lat"], p["lon"]],
            radius=11,
            color=color_marker,
            fill=True,
            fill_color=color_marker,
            fill_opacity=0.6,
            popup=folium.Popup(popup_text, max_width=200)
        ).add_to(mapa_centro)

    # Dibujar los reportes creados en tiempo real por el usuario mediante Session State
    for idx, rep in enumerate(st.session_state.registro_reportes):
        if barrio_seleccionado != "Todos" and rep["Sector"] != barrio_seleccionado:
            continue
            
        color_dinamico = "green" if "individual" in rep["Clasificación"].lower() else ("orange" if "posible" in rep["Clasificación"].lower() else "red")
        popup_dinamico = f"<b>{rep['Código']}</b><br>Sector: {rep['Sector']}<br>Ref: {rep['Referencia']}<br>Peso: {rep['Peso (Kg)']} kg"
        
        # Desplazamiento controlado para que no se encimen los marcadores en la simulación
        lat_b = lat_base + (idx * 0.0006) - 0.001
        lon_b = lon_base - (idx * 0.0006) + 0.001
        
        folium.CircleMarker(
            location=[lat_b, lon_b],
            radius=13,
            color=color_dinamico,
            fill=True,
            fill_color=color_dinamico,
            fill_opacity=0.7,
            popup=folium.Popup(popup_dinamico, max_width=200)
        ).add_to(mapa_centro)

    # Renderizar mapa en la pantalla de Inicio
    st_folium(mapa_centro, width=1100, height=450, returned_objects=[])

    st.markdown("---")
    st.markdown("### 📋 Historial de Reportes Guardados")
    
    if len(st.session_state.registro_reportes) > 0:
        df_datos = pd.DataFrame(st.session_state.registro_reportes)
        st.dataframe(df_datos, use_container_width=True)
        
        c_m1, c_m2 = st.columns(2)
        with c_m1:
            st.metric("Total Reportes Guardados", len(df_datos))
        with c_m2:
            st.metric("Material Recuperado Acumulado", f"{df_datos['Peso (Kg)'].sum():.2f} kg")
    else:
        st.info("💡 No hay nuevos reportes guardados en esta sesión. Los datos que captures en la pestaña 'Reportar residuo' o 'Punto crítico' se listarán aquí automáticamente.")

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
    from streamlit_js_eval import streamlit_js_eval
    from geopy.geocoders import Nominatim

    st.header("♻️ Reporte de residuos")

    if "reporte_enviado" not in st.session_state:
        st.session_state.reporte_enviado = False

    if st.session_state.reporte_enviado:
        st.success("🎉 ¡Tu reporte ha sido enviado y registrado con éxito!")
        st.subheader("¿Qué deseas hacer ahora?")
        
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
        st.subheader("📍 Ubicación del reporte")
        obtener_gps = st.checkbox("Obtener mi ubicación exacta en tiempo real (GPS)")
        
        coordenadas = None
        direccion_real = None

        if obtener_gps:
            loc = streamlit_js_eval(data_theme='dark', component='get_geolocation', key='data_geo')
            if loc:
                lat = loc['coords']['latitude']
                lon = loc['coords']['longitude']
                coordenadas = {"lat": [lat], "lon": [lon]}
                
                try:
                    geolocator = Nominatim(user_agent="ecocom2_circular_ia")
                    location = geolocator.reverse(f"{lat}, {lon}")
                    if location:
                        direccion_real = location.address
                        st.success(f"🏠 **Dirección detectada:** {direccion_real}")
                    else:
                        st.warning("⚠️ Coordenadas obtenidas, pero sin dirección exacta.")
                except Exception:
                    direccion_real = f"Lat: {lat:.5f}, Lon: {lon:.5f}"
                
                st.map(coordenadas)
            else:
                st.info("🌐 Buscando señal de GPS... Asegúrate de dar permisos de ubicación.")

        barrio = st.selectbox(
            "Seleccione el barrio del prototipo:",
            BARRIOS_PILOTO
        )

        referencia = st.text_input("Ingrese una referencia")

        if referencia and len(referencia) < 8:
            st.warning("Ingrese una referencia más específica.")

        imagen = st.file_uploader(
            "Seleccione una fotografía",
            type=["jpg", "jpeg", "png"]
        )

        if imagen is not None:
            img = Image.open(imagen)
            st.image(img, caption="Imagen cargada", use_container_width=True)

            if st.button("Analizar imagen", use_container_width=True):
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
                                st.write(f"Material base: {material}")
                                peso_total += peso * cantidad_obj
                                tipo_predominante = material
                            else:
                                st.warning(f"⚠️ {nombre_es} no corresponde a un residuo aprovechable.")

                    if residuos >= 10:
                        nivel = "🔴 Punto crítico confirmado"
                    elif residuos >= 5:
                        nivel = "🟡 Posible punto crítico"
                    elif residuos >= 1:
                        nivel = "🟢 Residuo individual"
                    else:
                        nivel = "⚪ Evidencia insuficiente"

                    st.markdown("### 📊 Resumen del Reporte")
                    st.write(f"📍 **Barrio/Ubicación:** {barrio if not direccion_real else 'Detección GPS'}")
                    st.write(f"📌 **Referencia:** {referencia}")
                    st.write(f"🗑️ **Objetos totales detectados:** {len(objetos)}")
                    st.write(f"♻️ **Residuos reciclables:** {residuos}")
                    st.write(f"⚖️ **Peso aproximado total:** {peso_total:.2f} kg")
                    st.write(f"🚨 **Clasificación operativa:** {nivel}")

                    # Almacenamiento seguro en caché del estado interno
                    st.session_state.cache_nuevo_reporte = {
                        "Código": f"REP-{len(st.session_state.registro_reportes) + 200}",
                        "Sector": barrio,
                        "Referencia": referencia if referencia else "Sin referencia",
                        "Objetos": residuos,
                        "Peso (Kg)": round(peso_total, 2),
                        "Predominante": tipo_predominante,
                        "Clasificación": nivel
                    }

                    if residuos == 0:
                        st.error("❌ No se identificaron residuos aprovechables.")
                    elif residuos <= 2:
                        st.info("📷 Se recomienda una fotografía más cercana para mejorar la confianza.")
                    else:
                        st.success("✅ Reporte listo para confirmación.")
                else:
                    st.error("❌ No se detectaron objetos en la toma.")

            # Validación correcta de la caché para mostrar el botón de envío
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

    barrio = st.selectbox(
        "Seleccione el barrio del prototipo:",
        BARRIOS_PILOTO,
        key="barrio2"
    )

    referencia = st.text_input("Referencia", key="referencia2")

    imagen = st.file_uploader(
        "Suba una fotografía",
        type=["jpg", "jpeg", "png"],
        key="imagen2"
    )

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

            if cantidad >= 8:
                nivel = "🔴 Punto crítico alto"
            elif cantidad >= 4:
                nivel = "🟡 Punto crítico medio"
            elif cantidad >= 1:
                nivel = "🟢 Punto crítico bajo"
            else:
                nivel = "⚪ Sin evidencia"

            st.warning(nivel)
            st.write(f"📍 Barrio: {barrio}")
            st.write(f"📌 Referencia: {referencia}")
            st.write(f"🗑️ Objetos detectados: {cantidad}")
            
            # Guardado inmediato en el historial central
            st.session_state.registro_reportes.append({
                "Código": f"CRIT-{len(st.session_state.registro_reportes) + 500}",
                "Sector": barrio,
                "Referencia": referencia if referencia else "Punto crítico manual",
                "Objetos": cantidad,
                "Peso (Kg)": round(cantidad * 0.4, 2),
                "Predominante": "Mixto Satélite",
                "Clasificación": nivel
            })
            st.success("¡Alerta registrada con éxito en el mapa de control de Inicio!
