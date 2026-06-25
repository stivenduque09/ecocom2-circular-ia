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
    "bottle": ("Botella", "Plástico", 0.05, True),
    "cup": ("Vaso", "Plástico", 0.03, True),
    "wine glass": ("Vidrio", "Vidrio", 0.20, True),
    "book": ("Libro", "Papel", 0.30, True),
    "chair": ("Silla", "Plástico", 2.00, True),
    "backpack": ("Mochila", "Textil", 0.50, True),
    "suitcase": ("Maleta", "Mixto", 2.50, True),
    "cell phone": ("Celular", "Electrónico", 0.20, True),
    "keyboard": ("Teclado", "Electrónico", 0.60, True),
    "mouse": ("Ratón", "Electrónico", 0.10, True),
    "tv": ("Televisor", "Electrónico", 8.00, True),
    "banana": ("Banano", "Orgánico", 0.10, True),
    "apple": ("Manzana", "Orgánico", 0.15, True),
    "orange": ("Naranja", "Orgánico", 0.20, True),

    "person": ("Persona", "No aplica", 0, False),
    "dog": ("Perro", "No aplica", 0, False),
    "cat": ("Gato", "No aplica", 0, False),
    "car": ("Vehículo", "No aplica", 0, False)
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

   if referencia and len(referencia) < 8:
    st.warning(
        "Ingrese una referencia más específica."
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

                       nombre_es, material, peso, reciclable = materiales[obj]

if reciclable:

    st.success(
        f"♻️ {nombre_es} - {material}"
    )

    peso_total += peso

else:

    st.warning(
        f"⚠️ {nombre_es} no corresponde a un residuo."
    )
               if cantidad >= 10:
    nivel = "🔴 Punto crítico confirmado"

elif cantidad >= 5:
    nivel = "🟡 Posible punto crítico"

elif cantidad >= 1:
    nivel = "🟢 Residuo individual"

else:
    nivel = "⚪ Evidencia insuficiente"

                st.write(f"📍 Barrio: {barrio}")
                st.write(f"📌 Referencia: {referencia}")
                st.write(f"🗑️ Objetos detectados: {cantidad}")
                st.write(f"⚖️ Peso aproximado: {peso_total:.2f} kg")
               if cantidad == 0:
    st.error(
        "❌ La evidencia no es suficiente para generar un reporte."
    )

elif cantidad <= 2:
    st.info(
        "📷 Se recomienda tomar una fotografía más cercana."
    )

else:
    st.success(
        "✅ Reporte validado correctamente."
    )
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
