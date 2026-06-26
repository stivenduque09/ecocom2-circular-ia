import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
from datetime import datetime
import pandas as pd
import folium
from streamlit_folium import st_folium
from shapely.geometry import Point, Polygon
import streamlit.components.v1 as components

st.set_page_config(
    page_title="EcoCom2 Circular IA",
    page_icon="♻️",
    layout="wide"
)

st.markdown("""
<style>
.stApp {background:#0f1f17;color:white;}
.main-title{font-size:34px;font-weight:bold;color:#4ade80;}
.gps-ok{background:#134e4a;padding:12px;border-radius:8px;}
.gps-error{background:#7f1d1d;padding:12px;border-radius:8px;}
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def cargar_modelo():
    return YOLO("best.pt")

modelo = cargar_modelo()

BARRIOS = [
    "Andalucía",
    "Villa del Socorro",
    "Moscú",
    "Santa Cruz",
    "La Francia"
]

POLIGONO = Polygon([
    (-75.5650,6.2850),
    (-75.5480,6.2850),
    (-75.5400,6.2950),
    (-75.5380,6.3100),
    (-75.5450,6.3200),
    (-75.5600,6.3180),
    (-75.5700,6.3080),
    (-75.5680,6.2950)
])

materiales = {
    "bottle":("Botella",0.05),
    "can":("Lata",0.02),
    "book":("Libro",0.30),
    "box":("Caja",0.30),
    "cup":("Vaso",0.03),
    "cell phone":("Celular",0.20),
    "laptop":("Portátil",2.50)
}

if "reportes" not in st.session_state:
    st.session_state.reportes = []

if "lat" not in st.session_state:
    st.session_state.lat = None

if "lon" not in st.session_state:
    st.session_state.lon = None

if "permitido" not in st.session_state:
    st.session_state.permitido = False

query = st.query_params

if "lat" in query and "lon" in query:
    lat = float(query["lat"])
    lon = float(query["lon"])

    st.session_state.lat = lat
    st.session_state.lon = lon

    punto = Point(lon, lat)

    st.session_state.permitido = POLIGONO.contains(punto)

menu = st.sidebar.radio(
    "Menú",
    [
        "🏠 Inicio",
        "📸 Reportar",
        "🚨 Punto crítico",
        "ℹ️ Información"
    ]
)

gps_html = '''
<button onclick="gps()" style="
width:100%;
padding:15px;
background:#10b981;
color:white;
border:none;
border-radius:8px;">
📡 VALIDAR GPS
</button>

<script>
function gps(){
navigator.geolocation.getCurrentPosition(
function(pos){
window.parent.location.search =
'?lat=' + pos.coords.latitude +
'&lon=' + pos.coords.longitude;
});
}
</script>
'''

if menu == "🏠 Inicio":

    st.markdown(
        '<div class="main-title">EcoCom2 Circular IA</div>',
        unsafe_allow_html=True
    )

    components.html(gps_html,height=80)

    if st.session_state.lat:

        if st.session_state.permitido:
            st.markdown(
                '<div class="gps-ok">✅ Dentro de la Comuna 2</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                '<div class="gps-error">🛑 Fuera de la Comuna 2</div>',
                unsafe_allow_html=True
            )

    mapa = folium.Map(
        location=[
            st.session_state.lat or 6.2982,
            st.session_state.lon or -75.5521
        ],
        zoom_start=15
    )

    if st.session_state.lat:

        folium.Marker(
            [
                st.session_state.lat,
                st.session_state.lon
            ],
            tooltip="Tu ubicación"
        ).add_to(mapa)

    for rep in st.session_state.reportes:

        color = "green"

        if "🔴" in rep["Nivel"]:
            color = "red"

        elif "🟡" in rep["Nivel"]:
            color = "orange"

        folium.CircleMarker(
            [rep["Lat"], rep["Lon"]],
            radius=10,
            color=color,
            fill=True,
            popup=rep["Codigo"]
        ).add_to(mapa)

    st_folium(mapa,width=1100,height=500)

    if len(st.session_state.reportes):

        df = pd.DataFrame(
            st.session_state.reportes
        )

        st.dataframe(df)

        st.download_button(
            "Descargar CSV",
            df.to_csv(index=False),
            "reportes.csv"
        )

elif menu == "📸 Reportar":

    if st.session_state.lat is None:
        st.warning(
            "Valida tu GPS primero."
        )
        st.stop()

    if not st.session_state.permitido:
        st.error(
            "Solo la Comuna 2 puede reportar."
        )
        st.stop()

    barrio = st.selectbox(
        "Barrio",
        BARRIOS
    )

    referencia = st.text_input(
        "Referencia"
    )

    imagen = st.file_uploader(
        "Sube una foto",
        type=["jpg","jpeg","png"]
    )

    if imagen:

        img = Image.open(imagen)

        if st.button("Analizar"):

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".jpg"
            ) as tmp:

                img.save(tmp.name)

                resultados = modelo(
                    tmp.name,
                    conf=0.15
                )

            c1,c2 = st.columns(2)

            with c1:
                st.image(
                    img,
                    caption="Original"
                )

            with c2:
                st.image(
                    resultados[0].plot(),
                    caption="IA"
                )

            objetos = []

            for r in resultados:
                for box in r.boxes:
                    clase = int(box.cls[0])
                    nombre = modelo.names[clase]
                    objetos.append(nombre)

            conteo = Counter(objetos)

            peso = 0

            for obj,cantidad in conteo.items():

                st.write(
                    f"{obj}: {cantidad}"
                )

                if obj in materiales:
                    peso += (
                        materiales[obj][1]
                        * cantidad
                    )

            total = len(objetos)

            if total >= 8:
                nivel = "🔴 Crítico"
            elif total >= 4:
                nivel = "🟡 Medio"
            else:
                nivel = "🟢 Bajo"

            st.write(
                f"Peso estimado: {peso:.2f} kg"
            )

            st.write(
                f"Clasificación: {nivel}"
            )

            if st.button(
                "Guardar reporte"
            ):

                st.session_state.reportes.append({
                    "Codigo":
                    f"REP-{len(st.session_state.reportes)+1}",
                    "Barrio": barrio,
                    "Referencia": referencia,
                    "Objetos": total,
                    "Peso": round(peso,2),
                    "Nivel": nivel,
                    "Lat": st.session_state.lat,
                    "Lon": st.session_state.lon,
                    "Fecha":
                    datetime.now().strftime(
                        "%d/%m/%Y %H:%M"
                    )
                })

                st.success(
                    "Reporte guardado."
                )

elif menu == "🚨 Punto crítico":

    st.header(
        "Punto crítico"
    )

    descripcion = st.text_area(
        "Descripción"
    )

    if st.button(
        "Registrar"
    ):

        st.session_state.reportes.append({
            "Codigo":
            f"CRIT-{len(st.session_state.reportes)+1}",
            "Barrio": "Crítico",
            "Referencia": descripcion,
            "Objetos": 10,
            "Peso": 5,
            "Nivel": "🔴 Crítico",
            "Lat":
            st.session_state.lat or 6.2982,
            "Lon":
            st.session_state.lon or -75.5521,
            "Fecha":
            datetime.now().strftime(
                "%d/%m/%Y %H:%M"
            )
        })

        st.success(
            "Punto crítico guardado."
        )

elif menu == "ℹ️ Información":

    st.header(
        "EcoCom2"
    )

    st.write(
        "Sistema de monitoreo ambiental "
        "de la Comuna 2."
    )
