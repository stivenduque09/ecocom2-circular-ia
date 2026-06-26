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
        background: rgba(251,191,36,0.12); border: 1px solid #fbbf24;
        border-radius: 8px; padding: 12px 16px; color: #fbbf24; font-weight: bold;
    }
    .gps-error {
        background: rgba(239,68,68,0.12); border: 1px solid #ef4444;
        border-radius: 8px; padding: 12px 16px; color: #ef4444; font-weight: bold;
    }
    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg,#10b981,#059669);
        border: none; font-weight: bold; font-size: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO REAL COMUNA 2 — SANTA CRUZ, MEDELLÍN
#
#  Límites oficiales verificados:
#   Norte  → Quebrada Negra/Seca (límite con Bello)
#   Oeste  → Río Medellín (límite con Comuna 5 Castilla)
#   Sur    → Quebrada La Rosa (límite con Comuna 4 Aranjuez)
#   Oriente→ Límite con Comuna 1 Popular (ladera)
#
#  Coordenadas WGS84 (lon, lat) del perímetro real ~220 ha
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    # Vértice SW — cerca del río Medellín, altura de Acevedo
    (-75.5720, 6.2960),
    # Borde oeste — siguiendo el río Medellín hacia el norte
    (-75.5710, 6.3020),
    (-75.5705, 6.3080),
    # Vértice NW — quebrada Negra, límite con Bello
    (-75.5700, 6.3130),
    (-75.5660, 6.3160),
    (-75.5610, 6.3170),
    # Vértice NE — ladera alta, límite con Bello/Comuna 1
    (-75.5560, 6.3155),
    (-75.5510, 6.3120),
    # Borde oriente — ladera hacia el sur, límite con Comuna 1
    (-75.5490, 6.3060),
    (-75.5480, 6.2990),
    (-75.5500, 6.2940),
    # Vértice SE — quebrada La Rosa, límite con Comuna 4
    (-75.5540, 6.2910),
    (-75.5600, 6.2920),
    # Cierre SW
    (-75.5660, 6.2940),
    (-75.5720, 6.2960),
])

# Los 11 barrios oficiales de la Comuna 2
BARRIOS_PILOTO = [
    "La Isla",
    "Playón de los Comuneros",
    "Pablo VI",
    "La Frontera",
    "La Francia",
    "Andalucía",
    "Villa del Socorro",
    "Villa Niza",
    "Moscú No. 1",
    "Santa Cruz",
    "La Rosa",
]

# Centro geográfico aproximado de la Comuna 2
LAT_CENTRO = 6.3040
LON_CENTRO = -75.5590

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
    "cache_reporte": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ====================================================================
# 4. LEER GPS DESDE QUERY PARAMS  (JS → ?lat=…&lon=… → Streamlit)
# ====================================================================
qp = st.query_params
if "lat" in qp and "lon" in qp:
    try:
        lat_qp = float(qp["lat"])
        lon_qp = float(qp["lon"])
        st.session_state.gps_lat = lat_qp
        st.session_state.gps_lon = lon_qp
        st.session_state.gps_validado = True
        st.session_state.fuera_de_rango = not POLIGONO_COMUNA2.contains(Point(lon_qp, lat_qp))
        st.query_params.clear()
    except Exception:
        pass

# ====================================================================
# 5. MODELO YOLO — conf=0.08 para detectar más objetos en basura real
# ====================================================================
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")

modelo = cargar_modelo()

# ====================================================================
# 6. DICCIONARIO MATERIALES  (clave=nombre YOLO en inglés)
#    Formato: (nombre_español, tipo_material, peso_kg_unidad, reciclable)
# ====================================================================
MATERIALES = {
    # Plástico
    "bottle":           ("Botella plástica",      "Plástico",    0.05,  True),
    "cup":              ("Vaso plástico",          "Plástico",    0.03,  True),
    "chair":            ("Silla plástica",         "Plástico",    2.00,  True),
    "bench":            ("Banco plástico",         "Plástico",    2.50,  True),
    "bucket":           ("Balde plástico",         "Plástico",    0.50,  True),
    "toy":              ("Juguete",                "Plástico",    0.50,  True),
    # Papel / Cartón
    "book":             ("Libro / Cuaderno",       "Papel",       0.30,  True),
    "newspaper":        ("Periódico",              "Papel",       0.10,  True),
    "box":              ("Caja de cartón",         "Cartón",      0.30,  True),
    # Vidrio
    "wine glass":       ("Copa de vidrio",         "Vidrio",      0.20,  True),
    "vase":             ("Jarrón / Matero vidrio", "Vidrio",      0.80,  True),
    # Aluminio
    "can":              ("Lata de aluminio",       "Aluminio",    0.02,  True),
    # Electrónico (RAEE)
    "cell phone":       ("Celular",                "Electrónico", 0.20,  True),
    "laptop":           ("Portátil",               "Electrónico", 2.50,  True),
    "keyboard":         ("Teclado",                "Electrónico", 0.60,  True),
    "mouse":            ("Ratón de computador",    "Electrónico", 0.10,  True),
    "remote":           ("Control remoto",         "Electrónico", 0.20,  True),
    "tv":               ("Televisor",              "Electrónico", 8.00,  True),
    "clock":            ("Reloj",                  "Electrónico", 0.30,  True),
    # Textil
    "backpack":         ("Mochila",                "Textil",      0.50,  True),
    "handbag":          ("Bolso",                  "Textil",      0.40,  True),
    "suitcase":         ("Maleta",                 "Textil",      2.50,  True),
    "tie":              ("Corbata",                "Textil",      0.10,  True),
    "umbrella":         ("Paraguas",               "Textil",      0.50,  True),
    # Orgánico
    "banana":           ("Banano",                 "Orgánico",    0.10,  True),
    "apple":            ("Manzana",                "Orgánico",    0.15,  True),
    "orange":           ("Naranja",                "Orgánico",    0.20,  True),
    "broccoli":         ("Brócoli",                "Orgánico",    0.25,  True),
    "carrot":           ("Zanahoria",              "Orgánico",    0.10,  True),
    "potted plant":     ("Planta / Matero",        "Orgánico",    1.00,  True),
    "bowl":             ("Recipiente / Tazón",     "Plástico",    0.15,  True),
    # Madera / Mixto
    "dining table":     ("Mesa de comedor",        "Madera",      12.00, True),
    "couch":            ("Sofá",                   "Mixto",       15.00, True),
    "bed":              ("Cama",                   "Mixto",       20.00, True),
    # No reciclables / no aplica
    "person":           ("Persona",                "No aplica",   0,     False),
    "dog":              ("Perro",                  "No aplica",   0,     False),
    "cat":              ("Gato",                   "No aplica",   0,     False),
    "car":              ("Vehículo",               "No aplica",   0,     False),
    "bus":              ("Bus",                    "No aplica",   0,     False),
    "truck":            ("Camión",                 "No aplica",   0,     False),
    "bicycle":          ("Bicicleta",              "No aplica",   0,     False),
    "motorcycle":       ("Motocicleta",            "No aplica",   0,     False),
    "traffic light":    ("Semáforo",               "No aplica",   0,     False),
    "stop sign":        ("Señal de tráfico",       "No aplica",   0,     False),
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

if st.session_state.gps_validado:
    if not st.session_state.fuera_de_rango:
        st.sidebar.markdown(
            f'<div class="gps-ok">✅ Dentro de la Comuna 2<br>'
            f'<small style="font-weight:normal">'
            f'Lat {st.session_state.gps_lat:.5f}<br>'
            f'Lon {st.session_state.gps_lon:.5f}</small></div>',
            unsafe_allow_html=True
        )
    else:
        st.sidebar.markdown(
            f'<div class="gps-error">🛑 Fuera de la Comuna 2<br>'
            f'<small style="font-weight:normal">'
            f'Lat {st.session_state.gps_lat:.5f}<br>'
            f'Lon {st.session_state.gps_lon:.5f}</small></div>',
            unsafe_allow_html=True
        )
else:
    st.sidebar.markdown(
        '<div class="gps-warn">⚠️ GPS no verificado<br>'
        '<small style="font-weight:normal">Ve a 🏠 Inicio para validar</small></div>',
        unsafe_allow_html=True
    )

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="background:rgba(16,185,129,0.08);padding:10px;border-radius:8px;
border:1px solid rgba(74,222,128,0.2);font-size:12px;color:#9ca3af;">
    ⚙️ <b style="color:#4ade80">EcoCom2 v3.2</b><br>
    Territorio INN 2026 | ITM Medellín<br>
    Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>
""", unsafe_allow_html=True)


# ====================================================================
# HELPERS
# ====================================================================

def boton_gps():
    """
    Botón GPS con múltiples estrategias de redirección.
    Funciona en Streamlit Cloud donde window.parent está bloqueado por CORS.
    Incluye fallback: campo de texto para pegar coordenadas manualmente.
    """
    components.html("""
    <div style="font-family:sans-serif;">
      <button onclick="pedirGPS()" id="btnGPS" style="
          background:linear-gradient(135deg,#10b981,#059669);
          color:white;border:none;padding:14px 0;font-size:15px;
          font-weight:bold;border-radius:8px;cursor:pointer;
          width:100%;letter-spacing:0.4px;margin-bottom:8px;">
          📡 VALIDAR MI UBICACIÓN GPS
      </button>
      <div id="msg" style="color:#9ca3af;font-size:13px;min-height:18px;"></div>
      <div id="manual" style="display:none;margin-top:10px;
           background:rgba(16,185,129,0.1);border:1px solid #4ade80;
           border-radius:6px;padding:10px;font-size:13px;color:#e8f5e9;">
        <b style="color:#4ade80">📋 Copia este enlace y pégalo en la barra de direcciones del navegador:</b><br><br>
        <span id="urlManual" style="word-break:break-all;color:#a7f3d0;background:rgba(0,0,0,0.3);
              padding:6px;border-radius:4px;display:block;margin-top:4px;"></span>
      </div>
    </div>
    <script>
    function pedirGPS() {
        var msg    = document.getElementById('msg');
        var manual = document.getElementById('manual');
        var btn    = document.getElementById('btnGPS');

        if (!navigator.geolocation) {
            msg.innerHTML = '❌ Tu navegador no soporta GPS.'; return;
        }
        btn.disabled = true;
        btn.style.opacity = '0.7';
        msg.innerHTML = '⏳ Obteniendo ubicación GPS... espera unos segundos.';

        navigator.geolocation.getCurrentPosition(
            function(pos) {
                var lat = pos.coords.latitude.toFixed(7);
                var lon = pos.coords.longitude.toFixed(7);
                msg.innerHTML = '✅ GPS: <b>' + lat + ', ' + lon + '</b> — redirigiendo...';

                var redirigido = false;

                // Intento 1: window.top (menos restrictivo que parent en algunos navegadores)
                try {
                    var url1 = window.top.location.href.split('?')[0] + '?lat=' + lat + '&lon=' + lon;
                    window.top.location.href = url1;
                    redirigido = true;
                } catch(e1) {}

                if (!redirigido) {
                    // Intento 2: window.parent
                    try {
                        var url2 = window.parent.location.href.split('?')[0] + '?lat=' + lat + '&lon=' + lon;
                        window.parent.location.href = url2;
                        redirigido = true;
                    } catch(e2) {}
                }

                if (!redirigido) {
                    // Fallback: construir URL y mostrársela al usuario
                    // La URL de Streamlit Cloud tiene el formato: https://xxx.streamlit.app/
                    // El iframe está en /_stcore/... así que subimos al origen
                    var appUrl = window.location.ancestorOrigins
                        ? window.location.ancestorOrigins[0]
                        : document.referrer.split('?')[0];

                    if (!appUrl) appUrl = window.location.origin;
                    var urlFinal = appUrl.replace(/[/]$/, '') + '?lat=' + lat + '&lon=' + lon;

                    document.getElementById('urlManual').textContent = urlFinal;
                    manual.style.display = 'block';
                    msg.innerHTML = '⚠️ Redirección automática bloqueada por el navegador. Copia el enlace de abajo y ábrelo en esta misma pestaña.';
                }

                btn.disabled = false;
                btn.style.opacity = '1';
            },
            function(err) {
                btn.disabled = false;
                btn.style.opacity = '1';
                var errores = {
                    1: '❌ Permiso de ubicación denegado. Haz clic en 🔒 en la barra de URL → Configuración del sitio → Ubicación → Permitir. Luego recarga.',
                    2: '❌ Señal GPS no disponible. Activa el WiFi o intenta en exteriores.',
                    3: '❌ Tiempo agotado. Vuelve a intentarlo.'
                };
                msg.innerHTML = errores[err.code] || ('❌ Error GPS: ' + err.message);
            },
            {enableHighAccuracy: true, timeout: 15000, maximumAge: 0}
        );
    }
    </script>
    """, height=120)


def analizar_imagen(img, confianza=0.08):
    """Corre YOLOv8 sobre la imagen PIL y devuelve los resultados."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        img.save(tmp.name)
        return modelo(tmp.name, conf=confianza)


def procesar_detecciones(resultados):
    """
    Convierte las detecciones YOLO en:
      - tabla (lista de dicts listos para DataFrame)
      - residuos (int): cantidad de objetos reciclables
      - peso_total (float)
      - tipo_predominante (str)
      - nivel (str): clasificación del punto
    """
    # Recopilar todos los objetos detectados
    objetos = []
    for r in resultados:
        for box in r.boxes:
            nombre_en = modelo.names[int(box.cls[0])]
            confianza = float(box.conf[0])
            objetos.append((nombre_en, confianza))

    if not objetos:
        return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados"

    conteo = Counter([o[0] for o in objetos])
    # Mejor confianza por clase
    mejor_conf = {}
    for nombre, conf in objetos:
        if nombre not in mejor_conf or conf > mejor_conf[nombre]:
            mejor_conf[nombre] = conf

    tabla = []
    peso_total = 0.0
    residuos = 0
    conteo_materiales = Counter()

    for obj_en, cantidad in conteo.items():
        if obj_en in MATERIALES:
            nombre_es, material, peso_u, reciclable = MATERIALES[obj_en]
        else:
            # Objeto no mapeado — lo incluimos como desconocido
            nombre_es = obj_en.title()
            material  = "Desconocido"
            peso_u    = 0.10
            reciclable = False

        conf_pct = f"{mejor_conf.get(obj_en, 0) * 100:.0f}%"

        if reciclable:
            residuos += cantidad
            peso_obj  = round(peso_u * cantidad, 2)
            peso_total += peso_obj
            conteo_materiales[material] += cantidad
            tabla.append({
                "Objeto detectado":   nombre_es,
                "Material":           material,
                "Cant.":              cantidad,
                "Peso est. (kg)":     peso_obj,
                "Confianza IA":       conf_pct,
                "♻️ Reciclable":      "✅ Sí",
            })
        else:
            tabla.append({
                "Objeto detectado":   nombre_es,
                "Material":           "—",
                "Cant.":              cantidad,
                "Peso est. (kg)":     0,
                "Confianza IA":       conf_pct,
                "♻️ Reciclable":      "❌ No aplica",
            })

    tipo_predominante = conteo_materiales.most_common(1)[0][0] if conteo_materiales else "Mixto"

    # Clasificación basada en cantidad de reciclables
    nivel = (
        "🔴 Punto crítico confirmado" if residuos >= 10
        else "🟡 Posible punto crítico"  if residuos >= 5
        else "🟢 Residuo individual"
    )

    return tabla, residuos, round(peso_total, 2), tipo_predominante, nivel


def mostrar_metricas(residuos, peso_total, nivel):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div class="metric-card"><h3 style="color:#4ade80">{residuos}</h3>'
            f'<p style="margin:0">Objetos reciclables</p></div>',
            unsafe_allow_html=True
        )
    with c2:
        st.markdown(
            f'<div class="metric-card"><h3 style="color:#4ade80">{peso_total} kg</h3>'
            f'<p style="margin:0">Peso estimado</p></div>',
            unsafe_allow_html=True
        )
    with c3:
        st.markdown(
            f'<div class="metric-card"><h3>{nivel}</h3>'
            f'<p style="margin:0">Clasificación del punto</p></div>',
            unsafe_allow_html=True
        )


# ====================================================================
# 8. INICIO
# ====================================================================
if menu == "🏠 Inicio":
    st.title("♻️ EcoCom2 Circular IA")
    st.write("Sistema inteligente de gestión de residuos — **solo residentes de la Comuna 2 pueden publicar reportes.**")

    st.markdown("### 📡 Verificar mi ubicación")

    # ── Botón GPS automático ──────────────────────────────────────────
    boton_gps()

    # ── Entrada manual como respaldo ──────────────────────────────────
    with st.expander("🔧 ¿No funciona el botón? Ingresa las coordenadas manualmente"):
        st.markdown(
            "Busca tu ubicación en [Google Maps](https://maps.google.com), "
            "haz clic derecho sobre tu posición y copia las coordenadas."
        )
        col_lat, col_lon = st.columns(2)
        with col_lat:
            lat_manual = st.text_input("Latitud (ej: 6.2985592)", key="lat_manual_input")
        with col_lon:
            lon_manual = st.text_input("Longitud (ej: -75.5552519)", key="lon_manual_input")

        if st.button("✅ Validar coordenadas ingresadas", key="btn_manual_gps"):
            try:
                lm = float(lat_manual)
                lom = float(lon_manual)
                if -90 <= lm <= 90 and -180 <= lom <= 180:
                    st.session_state.gps_lat = lm
                    st.session_state.gps_lon = lom
                    st.session_state.gps_validado = True
                    from shapely.geometry import Point
                    st.session_state.fuera_de_rango = not POLIGONO_COMUNA2.contains(Point(lom, lm))
                    st.rerun()
                else:
                    st.error("❌ Coordenadas fuera de rango válido.")
            except ValueError:
                st.error("❌ Ingresa números válidos. Ejemplo: 6.2985592 y -75.5552519")

    # ── Estado GPS ────────────────────────────────────────────────────
    if st.session_state.gps_validado:
        lat_u = st.session_state.gps_lat
        lon_u = st.session_state.gps_lon
        if not st.session_state.fuera_de_rango:
            st.markdown(
                f'<div class="gps-ok">✅ Dentro de la Comuna 2 — '
                f'Lat: {lat_u:.6f} | Lon: {lon_u:.6f}<br>'
                f'Puedes analizar imágenes y enviar reportes al mapa.</div>',
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f'<div class="gps-error">🛑 Fuera de la Comuna 2 — '
                f'Lat: {lat_u:.6f} | Lon: {lon_u:.6f}<br>'
                f'Puedes analizar materiales con la IA, pero el envío de reportes está bloqueado.</div>',
                unsafe_allow_html=True
            )
    else:
        st.markdown(
            '<div class="gps-warn">⚠️ GPS no verificado — '
            'Presiona el botón o ingresa tus coordenadas manualmente.</div>',
            unsafe_allow_html=True
        )

    st.markdown("---")
    st.markdown("### 🗺️ Mapa de Congestión — Comuna 2 Santa Cruz, Medellín")

    barrio_filtro = st.selectbox("Filtrar por barrio:", ["Todos"] + BARRIOS_PILOTO)

    lat_c = st.session_state.gps_lat or LAT_CENTRO
    lon_c = st.session_state.gps_lon or LON_CENTRO

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=15, tiles="CartoDB dark_matter")

    # Polígono oficial de la Comuna 2
    coords_poly = [(lat, lon) for lon, lat in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_poly,
        color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        popup="Límite oficial Comuna 2 — Santa Cruz",
        tooltip="📍 Área piloto EcoCom2"
    ).add_to(mapa)

    # Pin del usuario
    if st.session_state.gps_validado:
        color_u = "blue" if not st.session_state.fuera_de_rango else "gray"
        estado_u = "Residente ✅" if not st.session_state.fuera_de_rango else "Externo 🛑"
        folium.Marker(
            location=[st.session_state.gps_lat, st.session_state.gps_lon],
            popup=(f"📍 Tu ubicación<br>{estado_u}<br>"
                   f"{st.session_state.gps_lat:.6f}, {st.session_state.gps_lon:.6f}"),
            tooltip="📍 Tú estás aquí",
            icon=folium.Icon(color=color_u, icon="user", prefix="fa")
        ).add_to(mapa)

    # Reportes registrados
    for rep in st.session_state.registro_reportes:
        if barrio_filtro != "Todos" and rep.get("Sector") != barrio_filtro:
            continue
        lat_r = rep.get("Lat", LAT_CENTRO)
        lon_r = rep.get("Lon", LON_CENTRO)
        niv   = rep.get("Clasificación", "🟢")
        color = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
        popup_html = (
            f"<div style='font-family:sans-serif;min-width:170px;'>"
            f"<b>{rep['Código']}</b><br>"
            f"📍 {rep['Sector']}<br>📌 {rep['Referencia']}<br>"
            f"♻️ {rep['Objetos']} obj | ⚖️ {rep['Peso (Kg)']} kg<br>"
            f"🏷️ {rep['Predominante']}<br>"
            f"<span style='color:{color}'>● {niv}</span></div>"
        )
        folium.CircleMarker(
            location=[lat_r, lon_r], radius=12,
            color=color, fill=True, fill_color=color, fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=220),
            tooltip=f"Reporte {rep['Código']}"
        ).add_to(mapa)

    st_folium(mapa, width=1100, height=480, returned_objects=[])

    st.markdown("---")
    st.markdown("### 📋 Historial de Reportes")
    if st.session_state.registro_reportes:
        df = pd.DataFrame(st.session_state.registro_reportes)
        cols = [c for c in ["Código","Sector","Referencia","Objetos",
                             "Peso (Kg)","Predominante","Clasificación","Lat","Lon"]
                if c in df.columns]
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
# 9. REPORTAR RESIDUO
# ====================================================================
elif menu == "📸 Reportar Residuo":
    st.header("📸 Reporte de Residuos con IA")

    es_residente = st.session_state.gps_validado and not st.session_state.fuera_de_rango

    # ── Banner de estado ──────────────────────────────────────────────
    if not st.session_state.gps_validado:
        st.markdown(
            '<div class="gps-warn">⚠️ GPS no verificado — '
            'Puedes analizar materiales, pero valida tu ubicación en <b>🏠 Inicio</b> para enviar reportes.</div>',
            unsafe_allow_html=True
        )
    elif st.session_state.fuera_de_rango:
        st.markdown(
            f'<div class="gps-error">🛑 Fuera de la Comuna 2 '
            f'({st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}) — '
            f'Puedes analizar materiales con la IA, pero <b>el envío al mapa está bloqueado</b>.</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div class="gps-ok">✅ Residente verificado — '
            f'{st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f} — '
            f'Puedes analizar y enviar reportes al mapa.</div>',
            unsafe_allow_html=True
        )

    st.markdown("")

    if st.session_state.reporte_enviado:
        st.success("🎉 ¡Reporte enviado y publicado en el mapa comunitario con tus coordenadas GPS!")
        if st.button("🔄 Hacer otro reporte", type="primary", use_container_width=True):
            st.session_state.reporte_enviado = False
            st.session_state.cache_reporte   = None
            st.rerun()
    else:
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            barrio = st.selectbox("Barrio:", BARRIOS_PILOTO)
        with col_f2:
            referencia = st.text_input("Referencia exacta del lugar (calle, carrera, punto de referencia)")

        imagen = st.file_uploader("📷 Fotografía del residuo:", type=["jpg","jpeg","png"])

        if imagen is not None:
            img = Image.open(imagen)

            if st.button("🔍 Analizar imagen con IA", use_container_width=True, type="primary"):
                with st.spinner("Analizando con YOLOv8 (confianza ≥ 8%)…"):
                    resultados = analizar_imagen(img, confianza=0.08)

                # ── Comparación lado a lado ───────────────────────────
                st.markdown("### 🔬 Original vs Detecciones IA")
                col_o, col_d = st.columns(2)
                with col_o:
                    st.markdown("**📷 Imagen original**")
                    st.image(img, use_container_width=True)
                with col_d:
                    st.markdown("**🤖 Objetos detectados por la IA**")
                    st.image(resultados[0].plot(), caption="Detecciones YOLOv8", use_container_width=True)

                # ── Tabla de materiales en ESPAÑOL ────────────────────
                tabla, residuos, peso_total, tipo_predominante, nivel = procesar_detecciones(resultados)

                st.markdown("### 📊 Materiales Detectados")
                if tabla:
                    df_tabla = pd.DataFrame(tabla)
                    # Separar reciclables de no reciclables para mejor lectura
                    df_si  = df_tabla[df_tabla["♻️ Reciclable"] == "✅ Sí"]
                    df_no  = df_tabla[df_tabla["♻️ Reciclable"] == "❌ No aplica"]
                    if not df_si.empty:
                        st.markdown("**♻️ Objetos reciclables:**")
                        st.dataframe(df_si, use_container_width=True, hide_index=True)
                    if not df_no.empty:
                        st.markdown("**⚠️ Objetos no aprovechables:**")
                        st.dataframe(df_no, use_container_width=True, hide_index=True)
                else:
                    st.warning("⚠️ No se detectaron objetos reconocibles en la imagen.")

                # ── Métricas ──────────────────────────────────────────
                if residuos > 0 or peso_total > 0:
                    st.markdown("")
                    mostrar_metricas(residuos, peso_total, nivel)

                # ── Preparar reporte (solo si es residente) ───────────
                if es_residente and residuos > 0:
                    st.session_state.cache_reporte = {
                        "Código":       f"REP-{len(st.session_state.registro_reportes)+200}",
                        "Sector":       barrio,
                        "Referencia":   referencia or "Sin referencia",
                        "Objetos":      residuos,
                        "Peso (Kg)":    peso_total,
                        "Predominante": tipo_predominante,
                        "Clasificación":nivel,
                        "Lat":          st.session_state.gps_lat,
                        "Lon":          st.session_state.gps_lon,
                    }
                elif not es_residente:
                    st.markdown("---")
                    st.markdown(
                        '<div class="gps-error" style="text-align:center;padding:16px;">'
                        '🛑 <b>Análisis completado.</b><br>'
                        'Para enviar este reporte al mapa debes estar dentro de la <b>Comuna 2</b> '
                        'con GPS verificado. Ve a <b>🏠 Inicio</b> y valida tu ubicación.'
                        '</div>',
                        unsafe_allow_html=True
                    )

        # ── Confirmación y envío ──────────────────────────────────────
        if st.session_state.cache_reporte and es_residente:
            rep = st.session_state.cache_reporte
            st.markdown("---")
            st.markdown("### ✅ Confirmar y publicar reporte")
            st.markdown(f"""
| Campo | Valor |
|---|---|
| **Sector** | {rep['Sector']} |
| **Referencia** | {rep['Referencia']} |
| **Objetos reciclables** | {rep['Objetos']} |
| **Peso estimado** | {rep['Peso (Kg)']} kg |
| **Clasificación** | {rep['Clasificación']} |
| **Material predominante** | {rep['Predominante']} |
| **📍 Coordenadas GPS** | {rep['Lat']:.6f}, {rep['Lon']:.6f} |
""")
            if st.button("🚀 PUBLICAR REPORTE EN EL MAPA", type="primary", use_container_width=True):
                st.session_state.registro_reportes.append(rep)
                st.session_state.cache_reporte   = None
                st.session_state.reporte_enviado = True
                st.rerun()


# ====================================================================
# 10. PUNTO CRÍTICO
# ====================================================================
elif menu == "🚨 Punto Crítico":
    st.header("🚨 Registrar Punto Crítico")

    es_residente = st.session_state.gps_validado and not st.session_state.fuera_de_rango

    if not st.session_state.gps_validado:
        st.markdown('<div class="gps-warn">⚠️ Valida tu GPS desde <b>🏠 Inicio</b> primero.</div>', unsafe_allow_html=True)
        boton_gps()
        st.stop()

    if not es_residente:
        st.markdown(
            f'<div class="gps-error">🛑 Fuera de la Comuna 2 '
            f'({st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}) — '
            f'No puedes registrar puntos críticos.</div>',
            unsafe_allow_html=True
        )
        st.stop()

    st.markdown(
        f'<div class="gps-ok">✅ Residente verificado — '
        f'{st.session_state.gps_lat:.5f}, {st.session_state.gps_lon:.5f}</div>',
        unsafe_allow_html=True
    )
    st.markdown("")

    col_a, col_b = st.columns(2)
    with col_a:
        barrio = st.selectbox("Barrio:", BARRIOS_PILOTO, key="barrio_critico")
    with col_b:
        referencia = st.text_input("Referencia exacta:", key="ref_critico")

    imagen = st.file_uploader("📷 Foto del punto crítico:", type=["jpg","jpeg","png"], key="img_critico")

    if imagen is not None:
        img = Image.open(imagen)
        if st.button("🔍 Evaluar con IA", type="primary", use_container_width=True):
            with st.spinner("Analizando…"):
                resultados = analizar_imagen(img, confianza=0.08)

            st.markdown("### 🔬 Original vs Detecciones")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**📷 Original**")
                st.image(img, use_container_width=True)
            with c2:
                st.markdown("**🤖 Detecciones**")
                st.image(resultados[0].plot(), use_container_width=True)

            tabla, residuos, peso_total, tipo_predominante, _ = procesar_detecciones(resultados)
            total_det = sum(len(r.boxes) for r in resultados)

            nivel = (
                "🔴 Punto crítico alto"  if total_det >= 8
                else "🟡 Punto crítico medio" if total_det >= 4
                else "🟢 Punto crítico bajo"
            )

            if tabla:
                df_t = pd.DataFrame(tabla)
                df_si = df_t[df_t["♻️ Reciclable"] == "✅ Sí"]
                if not df_si.empty:
                    st.dataframe(df_si, use_container_width=True, hide_index=True)

            mostrar_metricas(residuos, peso_total, nivel)
            st.markdown(f"📍 Se registrará en: `{st.session_state.gps_lat:.6f}, {st.session_state.gps_lon:.6f}`")

            if st.button("🚨 REGISTRAR ALERTA EN EL MAPA", type="primary", use_container_width=True):
                st.session_state.registro_reportes.append({
                    "Código":       f"CRIT-{len(st.session_state.registro_reportes)+500}",
                    "Sector":       barrio,
                    "Referencia":   referencia or "Punto crítico",
                    "Objetos":      total_det,
                    "Peso (Kg)":    round(total_det * 0.4, 2),
                    "Predominante": tipo_predominante or "Mixto",
                    "Clasificación":nivel,
                    "Lat":          st.session_state.gps_lat,
                    "Lon":          st.session_state.gps_lon,
                })
                st.success("✅ ¡Alerta registrada en el mapa!")


# ====================================================================
# 11. INFORMACIÓN
# ====================================================================
elif menu == "ℹ️ Información":
    st.header("ℹ️ ¿Qué es EcoCom2 Circular IA?")
    st.markdown("""
**EcoCom2 Circular IA** es una plataforma de gestión inteligente de residuos sólidos
para la **Comuna 2 — Santa Cruz, Medellín**.

### 🔐 Validación Territorial GPS
- Solo residentes **dentro del polígono oficial** de la Comuna 2 pueden enviar reportes.
- La validación usa **GPS satelital** en tiempo real (sin depender del nombre del barrio).
- Observadores externos pueden **analizar materiales** con la IA pero no publicar reportes.

### 🤖 Inteligencia Artificial — YOLOv8
- Detecta objetos con confianza desde **8%** para capturar más objetos en imágenes de basura.
- Muestra resultados **en español** separados por reciclables y no aprovechables.
- Estima peso por objeto y clasificación del punto.
- Comparación visual: imagen original vs detecciones lado a lado.

### 🗺️ Mapa Comunitario
- Polígono oficial de la Comuna 2 basado en límites reales:
  norte = Quebrada Negra (Bello) · oeste = Río Medellín · sur = Quebrada La Rosa · oriente = ladera Com. 1
- Cada reporte se pinta en las **coordenadas GPS exactas** del lugar.

### 📍 Los 11 barrios de la Comuna 2
""")
    for b in BARRIOS_PILOTO:
        st.write(f"- 📍 **{b}**")
    st.markdown("""
---
**Versión:** 3.2 | **Proyecto:** Territorio INN 2026 | **Institución:** ITM Medellín
**Desarrollador:** Brandon Duque
""")
