import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile

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
    return YOLO("yolov8n.pt")

modelo = cargar_modelo()

# --------------------------------
# MATERIALES
# --------------------------------

materiales = {
    "bottle": ("Plástico", 0.05),
    "cup": ("Plástico", 0.03),
    "wine glass": ("Vidrio", 0.20),
    "book": ("Papel", 0.30),
    "tv": ("Electrónico", 8.0),
    "cell phone": ("Electrónico", 0.20),
    "keyboard": ("Electrónico", 0.60),
    "mouse": ("Electrónico", 0.10),
    "chair": ("Aprovechable", 2.0),
    "backpack": ("Textil", 0.50),
    "suitcase": ("Mixto", 2.50),
    "banana": ("Orgánico", 0.10),
    "apple": ("Orgánico", 0.15),
    "orange": ("Orgánico", 0.20),
    "bicycle": ("Metal", 8.0)
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
        "EcoCom2 Circular IA es un sistema que identifica residuos y puntos críticos mediante fotografías e inteligencia artificial."
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

    st.header("♻️ Reporte de residuos")

    barrio = st.selectbox(
        "Seleccione el barrio",
        [
            "Andalucía",
            "Villa del Socorro",
            "Moscú"
        ]
    )

    referencia = st.text_input(
        "Ingrese una referencia"
    )

    imagen = st.file_uploader(
        "Seleccione una fotografía",
        type=["jpg", "jpeg", "png"]
    )

    if imagen is not None:

        img = Image.open(imagen)

        st.image(
            img,
            caption="Imagen cargada",
            use_container_width=True
        )

        if st.button("Analizar imagen"):

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".jpg"
            ) as tmp:

                img.save(tmp.name)

                resultados = modelo(
                    tmp.name,
                    conf=0.20
                )

            imagen_resultado = resultados[0].plot()

            st.image(
                imagen_resultado,
                caption="Objetos detectados",
                use_container_width=True
            )

            objetos = []

            for r in resultados:
                for box in r.boxes:

                    clase = int(box.cls[0])

                    nombre = modelo.names[clase]

                    objetos.append(nombre)

            if len(objetos) > 0:

                st.success("Análisis completado")

                peso_total = 0

                for obj in set(objetos):

                    if obj in materiales:

                        material, peso = materiales[obj]

                        peso_total += peso

                        st.write(
                            f"♻️ {obj} → {material}"
                        )

                cantidad = len(objetos)

                if cantidad >= 8:
                    nivel = "🔴 Punto crítico alto"
                elif cantidad >= 4:
                    nivel = "🟡 Punto crítico medio"
                else:
                    nivel = "🟢 Punto crítico bajo"

                st.write(f"📍 Barrio: {barrio}")
                st.write(f"📌 Referencia: {referencia}")
                st.write(f"🗑️ Objetos detectados: {cantidad}")
                st.write(f"⚖️ Peso aproximado: {peso_total:.2f} kg")
                st.write(f"🚨 Clasificación: {nivel}")

            else:

                st.error(
                    "No se detectaron objetos."
                )

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

        if st.button(
            "Evaluar punto crítico"
        ):

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".jpg"
            ) as tmp:

                img.save(tmp.name)

                resultados = modelo(
                    tmp.name,
                    conf=0.20
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
