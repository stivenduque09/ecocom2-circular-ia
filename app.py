import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium
from streamlit_folium import st_folium
import pandas as pd
import streamlit.components.v1 as components
from shapely.geometry import Point, Polygon

# ====================================================================
# 1. CONFIGURACIÓN DE LA PÁGINA
# ====================================================================
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon="♻️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0f1f17; color: #e8f5e9; }
    .block-container { padding-top: 1.5rem; }
    h1, h2, h3 { color: #4ade80 !important; }
    .metric-card {
        background: rgba(16,185,129,0.1);
        border: 1px solid rgba(74,222,128,0.3);
        border-radius: 10px; padding: 16px; text-align: center;
    }
    .gps-ok {
        background: rgba(16,185,129,0.15); border: 1px solid #4ade80;
        border-radius: 8px; padding: 12px 16px; color: #4ade80; font-weight: bold;
    }
    .gps-warn {
        background: rgba(251,191,36,0.15); border: 1px solid #fbbf24;
        border-radius: 8px; padding: 12px 16px; color: #fbbf24; font-weight: bold;
    }
    .gps-error {
        background: rgba(239,68,68,0.15); border: 1px solid #ef4444;
        border-radius: 8px; padding: 12px 16px; color: #ef4444; font-weight: bold;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg,#10b981,#059669);
        border: none; font-weight: bold; font-size: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO CORREGIDO — COMUNA 2 SANTA CRUZ, MEDELLÍN
#    Coordenadas verificadas del límite oficial (más pequeño y preciso)
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    (-75.5610, 6.2900),
    (-75.5530, 6.2880),
    (-75.5460, 6.2910),
    (-75.5420, 6.2970),
    (-75.5410, 6.3040),
    (-75.5450, 6.3110),
    (-75.5530, 6.3140),
    (-75.5610, 6.3110),
    (-75.5650, 6.3040),
    (-75.5640, 6.2960),
    (-75.5610, 6.2900),
])

BARRIOS_PILOTO = ["Andalucía", "Villa del Socorro", "Moscú No. 1", "Moscú No. 2", "Santa Cruz", "La Francia"]
LAT_CENTRO = 6.3010
LON_CENTRO = -75.5530

# ====================================================================
# 3. ESTADO DE SESIÓN
# ====================================================================
for k, v in {
    "registro_reportes": [],
    "gps_lat": None,
    "gps_lon": None,
    "gps_validado": False,
    "fuera_de_rango": True,
    "reporte_enviado": False,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ====================================================================
# 4. LEER GPS DESDE QUERY PARAMS (JS → Streamlit)
# ====================================================================
qp = st.query_params
if "lat" in qp and "lon" in qp:
    try:
        lat_qp = float(qp["lat"])
        lon_qp = float(qp["lon"])
        st.session_state.gps_lat = lat_qp
        st.session_state.gps_lon = lon_qp
        st.session_state.gps_validado = True
        punto = Point(lon_qp, lat_qp)
        st.session_state.fuera_de_rango = not POLIGONO_COMUNA2.contains(punto)
        st.query_params.clear()
    except Exception:
        pass

# ====================================================================
# 5. CARGAR MODELO YOLO
# ====================================================================
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# ====================================================================
# 6. DICCIONARIO DE MATERIALES (clave inglés YOLO → español + info)
# ====================================================================
# (nombre_español, tipo_material, peso_kg, es_reciclable)
MATERIALES = {
    "bottle":       ("Botella plástica",    "Plástico",     0.05,  True),
    "cup":          ("Vaso plástico",       "Plástico",     0.03,  True),
    "chair":        ("Silla",              "Plástico",     2.00,  True),
    "bench":        ("Banco",              "Plástico",     2.50,  True),
    "bucket":       ("Balde",              "Plástico",     0.50,  True),
    "toy":          ("Juguete",            "Plástico",     0.50,  True),
    "book":         ("Libro/Cuaderno",     "Papel",        0.30,  True),
    "newspaper":    ("Periódico",          "Papel",        0.10,  True),
    "box":          ("Caja de cartón",     "Cartón",       0.30,  True),
    "wine glass":   ("Copa de vidrio",     "Vidrio",       0.20,  True),
    "vase":         ("Jarrón de vidrio",   "Vidrio",       0.80,  True),
    "can":          ("Lata de aluminio",   "Aluminio",     0.02,  True),
    "cell phone":   ("Celular",            "Electrónico",  0.20,  True),
    "laptop":       ("Portátil",           "Electrónico",  2.50,  True),
    "keyboard":     ("Teclado",            "Electrónico",  0.60,  True),
    "mouse":        ("Ratón",              "Electrónico",  0.10,  True),
    "remote":       ("Control remoto",     "Electrónico",  0.20,  True),
    "tv":           ("Televisor",          "Electrónico",  8.00,  True),
    "clock":        ("Reloj",              "Electrónico",  0.30,  True),
    "backpack":     ("Mochila",            "Textil",       0.50,  True),
    "handbag":      ("Bolso",              "Textil",       0.40,  True),
    "suitcase":     ("Maleta",             "Textil",       2.50,  True),
    "tie":          ("Corbata",            "Textil",       0.10,  True),
    "banana":       ("Banano",             "Orgánico",     0.10,  True),
    "apple":        ("Manzana",            "Orgánico",     0.15,  True),
    "orange":       ("Naranja",            "Orgánico",     0.20,  True),
    "broccoli":     ("Brócoli",            "Orgánico",     0.25,  True),
    "carrot":       ("Zanahoria",          "Orgánico",     0.10,  True),
    "couch":        ("Sofá",               "Mixto",       15.00,  True),
    "bed":          ("Cama",               "Mixto",       20.00,  True),
    "dining table": ("Mesa de comedor",    "Madera",      12.00,  True),
    "umbrella":     ("Paraguas",           "Mixto",        0.50,  True),
    "potted plant": ("Matero",             "Orgánico",     1.00,  True),
    # No reciclables / no aplican
    "person":       ("Persona",            "No aplica",    0,     False),
    "dog":          ("Perro",              "No aplica",    0,     False),
    "cat":          ("Gato",               "No aplica",    0,     False),
    "car":          ("Vehículo",           "No aplica",    0,     False),
    "bus":          ("Bus",                "No aplica",    0,     False),
    "truck":        ("Camión",             "No aplica",    0,     False),
    "bicycle":      ("Bicicleta",          "No aplica",    0,     False),
    "motorcycle":   ("Motocicleta",        "No aplica",    0,     False),
    "traffic light":("Semáforo",           "No aplica",    0,     False),
}

# ====================================================================
# 7. BARRA LATERAL
# ====================================================================
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## ♻️ EcoCom2")

menu = st.sidebar.radio(
    "Menú",
    ["🏠 Inicio", "📸 Reportar Residuo", "🚨 Punto Crítico", "ℹ️ Información"]
)

# Badge GPS en sidebar
if st.session_state.gps_validado:
    if not st.session_state.fuera_de_rango:
        st.sidebar.markdown(
            f'<div class="gps-ok">✅ GPS: Dentro de Comuna 2<br>'
            f'<small>{st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}</small></div>',
            unsafe_allow_html=True
        )
    else:
        st.sidebar.markdown(
            f'<div class="gps-error">🛑 GPS: Fuera de Comuna 2<br>'
            f'<small>{st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}</small></div>',
            unsafe_allow_html=True
        )
else:
    st.sidebar.markdown('<div class="gps-warn">⚠️ GPS no verificado</div>', unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="background:rgba(16,185,129,0.1);padding:10px;border-radius:8px;
border:1px solid rgba(74,222,128,0.2);font-size:12px;color:#9ca3af;">
    ⚙️ <b style="color:#4ade80">EcoCom2 v3.1</b><br>
    Territorio INN 2026 | ITM Medellín<br>
    Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>
""", unsafe_allow_html=True)


# ====================================================================
# FUNCIÓN: Botón GPS con JS
# ====================================================================
def mostrar_boton_gps():
    """Inyecta el botón GPS que redirige con ?lat=...&lon=... al hacer clic."""
    components.html("""
    <div style="font-family:sans-serif;">
        <button onclick="pedirGPS()" style="
            background:linear-gradient(135deg,#10b981,#059669);
            color:white;border:none;padding:14px 28px;font-size:15px;
            font-weight:bold;border-radius:8px;cursor:pointer;
            width:100%;letter-spacing:0.5px;margin-bottom:6px;">
            📡 VALIDAR MI UBICACIÓN GPS
        </button>
        <div id="msg" style="color:#9ca3af;font-size:13px;min-height:20px;"></div>
    </div>
    <script>
    function pedirGPS() {
        var msg = document.getElementById('msg');
        if (!navigator.geolocation) {
            msg.innerHTML = '❌ Tu navegador no soporta GPS.';
            return;
        }
        msg.innerHTML = '⏳ Solicitando GPS satelital... (puede tardar unos segundos)';
        navigator.geolocation.getCurrentPosition(
            function(pos) {
                var lat = pos.coords.latitude.toFixed(7);
                var lon = pos.coords.longitude.toFixed(7);
                msg.innerHTML = '✅ Coordenadas obtenidas: ' + lat + ', ' + lon + ' — redirigiendo...';
                setTimeout(function() {
                    window.parent.location.href =
                        window.parent.location.pathname + '?lat=' + lat + '&lon=' + lon;
                }, 600);
            },
            function(err) {
                var errores = {
                    1: 'Permiso denegado. Permite el GPS en tu navegador.',
                    2: 'Posición no disponible. Verifica señal GPS/WiFi.',
                    3: 'Tiempo agotado. Intenta de nuevo.'
                };
                msg.innerHTML = '❌ ' + (errores[err.code] || err.message);
            },
            { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
        );
    }
    </script>
    """, height=80)


# ====================================================================
# FUNCIÓN: Analizar imagen con YOLO y devolver resultados
# ====================================================================
def analizar_imagen(img):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        img.save(tmp.name)
        resultados = modelo(tmp.name, conf=0.10)
    return resultados


# ====================================================================
# FUNCIÓN: Procesar detecciones → tabla de materiales
# ====================================================================
def procesar_detecciones(resultados):
    objetos = []
    for r in resultados:
        for box in r.boxes:
            clase = int(box.cls[0])
            nombre_en = modelo.names[clase]
            confianza = float(box.conf[0])
            objetos.append((nombre_en, confianza))

    peso_total = 0.0
    residuos = 0
    tipo_predominante = "Varios"
    conteo = Counter([o[0] for o in objetos])
    confianzas = {}
    for nombre, conf in objetos:
        if nombre not in confianzas or conf > confianzas[nombre]:
            confianzas[nombre] = conf

    tabla = []
    for obj_en, cantidad in conteo.items():
        if obj_en in MATERIALES:
            nombre_es, material, peso_u, reciclable = MATERIALES[obj_en]
        else:
            nombre_es = obj_en
            material = "Desconocido"
            peso_u = 0.1
            reciclable = False

        conf_pct = f"{confianzas.get(obj_en, 0)*100:.0f}%"

        if reciclable:
            residuos += cantidad
            peso_obj = round(peso_u * cantidad, 2)
            peso_total += peso_obj
            tipo_predominante = material
            tabla.append({
                "Objeto detectado": nombre_es,
                "Material": material,
                "Cantidad": cantidad,
                "Peso estimado (kg)": peso_obj,
                "Confianza IA": conf_pct,
                "♻️ Reciclable": "✅ Sí",
            })
        else:
            tabla.append({
                "Objeto detectado": nombre_es,
                "Material": material,
                "Cantidad": cantidad,
                "Peso estimado (kg)": 0,
                "Confianza IA": conf_pct,
                "♻️ Reciclable": "❌ No",
            })

    nivel = (
        "🔴 Punto crítico confirmado" if residuos >= 10
        else "🟡 Posible punto crítico" if residuos >= 5
        else "🟢 Residuo individual"
    )

    return tabla, residuos, round(peso_total, 2), tipo_predominante, nivel


# ====================================================================
# 8. SECCIÓN: INICIO
# ====================================================================
if menu == "🏠 Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Sistema inteligente de gestión de residuos — **Solo residentes de la Comuna 2 pueden reportar al mapa.**")

    # --- GPS ---
    st.markdown("### 📡 Verificar mi ubicación")
    mostrar_boton_gps()

    if st.session_state.gps_validado:
        lat_u = st.session_state.gps_lat
        lon_u = st.session_state.gps_lon
        if not st.session_state.fuera_de_rango:
            st.markdown(
                f'<div class="gps-ok">✅ Dentro de la Comuna 2 — Lat: {lat_u:.5f} | Lon: {lon_u:.5f}<br>'
                f'Puedes analizar imágenes y enviar reportes al mapa comunitario.</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="gps-error">🛑 Fuera de la Comuna 2 — Lat: {lat_u:.5f} | Lon: {lon_u:.5f}<br>'
                f'Puedes analizar materiales con la IA, pero el envío de reportes está bloqueado.</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown(
            '<div class="gps-warn">⚠️ GPS no verificado — Presiona el botón para validar tu ubicación.</div>',
            unsafe_allow_html=True
        )

    st.markdown("---")

    # --- MAPA ---
    st.markdown("### 🗺️ Mapa Comunitario — Comuna 2, Santa Cruz")
    barrio_filtro = st.selectbox("Filtrar reportes por barrio:", ["Todos"] + BARRIOS_PILOTO)

    lat_c = st.session_state.gps_lat if st.session_state.gps_lat else LAT_CENTRO
    lon_c = st.session_state.gps_lon if st.session_state.gps_lon else LON_CENTRO

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=15, tiles="CartoDB dark_matter")

    # Polígono de la Comuna 2 (más pequeño y preciso)
    coords_poly = [(lat, lon) for lon, lat in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_poly,
        color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.06,
        popup="Límite oficial Comuna 2 — Santa Cruz",
        tooltip="📍 Área piloto EcoCom2"
    ).add_to(mapa)

    # Pin del usuario
    if st.session_state.gps_validado:
        color_u = "blue" if not st.session_state.fuera_de_rango else "gray"
        estado_u = "Residente validado ✅" if not st.session_state.fuera_de_rango else "Observador externo 🛑"
        folium.Marker(
            location=[st.session_state.gps_lat, st.session_state.gps_lon],
            popup=f"📍 Tu ubicación<br>{estado_u}<br>{st.session_state.gps_lat:.6f}, {st.session_state.gps_lon:.6f}",
            tooltip="📍 Tú estás aquí",
            icon=folium.Icon(color=color_u, icon="user", prefix="fa")
        ).add_to(mapa)

    # Reportes en coordenadas reales
    for rep in st.session_state.registro_reportes:
        if barrio_filtro != "Todos" and rep.get("Sector") != barrio_filtro:
            continue
        lat_r = rep.get("Lat", LAT_CENTRO)
        lon_r = rep.get("Lon", LON_CENTRO)
        nivel = rep.get("Clasificación", "🟢")
        color = "red" if "🔴" in nivel else ("orange" if "🟡" in nivel else "green")
        popup_html = (
            f"<div style='font-family:sans-serif;min-width:170px;'>"
            f"<b>{rep['Código']}</b><br>"
            f"📍 {rep['Sector']}<br>"
            f"📌 {rep['Referencia']}<br>"
            f"♻️ {rep['Objetos']} obj | ⚖️ {rep['Peso (Kg)']} kg<br>"
            f"🏷️ {rep['Predominante']}<br>"
            f"<span style='color:{color}'>● {nivel}</span></div>"
        )
        folium.CircleMarker(
            location=[lat_r, lon_r],
            radius=12, color=color, fill=True,
            fill_color=color, fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"Reporte {rep['Código']}"
        ).add_to(mapa)

    st_folium(mapa, width=1100, height=480, returned_objects=[])

    # --- HISTORIAL ---
    st.markdown("---")
    st.markdown("### 📋 Historial de Reportes")
    if st.session_state.registro_reportes:
        df = pd.DataFrame(st.session_state.registro_reportes)
        cols = [c for c in ["Código", "Sector", "Referencia", "Objetos",
                             "Peso (Kg)", "Predominante", "Clasificación",
                             "Lat", "Lon"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2><p>Puntos registrados</p></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{df["Peso (Kg)"].sum():.1f} kg</h2><p>Carga acumulada</p></div>', unsafe_allow_html=True)
        with c3:
            criticos = len(df[df["Clasificación"].str.contains("crítico", case=False, na=False)])
            st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{criticos}</h2><p>Puntos críticos</p></div>', unsafe_allow_html=True)
    else:
        st.info("💡 Sin reportes aún. Usa '📸 Reportar Residuo' para agregar el primero.")


# ====================================================================
# 9. SECCIÓN: REPORTAR RESIDUO
# ====================================================================
elif menu == "📸 Reportar Residuo":
    st.header("📸 Reporte de Residuos con IA")

    es_residente = st.session_state.gps_validado and not st.session_state.fuera_de_rango

    # Banner de estado
    if not st.session_state.gps_validado:
        st.markdown(
            '<div class="gps-warn">⚠️ GPS no verificado — Puedes analizar materiales, '
            'pero ve a <b>🏠 Inicio</b> y valida tu ubicación para enviar reportes al mapa.</div>',
            unsafe_allow_html=True
        )
    elif st.session_state.fuera_de_rango:
        st.markdown(
            f'<div class="gps-error">🛑 Estás fuera de la Comuna 2 '
            f'({st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}) — '
            f'Puedes ver los materiales detectados, pero <b>el envío al mapa está bloqueado</b>.</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div class="gps-ok">✅ Residente verificado — '
            f'{st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f} — '
            f'Puedes analizar y enviar reportes.</div>',
            unsafe_allow_html=True
        )

    st.markdown("")

    if st.session_state.reporte_enviado:
        st.success("🎉 ¡Reporte enviado y registrado en el mapa con tus coordenadas GPS!")
        if st.button("🔄 Hacer otro reporte", type="primary", use_container_width=True):
            st.session_state.reporte_enviado = False
            st.rerun()
    else:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            barrio = st.selectbox("Barrio:", BARRIOS_PILOTO)
        with col_f2:
            referencia = st.text_input("Referencia del lugar (ej: Cra 50 #107-62, frente al parque)")

        imagen = st.file_uploader("📷 Fotografía del residuo:", type=["jpg", "jpeg", "png"])

        if imagen is not None:
            img = Image.open(imagen)

            if st.button("🔍 Analizar imagen con IA", use_container_width=True, type="primary"):
                with st.spinner("Analizando con YOLOv8..."):
                    resultados = analizar_imagen(img)

                # Comparación lado a lado
                st.markdown("### 🔬 Original vs Detecciones IA")
                col_o, col_d = st.columns(2)
                with col_o:
                    st.markdown("**📷 Imagen original**")
                    st.image(img, use_container_width=True)
                with col_d:
                    st.markdown("**🤖 Detecciones de la IA**")
                    st.image(resultados[0].plot(), caption="Objetos identificados", use_container_width=True)

                # Procesar y mostrar tabla en ESPAÑOL
                tabla, residuos, peso_total, tipo_predominante, nivel = procesar_detecciones(resultados)

                st.markdown("### 📊 Materiales Detectados")
                if tabla:
                    st.dataframe(pd.DataFrame(tabla), use_container_width=True)
                else:
                    st.warning("⚠️ No se detectaron objetos reconocibles.")

                if residuos > 0 or peso_total > 0:
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.markdown(f'<div class="metric-card"><h3 style="color:#4ade80">{residuos}</h3><p>Residuos reciclables</p></div>', unsafe_allow_html=True)
                    with c2:
                        st.markdown(f'<div class="metric-card"><h3 style="color:#4ade80">{peso_total} kg</h3><p>Peso estimado</p></div>', unsafe_allow_html=True)
                    with c3:
                        st.markdown(f'<div class="metric-card"><h3>{nivel}</h3><p>Clasificación</p></div>', unsafe_allow_html=True)

                # Solo preparar reporte si es residente
                if es_residente and residuos > 0:
                    st.session_state.cache_reporte = {
                        "Código": f"REP-{len(st.session_state.registro_reportes) + 200}",
                        "Sector": barrio,
                        "Referencia": referencia if referencia else "Sin referencia",
                        "Objetos": residuos,
                        "Peso (Kg)": peso_total,
                        "Predominante": tipo_predominante,
                        "Clasificación": nivel,
                        "Lat": st.session_state.gps_lat,
                        "Lon": st.session_state.gps_lon,
                    }
                elif not es_residente:
                    st.markdown("---")
                    st.markdown(
                        '<div class="gps-error" style="text-align:center;">'
                        '🛑 <b>Análisis completado.</b> Para enviar este reporte al mapa comunitario '
                        'debes estar físicamente dentro de la <b>Comuna 2</b> con GPS verificado.'
                        '</div>',
                        unsafe_allow_html=True
                    )

        # Botón enviar — solo si hay reporte preparado
        if "cache_reporte" in st.session_state and es_residente:
            rep = st.session_state.cache_reporte
            st.markdown("---")
            st.markdown("### ✅ Confirmar y enviar reporte al mapa")
            st.markdown(f"""
| Campo | Valor |
|---|---|
| **Sector** | {rep['Sector']} |
| **Referencia** | {rep['Referencia']} |
| **Residuos reciclables** | {rep['Objetos']} objetos |
| **Peso estimado** | {rep['Peso (Kg)']} kg |
| **Clasificación** | {rep['Clasificación']} |
| **📍 Coordenadas GPS** | {rep['Lat']:.6f}, {rep['Lon']:.6f} |
""")
            if st.button("🚀 ENVIAR REPORTE DEFINITIVO", type="primary", use_container_width=True):
                st.session_state.registro_reportes.append(rep)
                del st.session_state.cache_reporte
                st.session_state.reporte_enviado = True
                st.rerun()


# ====================================================================
# 10. SECCIÓN: PUNTO CRÍTICO
# ====================================================================
elif menu == "🚨 Punto Crítico":
    st.header("🚨 Registrar Punto Crítico")

    es_residente = st.session_state.gps_validado and not st.session_state.fuera_de_rango

    if not st.session_state.gps_validado:
        st.markdown(
            '<div class="gps-warn">⚠️ Valida tu GPS desde <b>🏠 Inicio</b> para registrar alertas.</div>',
            unsafe_allow_html=True
        )
        mostrar_boton_gps()
        st.stop()

    if st.session_state.fuera_de_rango:
        st.markdown(
            f'<div class="gps-error">🛑 Fuera de la Comuna 2 '
            f'({st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}) — '
            f'No puedes registrar alertas de puntos críticos.</div>',
            unsafe_allow_html=True
        )
        st.stop()

    st.markdown(
        f'<div class="gps-ok">✅ Residente verificado — {st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}</div>',
        unsafe_allow_html=True
    )
    st.markdown("")

    col_a, col_b = st.columns(2)
    with col_a:
        barrio = st.selectbox("Barrio:", BARRIOS_PILOTO, key="barrio_critico")
    with col_b:
        referencia = st.text_input("Referencia:", key="ref_critico")

    imagen = st.file_uploader("📷 Foto del punto crítico:", type=["jpg","jpeg","png"], key="img_critico")

    if imagen is not None:
        img = Image.open(imagen)
        if st.button("🔍 Evaluar con IA", type="primary", use_container_width=True):
            with st.spinner("Analizando..."):
                resultados = analizar_imagen(img)

            st.markdown("### 🔬 Original vs Detecciones")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**📷 Original**")
                st.image(img, use_container_width=True)
            with c2:
                st.markdown("**🤖 Detecciones**")
                st.image(resultados[0].plot(), use_container_width=True)

            tabla, residuos, peso_total, tipo_predominante, _ = procesar_detecciones(resultados)
            cantidad_total = sum(len(r.boxes) for r in resultados)

            nivel = (
                "🔴 Punto crítico alto" if cantidad_total >= 8
                else "🟡 Punto crítico medio" if cantidad_total >= 4
                else "🟢 Punto crítico bajo"
            )

            if tabla:
                st.dataframe(pd.DataFrame(tabla), use_container_width=True)

            st.markdown(f"**Objetos totales detectados:** {cantidad_total} → **{nivel}**")
            st.markdown(f"📍 Se registrará en: `{st.session_state.gps_lat:.6f}, {st.session_state.gps_lon:.6f}`")

            if st.button("🚨 REGISTRAR ALERTA EN EL MAPA", type="primary", use_container_width=True):
                st.session_state.registro_reportes.append({
                    "Código": f"CRIT-{len(st.session_state.registro_reportes)+500}",
                    "Sector": barrio,
                    "Referencia": referencia if referencia else "Punto crítico",
                    "Objetos": cantidad_total,
                    "Peso (Kg)": round(cantidad_total * 0.4, 2),
                    "Predominante": tipo_predominante if tipo_predominante else "Mixto",
                    "Clasificación": nivel,
                    "Lat": st.session_state.gps_lat,
                    "Lon": st.session_state.gps_lon,
                })
                st.success("✅ ¡Alerta registrada en el mapa de congestión!")


# ====================================================================
# 11. SECCIÓN: INFORMACIÓN
# ====================================================================
elif menu == "ℹ️ Información":
    st.header("ℹ️ ¿Qué es EcoCom2 Circular IA?")
    st.markdown("""
**EcoCom2 Circular IA** es una plataforma de gestión inteligente de residuos sólidos para la **Comuna 2 — Santa Cruz, Medellín**.

### 🔐 Validación Territorial GPS
- Solo residentes **dentro del polígono oficial** de la Comuna 2 pueden enviar reportes al mapa.
- La validación usa **GPS satelital** del dispositivo en tiempo real.
- Observadores externos pueden **analizar materiales** con la IA pero no publicar reportes.

### 🤖 Inteligencia Artificial — YOLOv8
- Detecta objetos en fotografías automáticamente.
- Clasifica en: Plástico, Papel, Cartón, Vidrio, Aluminio, Electrónico, Orgánico, Textil, Madera.
- Muestra los resultados **en español** con peso estimado y confianza de la detección.
- Compara la imagen original con las detecciones lado a lado.

### 🗺️ Mapa Comunitario
- Cada reporte se pinta en las **coordenadas GPS exactas** del reporte.
- El polígono verde muestra el **límite real** de la zona piloto.
- Los colores indican nivel de criticidad: 🟢 Individual · 🟡 Posible crítico · 🔴 Crítico confirmado.

### 📍 Barrios del Prototipo
""")
    for b in BARRIOS_PILOTO:
        st.write(f"- 📍 **{b}**")
    st.markdown("""
---
**Versión:** 3.1 | **Proyecto:** Territorio INN 2026 | **Institución:** ITM Medellín
**Desarrollador:** Brandon Duque
""")
