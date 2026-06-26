
import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter


# --------------------------------
# CONFIGURACIÓN
# --------------------------------

st.set_page_config(
    page_title="EcoCom2 Circular IA",
    page_icon="♻️",
    layout="wide"
)

# --------------------------------
# CARGAR MODELO
# --------------------------------

@st.cache_resource
def cargar_modelo():
   return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# --------------------------------
# MATERIALES
# --------------------------------

materiales = {

    # ----------------------
    # PAPEL Y CARTÓN
    # ----------------------
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
    # ----------------------
    # PLÁSTICOS
    # ----------------------
    "bottle": ("Botella", "Plástico", 0.05, True),
    "cup": ("Vaso", "Plástico", 0.03, True),
    "chair": ("Silla", "Plástico", 2.00, True),
    "bench": ("Banco", "Plástico", 2.50, True),
    "toy": ("Juguete", "Plástico", 0.40, True),
    "bucket": ("Balde", "Plástico", 0.50, True),

    # ----------------------
    # VIDRIO
    # ----------------------
    "wine glass": ("Vidrio", "Vidrio", 0.20, True),
    "glass": ("Vidrio", "Vidrio", 0.20, True),
    "vase": ("Jarrón", "Vidrio", 0.80, True),

    # ----------------------
    # METALES
    # ----------------------
    "can": ("Lata", "Aluminio", 0.02, True),

    # ----------------------
    # ELECTRÓNICOS
    # ----------------------
    "cell phone": ("Celular", "Electrónico", 0.20, True),
    "keyboard": ("Teclado", "Electrónico", 0.60, True),
    "mouse": ("Ratón", "Electrónico", 0.10, True),
    "tv": ("Televisor", "Electrónico", 8.00, True),
    "laptop": ("Portátil", "Electrónico", 2.50, True),
    "remote": ("Control remoto", "Electrónico", 0.20, True),

    # ----------------------
    # TEXTILES
    # ----------------------
    "backpack": ("Mochila", "Textil", 0.50, True),
    "handbag": ("Bolso", "Textil", 0.40, True),
    "suitcase": ("Maleta", "Textil", 2.50, True),
    "tie": ("Corbata", "Textil", 0.10, True),

    # ----------------------
    # ORGÁNICOS
    # ----------------------
    "banana": ("Banano", "Orgánico", 0.10, True),
    "apple": ("Manzana", "Orgánico", 0.15, True),
    "orange": ("Naranja", "Orgánico", 0.20, True),
    "broccoli": ("Brócoli", "Orgánico", 0.25, True),
    "carrot": ("Zanahoria", "Orgánico", 0.10, True),

    # ----------------------
    # MUEBLES
    # ----------------------
    "couch": ("Sofá", "Mixto", 15.00, True),
    "bed": ("Cama", "Mixto", 20.00, True),
    "dining table": ("Mesa", "Madera", 12.00, True),

    # ----------------------
    # OBJETOS DEL HOGAR
    # ----------------------
    "clock": ("Reloj", "Electrónico", 0.30, True),
    "umbrella": ("Sombrilla", "Mixto", 0.50, True),

    # ----------------------
    # NO SON RESIDUOS
    # ----------------------
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


# --------------------------------
# MENÚ
# --------------------------------

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

# --------------------------------
# INICIO
# --------------------------------

if menu == "Inicio":

    st.title("♻️ EcoCom2 Circular IA")

    st.write(
        "Sistema inteligente de gestión de residuos mediante inteligencia artificial."
    )

# --------------------------------
# INFORMACIÓN
# --------------------------------

elif menu == "Información":

    st.header("¿Qué es EcoCom2 Circular IA?")

    st.write(
        "EcoCom2 Circular IA identifica residuos y puntos críticos mediante fotografías e inteligencia artificial."
    )

    st.header("Objetivos")

    st.write("♻️ Promover el reciclaje.")
    st.write("🌎 Reducir la contaminación.")
    st.write("📍 Identificar puntos críticos.")
    st.write("🤝 Apoyar la comunidad.")

# --------------------------------
# REPORTE DE RESIDUOS
# --------------------------------

elif menu == "Reportar residuo":

    # 1. IMPORTANTE: Importamos el componente de ubicación real
    from streamlit_js_eval import streamlit_js_eval

    st.header("♻️ Reporte de residuos")

    # 2. Inicializamos la variable de estado si no existe
    if "reporte_enviado" not in st.session_state:
        st.session_state.reporte_enviado = False

    # ==========================================
    # VISTA A: PANTALLA DE CONFIRMACIÓN FINAL
    # ==========================================
    if st.session_state.reporte_enviado:
        st.success("🎉 ¡Tu reporte ha sido enviado y registrado con éxito!")
        st.subheader("¿Qué deseas hacer ahora?")
        
        col_otro, col_salir = st.columns(2)
        
        with col_otro:
            if st.button("🔄 Hacer otro reporte", use_container_width=True, type="primary"):
                # Resetear el estado para volver a mostrar el formulario
                st.session_state.reporte_enviado = False
                st.rerun()
                
        with col_salir:
            if st.button("🚪 Salir al Inicio", use_container_width=True):
                st.session_state.reporte_enviado = False
                st.info("Para salir, selecciona 'Inicio' en el menú de la izquierda ♻️.")

    # ==========================================
    # VISTA B: FORMULARIO DE REPORTE (TU DISEÑO)
    # ==========================================
    else:
        # --- NUEVA SECCIÓN DE UBICACIÓN REAL ---
        st.subheader("📍 Ubicación del reporte")
        obtener_gps = st.checkbox("Obtener mi ubicación exacta en tiempo real (GPS)")
        coordenadas = None

        if obtener_gps:
            # Solicita la geolocalización al navegador web de tu ASUS
            loc = streamlit_js_eval(data_theme='dark', component='get_geolocation', key='data_geo')
            if loc:
                lat = loc['coords']['latitude']
                lon = loc['coords']['longitude']
                coordenadas = {"lat": [lat], "lon": [lon]}
                st.success(f"🗺️ Coordenadas capturadas: Lat {lat:.5f}, Lon {lon:.5f}")
                st.map(coordenadas) # Dibuja el mapa en pantalla
            else:
                st.info("Esperando permisos de ubicación del navegador... Por favor acéptalos en la barra de direcciones.")

        # Selector de barrio clásico (por si el GPS está apagado)
        barrio = st.selectbox(
            "Seleccione el barrio (Si no usa GPS)",
            ["Andalucía", "Villa del Socorro", "Moscú"]
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
                st.image(imagen_resultado, caption="Objetos detectados", use_container_width=True)

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

                    for obj, cantidad_obj in conteo.items():
                        if obj in materiales:
                            nombre_es, material, peso, reciclable = materiales[obj]
                            if reciclable:
                                residuos += cantidad_obj
                                st.success(f"♻️ {nombre_es}: {cantidad_obj} unidad(es)")
                                st.write(f"Material: {material}")
                                peso_total += peso * cantidad_obj
                            else:
                                st.warning(f"⚠️ {nombre_es} no corresponde a un residuo.")

                    if residuos >= 10:
                        nivel = "🔴 Punto crítico confirmado"
                    elif residuos >= 5:
                        nivel = "🟡 Posible punto crítico"
                    elif residuos >= 1:
                        nivel = "🟢 Residuo individual"
                    else:
                        nivel = "⚪ Evidencia insuficiente"

                    # --- IMPRESIÓN DE RESULTADOS ---
                    st.markdown("### 📊 Resumen del Reporte")
                    if coordenadas:
                        st.write("📍 Ubicación: Capturada mediante GPS Real.")
                    else:
                        st.write(f"📍 Barrio: {barrio}")
                        
                    st.write(f"📌 Referencia: {referencia}")
                    st.write(f"🗑️ Objetos detectados: {len(objetos)}")
                    st.write(f"♻️ Residuos reciclables: {residuos}")
                    st.write(f"⚖️ Peso aproximado: {peso_total:.2f} kg")
                    st.write(f"🚨 Clasificación: {nivel}")

                    if residuos == 0:
                        st.error("❌ No se identificaron residuos aprovechables.")
                    elif residuos <= 2:
                        st.info("📷 Se recomienda una fotografía más cercana.")
                    else:
                        st.success("✅ Reporte validado correctamente.")

                    # --- EL BOTÓN CLAVE QUE SOLICITASTE ---
                    st.write("---")
                    # Este botón activa el cambio a la Vista A
                    if st.button("🚀 ENVIAR REPORTE DEFINITIVO", type="primary", use_container_width=True):
                        st.session_state.reporte_enviado = True
                        st.rerun()
                else:
                    st.error("❌ No se detectaron objetos.")
# --------------------------------
# PUNTO CRÍTICO
# --------------------------------

elif menu == "Punto crítico":

    st.header("🚨 Punto crítico")

    barrio = st.selectbox(
        "Seleccione el barrio",
        [
            "Andalucía",
            "Villa del Socorro",
            "Moscú"
        ],
        key="barrio2"
    )

    referencia = st.text_input(
        "Referencia",
        key="referencia2"
    )

    imagen = st.file_uploader(
        "Suba una fotografía",
        type=["jpg", "jpeg", "png"],
        key="imagen2"
    )

    if imagen is not None:

        img = Image.open(imagen)

        st.image(
            img,
            use_container_width=True
        )

        if st.button("Evaluar punto crítico"):

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".jpg"
            ) as tmp:

                img.save(tmp.name)

                resultados = modelo(
                    tmp.name,
                    conf=0.10
                )

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
