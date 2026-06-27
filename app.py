import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter
import folium
from folium.plugins import LocateControl
from streamlit_folium import st_folium
import pandas as pd
from shapely.geometry import Point, Polygon
import json, os

# ====================================================================
# PERSISTENCIA — guarda los reportes en /tmp para sobrevivir recargas
# ====================================================================
REPORTES_FILE = "/tmp/ecocom2_reportes.json"

def cargar_reportes_disco():
    """Carga reportes guardados desde el archivo JSON."""
    if os.path.exists(REPORTES_FILE):
        try:
            with open(REPORTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def guardar_reportes_disco(reportes: list):
    """Guarda todos los reportes en el archivo JSON."""
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
    .badge-ok   { background:rgba(16,185,129,0.15); border:1px solid #4ade80;
                  border-radius:8px; padding:10px 14px; color:#4ade80; font-weight:bold; }
    .badge-warn { background:rgba(251,191,36,0.12); border:1px solid #fbbf24;
                  border-radius:8px; padding:10px 14px; color:#fbbf24; font-weight:bold; }
    .badge-err  { background:rgba(239,68,68,0.12); border:1px solid #ef4444;
                  border-radius:8px; padding:10px 14px; color:#ef4444; font-weight:bold; }
    .metric-card { background:rgba(16,185,129,0.08); border:1px solid rgba(74,222,128,0.3);
                   border-radius:10px; padding:14px; text-align:center; }
    .accion-btn { background:linear-gradient(135deg,#10b981,#059669) !important;
                  border:none !important; font-weight:bold !important; }
    div[data-testid="stButton"] button[kind="primary"] {
        background:linear-gradient(135deg,#10b981,#059669);
        border:none; font-weight:bold; font-size:14px; }
    /* Ocultar header de Streamlit */
    header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO COMUNA 2 — SANTA CRUZ, MEDELLÍN
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    (-75.5720, 6.2960), (-75.5710, 6.3020), (-75.5705, 6.3080),
    (-75.5700, 6.3130), (-75.5660, 6.3160), (-75.5610, 6.3170),
    (-75.5560, 6.3155), (-75.5510, 6.3120), (-75.5490, 6.3060),
    (-75.5480, 6.2990), (-75.5500, 6.2940), (-75.5540, 6.2910),
    (-75.5600, 6.2920), (-75.5660, 6.2940), (-75.5720, 6.2960),
])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

LAT_C = 6.3040
LON_C = -75.5590

# ====================================================================
# 3. SESIÓN
# ====================================================================
DEFAULTS = {
    "lat": None, "lon": None,
    "validado": False, "fuera": True,
    "direccion": "",
    "reporte_ok": False,
    "cache": None,
    "modo": None,
    "tab_activa": "mapa",
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Cargar reportes desde disco (persisten entre recargas de página)
if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()

# ====================================================================
# 4. MODELO YOLO
# ====================================================================
@st.cache_resource
def cargar_modelo():
    return YOLO("yolov8m.pt")
modelo = cargar_modelo()

# ====================================================================
# 5. MATERIALES
# ====================================================================
MAT = {
    "bottle":       ("Botella plástica",     "Plástico",    0.05, True),
    "cup":          ("Vaso plástico",        "Plástico",    0.03, True),
    "chair":        ("Silla plástica",       "Plástico",    2.00, True),
    "bench":        ("Banco plástico",       "Plástico",    2.50, True),
    "bucket":       ("Balde plástico",       "Plástico",    0.50, True),
    "toy":          ("Juguete",              "Plástico",    0.50, True),
    "bowl":         ("Recipiente plástico",  "Plástico",    0.15, True),
    "book":         ("Libro / Cuaderno",     "Papel",       0.30, True),
    "newspaper":    ("Periódico",            "Papel",       0.10, True),
    "box":          ("Caja de cartón",       "Cartón",      0.30, True),
    "wine glass":   ("Copa de vidrio",       "Vidrio",      0.20, True),
    "vase":         ("Jarrón de vidrio",     "Vidrio",      0.80, True),
    "can":          ("Lata de aluminio",     "Aluminio",    0.02, True),
    "cell phone":   ("Celular",              "Electrónico", 0.20, True),
    "laptop":       ("Portátil",             "Electrónico", 2.50, True),
    "keyboard":     ("Teclado",              "Electrónico", 0.60, True),
    "mouse":        ("Ratón de PC",          "Electrónico", 0.10, True),
    "remote":       ("Control remoto",       "Electrónico", 0.20, True),
    "tv":           ("Televisor",            "Electrónico", 8.00, True),
    "clock":        ("Reloj",                "Electrónico", 0.30, True),
    "backpack":     ("Mochila",              "Textil",      0.50, True),
    "handbag":      ("Bolso",                "Textil",      0.40, True),
    "suitcase":     ("Maleta",               "Textil",      2.50, True),
    "umbrella":     ("Paraguas",             "Textil",      0.50, True),
    "banana":       ("Banano",               "Orgánico",    0.10, True),
    "apple":        ("Manzana",              "Orgánico",    0.15, True),
    "orange":       ("Naranja",              "Orgánico",    0.20, True),
    "broccoli":     ("Brócoli",              "Orgánico",    0.25, True),
    "carrot":       ("Zanahoria",            "Orgánico",    0.10, True),
    "potted plant": ("Planta / Matero",      "Orgánico",    1.00, True),
    "dining table": ("Mesa de comedor",      "Madera",     12.00, True),
    "couch":        ("Sofá",                 "Mixto",      15.00, True),
    "bed":          ("Cama",                 "Mixto",      20.00, True),
    # No reciclables
    "person":       ("Persona",    "—", 0, False),
    "dog":          ("Perro",      "—", 0, False),
    "cat":          ("Gato",       "—", 0, False),
    "car":          ("Vehículo",   "—", 0, False),
    "bus":          ("Bus",        "—", 0, False),
    "truck":        ("Camión",     "—", 0, False),
    "bicycle":      ("Bicicleta",  "—", 0, False),
    "motorcycle":   ("Moto",       "—", 0, False),
    "traffic light":("Semáforo",   "—", 0, False),
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
    """Coordenadas → dirección legible (para auto-rellenar al hacer clic en el mapa)."""
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4_rev", timeout=6)
        r = geo.reverse(f"{lat}, {lon}", language="es")
        if r and r.raw.get("address"):
            a = r.raw["address"]
            partes = []
            calle = a.get("road") or a.get("pedestrian") or a.get("path") or ""
            num   = a.get("house_number", "")
            barrio= a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
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
        return modelo(tmp.name, conf=0.08)


def procesar(resultados):
    objetos = []
    for r in resultados:
        for box in r.boxes:
            objetos.append((modelo.names[int(box.cls[0])], float(box.conf[0])))

    if not objetos:
        return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados"

    conteo = Counter(o[0] for o in objetos)
    mejor  = {}
    for n, c in objetos:
        mejor[n] = max(mejor.get(n, 0), c)

    tabla, peso_total, residuos = [], 0.0, 0
    cnt_mat = Counter()

    for obj, cant in conteo.items():
        nom, mat, peso_u, recicl = MAT.get(obj, (obj.title(), "Desconocido", 0.1, False))
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
            tabla.append({"Objeto": nom, "Material": "—",
                          "Cant.": cant, "Peso (kg)": 0,
                          "Confianza": conf, "♻️": "❌ No"})

    tipo = cnt_mat.most_common(1)[0][0] if cnt_mat else "Mixto"

    # Clasificación basada en RATIO reciclable vs no-reciclable
    # (no en cantidad bruta) — como en la imagen de basura real:
    # mucha basura mezclada sin valor = 🔴 aunque haya muchos objetos
    total_obj     = sum(conteo.values())
    no_reciclables = total_obj - residuos
    ratio = residuos / total_obj if total_obj > 0 else 0

    if total_obj <= 2:
        # Pocos objetos — no es un punto crítico aún
        nivel = "🟢 Residuo puntual — 1 a 2 objetos"
    elif ratio >= 0.60:
        # 60%+ son reciclables → punto verde (bueno para aprovechar)
        nivel = "🟢 Punto verde — Alta valorización reciclable"
    elif ratio >= 0.30:
        # Mezcla 30-60% reciclable → amarillo
        nivel = "🟡 Punto amarillo — Residuos mixtos"
    else:
        # Menos del 30% reciclable → mayoría basura sin valor → rojo
        nivel = "🔴 Punto crítico — Acumulación sin valorización"

    return tabla, residuos, round(peso_total, 2), tipo, nivel


def badge(texto, tipo="ok"):
    cls = {"ok": "badge-ok", "warn": "badge-warn", "err": "badge-err"}[tipo]
    st.markdown(f'<div class="{cls}">{texto}</div>', unsafe_allow_html=True)
    st.markdown("")


def metricas(residuos, peso, nivel):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f'<div class="metric-card"><h3 style="color:#4ade80">{residuos}</h3>'
                    f'<p style="margin:0;font-size:13px">Reciclables detectados</p></div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><h3 style="color:#4ade80">{peso} kg</h3>'
                    f'<p style="margin:0;font-size:13px">Peso estimado</p></div>',
                    unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><h3>{nivel}</h3>'
                    f'<p style="margin:0;font-size:13px">Clasificación</p></div>',
                    unsafe_allow_html=True)


# ====================================================================
# 7. BARRA LATERAL — solo logo + info
# ====================================================================
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## ♻️ EcoCom2")

# Estado de validación en sidebar
if st.session_state.validado:
    if not st.session_state.fuera:
        st.sidebar.markdown(
            f'<div class="badge-ok" style="font-size:12px;">✅ Dentro de la Comuna 2<br>'
            f'<span style="font-weight:normal">{st.session_state.direccion[:50] if st.session_state.direccion else ""}</span></div>',
            unsafe_allow_html=True)
    else:
        st.sidebar.markdown(
            '<div class="badge-err" style="font-size:12px;">🛑 Fuera de la Comuna 2<br>'
            '<span style="font-weight:normal">Solo lectura del mapa</span></div>',
            unsafe_allow_html=True)
else:
    st.sidebar.markdown(
        '<div class="badge-warn" style="font-size:12px;">⚠️ Sin verificar<br>'
        '<span style="font-weight:normal">Ingresa tu dirección</span></div>',
        unsafe_allow_html=True)

st.sidebar.markdown("---")
menu = st.sidebar.radio("Menú", ["🏠 Inicio y Mapa", "📸 Reportar Residuo", "🚨 Punto Crítico", "ℹ️ Información"])
st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="font-size:11px;color:#6b7280;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#4ade80">EcoCom2 v4.0</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#4ade80">Brandon Duque</b>
</div>""", unsafe_allow_html=True)


# ====================================================================
# 8. PÁGINA: INICIO Y MAPA
# ====================================================================
if menu == "🏠 Inicio y Mapa":
    st.title("♻️ EcoCom2 Circular IA")
    st.caption("Sistema inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    # ── CAMPO DE DIRECCIÓN — se auto-rellena con el click del mapa ───
    # Valor inicial: lo que había antes o lo que vino del click
    dir_default = (st.session_state.get("click_dir") or
                   st.session_state.get("direccion") or "")

    col_inp, col_btn, col_cambiar = st.columns([5, 1, 1])
    with col_inp:
        dir_inp = st.text_input(
            "📍 Tu dirección:",
            value=dir_default,
            placeholder="Haz clic en el mapa o escribe tu dirección...",
            key="dir_campo",
            label_visibility="collapsed",
            help="Al hacer clic en el mapa se rellena automáticamente"
        )
    with col_btn:
        verificar_btn = st.button("🔍 Verificar", type="primary",
                                  use_container_width=True, key="btn_verificar")
    with col_cambiar:
        if st.session_state.validado:
            if st.button("🔄", use_container_width=True, key="btn_cambiar",
                         help="Cambiar dirección"):
                for k in ["validado","lat","lon","fuera","direccion",
                          "click_lat","click_lon","click_dir",
                          "punto_lat","punto_lon","punto_dir"]:
                    st.session_state.pop(k, None)
                st.rerun()

    if verificar_btn:
        texto = dir_inp.strip()
        if texto:
            with st.spinner("Buscando dirección..."):
                lat, lon, addr = geocodificar(texto)
            if lat:
                set_ubicacion(lat, lon, addr)
                st.rerun()
            else:
                st.error("❌ No encontré esa dirección. Intenta: Cra 50 #107-62, Andalucía, Medellín")
        else:
            st.warning("Escribe o selecciona una dirección primero.")

    # Badge de estado debajo del campo
    if st.session_state.validado:
        if not st.session_state.fuera:
            badge(f"✅ <b>Dentro de la Comuna 2</b> — {st.session_state.direccion[:80]}", "ok")
        else:
            badge(f"🛑 Fuera de la Comuna 2 — {st.session_state.direccion[:70]}", "err")
    elif dir_default:
        st.caption("👆 Presiona **🔍 Verificar** para confirmar si estás en la Comuna 2.")

    st.markdown("---")

    # ── MAPA ──────────────────────────────────────────────────────────
    st.markdown("### 🗺️ Toca el mapa para seleccionar el punto del residuo")
    st.caption("Al tocar un punto, la dirección aparece automáticamente arriba y en las pestañas de reporte.")

    lat_c = st.session_state.get("lat") or LAT_C
    lon_c = st.session_state.get("lon") or LON_C

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=15,
                      tiles="CartoDB dark_matter")

    # Polígono Comuna 2
    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_p, color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        tooltip="📍 Área piloto — Comuna 2 Santa Cruz"
    ).add_to(mapa)

    # Pin hogar del usuario
    if st.session_state.get("validado") and st.session_state.get("lat"):
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker(
            location=[st.session_state.lat, st.session_state.lon],
            popup=f"🏠 Tu dirección<br>{st.session_state.direccion}",
            tooltip="🏠 Tu ubicación",
            icon=folium.Icon(color=col_pin, icon="home", prefix="fa")
        ).add_to(mapa)

    # Pin rojo del punto clickeado
    if st.session_state.get("click_lat"):
        folium.Marker(
            location=[st.session_state.click_lat, st.session_state.click_lon],
            popup=f"📌 {st.session_state.get('click_dir','Punto seleccionado')}",
            tooltip="📌 Punto seleccionado",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(mapa)

    # Reportes registrados
    for rep in st.session_state.reportes:
        niv = rep.get("Clasificación", "🟢")
        col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
        folium.CircleMarker(
            location=[rep["Lat"], rep["Lon"]], radius=11,
            color=col, fill=True, fill_color=col, fill_opacity=0.85,
            popup=folium.Popup(
                f"<b>{rep['Código']}</b><br>📍 {rep['Sector']}<br>"
                f"📌 {rep['Referencia']}<br>♻️ {rep['Objetos']} obj "
                f"| ⚖️ {rep['Peso (Kg)']} kg<br><b>{niv}</b>",
                max_width=200),
            tooltip=rep["Código"]
        ).add_to(mapa)

    mapa_data = st_folium(mapa, width="100%", height=440,
                          returned_objects=["last_clicked"])

    # ── Click detectado → geocodificación inversa + auto-rellenar campo
    if mapa_data and mapa_data.get("last_clicked"):
        clk     = mapa_data["last_clicked"]
        lat_clk = round(clk["lat"], 7)
        lon_clk = round(clk["lng"], 7)
        if (lat_clk != st.session_state.get("click_lat") or
                lon_clk != st.session_state.get("click_lon")):
            st.session_state.click_lat = lat_clk
            st.session_state.click_lon = lon_clk
            with st.spinner("📍 Detectando dirección del punto..."):
                dir_obtenida = geocodificar_inversa(lat_clk, lon_clk)
            st.session_state.click_dir = dir_obtenida
            # Si no está verificado aún, pre-llenar también la validación
            if not st.session_state.get("validado"):
                set_ubicacion(lat_clk, lon_clk, dir_obtenida)
            st.rerun()   # <-- recarga y el campo muestra la nueva dirección

    # ── Variables del punto clickeado ────────────────────────────────
    clat  = st.session_state.get("click_lat")
    clon  = st.session_state.get("click_lon")
    cdir  = st.session_state.get("click_dir", "")
    dentro_click = POLIGONO_COMUNA2.contains(Point(clon, clat)) if clat else False

    # ── PANEL RÁPIDO: aparece al tocar el mapa, ANTES de las pestañas ─
    if clat:
        st.markdown("")
        if dentro_click and es_residente():
            st.markdown(
                f'<div style="background:rgba(16,185,129,0.12);border:1px solid #4ade80;'
                f'border-radius:10px;padding:12px 16px;margin-bottom:8px;">'
                f'<span style="color:#4ade80;font-weight:bold;font-size:14px;">'
                f'📌 {cdir}</span><br>'
                f'<span style="color:#9ca3af;font-size:12px;">✅ Dentro de la Comuna 2 · '
                f'{clat:.5f}, {clon:.5f}</span></div>',
                unsafe_allow_html=True)
            # Botones grandes que activan la pestaña correcta
            pb1, pb2, pb3 = st.columns(3)
            with pb1:
                if st.button("📸 Reportar Residuo",
                             type="primary", use_container_width=True,
                             key="btn_ir_residuo"):
                    st.session_state.tab_idx = 1
                    st.rerun()
            with pb2:
                if st.button("🚨 Punto Crítico",
                             use_container_width=True, key="btn_ir_critico"):
                    st.session_state.tab_idx = 2
                    st.rerun()
            with pb3:
                if st.button("🗑️ Limpiar", use_container_width=True,
                             key="btn_limpiar"):
                    for k in ["click_lat","click_lon","click_dir","cache",
                               "punto_lat","punto_lon","punto_dir","tab_idx"]:
                        st.session_state.pop(k, None)
                    st.rerun()
        elif not es_residente():
            st.markdown(
                f'<div style="background:rgba(251,191,36,0.1);border:1px solid #fbbf24;'
                f'border-radius:10px;padding:12px 16px;">'
                f'<span style="color:#fbbf24;font-size:13px;">'
                f'📌 {cdir}<br>⚠️ Verifica tu dirección arriba para poder reportar.</span></div>',
                unsafe_allow_html=True)
        elif not dentro_click:
            st.markdown(
                f'<div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;'
                f'border-radius:10px;padding:12px 16px;">'
                f'<span style="color:#ef4444;font-size:13px;">'
                f'📌 {cdir}<br>🛑 Este punto está fuera del área piloto de la Comuna 2.</span></div>',
                unsafe_allow_html=True)

    st.markdown("")

    # ── PESTAÑAS — el índice activo se controla desde session_state ───
    # st.tabs no permite activar por código, así que reordenamos las tabs
    # poniendo primero la que debe estar activa según tab_idx
    idx = st.session_state.get("tab_idx", 0)

    TABS_LABELS = [
        "📍 Punto",
        "📸 Reportar Residuo",
        "🚨 Punto Crítico",
        "📋 Historial",
    ]
    # Rotamos la lista para que la tab_idx quede de primera
    labels_rot = TABS_LABELS[idx:] + TABS_LABELS[:idx]
    tabs_rot   = st.tabs(labels_rot)

    # Mapear cada tab rotada a su índice original
    def get_tab(original_idx):
        pos_en_rot = (original_idx - idx) % len(TABS_LABELS)
        return tabs_rot[pos_en_rot]

    tab_mapa     = get_tab(0)
    tab_residuo  = get_tab(1)
    tab_critico  = get_tab(2)
    tab_historial= get_tab(3)

    # Resetear tab_idx después de mostrar para que no quede pegado
    # (solo se activa la primera vez que llega el rerun del botón)
    if "tab_idx" in st.session_state and st.session_state.get("_tab_mostrado"):
        del st.session_state["tab_idx"]
        st.session_state["_tab_mostrado"] = False
    elif "tab_idx" in st.session_state:
        st.session_state["_tab_mostrado"] = True

    # ── TAB 0: Punto seleccionado ─────────────────────────────────────
    with tab_mapa:
        if not clat:
            st.info("👆 Toca cualquier punto del mapa para ver la dirección y las opciones de reporte.")
        else:
            st.markdown(f'<div class="badge-ok" style="font-size:14px;">📌 {cdir}</div>',
                        unsafe_allow_html=True)
            st.caption(f"🌐 {clat:.6f}, {clon:.6f}")
            st.markdown("👇 Usa los botones de arriba o las pestañas para reportar.")

    # ── TAB 2: Reportar Residuo ───────────────────────────────────────
    with tab_residuo:
        if not es_residente():
            st.warning("⚠️ Verifica tu dirección en el campo de arriba para reportar.")
        elif not clat:
            st.info("👆 Primero toca un punto en el mapa.")
        elif not dentro_click:
            st.error("🛑 El punto seleccionado está fuera de la Comuna 2.")
        else:
            plat = clat; plon = clon; pdir = cdir
            # Dirección pre-rellenada automáticamente
            st.markdown(f'<div class="badge-ok" style="font-size:13px;">📌 {pdir}</div>',
                        unsafe_allow_html=True)
            st.markdown("")
            t1c1, t1c2 = st.columns(2)
            with t1c1:
                t1_barrio = st.selectbox("Barrio:", BARRIOS, key="t1_barrio")
            with t1c2:
                # Referencia = dirección detectada, editable
                t1_ref = st.text_input("Referencia (edita si quieres):",
                                       value=pdir, key="t1_ref")
            t1_img = st.file_uploader("📷 Foto del residuo:",
                                      type=["jpg","jpeg","png"], key="t1_img")
            if t1_img:
                img = Image.open(t1_img)
                if st.button("🔍 Analizar con IA", type="primary",
                             use_container_width=True, key="t1_analizar"):
                    with st.spinner("Analizando..."):
                        res = analizar(img)
                    c1t, c2t = st.columns(2)
                    with c1t:
                        st.image(img, caption="Original", use_container_width=True)
                    with c2t:
                        st.image(res[0].plot(), caption="Detecciones IA",
                                 use_container_width=True)
                    tabla, residuos, peso, tipo, nivel = procesar(res)
                    if tabla:
                        df_si = pd.DataFrame(tabla)
                        df_si = df_si[df_si["♻️"] == "✅ Sí"]
                        if not df_si.empty:
                            st.dataframe(df_si, use_container_width=True, hide_index=True)
                    if residuos > 0:
                        metricas(residuos, peso, nivel)
                    if residuos > 0:
                        st.session_state.cache = {
                            "Código":        f"REP-{len(st.session_state.reportes)+200}",
                            "Sector":        t1_barrio,
                            "Referencia":    t1_ref,
                            "Objetos":       residuos,
                            "Peso (Kg)":     peso,
                            "Predominante":  tipo,
                            "Clasificación": nivel,
                            "Lat": plat, "Lon": plon,
                        }
                    else:
                        st.warning("No se detectaron residuos reciclables.")

            if st.session_state.get("cache"):
                r = st.session_state.cache
                if r.get("Lat") == plat:
                    st.markdown(f"**Clasificación:** {r['Clasificación']} · "
                                f"**{r['Objetos']}** obj · **{r['Peso (Kg)']}** kg")
                    if st.button("🚀 PUBLICAR EN EL MAPA", type="primary",
                                 use_container_width=True, key="t1_publicar"):
                        st.session_state.reportes.append(r)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache = None
                        st.session_state.tab_idx = 3   # ir a Historial
                        for k in ["click_lat","click_lon","click_dir",
                                   "punto_lat","punto_lon","punto_dir"]:
                            st.session_state.pop(k, None)
                        st.success("✅ ¡Publicado! Aparece en el mapa y en Historial.")
                        st.rerun()

    # ── TAB 3: Punto Crítico ──────────────────────────────────────────
    with tab_critico:
        if not es_residente():
            st.warning("⚠️ Verifica tu dirección en el campo de arriba para registrar alertas.")
        elif not clat:
            st.info("👆 Primero toca un punto en el mapa.")
        elif not dentro_click:
            st.error("🛑 El punto seleccionado está fuera de la Comuna 2.")
        else:
            plat = clat; plon = clon; pdir = cdir
            st.markdown(f'<div class="badge-err" style="font-size:13px;">🚨 {pdir}</div>',
                        unsafe_allow_html=True)
            st.markdown("")
            t2c1, t2c2 = st.columns(2)
            with t2c1:
                t2_barrio = st.selectbox("Barrio:", BARRIOS, key="t2_barrio")
            with t2c2:
                t2_ref = st.text_input("Referencia:", value=pdir, key="t2_ref")
            t2_img = st.file_uploader("📷 Foto del punto crítico:",
                                      type=["jpg","jpeg","png"], key="t2_img")
            if t2_img:
                img2 = Image.open(t2_img)
                if st.button("🔍 Evaluar con IA", type="primary",
                             use_container_width=True, key="t2_analizar"):
                    with st.spinner("Analizando..."):
                        res2 = analizar(img2)
                    c1t2, c2t2 = st.columns(2)
                    with c1t2:
                        st.image(img2, caption="Original", use_container_width=True)
                    with c2t2:
                        st.image(res2[0].plot(), caption="Detecciones IA",
                                 use_container_width=True)
                    tabla2, res2_r, peso2, tipo2, _ = procesar(res2)
                    total2 = sum(len(r.boxes) for r in res2)
                    nivel2 = ("🔴 Punto crítico alto"   if total2 >= 8
                              else "🟡 Punto crítico medio" if total2 >= 4
                              else "🟢 Punto crítico bajo")
                    metricas(res2_r, peso2, nivel2)
                    if st.button("🚨 REGISTRAR ALERTA", type="primary",
                                 use_container_width=True, key="t2_registrar"):
                        nuevo_crit = {
                            "Código":        f"CRIT-{len(st.session_state.reportes)+500}",
                            "Sector":        t2_barrio,
                            "Referencia":    t2_ref,
                            "Objetos":       total2,
                            "Peso (Kg)":     round(total2 * 0.4, 2),
                            "Predominante":  tipo2 or "Mixto",
                            "Clasificación": nivel2,
                            "Lat": plat, "Lon": plon,
                        }
                        st.session_state.reportes.append(nuevo_crit)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.tab_idx = 3
                        for k in ["click_lat","click_lon","click_dir"]:
                            st.session_state.pop(k, None)
                        st.success("✅ ¡Alerta registrada! Queda guardada permanentemente en el mapa.")
                        st.rerun()

    # ── TAB 4: Historial ─────────────────────────────────────────────
    with tab_historial:
        if st.session_state.reportes:
            df = pd.DataFrame(st.session_state.reportes)
            cols = [c for c in ["Código","Sector","Referencia","Objetos",
                                 "Peso (Kg)","Clasificación","Lat","Lon"]
                    if c in df.columns]
            st.dataframe(df[cols], use_container_width=True, hide_index=True)
            hc1, hc2, hc3 = st.columns(3)
            with hc1:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">'
                            f'{len(df)}</h2><p>Reportes</p></div>', unsafe_allow_html=True)
            with hc2:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">'
                            f'{df["Peso (Kg)"].sum():.1f} kg</h2><p>Carga total</p></div>',
                            unsafe_allow_html=True)
            with hc3:
                crit = df["Clasificación"].str.contains("crítico", case=False, na=False).sum()
                st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">'
                            f'{crit}</h2><p>Puntos críticos</p></div>', unsafe_allow_html=True)

            # ── Marcar reporte como resuelto (lo elimina del mapa) ────
            st.markdown("---")
            st.markdown("**✅ ¿El problema ya fue atendido? Márcalo como resuelto:**")
            codigos = [r["Código"] for r in st.session_state.reportes]
            sel_codigo = st.selectbox("Selecciona el código del reporte:", codigos,
                                      key="hist_sel")
            if st.button("✅ Marcar como RESUELTO y retirar del mapa",
                         use_container_width=True, key="hist_resolver"):
                st.session_state.reportes = [
                    r for r in st.session_state.reportes if r["Código"] != sel_codigo
                ]
                guardar_reportes_disco(st.session_state.reportes)
                st.success(f"✅ Reporte {sel_codigo} marcado como resuelto y retirado del mapa.")
                st.rerun()
        else:
            st.info("Sin reportes aún. Toca el mapa y usa las pestañas para reportar.")

    # ── HISTORIAL ─────────────────────────────────────────────────────
    if st.session_state.reportes:
        st.markdown("---")
        st.markdown("### 📋 Historial de Reportes")
        df = pd.DataFrame(st.session_state.reportes)
        cols = [c for c in ["Código","Sector","Referencia","Objetos",
                             "Peso (Kg)","Clasificación","Lat","Lon"] if c in df.columns]
        st.dataframe(df[cols], use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2>'
                        f'<p>Puntos registrados</p></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">'
                        f'{df["Peso (Kg)"].sum():.1f} kg</h2><p>Carga acumulada</p></div>',
                        unsafe_allow_html=True)
        with c3:
            crit = df["Clasificación"].str.contains("crítico", case=False, na=False).sum()
            st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{crit}</h2>'
                        f'<p>Puntos críticos</p></div>', unsafe_allow_html=True)


# ====================================================================
# 9. PÁGINA: REPORTAR RESIDUO
# ====================================================================
elif menu == "📸 Reportar Residuo":

    # Redirigir si viene del click del mapa
    if st.session_state.tab_activa == "reportar":
        st.session_state.tab_activa = "mapa"

    st.header("📸 Reportar Residuo con IA")

    # Banner estado
    if not es_residente():
        badge("⚠️ Verifica tu dirección en <b>🏠 Inicio y Mapa</b> para poder enviar reportes. "
              "Puedes analizar materiales aunque no estés verificado.", "warn")
    else:
        badge(f"✅ Verificado en la Comuna 2 — {st.session_state.direccion[:60]}", "ok")

    st.markdown("")

    if st.session_state.reporte_ok:
        st.success("🎉 ¡Reporte publicado en el mapa comunitario!")
        if st.button("🔄 Hacer otro reporte", type="primary", use_container_width=True):
            st.session_state.reporte_ok = False
            st.session_state.cache = None
            st.rerun()
        st.stop()

    # ── Formulario ────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        barrio = st.selectbox("Barrio:", BARRIOS)
    with col2:
        referencia = st.text_input("Referencia del lugar:",
                                   placeholder="Ej: Frente al parque, Cra 50 #107")

    # Coordenadas del punto: preferir click del mapa, si no la dirección
    punto_lat = st.session_state.get("punto_lat") or st.session_state.lat or LAT_C
    punto_lon = st.session_state.get("punto_lon") or st.session_state.lon or LON_C

    if st.session_state.get("punto_lat"):
        st.markdown(
            f'<div class="badge-ok" style="font-size:13px;">📌 Punto del mapa: '
            f'<b>{punto_lat:.6f}, {punto_lon:.6f}</b> '
            f'<span style="font-weight:normal">(seleccionado haciendo clic en el mapa)</span></div>',
            unsafe_allow_html=True)
    elif st.session_state.validado:
        st.markdown(
            f'<div class="badge-warn" style="font-size:13px;">📍 Usando tu dirección verificada: '
            f'<b>{punto_lat:.6f}, {punto_lon:.6f}</b> — '
            f'<span style="font-weight:normal">Para mayor precisión, haz clic en el mapa primero.</span></div>',
            unsafe_allow_html=True)

    st.markdown("")
    imagen = st.file_uploader("📷 Sube la fotografía del residuo:", type=["jpg","jpeg","png"])

    if imagen:
        img = Image.open(imagen)

        if st.button("🔍 Analizar con IA", type="primary", use_container_width=True):
            with st.spinner("Analizando con YOLOv8..."):
                resultados = analizar(img)

            # Comparación lado a lado
            st.markdown("### 🔬 Original vs Detecciones")
            co, cd = st.columns(2)
            with co:
                st.markdown("**📷 Imagen original**")
                st.image(img, use_container_width=True)
            with cd:
                st.markdown("**🤖 Detecciones de la IA**")
                st.image(resultados[0].plot(), use_container_width=True)

            tabla, residuos, peso, tipo, nivel = procesar(resultados)

            st.markdown("### 📊 Materiales Detectados")
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
            else:
                st.warning("No se detectaron objetos reconocibles.")

            if residuos > 0:
                metricas(residuos, peso, nivel)

            # Guardar en caché si es residente
            if es_residente() and residuos > 0:
                st.session_state.cache = {
                    "Código":       f"REP-{len(st.session_state.reportes)+200}",
                    "Sector":       barrio,
                    "Referencia":   referencia or "Sin referencia",
                    "Objetos":      residuos,
                    "Peso (Kg)":    peso,
                    "Predominante": tipo,
                    "Clasificación":nivel,
                    "Lat":          punto_lat,
                    "Lon":          punto_lon,
                }
            elif not es_residente():
                badge("🛑 Análisis listo. Verifica tu dirección en <b>🏠 Inicio</b> para enviar el reporte.", "err")

    # Botón enviar
    if st.session_state.cache and es_residente():
        r = st.session_state.cache
        st.markdown("---")
        st.markdown("### ✅ Confirmar y publicar")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"""
**Sector:** {r['Sector']}  
**Referencia:** {r['Referencia']}  
**Reciclables:** {r['Objetos']} objetos  
**Peso estimado:** {r['Peso (Kg)']} kg  
""")
        with c2:
            st.markdown(f"""
**Clasificación:** {r['Clasificación']}  
**Material predominante:** {r['Predominante']}  
**📍 Coordenadas:** {r['Lat']:.6f}, {r['Lon']:.6f}  
""")
        if st.button("🚀 PUBLICAR REPORTE EN EL MAPA", type="primary", use_container_width=True):
            st.session_state.reportes.append(r)
            st.session_state.cache = None
            st.session_state.punto_lat = None
            st.session_state.punto_lon = None
            st.session_state.reporte_ok = True
            st.rerun()


# ====================================================================
# 10. PÁGINA: PUNTO CRÍTICO
# ====================================================================
elif menu == "🚨 Punto Crítico":

    if st.session_state.tab_activa == "critico":
        st.session_state.tab_activa = "mapa"

    st.header("🚨 Registrar Punto Crítico")

    if not es_residente():
        badge("⚠️ Debes verificar tu dirección en <b>🏠 Inicio y Mapa</b> para registrar alertas.", "warn")
        st.stop()

    badge(f"✅ Verificado en la Comuna 2 — {st.session_state.direccion[:60]}", "ok")
    st.markdown("")

    punto_lat = st.session_state.get("punto_lat") or st.session_state.lat or LAT_C
    punto_lon = st.session_state.get("punto_lon") or st.session_state.lon or LON_C

    if st.session_state.get("punto_lat"):
        st.markdown(
            f'<div class="badge-ok" style="font-size:13px;">📌 Punto del mapa: '
            f'<b>{punto_lat:.6f}, {punto_lon:.6f}</b></div>',
            unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        barrio = st.selectbox("Barrio:", BARRIOS, key="barrio_crit")
    with col_b:
        referencia = st.text_input("Referencia exacta:", key="ref_crit",
                                   placeholder="Ej: Esquina Cra 51 con Calle 108")

    imagen = st.file_uploader("📷 Foto del punto:", type=["jpg","jpeg","png"], key="img_crit")

    if imagen:
        img = Image.open(imagen)
        if st.button("🔍 Evaluar con IA", type="primary", use_container_width=True):
            with st.spinner("Analizando..."):
                resultados = analizar(img)

            co, cd = st.columns(2)
            with co:
                st.markdown("**📷 Original**")
                st.image(img, use_container_width=True)
            with cd:
                st.markdown("**🤖 Detecciones**")
                st.image(resultados[0].plot(), use_container_width=True)

            tabla, residuos, peso, tipo, _ = procesar(resultados)
            total = sum(len(r.boxes) for r in resultados)
            nivel = ("🔴 Punto crítico alto"  if total >= 8
                     else "🟡 Punto crítico medio" if total >= 4
                     else "🟢 Punto crítico bajo")

            if tabla:
                df_t = pd.DataFrame(tabla)
                df_si = df_t[df_t["♻️"] == "✅ Sí"]
                if not df_si.empty:
                    st.dataframe(df_si, use_container_width=True, hide_index=True)

            metricas(residuos, peso, nivel)

            if st.button("🚨 REGISTRAR ALERTA EN EL MAPA", type="primary", use_container_width=True):
                st.session_state.reportes.append({
                    "Código":       f"CRIT-{len(st.session_state.reportes)+500}",
                    "Sector":       barrio,
                    "Referencia":   referencia or "Punto crítico",
                    "Objetos":      total,
                    "Peso (Kg)":    round(total * 0.4, 2),
                    "Predominante": tipo or "Mixto",
                    "Clasificación":nivel,
                    "Lat":          punto_lat,
                    "Lon":          punto_lon,
                })
                st.success("✅ ¡Alerta registrada! Aparecerá en el mapa de la sección Inicio.")
                st.session_state.punto_lat = None
                st.session_state.punto_lon = None


# ====================================================================
# 11. INFORMACIÓN
# ====================================================================
elif menu == "ℹ️ Información":
    st.header("ℹ️ EcoCom2 Circular IA")
    st.markdown("""
**EcoCom2 Circular IA** es una plataforma de gestión inteligente de residuos sólidos
para la **Comuna 2 — Santa Cruz, Medellín**.

### 🔐 ¿Cómo funciona la verificación?
1. En **🏠 Inicio y Mapa**, escribe tu dirección (ej: *Cra 50 #107-62, Andalucía*).
2. El sistema la convierte en coordenadas y verifica si estás dentro del polígono oficial.
3. Si estás dentro → puedes reportar. Si no → solo puedes ver el mapa y analizar imágenes.

### 🗺️ Cómo usar el mapa
1. **Haz clic** en el mapa sobre el punto exacto donde está el residuo.
2. Aparecen automáticamente los botones: **Reportar Residuo** o **Punto Crítico**.
3. Se llevan las coordenadas exactas al formulario, sin escribir nada.

### 🤖 Inteligencia Artificial — YOLOv8
- Detecta objetos con confianza desde **8%** para capturar más basura real.
- Muestra resultados en **español** separados: ♻️ Reciclables · ❌ No aprovechables.
- Compara imagen original vs detecciones lado a lado.

### 📍 Los 11 barrios de la Comuna 2
""")
    for b in BARRIOS:
        st.write(f"- 📍 **{b}**")
    st.markdown("""
---
**Versión:** 4.0 | **Proyecto:** Territorio INN 2026 | **ITM Medellín**  
**Desarrollador:** Brandon Duque
""")
