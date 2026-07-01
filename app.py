import streamlit as st
from PIL import Image
import tempfile
import folium
from streamlit_folium import st_folium
import pandas as pd
from shapely.geometry import Point, Polygon
import json, os
from datetime import datetime
import base64
from io import BytesIO
import anthropic

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
    /* ── Fondo principal: blanco roto / crema cálido ─────────────── */
    .stApp {
        background-color: #f0fdf4;
        color: #1a2e1a;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    .block-container { padding-top: 1rem; max-width: 1200px; }

    /* ══════════════════════════════════════════════════════════════
       SIDEBAR — Estrategia: fondo verde oscuro, TODAS las cajas
       que flotan encima también oscuras → texto blanco siempre visible
       ══════════════════════════════════════════════════════════════ */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #166534 0%, #15803d 100%) !important;
        border-right: 3px solid #4ade80;
    }

    [data-testid="stSidebar"] * { color: #f0fdf4 !important; }

    [data-testid="stSidebar"] .stRadio label {
        font-size: 15px !important; font-weight: 600 !important;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
        background: rgba(255,255,255,0.10) !important;
        border-radius: 8px !important; padding: 8px 12px !important;
        margin: 3px 0 !important; transition: background 0.2s !important;
    }
    [data-testid="stSidebar"] .stRadio div[role="radiogroup"] label:hover {
        background: rgba(255,255,255,0.22) !important;
    }

    /* ── BADGES ──────────────────────────────────────────────────── */
    [data-testid="stSidebar"] .badge-ok {
        background: #14532d !important;
        border: 2px solid #4ade80 !important;
        border-radius: 10px !important; padding: 10px 14px !important;
    }
    [data-testid="stSidebar"] .badge-warn {
        background: #451a03 !important;
        border: 2px solid #f59e0b !important;
        border-radius: 10px !important; padding: 10px 14px !important;
    }
    [data-testid="stSidebar"] .badge-err {
        background: #450a0a !important;
        border: 2px solid #f87171 !important;
        border-radius: 10px !important; padding: 10px 14px !important;
    }

    /* ── EXPANDERS (🔐 Admin, 🤖 EcoBot) ─────────────────────────── */
    [data-testid="stSidebar"] details {
        background: rgba(0, 40, 20, 0.70) !important;
        border: 1px solid rgba(74,222,128,0.45) !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] details > summary {
        background: rgba(0, 50, 25, 0.50) !important;
        border-radius: 8px !important;
        padding: 8px 12px !important;
        font-weight: 600 !important;
        cursor: pointer !important;
    }
    [data-testid="stSidebar"] details[open] > summary {
        border-radius: 8px 8px 0 0 !important;
        border-bottom: 1px solid rgba(74,222,128,0.25) !important;
    }
    [data-testid="stSidebar"] details > div {
        background: rgba(0, 40, 20, 0.55) !important;
        border-radius: 0 0 8px 8px !important;
        padding: 8px 6px !important;
    }

    /* ── INPUTS dentro del sidebar ────────────────────────────────── */
    [data-testid="stSidebar"] input[type="text"],
    [data-testid="stSidebar"] input[type="password"],
    [data-testid="stSidebar"] input {
        background: #f0fdf4 !important;
        color: #14532d !important;
        border: 1px solid #4ade80 !important;
        border-radius: 6px !important;
    }

    /* ── FOOTER del sidebar ───────────────────────────────────────── */
    [data-testid="stSidebar"] .ecocom2-footer {
        background: rgba(0, 30, 15, 0.55) !important;
        border: 1px solid rgba(74,222,128,0.35) !important;
        border-radius: 6px !important;
    }

    /* ── Títulos ─────────────────────────────────────────────────── */
    h1 { color: #166534 !important; font-size: 2rem !important; font-weight: 800 !important; }
    h2 { color: #15803d !important; font-weight: 700 !important; }
    h3 { color: #16a34a !important; font-weight: 600 !important; }

    header { background-color: transparent !important; }

    /* ── Cards de métricas ───────────────────────────────────────── */
    .metric-card {
        background: #ffffff;
        border: 2px solid #bbf7d0;
        border-radius: 14px; padding: 18px;
        text-align: center;
        box-shadow: 0 4px 12px rgba(22,163,74,0.10);
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-2px); }
    .metric-card h2, .metric-card h3 { margin: 0 0 4px 0 !important; }
    .metric-card p { color: #4b5563 !important; font-size: 13px !important; margin: 0; }

    /* ── Botones primarios y secundarios ─────────────────────────── */
    div[data-testid="stButton"] button[kind="primary"] {
        background: linear-gradient(135deg, #16a34a, #15803d) !important;
        color: white !important; border: none !important;
        font-weight: 700 !important; font-size: 15px !important;
        border-radius: 10px !important; padding: 10px 20px !important;
        box-shadow: 0 4px 12px rgba(22,163,74,0.35) !important;
        transition: all 0.2s !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 16px rgba(22,163,74,0.45) !important;
    }
    div[data-testid="stButton"] button[kind="secondary"] {
        background: #ffffff !important; color: #166534 !important;
        border: 2px solid #16a34a !important;
        font-weight: 600 !important; border-radius: 10px !important;
    }

    /* ── Elementos Generales ─────────────────────────────────────── */
    div[data-testid="stTextInput"] input {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; font-size: 15px !important;
        background: #ffffff !important; color: #1a2e1a !important;
        padding: 10px 14px !important;
    }
    div[data-testid="stSelectbox"] > div > div {
        border: 2px solid #86efac !important; border-radius: 10px !important; background: #ffffff !important;
    }
    .stTabs [data-baseweb="tab-list"] { background: #dcfce7; border-radius: 10px; padding: 4px; gap: 4px; }
    .stTabs [data-baseweb="tab"] { background: transparent; border-radius: 8px; color: #166534 !important; font-weight: 600; padding: 8px 14px; }
    .stTabs [aria-selected="true"] { background: #16a34a !important; color: white !important; border-radius: 8px; }
    div[data-testid="stExpander"] { border: 1px solid #bbf7d0 !important; border-radius: 10px !important; background: #ffffff !important; margin-bottom: 8px !important; }
    div[data-testid="stDataFrameContainer"] { border: 2px solid #bbf7d0; border-radius: 10px; overflow: hidden; }

    /* ── Info / Warning / Error boxes ───────────────────────────── */
    div[data-testid="stInfo"] { background: #eff6ff !important; border-left: 4px solid #3b82f6 !important; color: #1e3a5f !important; border-radius: 8px !important; }
    div[data-testid="stWarning"] { background: #fefce8 !important; border-left: 4px solid #f59e0b !important; color: #713f12 !important; border-radius: 8px !important; }
    div[data-testid="stSuccess"] { background: #f0fdf4 !important; border-left: 4px solid #16a34a !important; color: #14532d !important; border-radius: 8px !important; }
    div[data-testid="stError"] { background: #fef2f2 !important; border-left: 4px solid #dc2626 !important; color: #7f1d1d !important; border-radius: 8px !important; }
    div[data-testid="stFileUploader"] { background: #f0fdf4 !important; border: 2px dashed #4ade80 !important; border-radius: 12px !important; padding: 16px !important; }

    /* ── Chat del agente (Estilos limpios e independientes) ──────── */
    .chat-burbuja-bot {
        background: #052e16 !important;
        color: #f0fdf4 !important;
        border: 1px solid #4ade80 !important;
        border-radius: 10px !important;
        padding: 10px 14px !important;
        font-size: 13px !important;
        margin-bottom: 8px !important;
    }
    .chat-burbuja-user {
        background: #14532d !important;
        color: #f0fdf4 !important;
        border-radius: 10px !important;
        padding: 10px 14px !important;
        font-size: 13px !important;
        text-align: right !important;
        margin-bottom: 8px !important;
    }

    /* ── Botones de Preguntas Rápidas en Verde ───────────────────── */
    [data-testid="stSidebar"] .stButton button {
        background: linear-gradient(135deg, #16a34a, #15803d) !important;
        border: none !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] .stButton button p {
        color: white !important; 
        font-weight: 600 !important;
    }
    [data-testid="stSidebar"] .stButton button:hover {
        box-shadow: 0 4px 12px rgba(22,163,74,0.45) !important;
    }
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO COMUNA 2 — SANTA CRUZ, MEDELLÍN
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    (-75.5613, 6.2933), (-75.5608, 6.2965), (-75.5598, 6.3005),
    (-75.5585, 6.3055), (-75.5560, 6.3098), (-75.5540, 6.3100),
    (-75.5500, 6.3032), (-75.5498, 6.2980), (-75.5500, 6.2935),
    (-75.5500, 6.2895), (-75.5555, 6.2890), (-75.5590, 6.2895),
    (-75.5613, 6.2933)
])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

LAT_C = 6.3104
LON_C = -75.5552

# ====================================================================
# 3. SESIÓN
# ====================================================================
for k, v in {
    "lat": None, "lon": None, "validado": False, "fuera": True,
    "direccion": "", "reporte_ok": False, "cache": None,
    "seccion": "info",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()

# ====================================================================
# 4. HELPERS DE MAPAS Y CONVERSIÓN
# ====================================================================
@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar(direccion: str):
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v5", timeout=8)
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
        geo = Nominatim(user_agent="ecocom2_v5_rev", timeout=6)
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


def img_a_b64(img_pil, max_px=800) -> str:
    """Convierte una imagen PIL a base64 JPEG thumbnail."""
    try:
        thumb = img_pil.copy()
        thumb.thumbnail((max_px, max_px))
        buf = BytesIO()
        thumb.save(buf, format="JPEG", quality=75)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def es_residente():
    return st.session_state.validado and not st.session_state.fuera


def set_ubicacion(lat, lon, direccion=""):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.validado = True
    st.session_state.fuera = not POLIGONO_COMUNA2.contains(Point(lon, lat))
    st.session_state.direccion = direccion


def badge(txt, tipo="ok"):
    cls = {"ok":"badge-ok","warn":"badge-warn","err":"badge-err"}[tipo]
    st.markdown(f'<div class="{cls}">{txt}</div><br>', unsafe_allow_html=True)


def metricas(residuos, peso, nivel):
    c1, c2, c3 = st.columns(3)
    color = "#4ade80" if "🟢" in nivel else ("#fbbf24" if "🟡" in nivel else "#f87171")
    with c1:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color}">{residuos}</h3>'
                    f'<p style="margin:0;font-size:12px">Objetos Reciclables</p></div>',
                    unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color}">{peso} kg</h3>'
                    f'<p style="margin:0;font-size:12px">Peso estimado</p></div>',
                    unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="metric-card"><h3 style="color:{color};font-size:14px">'
                    f'{nivel}</h3><p style="margin:0;font-size:12px">Clasificación</p></div>',
                    unsafe_allow_html=True)

# ====================================================================
# 5. INTEGRACIÓN IA MULTIMODAL (CLAUDE 3.5 SONNET)
# ====================================================================
def analizar_con_ia_multimodal(img_pil):
    """Envía la imagen a Anthropic para extraer datos de residuos en JSON."""
    b64_img = img_a_b64(img_pil, max_px=800)
    api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
    
    if not api_key:
        st.error("⚠️ Falla técnica: No se ha configurado la API Key de Anthropic en Streamlit Secrets.")
        return None

    prompt = """
    Actúa como un experto en gestión de residuos sólidos para la ciudad de Medellín.
    Analiza la imagen proporcionada y extrae la siguiente información estrictamente en este formato JSON puro, sin texto adicional:
    {
        "materiales": [
            {"Objeto": "nombre del objeto", "Material": "tipo (Plástico/Cartón/Vidrio/Orgánico/Escombros)", "Cant.": 1, "♻️": "✅ Sí" o "❌ No"}
        ],
        "peso_estimado_kg": número_flotante_con_el_peso_total,
        "objetos_reciclables": número_entero_total_de_reciclables_en_la_imagen,
        "tipo_predominante": "Plástico|Cartón|Mixto|Escombros|Orgánico",
        "nivel_urgencia": "🟢 Punto verde — Alta valorización reciclable" o "🟡 Punto amarillo — Residuos mixtos" o "🔴 Punto crítico — Acumulación sin valorización",
        "descripcion": "Breve descripción de máximo 15 palabras de lo que ves"
    }
    Asegúrate de que la salida sea ÚNICAMENTE el JSON.
    """
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=600,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64_img}},
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        texto_json = response.content[0].text.strip()
        # Limpieza de markdown si el modelo lo añade
        if texto_json.startswith("```json"):
            texto_json = texto_json[7:-3].strip()
        elif texto_json.startswith("```"):
            texto_json = texto_json[3:-3].strip()
            
        return json.loads(texto_json)
    except Exception as e:
        st.error(f"Error procesando con la IA Multimodal: {e}")
        return None

# ====================================================================
# 6. BARRA LATERAL
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

PAGINAS = ["🏠 Inicio y Mapa", "🛡️ Panel Admin", "ℹ️ Información"]
menu = st.sidebar.radio("Menú", PAGINAS)

st.sidebar.markdown("---")
es_admin = st.session_state.get("admin_ok", False)

if not es_admin:
    with st.sidebar.expander("🔐 Acceso Administrador"):
        pwd = st.text_input("Contraseña:", type="password", key="adm_pwd",
                            placeholder="Ingresa la contraseña")
        if st.button("Ingresar", key="adm_login", type="primary",
                     use_container_width=True):
            if pwd == "ecocom2admin2026":
                st.session_state.admin_ok = True
                st.success("✅ Sesión iniciada")
                st.rerun()
            else:
                st.error("❌ Contraseña incorrecta")
else:
    st.sidebar.markdown(
        '<div class="badge-ok" style="font-size:12px;margin-bottom:6px;">'
        '🛡️ Admin activo<br>'
        '<span style="font-weight:normal">Brandon Duque · ITM</span></div>',
        unsafe_allow_html=True)
    if st.sidebar.button("🔓 Cerrar sesión", key="adm_logout",
                         use_container_width=True):
        st.session_state.admin_ok = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div class="ecocom2-footer" style="font-size:11px;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
⚙️ <b style="color:#16a34a">EcoCom2 v6.0 (IA Multimodal)</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#16a34a">Brandon Duque</b>
</div>""", unsafe_allow_html=True)


# ====================================================================
# 7. INICIO Y MAPA
# ====================================================================
if menu == "🏠 Inicio y Mapa":
    st.title("♻️ EcoCom2 Circular IA")
    st.caption("Gestión inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    if "agente_msgs" not in st.session_state:
        st.session_state.agente_msgs = [
            {"role": "assistant",
             "content": "¡Hola! 👋 Soy EcoBot, tu asistente de EcoCom2.\n\n¿En qué te ayudo hoy?"}
        ]
    if "agente_pendiente" not in st.session_state:
        st.session_state.agente_pendiente = False

    def llamar_ecobot(mensajes_historial: list) -> str:
        SISTEMA_AGENTE = """Eres EcoBot, el asistente amigable de EcoCom2 Circular IA. 
        Responde en español, CORTA (máximo 3 oraciones), amigable y clara. Usa emojis."""
        try:
            api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
            if not api_key: return "Falta configurar la API de Anthropic."
            client = anthropic.Anthropic(api_key=api_key)
            
            mensajes_api = [{"role": m["role"], "content": m["content"]} for m in mensajes_historial]
            resp = client.messages.create(
                model="claude-3-5-sonnet-20240620", max_tokens=250, system=SISTEMA_AGENTE, messages=mensajes_api
            )
            return resp.content[0].text
        except Exception:
            return "🤖 Sin conexión al asistente. Pasos: 1️⃣ Verifica dirección 2️⃣ Toca el mapa 3️⃣ Sube foto."

    if st.session_state.agente_pendiente:
        st.session_state.agente_pendiente = False
        with st.spinner("🤖 EcoBot está pensando..."):
            respuesta = llamar_ecobot(st.session_state.agente_msgs)
        st.session_state.agente_msgs.append({"role": "assistant", "content": respuesta})
        st.rerun()

    with st.sidebar.expander("🤖 Asistente EcoCom2", expanded=False):
        st.markdown("""
<div class="eco-chat-header-gradient" style="background:linear-gradient(135deg,#4ade80,#16a34a);
border-radius:10px;padding:10px 14px;font-weight:700;
font-size:14px;text-align:center;margin-bottom:10px;">
🤖 Hola, soy EcoBot<br>
<span style="font-weight:400;font-size:12px">Te ayudo a reportar residuos</span>
</div>""", unsafe_allow_html=True)

        # ── SOLUCIÓN DEL CHAT CSS ──────────────────────────────────────
        for msg in st.session_state.agente_msgs[-6:]:
            if msg["role"] == "assistant":
                st.markdown(f'<div class="chat-burbuja-bot">🤖 {msg["content"]}</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="chat-burbuja-user">👤 {msg["content"]}</div>', unsafe_allow_html=True)
        # ───────────────────────────────────────────────────────────────

        pregunta = st.text_input("Pregunta:", placeholder="¿Cómo reporto basura?", key="agente_input", label_visibility="collapsed")
        col_send, col_clear = st.columns([3, 1])
        with col_send:
            enviar = st.button("Enviar ➤", key="agente_enviar", type="primary", use_container_width=True)
        with col_clear:
            if st.button("🗑️", key="agente_limpiar", use_container_width=True, help="Limpiar chat"):
                st.session_state.agente_msgs = [st.session_state.agente_msgs[0]]
                st.rerun()

        if enviar and pregunta.strip():
            st.session_state.agente_msgs.append({"role": "user", "content": pregunta.strip()})
            st.session_state.agente_pendiente = True
            st.rerun()

        st.markdown("<p style='font-size:11px;color:#6b7280;margin:8px 0 4px 0;'>Preguntas rápidas:</p>", unsafe_allow_html=True)
        for pq in ["¿Cómo reporto basura?", "¿Qué significa 🔴 rojo?", "¿Para qué sirve la IA?"]:
            if st.button(pq, key=f"pq_{pq[:15]}", use_container_width=True):
                st.session_state.agente_msgs.append({"role": "user", "content": pq})
                st.session_state.agente_pendiente = True
                st.rerun()

    dir_auto = st.session_state.get("click_dir") or st.session_state.get("direccion") or ""
    c_inp, c_btn = st.columns([5, 1])
    with c_inp:
        dir_inp = st.text_input("📍 Dirección:", value=dir_auto, placeholder="Toca el mapa o escribe...", label_visibility="collapsed", key="dir_campo")
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

    if st.session_state.validado:
        if not st.session_state.fuera:
            badge(f"✅ <b>Dentro de la Comuna 2</b> — {st.session_state.direccion[:80]}", "ok")
        else:
            badge(f"🛑 Fuera de la Comuna 2 — {st.session_state.direccion[:70]}", "err")
        if st.button("🔄 Cambiar dirección", key="cambiar_dir"):
            for k in ["validado","lat","lon","fuera","direccion","click_lat","click_lon","click_dir","punto_lat","punto_lon","cache"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")
    st.markdown("### 🗺️ Toca el punto exacto del residuo en el mapa")

    lat_c = st.session_state.get("lat") or LAT_C
    lon_c = st.session_state.get("lon") or LON_C
    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=14, tiles="CartoDB positron")
    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(locations=coords_p, color="#4ade80", weight=2, fill=True, fill_color="#4ade80", fill_opacity=0.07).add_to(mapa)

    if st.session_state.get("validado") and st.session_state.get("lat"):
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker([st.session_state.lat, st.session_state.lon], icon=folium.Icon(color=col_pin, icon="home", prefix="fa")).add_to(mapa)

    if st.session_state.get("click_lat"):
        folium.Marker([st.session_state.click_lat, st.session_state.click_lon], icon=folium.Icon(color="red", icon="map-marker", prefix="fa")).add_to(mapa)

    for rep in st.session_state.reportes:
        niv = rep.get("Clasificación", "🟢")
        col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
        foto_b64 = rep.get("FotoB64", "")
        img_html = f'<br><img src="data:image/jpeg;base64,{foto_b64}" style="width:180px;border-radius:6px;margin-top:6px;">' if foto_b64 else ""
        popup_html = f"<div style='font-family:sans-serif;min-width:190px;'><b style='color:{col}'>{niv}</b><br><b>{rep['Código']}</b><br>📍 {rep['Sector']}<br>♻️ {rep['Objetos']} obj | ⚖️ {rep['Peso (Kg)']} kg<br>🔖 {rep.get('Estado','')}{img_html}</div>"
        folium.CircleMarker([rep["Lat"], rep["Lon"]], radius=12, color=col, fill=True, fill_color=col, fill_opacity=0.85, popup=folium.Popup(popup_html, max_width=220)).add_to(mapa)

    mapa_data = st_folium(mapa, width="100%", height=340, returned_objects=["last_clicked"])

    if mapa_data and mapa_data.get("last_clicked"):
        clk = mapa_data["last_clicked"]
        st.session_state.click_lat, st.session_state.click_lon = round(clk["lat"], 7), round(clk["lng"], 7)
        st.session_state.click_dir = geocodificar_inversa(st.session_state.click_lat, st.session_state.click_lon)
        if not st.session_state.get("validado"):
            set_ubicacion(st.session_state.click_lat, st.session_state.click_lon, st.session_state.click_dir)
        st.rerun()

    clat, clon, cdir = st.session_state.get("click_lat"), st.session_state.get("click_lon"), st.session_state.get("click_dir", "")
    dentro_clk = POLIGONO_COMUNA2.contains(Point(clon, clat)) if clat else False

    if clat:
        st.markdown("")
        color_card = "#4ade80" if dentro_clk else "#ef4444"
        st.markdown(f'<div style="background:rgba(16,185,129,0.08);border:1px solid {color_card};border-radius:10px;padding:12px 16px;margin-bottom:10px;"><span style="color:{color_card};font-weight:bold;font-size:14px;">📌 {cdir}</span></div>', unsafe_allow_html=True)

        if dentro_clk and es_residente():
            st.markdown("")
            bc1, bc2, bc3 = st.columns([2, 2, 1])
            with bc1:
                if st.button("📸 Reportar Residuo", type="primary", use_container_width=True):
                    st.session_state.seccion = "residuo"
                    st.rerun()
            with bc2:
                if st.button("🚨 Punto Crítico", use_container_width=True):
                    st.session_state.seccion = "critico"
                    st.rerun()
            with bc3:
                if st.button("✖", use_container_width=True):
                    for k in ["click_lat","click_lon","click_dir","cache"]: st.session_state.pop(k, None)
                    st.rerun()
        elif clat and not es_residente():
            badge("⚠️ Verifica tu dirección arriba para reportar en este punto.", "warn")

    seccion = st.session_state.get("seccion", "info")
    if seccion != "info":
        iconos = {"residuo": "📸 Reportar Residuo", "critico": "🚨 Punto Crítico", "historial": "📋 Historial"}
        st.markdown(f'<div style="border-bottom:2px solid #4ade80;padding:6px 0 4px 0;color:#4ade80;font-weight:bold;font-size:15px;margin-bottom:12px;">{iconos.get(seccion,"")}</div>', unsafe_allow_html=True)

    # ── SECCIÓN: REPORTAR CON IA MULTIMODAL ──────────────────────────
    if seccion == "residuo":
        st.markdown("### 📸 Reportar Residuo (IA Multimodal Avanzada)")
        plat, plon, pdir = clat, clon, cdir
        badge(f"📌 {pdir}", "ok")

        r1, r2 = st.columns(2)
        with r1: r_barrio = st.selectbox("Barrio:", BARRIOS, key="r_barrio")
        with r2: r_ref = st.text_input("Referencia:", value=pdir, key="r_ref")

        r_img = st.file_uploader("📷 Foto del residuo:", type=["jpg","jpeg","png"], key="r_img")
        if r_img:
            img = Image.open(r_img)
            if st.button("🔍 Analizar Fotografía con IA", type="primary", use_container_width=True):
                with st.spinner("🤖 Claude 3.5 analizando la composición, peso y urgencia..."):
                    datos_ia = analizar_con_ia_multimodal(img)
                
                if datos_ia:
                    st.image(img, use_container_width=True, caption=datos_ia.get("descripcion", "Imagen analizada"))
                    
                    df_materiales = pd.DataFrame(datos_ia.get("materiales", []))
                    if not df_materiales.empty:
                        st.markdown("**🔍 Desglose de Materiales Detectados:**")
                        st.dataframe(df_materiales, use_container_width=True, hide_index=True)
                    
                    peso = datos_ia.get("peso_estimado_kg", 0.0)
                    residuos = datos_ia.get("objetos_reciclables", 0)
                    nivel = datos_ia.get("nivel_urgencia", "🟢 Punto verde — Alta valorización reciclable")
                    tipo = datos_ia.get("tipo_predominante", "Mixto")
                    
                    metricas(residuos, peso, nivel)

                    st.session_state.cache = {
                        "Código": f"REP-{len(st.session_state.reportes)+200}",
                        "Sector": r_barrio, "Referencia": r_ref,
                        "Objetos": residuos, "Peso (Kg)": peso,
                        "Predominante": tipo, "Clasificación": nivel,
                        "Lat": plat, "Lon": plon,
                        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Estado": "🔴 Pendiente",
                        "FotoB64": img_a_b64(img, max_px=200), # Pequeña para el mapa
                    }

        if st.session_state.get("cache"):
            r = st.session_state.cache
            cp, cc = st.columns(2)
            with cp:
                if st.button("🚀 PUBLICAR EN EL MAPA", type="primary", use_container_width=True):
                    st.session_state.reportes.append(r)
                    guardar_reportes_disco(st.session_state.reportes)
                    st.session_state.cache = None
                    st.session_state.seccion = "historial"
                    for k in ["click_lat","click_lon","click_dir"]: st.session_state.pop(k, None)
                    st.success("✅ ¡Publicado en la Nube Comunitaria!")
                    st.rerun()
            with cc:
                if st.button("❌ Cancelar", use_container_width=True):
                    st.session_state.cache = None
                    st.rerun()

    elif seccion == "critico":
        st.markdown("### 🚨 Registrar Punto Crítico (IA Multimodal)")
        plat, plon, pdir = clat, clon, cdir
        cr1, cr2 = st.columns(2)
        with cr1: cr_barrio = st.selectbox("Barrio:", BARRIOS, key="cr_barrio")
        with cr2: cr_ref = st.text_input("Referencia:", value=pdir, key="cr_ref")

        cr_img = st.file_uploader("📷 Foto del punto crítico:", type=["jpg","jpeg","png"], key="cr_img")
        if cr_img:
            img2 = Image.open(cr_img)
            if st.button("🔍 Evaluar Riesgo con IA", type="primary", use_container_width=True):
                with st.spinner("🤖 Evaluando acumulación y material..."):
                    datos_ia2 = analizar_con_ia_multimodal(img2)
                st.session_state.cache_foto_b64 = img_a_b64(img2, max_px=200)

                if datos_ia2:
                    st.image(img2, use_container_width=True, caption=datos_ia2.get("descripcion", ""))
                    df_mat2 = pd.DataFrame(datos_ia2.get("materiales", []))
                    if not df_mat2.empty:
                        st.dataframe(df_mat2, use_container_width=True, hide_index=True)

                    st.session_state.cache_critico = {
                        "residuos": datos_ia2.get("objetos_reciclables", 0),
                        "peso": datos_ia2.get("peso_estimado_kg", 0.0),
                        "tipo": datos_ia2.get("tipo_predominante", "Mixto"),
                        "nivel": datos_ia2.get("nivel_urgencia", "🔴 Punto crítico — Acumulación sin valorización"),
                        "Lat": plat, "Lon": plon
                    }

            if st.session_state.get("cache_critico"):
                cc = st.session_state.cache_critico
                metricas(cc["residuos"], cc["peso"], cc["nivel"])
                st.markdown("")
                cr_pub, cr_can = st.columns(2)
                with cr_pub:
                    if st.button("🚨 REGISTRAR ALERTA EN EL MAPA", type="primary", use_container_width=True):
                        nuevo = {
                            "Código": f"CRIT-{len(st.session_state.reportes)+500}",
                            "Sector": cr_barrio, "Referencia": cr_ref,
                            "Objetos": cc["residuos"], "Peso (Kg)": cc["peso"],
                            "Predominante": cc["tipo"], "Clasificación": cc["nivel"],
                            "Lat": cc["Lat"], "Lon": cc["Lon"],
                            "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            "Estado": "🔴 Pendiente",
                            "FotoB64": st.session_state.get("cache_foto_b64", ""),
                        }
                        st.session_state.reportes.append(nuevo)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache_critico = None
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir"]: st.session_state.pop(k, None)
                        st.success("✅ ¡Alerta registrada permanentemente!")
                        st.rerun()
                with cr_can:
                    if st.button("❌ Cancelar", use_container_width=True):
                        st.session_state.cache_critico = None
                        st.rerun()

    elif seccion == "historial":
        st.markdown("### 📋 Historial de Reportes")
        if not st.session_state.reportes:
            st.info("Sin reportes aún.")
        else:
            df = pd.DataFrame(st.session_state.reportes)
            h1, h2, h3, h4 = st.columns(4)
            pendientes = df.get("Estado", pd.Series([])).str.contains("Pendiente", na=False).sum() if "Estado" in df.columns else len(df)
            resueltos  = df.get("Estado", pd.Series([])).str.contains("Resuelto",  na=False).sum() if "Estado" in df.columns else 0
            crit = df["Clasificación"].str.contains("crítico", case=False, na=False).sum()
            with h1: st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2><p>Total</p></div>', unsafe_allow_html=True)
            with h2: st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{crit}</h2><p>Críticos 🔴</p></div>', unsafe_allow_html=True)
            with h3: st.markdown(f'<div class="metric-card"><h2 style="color:#fbbf24">{pendientes}</h2><p>Pendientes</p></div>', unsafe_allow_html=True)
            with h4: st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{resueltos}</h2><p>Resueltos ✅</p></div>', unsafe_allow_html=True)
            st.markdown("")
            COLS = ["Código","Fecha","Estado","Sector","Referencia","Objetos","Peso (Kg)","Clasificación"]
            cols_ok = [c for c in COLS if c in df.columns]
            st.dataframe(df[cols_ok], use_container_width=True, hide_index=True)

# ====================================================================
# 9. PANEL ADMINISTRADOR
# ====================================================================
elif menu == "🛡️ Panel Admin":
    if not st.session_state.get("admin_ok"):
        st.markdown("")
        col_login = st.columns([1, 2, 1])[1]
        with col_login:
            st.markdown('<div style="background:rgba(16,185,129,0.08);border:1px solid #4ade80;border-radius:14px;padding:32px 28px;text-align:center;"><h2 style="color:#4ade80;margin-bottom:4px;">🛡️ Panel Admin</h2><p style="color:#9ca3af;font-size:14px;margin-bottom:20px;">EcoCom2 Circular IA · ITM Medellín</p></div>', unsafe_allow_html=True)
            st.markdown("")
            pwd_input = st.text_input("Contraseña de administrador:", type="password", key="login_pwd")
            if st.button("🔐 Iniciar sesión", type="primary", use_container_width=True):
                if pwd_input == "ecocom2admin2026":
                    st.session_state.admin_ok = True
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")
        st.stop()

    st.markdown('<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;"><div><h1 style="color:#4ade80;margin:0;">🛡️ Panel de Administración</h1><p style="color:#9ca3af;margin:0;font-size:13px;">EcoCom2 Circular IA · Comuna 2 Santa Cruz · ITM Medellín</p></div></div>', unsafe_allow_html=True)

    accion = st.session_state.pop("adm_accion_pendiente", None)
    if accion:
        cod_obj = accion["codigo"]
        tipo_acc = accion["tipo"]
        if tipo_acc == "estado":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj: r["Estado"] = accion["valor"]; break
        elif tipo_acc == "resuelto":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj: r["Estado"] = "✅ Resuelto"; break
        elif tipo_acc == "eliminar":
            st.session_state.reportes = [r for r in st.session_state.reportes if r["Código"] != cod_obj]
        elif tipo_acc == "en_proceso":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj: r["Estado"] = "🟡 En proceso de recolección"; break
        guardar_reportes_disco(st.session_state.reportes)
        st.rerun()

    reportes = st.session_state.reportes
    tab_dash, tab_mapa, tab_lista, tab_export = st.tabs(["📊 Dashboard", "🗺️ Mapa de control", "🗂️ Gestión de reportes", "📥 Exportar / Limpiar"])

    with tab_dash:
        if not reportes:
            st.info("Sin reportes aún.")
        else:
            df_a = pd.DataFrame(reportes)
            total = len(df_a)
            criticos = int(df_a["Clasificación"].str.contains("crítico", case=False, na=False).sum())
            amarillos= int(df_a["Clasificación"].str.contains("amarillo", case=False, na=False).sum())
            verdes   = int(df_a["Clasificación"].str.contains("verde", case=False, na=False).sum())
            peso_t   = float(df_a["Peso (Kg)"].sum())
            pendientes = int(df_a["Estado"].str.contains("Pendiente", na=False).sum()) if "Estado" in df_a.columns else total
            resueltos  = int(df_a["Estado"].str.contains("Resuelto", na=False).sum()) if "Estado" in df_a.columns else 0

            k1,k2,k3,k4,k5,k6 = st.columns(6)
            for col, val, label, color in [(k1, total, "Total", "#4ade80"), (k2, criticos, "🔴 Críticos", "#f87171"), (k3, amarillos, "🟡 Mixtos", "#fbbf24"), (k4, verdes, "🟢 Reciclables","#4ade80"), (k5, pendientes, "⏳ Pendientes", "#fb923c"), (k6, resueltos, "✅ Resueltos", "#34d399")]:
                with col: st.markdown(f'<div class="metric-card"><h2 style="color:{color};margin:0">{val}</h2><p style="font-size:11px;margin:4px 0 0 0;color:#9ca3af">{label}</p></div>', unsafe_allow_html=True)
            st.markdown(f'<div style="background:rgba(167,139,250,0.1);border:1px solid #a78bfa;border-radius:8px;padding:10px 16px;margin-top:12px;font-size:14px;">⚖️ <b style="color:#a78bfa">Carga total acumulada: {peso_t:.1f} kg</b> en {total} reportes</div>', unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("#### 📍 Reportes por Barrio")
            if "Sector" in df_a.columns:
                conteo_barrio = df_a["Sector"].value_counts().reset_index()
                conteo_barrio.columns = ["Barrio", "Reportes"]
                st.dataframe(conteo_barrio, use_container_width=True, hide_index=True)

    with tab_mapa:
        if not reportes:
            st.info("Sin reportes aún.")
        else:
            mapa_adm = folium.Map(location=[LAT_C, LON_C], zoom_start=14, tiles="CartoDB positron")
            coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
            folium.Polygon(locations=coords_p, color="#4ade80", weight=2, fill=True, fill_color="#4ade80", fill_opacity=0.06).add_to(mapa_adm)
            for rep in reportes:
                niv = rep.get("Clasificación", "")
                est = rep.get("Estado", "")
                col = "red" if "🔴" in niv else ("orange" if "🟡" in niv else "green")
                if "Resuelto" in est: col = "gray"
                foto_b64 = rep.get("FotoB64", "")
                img_html  = f'<br><img src="data:image/jpeg;base64,{foto_b64}" style="width:160px;border-radius:4px;margin-top:4px;">' if foto_b64 else ""
                popup_adm = f"<div style='font-family:sans-serif;min-width:190px;'><b style='color:{col}'>{niv}</b><br><b>{rep['Código']}</b><br>📍 {rep.get('Sector','')} · {rep.get('Referencia','')[:35]}<br>♻️ {rep.get('Objetos',0)} obj | ⚖️ {rep.get('Peso (Kg)',0)} kg<br>🕐 {rep.get('Fecha','')} | 🔖 {est}{img_html}</div>"
                folium.CircleMarker(location=[rep["Lat"], rep["Lon"]], radius=13, color=col, fill=True, fill_color=col, fill_opacity=0.85, popup=folium.Popup(popup_adm, max_width=220)).add_to(mapa_adm)
            st_folium(mapa_adm, width="100%", height=480, returned_objects=[])

    with tab_lista:
        if not reportes:
            st.info("Sin reportes aún.")
        else:
            ESTADOS = ["🔴 Pendiente","🟡 En proceso de recolección","✅ Resuelto"]
            for rep in list(reportes):
                codigo = rep["Código"]
                key_safe = codigo.replace(" ","_").replace("/","_").replace("-","_")
                estado = rep.get("Estado","🔴 Pendiente")
                nivel = rep.get("Clasificación","")
                icono = "🔴" if "crítico" in nivel.lower() else ("🟡" if "amarillo" in nivel.lower() else "🟢")
                if "Resuelto" in estado: icono = "✅"
                if "proceso"  in estado: icono = "🟡"

                with st.expander(f"{icono} {codigo} · {rep.get('Sector','?')} · {rep.get('Referencia','')[:30]} · {estado}", expanded=False):
                    foto_b64 = rep.get("FotoB64","")
                    if foto_b64:
                        st.markdown(f'<img src="data:image/jpeg;base64,{foto_b64}" style="max-width:320px;border-radius:8px;margin-bottom:10px;">', unsafe_allow_html=True)
                    i1, i2 = st.columns(2)
                    with i1: st.markdown(f"**Código:** {codigo}  \n**Barrio:** {rep.get('Sector','—')}  \n**Referencia:** {rep.get('Referencia','—')}")
                    with i2: st.markdown(f"**Clasificación:** {nivel}  \n**Peso:** {rep.get('Peso (Kg)',0)} kg  \n**Material:** {rep.get('Predominante','—')}")
                    idx_est = ESTADOS.index(estado) if estado in ESTADOS else 0
                    nuevo_estado = st.selectbox("",ESTADOS,index=idx_est, label_visibility="collapsed", key=f"sel_{key_safe}")
                    b1,b2,b3,b4 = st.columns(4)
                    with b1:
                        if st.button("💾 Guardar",key=f"grd_{key_safe}", use_container_width=True): st.session_state.adm_accion_pendiente={"codigo":codigo,"tipo":"estado","valor":nuevo_estado}; st.rerun()
                    with b3:
                        if st.button("✅ Resuelto",key=f"res_{key_safe}", type="primary",use_container_width=True): st.session_state.adm_accion_pendiente={"codigo":codigo,"tipo":"resuelto"}; st.rerun()
                    with b4:
                        if st.button("🗑️ Eliminar",key=f"del_{key_safe}", use_container_width=True): st.session_state.adm_accion_pendiente={"codigo":codigo,"tipo":"eliminar"}; st.rerun()

    with tab_export:
        if reportes:
            df_exp = pd.DataFrame(reportes)
            cols_exp = [c for c in df_exp.columns if c != "FotoB64"]
            csv_bytes = df_exp[cols_exp].to_csv(index=False).encode("utf-8")
            st.download_button("📥 Descargar CSV", data=csv_bytes, file_name=f"ecocom2_reportes.csv", mime="text/csv", use_container_width=True)
            if st.button("🗑️ ELIMINAR todos los ✅ Resueltos del mapa", use_container_width=True):
                st.session_state.reportes = [r for r in st.session_state.reportes if "Resuelto" not in r.get("Estado","")]
                guardar_reportes_disco(st.session_state.reportes)
                st.success("Limpieza completa.")
                st.rerun()

elif menu == "ℹ️ Información":
    st.title("♻️ EcoCom2 Circular IA")
    st.markdown('<div style="background:rgba(16,185,129,0.1);border:1px solid #4ade80;border-radius:10px;padding:16px;margin-bottom:20px;font-size:15px;">🌱 <b style="color:#4ade80">Plataforma de Gestión Inteligente de Residuos</b><br>Tecnología IA al servicio de una <b>Comuna 2 más limpia y sostenible</b>.</div>', unsafe_allow_html=True)
    st.markdown("## 🤖 ¿Cómo funciona la IA Multimodal?")
    st.markdown("EcoCom2 usa **Claude 3.5 Sonnet**, un modelo cognitivo de visión artificial avanzado. Al subir una foto, la IA analiza el contexto completo de los residuos para estimar peso, materiales reciclables y urgencia, generando reportes de alta precisión.")
    st.markdown("""
<div style="background:rgba(16,185,129,0.06);border:1px solid rgba(74,222,128,0.2);border-radius:10px;padding:16px;text-align:center;color:#9ca3af;font-size:13px;">
⚙️ <b style="color:#4ade80">EcoCom2 Circular IA v6.0</b><br>
Proyecto <b style="color:#4ade80">Territorio INN 2026</b> · Instituto Tecnológico Metropolitano (ITM) · Medellín<br>
Desarrollado por: <b style="color:#4ade80">Brandon Duque</b> · Comuna 2 Santa Cruz
</div>
""", unsafe_allow_html=True)
