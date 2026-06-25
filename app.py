import streamlit as st
from PIL import Image

st.set_page_config(
    page_title="EcoCom2 Circular IA",
    page_icon="♻️"
)

st.title("♻️ EcoCom2 Circular IA")

st.write(
    "Sistema inteligente para la identificación y clasificación de residuos."
)

barrio = st.selectbox(
    "Seleccione el barrio",
    ["Andalucía", "Villa del Socorro", "Moscú"]
)

referencia = st.text_input(
    "Ingrese una referencia del lugar"
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
