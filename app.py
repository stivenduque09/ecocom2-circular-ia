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
from datetime import datetime

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
# Verificado con calles reales (imágenes del proyecto)
#
# Barrios incluidos (11 oficiales):
#   La Rosa · Santa Cruz · Moscú No.1 · Villa Niza · Andalucía
#   Villa del Socorro · La Francia · La Frontera
#   Playón de los Comuneros · Pablo VI · La Isla
#
# Límites reales:
#   Sur:   La Rosa / Calle 92-95    (lat ≈ 6.296)
#   Norte: Playón — antes de Bello  (lat ≈ 6.317, NO incluye Zamora)
#   Oeste: Carrera 52               (lon ≈ -75.560 a -75.562)
#   Este:  antes de Popular/ladera  (lon ≈ -75.550 a -75.553)
#          Santo Domingo y Popular  quedan FUERA (son otra comuna)
# ============================================================
POLIGONO_COMUNA2 = Polygon([

    # Sur-occidente (Carrera 52 - Santa Cruz)
    (-75.5613, 6.2933),

    # Subiendo por el límite con Castilla
    (-75.5608, 6.2965),
    (-75.5598, 6.3005),
    (-75.5585, 6.3055),

    # Norte
    (-75.5560, 6.3098),
    (-75.5540, 6.3100),

    # Oriente norte
    (-75.5500, 6.3032),

    # Oriente medio
    (-75.5498, 6.2980),

    # Moscú
    (-75.5500, 6.2935),

    # Suroriente
    (-75.5500, 6.2895),

    # Sur
    (-75.5555, 6.2890),
    (-75.5590, 6.2895),

    # Cierre
    (-75.5613, 6.2933)

])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

# Centro de la Comuna 2
LAT_C = 6.3104
LON_C = -75.5552

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
PAGINAS_BASE = ["🏠 Inicio y Mapa", "ℹ️ Información"]
PAGINAS_ADMIN = ["🏠 Inicio y Mapa", "🛡️ Panel Admin", "ℹ️ Información"]
es_admin = st.session_state.get("admin_ok", False)
menu = st.sidebar.radio("Menú", PAGINAS_ADMIN if es_admin else PAGINAS_BASE,
                        key="menu_principal")

st.sidebar.markdown("---")

# ── Login de administrador ────────────────────────────────────────
if not es_admin:
    with st.sidebar.expander("🔐 Acceso Administrador"):
        pwd = st.text_input("Contraseña:", type="password", key="adm_pwd")
        if st.button("Ingresar", key="adm_login"):
            if pwd == "ecocom2admin2026":   # ← cambia esta contraseña
                st.session_state.admin_ok = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta")
else:
    st.sidebar.markdown(
        '<div class="badge-ok" style="font-size:12px;">🛡️ Admin activo<br>'
        '<span style="font-weight:normal">Brandon Duque · ITM</span></div>',
        unsafe_allow_html=True)
    if st.sidebar.button("🔓 Cerrar sesión admin", key="adm_logout"):
        st.session_state.admin_ok = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="font-size:11px;color:#6b7280;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#4ade80">EcoCom2 v4.2</b><br>
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

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=14, tiles="CartoDB dark_matter")

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

    mapa_data = st_folium(mapa, width="100%", height=340,
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

        # ── BOTONES DE ACCIÓN — redirigen al menú lateral ───────────
        if dentro_clk and es_residente():
            st.markdown("")
            # Guardar el punto seleccionado para que lo use la página de reporte
            st.session_state.punto_para_reporte = {
                "lat": clat, "lon": clon, "dir": cdir
            }
            bc1, bc2, bc3 = st.columns([2, 2, 1])
            with bc1:
                if st.button("📸 Reportar Residuo",
                             type="primary", use_container_width=True, key="btn_ir_rep"):
                    st.session_state.seccion = "residuo"
                    st.rerun()
            with bc2:
                if st.button("🚨 Punto Crítico",
                             use_container_width=True, key="btn_ir_crit"):
                    st.session_state.seccion = "critico"
                    st.rerun()
            with bc3:
                if st.button("✖", use_container_width=True, key="btn_quit",
                             help="Quitar punto seleccionado"):
                    for k in ["click_lat","click_lon","click_dir",
                               "cache","punto_para_reporte"]:
                        st.session_state.pop(k, None)
                    st.rerun()
        elif clat and not es_residente():
            badge("⚠️ Verifica tu dirección arriba para reportar en este punto.", "warn")

    st.markdown("")

    st.markdown("")
    seccion = st.session_state.get("seccion", "info")

    # ── Indicador de sección activa (compacto, sin duplicar botones) ──
    if seccion != "info":
        iconos = {"residuo": "📸 Reportar Residuo", "critico": "🚨 Punto Crítico",
                  "historial": "📋 Historial"}
        st.markdown(
            f'<div style="border-bottom:2px solid #4ade80;padding:6px 0 4px 0;'
            f'color:#4ade80;font-weight:bold;font-size:15px;margin-bottom:12px;">'
            f'{iconos.get(seccion,"")}</div>',
            unsafe_allow_html=True)

    # ── SECCIÓN: Punto en el mapa ──────────────────────────────────────
    if seccion == "info":
        if not clat:
            st.info("👆 Toca cualquier punto del mapa y usa los botones que aparecen para reportar.")

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

                    # ── Fallback manual si YOLO no detecta nada ──────
                    # (escombros, basura genérica, plástico oscuro, etc.)
                    if residuos == 0 and len(tabla) == 0:
                        st.warning(
                            "⚠️ La IA no reconoció objetos específicos. "
                            "Esto ocurre con escombros, basura mezclada o bolsas oscuras. "
                            "Clasifica manualmente:"
                        )
                        tipo_manual = st.selectbox(
                            "¿Qué tipo de residuo observas en la imagen?",
                            [
                                "🏗️ Escombros / Residuos de construcción",
                                "🗑️ Basura doméstica mezclada / bolsas",
                                "🧹 Residuos orgánicos (comida, vegetación)",
                                "♻️ Materiales reciclables sin identificar",
                                "⚠️ Mezcla de varios tipos",
                            ],
                            key="r_tipo_manual"
                        )
                        cant_manual = st.slider(
                            "Cantidad aproximada de residuos visibles:",
                            1, 20, 5, key="r_cant_manual"
                        )
                        # Clasificar según selección
                        MAP_MANUAL = {
                            "🏗️ Escombros / Residuos de construcción":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Escombros", round(cant_manual * 5.0, 1)),
                            "🗑️ Basura doméstica mezclada / bolsas":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Residuo mixto", round(cant_manual * 0.5, 1)),
                            "🧹 Residuos orgánicos (comida, vegetación)":
                                ("🟡 Punto amarillo — Residuos mixtos",
                                 "Orgánico", round(cant_manual * 0.3, 1)),
                            "♻️ Materiales reciclables sin identificar":
                                ("🟢 Punto verde — Alta valorización reciclable",
                                 "Reciclable", round(cant_manual * 0.4, 1)),
                            "⚠️ Mezcla de varios tipos":
                                ("🟡 Punto amarillo — Residuos mixtos",
                                 "Mixto", round(cant_manual * 1.0, 1)),
                        }
                        nivel, tipo, peso = MAP_MANUAL[tipo_manual]
                        residuos = cant_manual if "reciclable" in tipo_manual.lower() else 0
                        metricas(residuos, peso, nivel)
                    else:
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
                        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Estado": "🔴 Pendiente",
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

                # ── Botón de análisis — guarda resultados en cache_critico ──
                if st.button("🔍 Evaluar con IA", type="primary",
                             use_container_width=True, key="cr_analizar"):
                    with st.spinner("Analizando con YOLOv8..."):
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
                        df_si2 = pd.DataFrame(tabla2)
                        df_si2 = df_si2[df_si2["♻️"] == "✅ Sí"]
                        if not df_si2.empty:
                            st.dataframe(df_si2, use_container_width=True, hide_index=True)

                    # Guardar en session_state para que persista entre reruns
                    st.session_state.cache_critico = {
                        "residuos":    res2_r,
                        "peso":        peso2,
                        "tipo":        tipo2,
                        "nivel":       nivel2,
                        "total":       total2,
                        "ia_detecto":  total2 > 0,
                        "Lat":         plat,
                        "Lon":         plon,
                    }

                # ── Resultados y botón REGISTRAR — FUERA del bloque analizar ──
                # (esto persiste entre reruns gracias a cache_critico)
                if st.session_state.get("cache_critico"):
                    cc = st.session_state.cache_critico

                    # Si la IA no detectó nada → selector manual
                    if not cc["ia_detecto"]:
                        st.warning(
                            "⚠️ La IA no reconoció objetos específicos "
                            "(escombros, bolsas oscuras, basura mezclada). "
                            "Clasifica manualmente:"
                        )
                        OPCIONES_MC = [
                            "🏗️ Escombros / Residuos de construcción",
                            "🗑️ Basura doméstica mezclada / bolsas",
                            "🧹 Residuos orgánicos (comida, vegetación)",
                            "⚠️ Mezcla de varios tipos",
                        ]
                        tipo_mc = st.selectbox("¿Qué ves en la imagen?",
                                               OPCIONES_MC, key="cr_tipo_manual")
                        cant_mc = st.slider("Cantidad aproximada de residuos:", 1, 30, 8,
                                            key="cr_cant_manual")
                        MAP_MC = {
                            "🏗️ Escombros / Residuos de construcción":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Escombros", round(cant_mc * 5.0, 1)),
                            "🗑️ Basura doméstica mezclada / bolsas":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Residuo mixto", round(cant_mc * 0.8, 1)),
                            "🧹 Residuos orgánicos (comida, vegetación)":
                                ("🟡 Punto amarillo — Residuos mixtos",
                                 "Orgánico", round(cant_mc * 0.3, 1)),
                            "⚠️ Mezcla de varios tipos":
                                ("🔴 Punto crítico — Acumulación sin valorización",
                                 "Mixto", round(cant_mc * 1.5, 1)),
                        }
                        nivel_f, tipo_f, peso_f = MAP_MC[tipo_mc]
                        total_f = cant_mc
                        residuos_f = 0
                    else:
                        nivel_f   = cc["nivel"]
                        tipo_f    = cc["tipo"]
                        peso_f    = cc["peso"]
                        total_f   = cc["total"]
                        residuos_f= cc["residuos"]

                    metricas(residuos_f, peso_f, nivel_f)

                    # Botón REGISTRAR fuera del bloque analizar → siempre visible
                    st.markdown("")
                    cr_pub, cr_can = st.columns(2)
                    with cr_pub:
                        if st.button("🚨 REGISTRAR ALERTA EN EL MAPA",
                                     type="primary", use_container_width=True,
                                     key="cr_registrar"):
                            nuevo = {
                                "Código":        f"CRIT-{len(st.session_state.reportes)+500}",
                                "Sector":        cr_barrio,
                                "Referencia":    cr_ref,
                                "Objetos":       total_f,
                                "Peso (Kg)":     round(peso_f, 2),
                                "Predominante":  tipo_f or "Mixto",
                                "Clasificación": nivel_f,
                                "Lat":           cc["Lat"],
                                "Lon":           cc["Lon"],
                                "Fecha":         datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "Estado":        "🔴 Pendiente",
                            }
                            st.session_state.reportes.append(nuevo)
                            guardar_reportes_disco(st.session_state.reportes)
                            st.session_state.cache_critico = None
                            st.session_state.seccion = "historial"
                            for k in ["click_lat","click_lon","click_dir"]:
                                st.session_state.pop(k, None)
                            st.success("✅ ¡Alerta registrada permanentemente!")
                            st.rerun()
                    with cr_can:
                        if st.button("❌ Cancelar", use_container_width=True,
                                     key="cr_cancelar"):
                            st.session_state.cache_critico = None
                            st.rerun()

    # ── SECCIÓN: Historial ─────────────────────────────────────────────
    elif seccion == "historial":
        st.markdown("### 📋 Historial de Reportes")
        if not st.session_state.reportes:
            st.info("Sin reportes aún. Toca el mapa y usa '📸 Reportar Residuo' para el primero.")
        else:
            df = pd.DataFrame(st.session_state.reportes)

            # Métricas resumen
            h1, h2, h3, h4 = st.columns(4)
            pendientes = df.get("Estado", pd.Series([])).str.contains("Pendiente", na=False).sum() if "Estado" in df.columns else len(df)
            resueltos  = df.get("Estado", pd.Series([])).str.contains("Resuelto",  na=False).sum() if "Estado" in df.columns else 0
            crit = df["Clasificación"].str.contains("crítico", case=False, na=False).sum()
            with h1:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2><p>Total</p></div>', unsafe_allow_html=True)
            with h2:
                st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{crit}</h2><p>Críticos 🔴</p></div>', unsafe_allow_html=True)
            with h3:
                st.markdown(f'<div class="metric-card"><h2 style="color:#fbbf24">{pendientes}</h2><p>Pendientes</p></div>', unsafe_allow_html=True)
            with h4:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{resueltos}</h2><p>Resueltos ✅</p></div>', unsafe_allow_html=True)

            st.markdown("")

            # Tabla con columnas relevantes
            COLS = ["Código","Fecha","Estado","Sector","Referencia",
                    "Objetos","Peso (Kg)","Clasificación"]
            cols_ok = [c for c in COLS if c in df.columns]
            st.dataframe(df[cols_ok], use_container_width=True, hide_index=True)

            # Exportar CSV
            csv_data = df[cols_ok].to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Exportar como CSV",
                data=csv_data,
                file_name=f"ecocom2_reportes_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )

# ====================================================================
# 9. INFORMACIÓN
# ====================================================================
elif menu == "🛡️ Panel Admin":
    st.title("🛡️ Panel de Administración — EcoCom2")
    st.caption("Solo el administrador autorizado puede gestionar los reportes desde aquí.")

    if not st.session_state.get("admin_ok"):
        st.error("🔐 Acceso denegado. Inicia sesión como administrador en el menú lateral.")
        st.stop()

    reportes = st.session_state.reportes

    if not reportes:
        st.info("No hay reportes registrados aún.")
    else:
        df_a = pd.DataFrame(reportes)

        # ── Métricas admin ────────────────────────────────────────────
        st.markdown("### 📊 Resumen del territorio")
        a1, a2, a3, a4, a5 = st.columns(5)
        total   = len(df_a)
        criticos= df_a["Clasificación"].str.contains("crítico", case=False, na=False).sum()
        amarillo= df_a["Clasificación"].str.contains("amarillo", case=False, na=False).sum()
        verde   = df_a["Clasificación"].str.contains("verde", case=False, na=False).sum()
        peso_t  = df_a["Peso (Kg)"].sum()
        for col, val, label, color in [
            (a1, total,    "Total reportes",  "#4ade80"),
            (a2, criticos, "🔴 Críticos",     "#f87171"),
            (a3, amarillo, "🟡 Mixtos",       "#fbbf24"),
            (a4, verde,    "🟢 Reciclables",  "#4ade80"),
            (a5, f"{peso_t:.0f} kg", "Carga total", "#a78bfa"),
        ]:
            with col:
                st.markdown(
                    f'<div class="metric-card"><h2 style="color:{color}">{val}</h2>'
                    f'<p style="font-size:12px">{label}</p></div>',
                    unsafe_allow_html=True)

        st.markdown("---")

        # ── Gestión individual de reportes ────────────────────────────
        # IMPORTANTE: Las keys usan rep['Código'] (estable), NO el índice numérico.
        # El índice cambia al eliminar reportes y provoca removeChild en React.
        st.markdown("### 🗂️ Gestión de alertas")

        # Manejar acciones pendientes ANTES de renderizar la lista
        # (evita mutar la lista mientras se itera)
        accion = st.session_state.pop("adm_accion_pendiente", None)
        if accion:
            cod_obj  = accion["codigo"]
            tipo_acc = accion["tipo"]
            if tipo_acc == "estado":
                for r in st.session_state.reportes:
                    if r["Código"] == cod_obj:
                        r["Estado"] = accion["valor"]
                        break
                guardar_reportes_disco(st.session_state.reportes)
            elif tipo_acc in ("resuelto", "eliminar"):
                if tipo_acc == "resuelto":
                    for r in st.session_state.reportes:
                        if r["Código"] == cod_obj:
                            r["Estado"] = "✅ Resuelto"
                            break
                    guardar_reportes_disco(st.session_state.reportes)
                else:
                    st.session_state.reportes = [
                        r for r in st.session_state.reportes
                        if r["Código"] != cod_obj
                    ]
                    guardar_reportes_disco(st.session_state.reportes)
            st.rerun()

        ESTADOS = ["🔴 Pendiente", "🟡 En proceso de recolección", "✅ Resuelto"]

        for rep in list(st.session_state.reportes):   # list() → copia estable
            codigo = rep["Código"]
            # Sanear el código para usarlo como key (solo alfanumérico + guión)
            key_safe = codigo.replace(" ", "_").replace("/", "_")
            estado = rep.get("Estado", "🔴 Pendiente")
            nivel  = rep.get("Clasificación", "")
            icono  = "🔴" if "crítico" in nivel.lower() else ("🟡" if "amarillo" in nivel.lower() else "🟢")

            with st.expander(
                f"{icono} {codigo} — {rep.get('Sector','?')} — "
                f"{rep.get('Referencia','?')[:35]} | {estado}",
                expanded=False
            ):
                dc1, dc2 = st.columns(2)
                with dc1:
                    st.markdown(
                        f"**Código:** {codigo}  \n"
                        f"**Sector:** {rep.get('Sector','—')}  \n"
                        f"**Referencia:** {rep.get('Referencia','—')}  \n"
                        f"**Registrado:** {rep.get('Fecha','Sin fecha')}"
                    )
                with dc2:
                    st.markdown(
                        f"**Clasificación:** {nivel}  \n"
                        f"**Objetos:** {rep.get('Objetos','—')}  \n"
                        f"**Peso:** {rep.get('Peso (Kg)','—')} kg  \n"
                        f"**Material:** {rep.get('Predominante','—')}"
                    )

                # Selectbox de estado — key estable basada en Código
                idx_est = ESTADOS.index(estado) if estado in ESTADOS else 0
                nuevo_estado = st.selectbox(
                    "Estado:", ESTADOS, index=idx_est,
                    key=f"sel_{key_safe}")

                ac1, ac2, ac3 = st.columns(3)
                with ac1:
                    if st.button("💾 Guardar", key=f"grd_{key_safe}",
                                 use_container_width=True):
                        st.session_state.adm_accion_pendiente = {
                            "codigo": codigo, "tipo": "estado",
                            "valor": nuevo_estado}
                        st.rerun()
                with ac2:
                    if st.button("✅ Resuelto", key=f"res_{key_safe}",
                                 type="primary", use_container_width=True):
                        st.session_state.adm_accion_pendiente = {
                            "codigo": codigo, "tipo": "resuelto"}
                        st.rerun()
                with ac3:
                    if st.button("🗑️ Eliminar", key=f"del_{key_safe}",
                                 use_container_width=True):
                        st.session_state.adm_accion_pendiente = {
                            "codigo": codigo, "tipo": "eliminar"}
                        st.rerun()

        st.markdown("---")
        st.markdown("### 📥 Exportar datos")
        df_exp = pd.DataFrame(st.session_state.reportes)
        csv_exp = df_exp.to_csv(index=False).encode("utf-8")
        st.download_button(
            "📥 Descargar todos los reportes en CSV",
            data=csv_exp,
            file_name=f"ecocom2_admin_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        st.markdown("---")
        st.markdown("### ⚠️ Zona de riesgo")
        if st.button("🗑️ ELIMINAR TODOS los reportes resueltos",
                     use_container_width=True, key="adm_limpiar_resueltos"):
            antes = len(st.session_state.reportes)
            st.session_state.reportes = [
                r for r in st.session_state.reportes
                if r.get("Estado") != "✅ Resuelto"
            ]
            guardar_reportes_disco(st.session_state.reportes)
            eliminados = antes - len(st.session_state.reportes)
            st.success(f"✅ {eliminados} reporte(s) resuelto(s) eliminado(s) del mapa.")
            st.rerun()

elif menu == "ℹ️ Información":
    st.title("♻️ EcoCom2 Circular IA")
    st.markdown(
        '<div style="background:rgba(16,185,129,0.1);border:1px solid #4ade80;'
        'border-radius:10px;padding:16px;margin-bottom:20px;font-size:15px;">'
        '🌱 <b style="color:#4ade80">Plataforma de Gestión Inteligente de Residuos</b><br>'
        'Tecnología IA al servicio de una <b>Comuna 2 más limpia y sostenible</b>.'
        '</div>', unsafe_allow_html=True)

    st.markdown("## 🔄 ¿Qué es la Economía Circular?")
    st.markdown("""
La **economía circular** es un modelo de producción y consumo que busca **eliminar los residuos
desde el diseño**, manteniendo los materiales en uso el mayor tiempo posible. A diferencia de la
economía lineal (fabricar → usar → tirar), la economía circular propone:

- **Reducir** el consumo de recursos y la generación de residuos
- **Reutilizar** materiales y productos antes de descartarlos
- **Reciclar** lo que ya no puede ser reutilizado para crear nuevos materiales
- **Recuperar** energía de los residuos que no pueden reciclarse
""")

    i1, i2, i3 = st.columns(3)
    with i1:
        st.markdown("""
<div style="background:rgba(16,185,129,0.1);border:1px solid #4ade80;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#4ade80">♻️</h2>
<b style="color:#4ade80">Reciclar</b><br>
<span style="font-size:13px;color:#9ca3af">Papel, plástico, vidrio,<br>
aluminio y electrónicos</span>
</div>""", unsafe_allow_html=True)
    with i2:
        st.markdown("""
<div style="background:rgba(251,191,36,0.1);border:1px solid #fbbf24;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#fbbf24">🔁</h2>
<b style="color:#fbbf24">Reutilizar</b><br>
<span style="font-size:13px;color:#9ca3af">Muebles, ropa, aparatos<br>
que aún sirven</span>
</div>""", unsafe_allow_html=True)
    with i3:
        st.markdown("""
<div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#ef4444">🌱</h2>
<b style="color:#ef4444">Compostar</b><br>
<span style="font-size:13px;color:#9ca3af">Residuos orgánicos que<br>
se convierten en abono</span>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 🗺️ ¿Qué es un Punto Crítico de Residuos?")
    st.markdown("""
Un **punto crítico** es una zona donde se acumulan residuos de forma irregular, afectando la
salud pública, el medio ambiente y la calidad de vida del barrio. En la **Comuna 2 — Santa Cruz**
existen zonas donde los residuos se depositan en espacios públicos sin recolección oportuna.

### 🟢 🟡 🔴 Sistema de Clasificación EcoCom2

| Color | Significado | Acción recomendada |
|---|---|---|
| 🟢 **Verde** | ≥60% objetos reciclables. Punto de **alta valorización** | Ruta de reciclaje |
| 🟡 **Amarillo** | 30-60% mixto: reciclables + basura | Separación en origen |
| 🔴 **Rojo** | <30% reciclable. Acumulación crítica sin valor | Recolección urgente |
""")

    st.markdown("---")
    st.markdown("## 🤖 ¿Cómo funciona la IA?")
    st.markdown("""
EcoCom2 usa **YOLOv8** (You Only Look Once), un modelo de visión artificial que analiza imágenes
en tiempo real para detectar y clasificar objetos. El sistema:

1. **Detecta** todos los objetos visibles en la fotografía
2. **Clasifica** cada objeto en su tipo de material (Plástico, Papel, Vidrio, Metal, Electrónico, Orgánico)
3. **Calcula** el peso estimado y el ratio reciclable/no-reciclable
4. **Clasifica** el punto como Verde 🟢, Amarillo 🟡 o Rojo 🔴

### 📦 Materiales que detecta la IA
""")

    mat_cols = st.columns(3)
    categorias = {
        "🧴 Plástico": ["Botellas", "Vasos", "Bolsas", "Baldes", "Sillas", "Juguetes"],
        "📄 Papel/Cartón": ["Libros", "Periódicos", "Cajas", "Cuadernos"],
        "🍶 Vidrio": ["Botellas", "Frascos", "Jarrones", "Copas"],
        "🥫 Metal/Aluminio": ["Latas", "Cuchillos", "Tijeras", "Utensilios"],
        "💻 Electrónicos": ["Celulares", "Portátiles", "Teclados", "Televisores", "Relojes"],
        "🌿 Orgánico": ["Frutas", "Verduras", "Comida", "Plantas"],
        "👕 Textil": ["Ropa", "Mochilas", "Bolsos", "Maletas"],
        "🪵 Madera/Mixto": ["Mesas", "Sofás", "Camas", "Colchones"],
    }
    cat_items = list(categorias.items())
    for i, col in enumerate(mat_cols):
        with col:
            for cat, items in cat_items[i*3:(i+1)*3]:
                st.markdown(
                    f'<div style="background:rgba(16,185,129,0.06);border-radius:8px;'
                    f'padding:10px;margin-bottom:8px;font-size:13px;">'
                    f'<b style="color:#4ade80">{cat}</b><br>'
                    f'<span style="color:#9ca3af">{" · ".join(items)}</span></div>',
                    unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## 📍 Cómo usar EcoCom2")
    st.markdown("""
1. **Verifica tu dirección** en 🏠 Inicio y Mapa — escribe tu dirección y presiona 🔍 Verificar
2. **Toca el mapa** en el punto exacto donde están los residuos
3. **Presiona el botón** "📸 Ir a Reportar Residuo" o "🚨 Ir a Punto Crítico"
4. **Sube una foto** del residuo y deja que la IA lo analice
5. **Publica el reporte** — quedará guardado en el mapa comunitario

> Solo residentes **dentro del polígono de la Comuna 2** pueden publicar reportes.
> Cualquier persona puede analizar imágenes con la IA.
""")

    st.markdown("---")
    st.markdown("## 📍 Los 11 barrios de la Comuna 2 — Santa Cruz")
    bc1, bc2 = st.columns(2)
    mitad = len(BARRIOS) // 2
    with bc1:
        for b in BARRIOS[:mitad+1]:
            st.markdown(f"- 📍 **{b}**")
    with bc2:
        for b in BARRIOS[mitad+1:]:
            st.markdown(f"- 📍 **{b}**")

    st.markdown("---")
    st.markdown("""
<div style="background:rgba(16,185,129,0.06);border:1px solid rgba(74,222,128,0.2);
border-radius:10px;padding:16px;text-align:center;color:#9ca3af;font-size:13px;">
⚙️ <b style="color:#4ade80">EcoCom2 Circular IA v4.0</b><br>
Proyecto <b style="color:#4ade80">Territorio INN 2026</b> · Instituto Tecnológico Metropolitano (ITM) · Medellín<br>
Desarrollado por: <b style="color:#4ade80">Brandon Duque</b> · Comuna 2 Santa Cruz
</div>
""", unsafe_allow_html=True)
