import streamlit as st
from PIL import Image
from ultralytics import YOLO
import tempfile

st.set_page_config(
    page_title="EcoCom2 Circular IA",
    page_icon="♻️",
    layout="wide"
)

@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8n.pt")

modelo = cargar_modelo()

materiales = {
    "bottle": ("Plástico",0.05),
    "cup": ("Plástico",0.03),
    "wine glass": ("Vidrio",0.20),
    "book": ("Papel",0.30),
    "cell phone": ("Electrónico",0.20),
    "keyboard": ("Electrónico",0.60),
    "mouse": ("Electrónico",0.10),
    "chair": ("Aprovechable",2.00),
    "backpack": ("Textil",0.50),
    "suitcase": ("Mixto",2.50)
}

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

if menu == "Inicio":

    st.title("♻️ EcoCom2 Circular IA")

    st.write(
        "Sistema inteligente de gestión de residuos mediante inteligencia artificial."
    )

if menu == "Información":

    st.header("¿Qué es EcoCom2?")

    st.write(
        "EcoCom2 Circular IA es un sistema que identifica residuos y puntos críticos utilizando fotografías e inteligencia artificial."
    )

    st.header("Objetivos")

    st.write("• Promover el reciclaje.")
    st.write("• Reducir la contaminación.")
    st.write("• Identificar puntos críticos.")
    st.write("• Apoyar la comunidad.")

if menu == "Reportar residuo":

    st.header("♻️ Reporte de residuos")

    barrio = st.selectbox(
        "Barrio",
        [
            "Andalucía",
            "Villa del Socorro",
            "Moscú"
        ]
    )

    referencia = st.text_input(
        "Referencia del lugar"
    )

    imagen = st.file_uploader(
        "Suba una fotografía",
        type=["jpg","jpeg","png"]
    )

    if imagen:

        img = Image.open(imagen)

        st.image(img)

        if st.button("Analizar"):

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".jpg"
            ) as tmp:

                img.save(tmp.name)

                resultados = modelo(tmp.name)

            objetos = []

            for r in resultados:
                for box in r.boxes:

                    clase = int(box.cls[0])

                    nombre = modelo.names[clase]

                    objetos.append(nombre)

            if objetos:

                st.success("Análisis terminado.")

                peso_total = 0

                for obj in set(objetos):

                    if obj in materiales:

                        material,peso = materiales[obj]

                        peso_total += peso

                        st.write(
                            f"♻️ {obj}: {material}"
                        )

                st.write(
                    f"⚖️ Peso aproximado: {peso_total:.2f} kg"
                )

                st.write(
                    f"📍 Barrio: {barrio}"
                )

                st.write(
                    f"📌 Referencia: {referencia}"
                )

            else:

                st.error(
                    "No se detectaron materiales."
                )

if menu == "Punto crítico":

    st.header("🚨 Punto crítico")

    barrio = st.selectbox(
        "Barrio",
        [
            "Andalucía",
            "Villa del Socorro",
            "Moscú"
        ],
        key="barrio2"
    )

    referencia = st.text_input(
        "Referencia",
        key="ref2"
    )

    imagen = st.file_uploader(
        "Suba una fotografía",
        type=["jpg","jpeg","png"],
        key="imagen2"
    )

    if imagen:

        img = Image.open(imagen)

        st.image(img)

        if st.button("Evaluar"):

            st.warning(
                "🚨 Posible punto crítico detectado."
            )

            st.write(
                f"📍 {barrio}"
            )

            st.write(
                f"📌 {referencia}"
            )

imagen = st.file_uploader(
    "Suba una fotografía",
    type=["jpg", "jpeg", "png"]
)

if imagen:

    img = Image.open(imagen)

    st.image(img, caption="Imagen cargada")

    if st.button("Analizar imagen"):
        st.success("Imagen recibida correctamente.")
        st.write("🤖 Próximamente se ejecutará la IA.")
