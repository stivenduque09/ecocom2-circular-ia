import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium
from streamlit_folium import st_folium
import pandas as pd
from shapely.geometry import Point, Polygon
import json, os

# ====================================================================
# PERSISTENCIA
# ====================================================================
REPORTES_FILE = "/tmp/ecocom2_reportes.json"

def cargar_reportes_disco():
    if os.path.exists(REPORTES_FILE):
        try:
            with open(REPORTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_reportes_disco(reportes):
    try:
        with open(REPORTES_FILE, "w", encoding="utf-8") as f:
            json.dump(reportes, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ====================================================================
# 1. CONFIGURACIÓN
# ====================================================================
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon="♻️", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #0f1f17; color: #e8f5e9; }
    .block-container { padding-top: 1rem; max-width: 1200px; }
    h1, h2, h3 { color: #4ade80 !important; }
    header { visibility: hidden; }
    .badge-ok  { background:rgba(16,185,129,0.15); border:1px solid #4ade80;
                 border-radius:8px; padding:10px 14px; color:#4ade80; font-weight:bold; }
    .badge-warn{ background:rgba(251,191,36,0.12); border:1px solid #fbbf24;
                 border-radius:8px; padding:10px 14px; color:#fbbf24; font-weight:bold; }
    .badge-err { background:rgba(239,68,68,0.12); border:1px solid #ef4444;
                 border-radius:8px; padding:10px 14px; color:#ef4444; font-weight:bold; }
    .metric-card { background:rgba(16,185,129,0.08); border:1px solid rgba(74,222,128,0.3);
                   border-radius:10px; padding:14px; text-align:center; }
    /* Botones de navegación tipo pestaña */
    .nav-btn button { border-radius:6px !important; font-weight:bold !important; font-size:13px !important; }
    div[data-testid="stButton"] button[kind="primary"] {
        background:linear-gradient(135deg,#10b981,#059669);
        border:none; font-weight:bold; }
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO COMUNA 2 — SANTA CRUZ, MEDELLÍN
#    Desde Estación Acevedo (sur) → Andalucía → Comuneros → Santa Cruz
#    → Villa del Socorro (norte). Límite oeste = Autopista Norte.
# ====================================================================
# ============================================================
# Polígono COMUNA 2 — SANTA CRUZ, Medellín
# Verificado con límites reales (Decreto 346/2000 + OSM)
#
# Referencias:
#  Acevedo metro      lat=6.2976  lon=-75.5686  (vértice SW)
#  Andalucía cable    lat=6.3097  lon=-75.5598  (punto medio)
#  Santo Domingo      lat=6.3187  lon=-75.5490  (punto NE)
#  Norte: Quebrada Negra/Seca → límite Bello (lat≈6.318)
#  Oeste: Río Medellín        → lon ≈ -75.568
#  Sur:   Quebrada La Rosa    → lat ≈ 6.296
#  Este:  Ladera Popular      → lon ≈ -75.549
# ============================================================
POLIGONO_COMUNA2 = Polygon([
    # SW — Acevedo, junto al Río Medellín (punto de inicio sur)
    (-75.5690, 6.2965),
    # Oeste — Río Medellín subiendo al norte
    (-75.5685, 6.3010),
    (-75.5678, 6.3060),
    (-75.5670, 6.3110),
    # NW — Quebrada Negra, límite con Bello
    (-75.5655, 6.3155),
    (-75.5615, 6.3178),
    (-75.5575, 6.3182),
    # NE — ladera alta, Bello / Popular (Santo Domingo)
    (-75.5535, 6.3168),
    (-75.5500, 6.3135),   # Metrocable Santo Domingo
    # Este — ladera bajando (límite con Popular)
    (-75.5485, 6.3080),
    (-75.5480, 6.3020),
    (-75.5492, 6.2975),
    # SE — Quebrada La Rosa, límite con Aranjuez
    (-75.5525, 6.2955),
    (-75.5570, 6.2950),
    # Sur — cerrando hacia Acevedo
    (-75.5630, 6.2952),
    (-75.5670, 6.2958),
    (-75.5690, 6.2965),   # cierre
])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

# Centro de la Comuna 2
LAT_C = 6.3070
LON_C = -75.5515

# ====================================================================
# 3. SESIÓN
# ====================================================================
for k, v in {
    "lat": None, "lon": None, "validado": False, "fuera": True,
    "direccion": "", "reporte_ok": False, "cache": None,
    "seccion": "info",   # "info" | "residuo" | "critico" | "historial"
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()

# ====================================================================
# 4. MODELO YOLO — conf 0.05 para detectar más objetos en basura real
# ====================================================================
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")
modelo = cargar_modelo()

# ====================================================================
# 5. MATERIALES — incluye bolsas de basura y más residuos reales
# ====================================================================
MAT = {
    # ── Plástico ──────────────────────────────────────────────────────
    "bottle":         ("Botella plástica",         "Plástico",    0.05, True),
    "cup":            ("Vaso / Recipiente plástico","Plástico",    0.03, True),
    "chair":          ("Silla plástica",            "Plástico",    2.00, True),
    "bench":          ("Banco plástico",            "Plástico",    2.50, True),
    "bucket":         ("Balde plástico",            "Plástico",    0.50, True),
    "bowl":           ("Recipiente plástico",       "Plástico",    0.15, True),
    "toy":            ("Juguete plástico",          "Plástico",    0.50, True),
    "frisbee":        ("Disco plástico",            "Plástico",    0.10, True),
    # Bolsas de basura — YOLO las detecta como handbag/backpack en baja confianza
    "handbag":        ("Bolsa de basura / Bolso",   "Plástico",    0.40, True),
    "backpack":       ("Bolsa / Mochila",           "Textil",      0.50, True),
    "suitcase":       ("Bolsa grande / Maleta",     "Textil",      1.00, True),
    # ── Papel / Cartón ────────────────────────────────────────────────
    "book":           ("Libro / Cuaderno",          "Papel",       0.30, True),
    "newspaper":      ("Periódico / Papel",         "Papel",       0.10, True),
    "box":            ("Caja de cartón",            "Cartón",      0.30, True),
    # ── Vidrio ────────────────────────────────────────────────────────
    "wine glass":     ("Botella / Copa de vidrio",  "Vidrio",      0.20, True),
    "vase":           ("Frasco / Jarrón de vidrio", "Vidrio",      0.80, True),
    # ── Aluminio / Metal ──────────────────────────────────────────────
    "can":            ("Lata de aluminio",          "Aluminio",    0.02, True),
    "knife":          ("Cuchillo / Utensilio metal","Metal",       0.10, True),
    "fork":           ("Tenedor / Utensilio metal", "Metal",       0.05, True),
    "spoon":          ("Cuchara / Utensilio metal", "Metal",       0.05, True),
    "scissors":       ("Tijeras",                   "Metal",       0.10, True),
    # ── Electrónico ───────────────────────────────────────────────────
    "cell phone":     ("Celular",                   "Electrónico", 0.20, True),
    "laptop":         ("Portátil",                  "Electrónico", 2.50, True),
    "keyboard":       ("Teclado",                   "Electrónico", 0.60, True),
    "mouse":          ("Ratón de computador",       "Electrónico", 0.10, True),
    "remote":         ("Control remoto",            "Electrónico", 0.20, True),
    "tv":             ("Televisor",                 "Electrónico", 8.00, True),
    "clock":          ("Reloj",                     "Electrónico", 0.30, True),
    # ── Orgánico ──────────────────────────────────────────────────────
    "banana":         ("Banano",                    "Orgánico",    0.10, True),
    "apple":          ("Manzana",                   "Orgánico",    0.15, True),
    "orange":         ("Naranja",                   "Orgánico",    0.20, True),
    "broccoli":       ("Brócoli",                   "Orgánico",    0.25, True),
    "carrot":         ("Zanahoria",                 "Orgánico",    0.10, True),
    "potted plant":   ("Planta / Matero",           "Orgánico",    1.00, True),
    "pizza":          ("Residuo de comida",         "Orgánico",    0.30, True),
    "sandwich":       ("Residuo de comida",         "Orgánico",    0.20, True),
    "hot dog":        ("Residuo de comida",         "Orgánico",    0.15, True),
    "cake":           ("Residuo de comida",         "Orgánico",    0.20, True),
    "donut":          ("Residuo de comida",         "Orgánico",    0.10, True),
    # ── Madera / Mixto ────────────────────────────────────────────────
    "dining table":   ("Mesa / Madera",             "Madera",     12.00, True),
    "couch":          ("Sofá / Mueble",             "Mixto",      15.00, True),
    "bed":            ("Cama / Colchón",            "Mixto",      20.00, True),
    "umbrella":       ("Paraguas",                  "Mixto",       0.50, True),
    "tie":            ("Corbata / Textil",          "Textil",      0.10, True),
    # ── No aplica / No reciclable ──────────────────────────────────────
    "person":         ("Persona",     "—", 0, False),
    "dog":            ("Perro",       "—", 0, False),
    "cat":            ("Gato",        "—", 0, False),
    "car":            ("Vehículo",    "—", 0, False),
    "bus":            ("Bus",         "—", 0, False),
    "truck":          ("Camión",      "—", 0, False),
    "bicycle":        ("Bicicleta",   "—", 0, False),
    "motorcycle":     ("Moto",        "—", 0, False),
    "traffic light":  ("Semáforo",    "—", 0, False),
    "stop sign":      ("Señal tráfico","—",0, False),
    "bird":           ("Ave",         "—", 0, False),
    "toothbrush":     ("Cepillo dental","—",0, False),
}

# ====================================================================
# 6. HELPERS
# ====================================================================
@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar(direccion: str):
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4", timeout=8)
        r = geo.geocode(f"{direccion}, Medellín, Antioquia, Colombia")
        if r:
            return r.latitude, r.longitude, r.address
    except Exception:
        pass
    return None, None, None


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar_inversa(lat: float, lon: float) -> str:
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4_rev", timeout=6)
        r = geo.reverse(f"{lat}, {lon}", language="es")
        if r and r.raw.get("address"):
            a = r.raw["address"]
            partes = []
            calle  = a.get("road") or a.get("pedestrian") or a.get("path") or ""
            num    = a.get("house_number", "")
            barrio = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
            if calle:
                partes.append(calle + (f" #{num}" if num else ""))
            if barrio:
                partes.append(barrio)
            partes.append("Medellín")
            return ", ".join(partes) if partes else r.address
        return f"{lat:.5f}, {lon:.5f}"
    except Exception:
        return f"{lat:.5f}, {lon:.5f}"


def es_residente():
    return st.session_state.validado and not st.session_state.fuera


def set_ubicacion(lat, lon, direccion=""):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.validado = True
    st.session_state.fuera = not POLIGONO_COMUNA2.contains(Point(lon, lat))
    st.session_state.direccion = direccion


def analizar(img):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
        img.save(tmp.name)
        # conf=0.05 detecta más objetos en imágenes de basura real
        return modelo(tmp.name, conf=0.05)


def procesar(resultados):
    """
    Clasifica la escena según ratio de reciclables:
    🟢 Verde      ≥60% reciclables  → alta valorización
    🟡 Amarillo   30-60% mixto      → mezcla
    🔴 Rojo       <30% reciclables  → acumulación sin valor (como la foto de basura)
    """
    objetos = []
    for r in resultados:
        for box in r.boxes:
            objetos.append((modelo.names[int(box.cls[0])], float(box.conf[0])))

    if not objetos:
        return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados"

    conteo = Counter(o[0] for o in objetos)
    mejor  = {n: max(c for nn, c in objetos if nn == n) for n in conteo}

    tabla, peso_total, residuos, no_rec = [], 0.0, 0, 0
    cnt_mat = Counter()

    for obj, cant in conteo.items():
        nom, mat, peso_u, recicl = MAT.get(obj, (obj.replace("_"," ").title(), "Desconocido", 0.1, False))
        conf = f"{mejor[obj]*100:.0f}%"
        if recicl:
            residuos += cant
            p = round(peso_u * cant, 2)
            peso_total += p
            cnt_mat[mat] += cant
            tabla.append({"Objeto": nom, "Material": mat,
                          "Cant.": cant, "Peso (kg)": p,
                          "Confianza": conf, "♻️": "✅ Sí"})
        else:
            no_rec += cant
            tabla.append({"Objeto": nom, "Material": "—",
                          "Cant.": cant, "Peso (kg)": 0,
                          "Confianza": conf, "♻️": "❌ No"})

    tipo  = cnt_mat.most_common(1)[0][0] if cnt_mat else "Mixto"
    total = residuos + no_rec
    ratio = residuos / total if total > 0 else 0

    if total <= 2:
        nivel = "🟢 Residuo puntual"
    elif ratio >= 0.60:
        nivel = "🟢 Punto verde — Alta valorización reciclable"
    elif ratio >= 0.30:
        nivel = "🟡 Punto amarillo — Residuos mixtos"
    else:
        nivel = "🔴 Punto crítico — Acumulación sin valorización"

    return tabla, residuos, round(peso_total, 2), tipo, nivel


def badge(txt, tipo="ok"):
    cls = {"ok":"badge-ok","warn":"badge-warn","err":"badge-err"}[tipo]
    st.markdown(f'<div class="{cls}">{txt}</div><br>', unsafe_allow_html=True)


def metricas(residuos, peso, nivel):
    c1, c2, c3 = st.columns(3)
    color = "#4ade80" if "🟢" in nivel else ("#fbbf24" if "🟡" in nivel else "#f87171")
    with c1:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color}">{residuos}</h3>'
                    f'<p style="margin:0;font-size:12px">Reciclables</p></div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color}">{peso} kg</h3>'
                    f'<p style="margin:0;font-size:12px">Peso estimado</p></div>',
                    unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color};font-size:14px">'
                    f'{nivel}</h3><p style="margin:0;font-size:12px">Clasificación</p></div>',
                    unsafe_allow_html=True)


def nav_tabs(seccion_actual):
    """Barra de navegación como pestañas usando botones — funciona en celular."""
    SECCIONES = [
        ("info",      "📍 Info del punto"),
        ("residuo",   "📸 Reportar Residuo"),
        ("critico",   "🚨 Punto Crítico"),
        ("historial", "📋 Historial"),
    ]
    cols = st.columns(len(SECCIONES))
    for col, (key, label) in zip(cols, SECCIONES):
        with col:
            # Botón resaltado si es la sección activa
            es_activa = seccion_actual == key
            btn_type = "primary" if es_activa else "secondary"
            if st.button(label, key=f"nav_{key}",
                         use_container_width=True, type=btn_type):
                st.session_state.seccion = key
                st.rerun()


# ====================================================================
# 7. BARRA LATERAL
# ====================================================================
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## ♻️ EcoCom2")

if st.session_state.validado:
    if not st.session_state.fuera:
        st.sidebar.markdown(
            f'<div class="badge-ok" style="font-size:12px;">✅ Dentro de la Comuna 2<br>'
            f'<span style="font-weight:normal">{st.session_state.direccion[:55]}</span></div>',
            unsafe_allow_html=True)
    else:
        st.sidebar.markdown(
            '<div class="badge-err" style="font-size:12px;">🛑 Fuera de la Comuna 2<br>'
            '<span style="font-weight:normal">Solo lectura del mapa</span></div>',
            unsafe_allow_html=True)
else:
    st.sidebar.markdown(
        '<div class="badge-warn" style="font-size:12px;">⚠️ Sin verificar<br>'
        '<span style="font-weight:normal">Ingresa tu dirección abajo</span></div>',
        unsafe_allow_html=True)

st.sidebar.markdown("---")
menu = st.sidebar.radio("Menú", ["🏠 Inicio y Mapa", "ℹ️ Información"])
st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="font-size:11px;color:#6b7280;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#4ade80">EcoCom2 v4.1</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>""", unsafe_allow_html=True)


# ====================================================================
# 8. INICIO Y MAPA
# ====================================================================
if menu == "🏠 Inicio y Mapa":
    st.title("♻️ EcoCom2 Circular IA")
    st.caption("Gestión inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    # ── CAMPO DE DIRECCIÓN (se auto-rellena al hacer clic en el mapa) ─
    dir_auto = st.session_state.get("click_dir") or st.session_state.get("direccion") or ""

    c_inp, c_btn = st.columns([5, 1])
    with c_inp:
        dir_inp = st.text_input(
            "📍 Dirección:",
            value=dir_auto,
            placeholder="Toca el mapa o escribe tu dirección en la Comuna 2...",
            label_visibility="collapsed",
            key="dir_campo",
        )
    with c_btn:
        if st.button("🔍 Verificar", type="primary", use_container_width=True):
            if dir_inp.strip():
                with st.spinner("Buscando..."):
                    lat, lon, addr = geocodificar(dir_inp.strip())
                if lat:
                    set_ubicacion(lat, lon, addr)
                    st.rerun()
                else:
                    st.error("❌ No encontré esa dirección. Intenta: Cra 50 #107-62, Andalucía")
            else:
                st.warning("Escribe o toca el mapa para obtener una dirección.")

    # Badge de estado
    if st.session_state.validado:
        if not st.session_state.fuera:
            badge(f"✅ <b>Dentro de la Comuna 2</b> — {st.session_state.direccion[:80]}", "ok")
        else:
            badge(f"🛑 Fuera de la Comuna 2 — {st.session_state.direccion[:70]}<br>"
                  f"<span style='font-weight:normal;font-size:12px'>"
                  f"Puedes usar el analizador de materiales, pero no publicar reportes.</span>", "err")
        if st.button("🔄 Cambiar dirección", key="cambiar_dir"):
            for k in ["validado","lat","lon","fuera","direccion",
                      "click_lat","click_lon","click_dir",
                      "punto_lat","punto_lon","cache"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")
    st.markdown("### 🗺️ Toca el punto exacto del residuo en el mapa")
    st.caption("Al tocar, la dirección aparece automáticamente arriba y puedes reportar directo.")

    lat_c = st.session_state.get("lat") or LAT_C
    lon_c = st.session_state.get("lon") or LON_C

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=15, tiles="CartoDB dark_matter")

    # Polígono oficial
    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_p, color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        tooltip="📍 Área piloto — Comuna 2 Santa Cruz (Acevedo → Villa del Socorro)"
    ).add_to(mapa)

    # Pin hogar
    if st.session_state.get("validado") and st.session_state.get("lat"):
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker(
            location=[st.session_state.lat, st.session_state.lon],
            popup=f"🏠 {st.session_state.direccion}",
            tooltip="🏠 Tu dirección verificada",
            icon=folium.Icon(color=col_pin, icon="home", prefix="fa")
        ).add_to(mapa)

    # Pin punto seleccionado
    if st.session_state.get("click_lat"):
        folium.Marker(
            location=[st.session_state.click_lat, st.session_state.click_lon],
            popup=f"📌 {st.session_state.get('click_dir','Punto seleccionado')}",
            tooltip="📌 Punto seleccionado",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(mapa)

    # Reportes guardados
    for rep in st.session_state.reportes:
        niv = rep.get("Clasificación", "🟢")
        col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
        folium.CircleMarker(
            location=[rep["Lat"], rep["Lon"]], radius=12,
            color=col, fill=True, fill_color=col, fill_opacity=0.85,
            popup=folium.Popup(
                f"<b>{rep['Código']}</b><br>📍 {rep['Sector']}<br>"
                f"📌 {rep['Referencia']}<br>♻️ {rep['Objetos']} obj "
                f"| ⚖️ {rep['Peso (Kg)']} kg<br><b>{niv}</b>",
                max_width=210),
            tooltip=f"{rep['Código']} — {niv}"
        ).add_to(mapa)

    mapa_data = st_folium(mapa, width="100%", height=440,
                          returned_objects=["last_clicked"])

    # ── Click en el mapa → dirección automática en el campo de arriba ─
    if mapa_data and mapa_data.get("last_clicked"):
        clk = mapa_data["last_clicked"]
        lat_clk = round(clk["lat"], 7)
        lon_clk = round(clk["lng"], 7)
        if (lat_clk != st.session_state.get("click_lat") or
                lon_clk != st.session_state.get("click_lon")):
            st.session_state.click_lat = lat_clk
            st.session_state.click_lon = lon_clk
            with st.spinner("📍 Detectando dirección..."):
                dir_obtenida = geocodificar_inversa(lat_clk, lon_clk)
            st.session_state.click_dir = dir_obtenida
            # Si aún no estaba verificado, validar automáticamente
            if not st.session_state.get("validado"):
                set_ubicacion(lat_clk, lon_clk, dir_obtenida)
            st.rerun()  # ← recarga y el campo de dirección muestra la nueva

    # ====================================================================
    # PANEL DE ACCIÓN — aparece cuando hay punto seleccionado
    # ====================================================================
    clat       = st.session_state.get("click_lat")
    clon       = st.session_state.get("click_lon")
    cdir       = st.session_state.get("click_dir", "")
    dentro_clk = POLIGONO_COMUNA2.contains(Point(clon, clat)) if clat else False

    if clat:
        st.markdown("")
        # Tarjeta de dirección del punto
        color_card = "#4ade80" if dentro_clk else "#ef4444"
        estado_txt = "✅ Dentro de la Comuna 2" if dentro_clk else "🛑 Fuera del área piloto"
        st.markdown(
            f'<div style="background:rgba(16,185,129,0.08);border:1px solid {color_card};'
            f'border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
            f'<span style="color:{color_card};font-weight:bold;font-size:14px;">📌 {cdir}</span><br>'
            f'<span style="color:#9ca3af;font-size:12px;">{estado_txt} · {clat:.5f}, {clon:.5f}</span>'
            f'</div>',
            unsafe_allow_html=True)

        # ── BOTONES DE ACCIÓN RÁPIDA ──────────────────────────────────
        # Llevan directamente a la pestaña correspondiente (abajo del mapa)
        if dentro_clk and es_residente():
            ba1, ba2, ba3 = st.columns(3)
            with ba1:
                if st.button("📸 Reportar Residuo",
                             type="primary", use_container_width=True, key="btn_rep"):
                    st.session_state.seccion = "residuo"
                    st.session_state.scroll_to_form = True
                    st.rerun()   # ← recarga y la pestaña "📸 Reportar Residuo" queda activa
            with ba2:
                if st.button("🚨 Punto Crítico",
                             use_container_width=True, key="btn_crit"):
                    st.session_state.seccion = "critico"
                    st.session_state.scroll_to_form = True
                    st.rerun()
            with ba3:
                if st.button("🗑️ Quitar punto", use_container_width=True, key="btn_quit"):
                    for k in ["click_lat","click_lon","click_dir","cache","seccion",
                               "scroll_to_form"]:
                        st.session_state.pop(k, None)
                    st.rerun()
        elif not es_residente():
            badge("⚠️ Verifica tu dirección arriba para poder reportar en este punto.", "warn")

    st.markdown("")

    # ── Ancla para scroll automático al formulario ────────────────────
    st.markdown('<div id="formulario-ancla"></div>', unsafe_allow_html=True)

    # Si el usuario viene de los botones de acción → bajar la pantalla
    if st.session_state.pop("scroll_to_form", False):
        import streamlit.components.v1 as _comp
        _comp.html("""<script>
            setTimeout(function(){
                var el = window.parent.document.getElementById('formulario-ancla');
                if(el){ el.scrollIntoView({behavior:'smooth', block:'start'}); }
                else {
                    window.parent.scrollTo({top: document.body.scrollHeight, behavior:'smooth'});
                }
            }, 400);
        </script>""", height=0)

    # ====================================================================
    # PESTAÑAS DE NAVEGACIÓN — visibles en celular y computador
    # ====================================================================
    seccion = st.session_state.get("seccion", "info")
    nav_tabs(seccion)
    st.markdown("")

    # ── SECCIÓN: Info del punto ────────────────────────────────────────
    if seccion == "info":
        if not clat:
            st.info("👆 Toca cualquier punto del mapa para ver la dirección y las opciones de reporte.")
        else:
            badge(f"📌 <b>{cdir}</b><br>"
                  f"<span style='font-weight:normal;font-size:13px'>"
                  f"{'✅ Dentro de la Comuna 2' if dentro_clk else '🛑 Fuera del área piloto'} — "
                  f"{clat:.6f}, {clon:.6f}</span>",
                  "ok" if dentro_clk else "err")
            if dentro_clk and es_residente():
                st.markdown("👇 Usa los botones de arriba o las pestañas **📸 Reportar Residuo** o **🚨 Punto Crítico**.")

    # ── SECCIÓN: Reportar Residuo ──────────────────────────────────────
    elif seccion == "residuo":
        st.markdown("### 📸 Reportar Residuo")

        if not es_residente():
            badge("⚠️ Verifica tu dirección para reportar.", "warn")
        elif not clat or not dentro_clk:
            badge("⚠️ Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"📌 {pdir}", "ok")

            r1, r2 = st.columns(2)
            with r1:
                r_barrio = st.selectbox("Barrio:", BARRIOS, key="r_barrio")
            with r2:
                r_ref = st.text_input("Referencia (edita si quieres):",
                                      value=pdir, key="r_ref")

            r_img = st.file_uploader("📷 Foto del residuo:",
                                     type=["jpg","jpeg","png"], key="r_img")
            if r_img:
                img = Image.open(r_img)
                if st.button("🔍 Analizar con IA", type="primary",
                             use_container_width=True, key="r_analizar"):
                    with st.spinner("Analizando imagen (conf ≥ 5%)..."):
                        res = analizar(img)
                    co, cd = st.columns(2)
                    with co:
                        st.markdown("**📷 Original**")
                        st.image(img, use_container_width=True)
                    with cd:
                        st.markdown("**🤖 Detecciones IA**")
                        st.image(res[0].plot(), use_container_width=True)

                    tabla, residuos, peso, tipo, nivel = procesar(res)
                    if tabla:
                        df_t = pd.DataFrame(tabla)
                        df_si = df_t[df_t["♻️"] == "✅ Sí"]
                        df_no = df_t[df_t["♻️"] == "❌ No"]
                        if not df_si.empty:
                            st.markdown("**♻️ Reciclables:**")
                            st.dataframe(df_si, use_container_width=True, hide_index=True)
                        if not df_no.empty:
                            st.markdown("**⚠️ No aprovechables:**")
                            st.dataframe(df_no, use_container_width=True, hide_index=True)
                    metricas(residuos, peso, nivel)
                    st.session_state.cache = {
                        "Código":        f"REP-{len(st.session_state.reportes)+200}",
                        "Sector":        r_barrio,
                        "Referencia":    r_ref,
                        "Objetos":       residuos,
                        "Peso (Kg)":     peso,
                        "Predominante":  tipo,
                        "Clasificación": nivel,
                        "Lat": plat, "Lon": plon,
                    }

            if st.session_state.get("cache"):
                r = st.session_state.cache
                st.markdown(f"**Listo:** {r['Clasificación']} · {r['Objetos']} reciclables · {r['Peso (Kg)']} kg")
                cp, cc = st.columns(2)
                with cp:
                    if st.button("🚀 PUBLICAR EN EL MAPA", type="primary",
                                 use_container_width=True, key="r_publicar"):
                        st.session_state.reportes.append(r)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache = None
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir"]:
                            st.session_state.pop(k, None)
                        st.success("✅ ¡Publicado! Guardado permanentemente en el mapa.")
                        st.rerun()
                with cc:
                    if st.button("❌ Cancelar", use_container_width=True, key="r_cancelar"):
                        st.session_state.cache = None
                        st.rerun()

    # ── SECCIÓN: Punto Crítico ─────────────────────────────────────────
    elif seccion == "critico":
        st.markdown("### 🚨 Registrar Punto Crítico")

        if not es_residente():
            badge("⚠️ Verifica tu dirección para registrar alertas.", "warn")
        elif not clat or not dentro_clk:
            badge("⚠️ Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"🚨 {pdir}", "err")

            cr1, cr2 = st.columns(2)
            with cr1:
                cr_barrio = st.selectbox("Barrio:", BARRIOS, key="cr_barrio")
            with cr2:
                cr_ref = st.text_input("Referencia:", value=pdir, key="cr_ref")

            cr_img = st.file_uploader("📷 Foto del punto crítico:",
                                      type=["jpg","jpeg","png"], key="cr_img")
            if cr_img:
                img2 = Image.open(cr_img)
                if st.button("🔍 Evaluar con IA", type="primary",
                             use_container_width=True, key="cr_analizar"):
                    with st.spinner("Analizando..."):
                        res2 = analizar(img2)
                    co2, cd2 = st.columns(2)
                    with co2:
                        st.markdown("**📷 Original**")
                        st.image(img2, use_container_width=True)
                    with cd2:
                        st.markdown("**🤖 Detecciones IA**")
                        st.image(res2[0].plot(), use_container_width=True)

                    tabla2, res2_r, peso2, tipo2, nivel2 = procesar(res2)
                    total2 = sum(len(r.boxes) for r in res2)
                    if tabla2:
                        df_t2 = pd.DataFrame(tabla2)
                        df_si2 = df_t2[df_t2["♻️"] == "✅ Sí"]
                        if not df_si2.empty:
                            st.dataframe(df_si2, use_container_width=True, hide_index=True)
                    metricas(res2_r, peso2, nivel2)

                    if st.button("🚨 REGISTRAR ALERTA EN EL MAPA", type="primary",
                                 use_container_width=True, key="cr_registrar"):
                        nuevo = {
                            "Código":        f"CRIT-{len(st.session_state.reportes)+500}",
                            "Sector":        cr_barrio,
                            "Referencia":    cr_ref,
                            "Objetos":       total2,
                            "Peso (Kg)":     round(total2 * 0.4, 2),
                            "Predominante":  tipo2 or "Mixto",
                            "Clasificación": nivel2,
                            "Lat": plat, "Lon": plon,
                        }
                        st.session_state.reportes.append(nuevo)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir"]:
                            st.session_state.pop(k, None)
                        st.success("✅ ¡Alerta registrada permanentemente en el mapa!")
                        st.rerun()

    # ── SECCIÓN: Historial ─────────────────────────────────────────────
    elif seccion == "historial":
        st.markdown("### 📋 Historial de Reportes")
        if st.session_state.reportes:
            df = pd.DataFrame(st.session_state.reportes)
            cols = [c for c in ["Código","Sector","Referencia","Objetos",
                                 "Peso (Kg)","Clasificación","Lat","Lon"]
                    if c in df.columns]
            st.dataframe(df[cols], use_container_width=True, hide_index=True)
            h1, h2, h3 = st.columns(3)
            with h1:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">'
                            f'{len(df)}</h2><p>Reportes guardados</p></div>',
                            unsafe_allow_html=True)
            with h2:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">'
                            f'{df["Peso (Kg)"].sum():.1f} kg</h2><p>Carga total</p></div>',
                            unsafe_allow_html=True)
            with h3:
                crit = df["Clasificación"].str.contains("crítico|rojo", case=False, na=False).sum()
                st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">'
                            f'{crit}</h2><p>Puntos críticos</p></div>',
                            unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("**✅ Marcar como resuelto** (retira el ícono del mapa):")
            codigos = [r["Código"] for r in st.session_state.reportes]
            sel = st.selectbox("Código del reporte:", codigos, key="h_sel")
            if st.button("✅ Retirar del mapa — problema resuelto",
                         use_container_width=True, key="h_resolver"):
                st.session_state.reportes = [
                    r for r in st.session_state.reportes if r["Código"] != sel]
                guardar_reportes_disco(st.session_state.reportes)
                st.success(f"✅ Reporte {sel} retirado del mapa.")
                st.rerun()
        else:
            st.info("Sin reportes aún. Toca el mapa y usa '📸 Reportar Residuo' para el primero.")

# ====================================================================
# 9. INFORMACIÓN
# ====================================================================
elif menu == "ℹ️ Información":
    st.header("ℹ️ EcoCom2 Circular IA")
    st.markdown("""
**EcoCom2 Circular IA** — Gestión inteligente de residuos para la **Comuna 2, Santa Cruz, Medellín**.

### 📍 Área de cobertura
Desde la **Estación Acevedo** (sur) hasta **Villa del Socorro** (norte), cubriendo los 11 barrios:
Andalucía · Comuneros · Santa Cruz · Villa del Socorro · Moscú No.1 · La Francia · La Frontera · Pablo VI · Villa Niza · La Isla · La Rosa.

### 🔐 ¿Cómo verificarme?
1. Toca un punto del mapa → la dirección aparece sola en el campo de arriba
2. Presiona **🔍 Verificar** → el sistema confirma si estás en la Comuna 2
3. Si estás dentro → puedes reportar. Si no → puedes analizar imágenes pero no publicar.

### 🗺️ Cómo usar el mapa
1. Toca el punto exacto donde está el residuo → aparece la dirección automáticamente
2. Presiona **📸 Reportar Residuo aquí** o **🚨 Marcar Punto Crítico**
3. El formulario se abre directo abajo — sube la foto → IA analiza → publica

### 🤖 Clasificación IA (YOLOv8)
| Color | Significado |
|---|---|
| 🟢 Verde | Mayoría reciclables (≥60%) — alta valorización |
| 🟡 Amarillo | Mezcla de reciclables y basura (30-60%) |
| 🔴 Rojo | Mayoría basura sin valor reciclable (<30%) — acumulación crítica |

### 💾 Persistencia
Los reportes se guardan automáticamente y permanecen en el mapa entre recargas de página.
Cuando el problema sea atendido, márcalo como resuelto desde **📋 Historial**.
""")
    for b in BARRIOS:
        st.write(f"- 📍 **{b}**")
    st.markdown("---\n**Versión:** 4.1 | **ITM Medellín** | Dev: Brandon Duque")
