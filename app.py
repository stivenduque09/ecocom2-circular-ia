import streamlit as st
from ultralytics import YOLO, YOLOE
from PIL import Image, ImageFilter, ImageOps
import tempfile
from collections import Counter
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium
import pandas as pd
from shapely.geometry import Point, Polygon
import json, os
from urllib.parse import quote as url_quote
import sqlite3
import unicodedata
import difflib
from pathlib import Path
from datetime import datetime
import base64
from io import BytesIO
from streamlit_js_eval import get_geolocation
import imagehash
from math import radians, sin, cos, sqrt, atan2
import re
import time
import hashlib  # MEJORA 4 — para detectar si una foto ya fue analizada
import hmac            # SEGURIDAD — comparación de contraseña en tiempo constante
import html as _html   # SEGURIDAD — escapar texto de usuarios antes de pintarlo como HTML
import logging         # SEGURIDAD — dejar rastro de errores en vez de tragárselos en silencio
import threading       # SEGURIDAD — evitar escrituras simultáneas a la base de datos
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger("ecocom2")

# ====================================================================
# SEGURIDAD — constantes y utilidades (tomadas/adaptadas de app v8)
# ====================================================================
MAX_INTENTOS_ADMIN = 5
BLOQUEO_ADMIN_SEGUNDOS = 300          # 5 min de bloqueo tras demasiados intentos
MAX_BYTES_FOTO = 8 * 1024 * 1024      # 8 MB por foto
MAX_PIXELES_FOTO = 40_000_000         # evita "bombas de descompresión"
MAX_LADO_FOTO = 1600                  # lado mayor al que se reducen las fotos para analizarlas
MAX_LARGO_MENSAJE_BOT = 500           # caracteres por mensaje a EcoBot
MAX_MENSAJES_BOT_HORA = 30            # mensajes a EcoBot por sesión y hora
MAX_LARGO_TEXTO_LIBRE = 600           # observaciones / referencia

_LOCK_DB = threading.Lock()


def esc(valor) -> str:
    """Escapa cualquier texto escrito por un usuario antes de meterlo en HTML
    (unsafe_allow_html, popups de folium, etc.). Evita XSS almacenado: sin
    esto, una 'Referencia' como <img src=x onerror=...> se ejecutaría en el
    navegador de TODO el que abra el mapa, incluido el administrador."""
    return _html.escape(str(valor if valor is not None else ""), quote=True)


def limpiar_texto_libre(txt: str, max_len: int = MAX_LARGO_TEXTO_LIBRE) -> str:
    """Quita caracteres de control y recorta el largo de un texto libre."""
    txt = "".join(ch for ch in (txt or "") if ch == "\n" or ch >= " ")
    # Sin enlaces: el mapa es público y alguien podría pegar un link de phishing/spam
    txt = re.sub(r"(https?://|www\.)\S+", "[enlace eliminado]", txt, flags=re.IGNORECASE)
    # Sin celulares: un número escrito en 'Observaciones' queda visible en el mapa público
    txt = re.sub(r"(?<!\d)(?:\+?57[\s.-]?)?3\d{2}[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)",
                 "[número oculto]", txt)
    return txt.strip()[:max_len]


def seguro_excel(valor):
    """Evita 'inyección de fórmulas' en Excel: si un texto empieza con = + - @
    Excel lo ejecutaría como fórmula al abrir el archivo. Se antepone un
    apóstrofo para que se lea como texto."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2300-\u23FF\u2600-\u27BF\u2B00-\u2BFF"
    "\uFE0F\u200D\u20E3\u2139\u2122]")


def sin_emojis(txt):
    """Quita emojis de un texto (por ejemplo, de reportes viejos guardados
    cuando la app los usaba) y deja los espacios ordenados."""
    if not isinstance(txt, str):
        return txt
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", txt)).strip()


def semaforo(niv) -> str:
    """Devuelve 'rojo', 'amarillo' o 'verde' a partir del texto de
    clasificación. Reconoce las palabras (crítico / amarillo / verde) y
    también los reportes antiguos que traen el círculo de color."""
    t = str(niv or "").lower()
    if "\U0001F534" in t or "crítico" in t or "critico" in t or "rojo" in t:
        return "rojo"
    if "\U0001F7E1" in t or "amarillo" in t or "mixto" in t:
        return "amarillo"
    return "verde"


def _sal_respaldo() -> str:
    """Secreto para ocultar los teléfonos en el respaldo. Se configura en
    Secrets como BACKUP_SALT (cualquier texto largo y secreto)."""
    try:
        sal = str(st.secrets.get("BACKUP_SALT", "")).strip()
    except Exception:
        sal = ""
    return sal or os.environ.get("ECOCOM2_BACKUP_SALT", "").strip()


def pseudonimo_residente(codigo: str) -> str:
    """Convierte el teléfono/código de un residente en una 'huella' que no se
    puede revertir (HMAC-SHA256 con secreto). Sirve para reconocer al mismo
    residente sin publicar su número. Sin BACKUP_SALT devuelve '' (el dato
    simplemente no se respalda: privacidad primero)."""
    codigo = (codigo or "").strip().lower()
    sal = _sal_respaldo()
    if not codigo or not sal:
        return ""
    if codigo.startswith("h:"):
        return codigo
    return "h:" + hmac.new(sal.encode("utf-8"), codigo.encode("utf-8"),
                           hashlib.sha256).hexdigest()[:32]


def coincide_residente(guardado, buscado) -> bool:
    """True si el código/teléfono 'buscado' corresponde al guardado en un
    reporte, ya sea guardado en claro o como huella (reportes restaurados)."""
    g = (guardado or "").strip().lower()
    b = (buscado or "").strip().lower()
    if not g or not b:
        return False
    if g == b:
        return True
    if g.startswith("h:"):
        h = pseudonimo_residente(b)
        return bool(h) and hmac.compare_digest(g, h)
    return False


def contacto_visible(valor) -> str:
    """Para exportar: no mostrar huellas como si fueran teléfonos."""
    v = (valor or "")
    return "(protegido)" if str(v).startswith("h:") else v


def solo_b64(valor) -> str:
    """Deja únicamente caracteres válidos de base64 (nada que rompa un src=)."""
    return re.sub(r"[^A-Za-z0-9+/=]", "", str(valor or ""))


def nombre_archivo_seguro(nombre: str) -> str:
    """Deja solo letras, números, guion y punto — sin rutas ni '..'."""
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(nombre or ""))
    return base.lstrip(".")[:80] or "archivo.jpg"

# ====================================================================
# PERSISTENCIA — SQLite en vez de JSON en /tmp
# ====================================================================
DB_PATH = Path(__file__).resolve().parent / "data" / "ecocom2.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_CAMPOS    = ["Código","Sector","Referencia","Objetos","Peso (Kg)",
              "Predominante","Clasificación","Lat","Lon","Fecha","Estado","FotoB64",
              "Observaciones","NotaVozB64","FotosExtraB64","CodigoResidente","PHash",
              "Confirmaciones","FotoClasificadaB64","FotoResueltaB64","FotoResueltaURL",
              "FechaResuelto","ReportesFalsos","FotoURL","FotoClasificadaURL"]
_COLUMNAS  = ["codigo","sector","referencia","objetos","peso_kg",
              "predominante","clasificacion","lat","lon","fecha","estado","foto_b64",
              "observaciones","nota_voz_b64","fotos_extra_b64","residente_codigo","phash",
              "confirmaciones","foto_clasificada_b64","foto_resuelta_b64","foto_resuelta_url",
              "fecha_resuelto","reportes_falsos","foto_url","foto_clasificada_url"]

def _conectar_db():
    """Conexión SQLite segura ante varias sesiones a la vez: modo WAL (los
    lectores no bloquean al escritor) y espera de hasta 30 s si la base está
    ocupada, en vez de fallar al instante y perder el reporte."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except sqlite3.Error:
        pass
    return conn

def _crear_tabla():
    try:
        with _conectar_db() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reportes (
                    codigo TEXT PRIMARY KEY,
                    sector TEXT,
                    referencia TEXT,
                    objetos INTEGER,
                    peso_kg REAL,
                    predominante TEXT,
                    clasificacion TEXT,
                    lat REAL,
                    lon REAL,
                    fecha TEXT,
                    estado TEXT,
                    foto_b64 TEXT,
                    observaciones TEXT
                )
            """)
            # Migración suave: agregar columnas nuevas si la tabla ya
            # existía de una versión anterior. SQLite no soporta
            # "ADD COLUMN IF NOT EXISTS", así que intentamos y
            # silenciamos el error si la columna ya existe.
            for col_sql in ["observaciones TEXT", "nota_voz_b64 TEXT",
                            "fotos_extra_b64 TEXT", "residente_codigo TEXT",
                            "phash TEXT", "confirmaciones INTEGER DEFAULT 0",
                            "foto_clasificada_b64 TEXT", "foto_resuelta_b64 TEXT",
                            "foto_resuelta_url TEXT", "fecha_resuelto TEXT",
                            "reportes_falsos INTEGER DEFAULT 0",
                            "foto_url TEXT", "foto_clasificada_url TEXT"]:
                try:
                    conn.execute(f"ALTER TABLE reportes ADD COLUMN {col_sql}")
                except Exception:
                    pass
    except Exception as e:
        _log.error("No se pudo crear/migrar la tabla de reportes: %s", e)

_crear_tabla()

def cargar_reportes_disco():
    try:
        with _conectar_db() as conn:
            filas = conn.execute("SELECT * FROM reportes ORDER BY fecha ASC").fetchall()
        lista = [
            {campo: fila[col] for campo, col in zip(_CAMPOS, _COLUMNAS)}
            for fila in filas
        ]
        for r in lista:   # reportes antiguos traen emojis: se limpian al leerlos
            for k in ("Estado", "Clasificación", "Predominante"):
                if k in r:
                    r[k] = sin_emojis(r[k])
        return lista
    except Exception as e:
        _log.error("No se pudieron cargar los reportes: %s", e)
        return []

def _guardar_sqlite(reportes, eliminados=None, borrar_todo=False):
    """Escribe los reportes en la base SQLite local.

    ANTES esta función hacía DELETE de toda la tabla y reinsertaba lo que
    hubiera en la memoria de ESA sesión. Con dos personas usando la app a la
    vez, quien guardaba segundo borraba los reportes nuevos de la otra, y
    cualquier error se tragaba en silencio. AHORA:
      - Hace UPSERT (inserta o actualiza) reporte por reporte, en una sola
        transacción.
      - Solo borra lo que se le pide explícitamente (eliminados) o todo si
        borrar_todo=True (zona de peligro del admin).
    Devuelve True si guardó bien, False si falló (y deja el error en el log).
    """
    try:
        with _LOCK_DB:
            with _conectar_db() as conn:
                if borrar_todo:
                    conn.execute("DELETE FROM reportes")
                elif eliminados:
                    conn.executemany("DELETE FROM reportes WHERE codigo = ?",
                                     [(c,) for c in eliminados])
                if reportes:
                    conn.executemany(
                        f"INSERT OR REPLACE INTO reportes ({','.join(_COLUMNAS)}) "
                        f"VALUES ({','.join('?' * len(_COLUMNAS))})",
                        [tuple(r.get(campo) for campo in _CAMPOS) for r in reportes]
                    )
        return True
    except Exception as e:
        _log.error("Fallo guardando en SQLite: %s", e)
        return False


def _sincronizar_con_db(reportes, eliminados=None):
    """Trae a la lista en memoria los reportes que OTRAS sesiones hayan
    guardado en la base y esta sesión todavía no conoce, para que al guardar
    no se pierdan ni se sobrescriban. Modifica 'reportes' en el lugar."""
    try:
        excluidos = set(eliminados or [])
        conocidos = {r.get("Código") for r in reportes}
        for r_db in cargar_reportes_disco():
            cod = r_db.get("Código")
            if cod and cod not in conocidos and cod not in excluidos:
                reportes.append(r_db)
    except Exception as e:
        _log.error("Fallo sincronizando con la base: %s", e)


def generar_codigo(prefijo: str, base: int) -> str:
    """Genera un código único (REP-205, CRIT-512...). ANTES se usaba
    len(reportes)+base: si el admin borraba un reporte, el siguiente nuevo
    repetía un código ya existente y, con INSERT OR REPLACE, habría
    SOBRESCRITO el reporte de otra persona (y su foto en GitHub)."""
    usados = {r.get("Código") for r in st.session_state.get("reportes", [])}
    try:
        usados |= {r.get("Código") for r in cargar_reportes_disco()}
    except Exception:
        pass
    numeros = [int(m.group(1)) for c in usados if c
               for m in [re.match(rf"^{re.escape(prefijo)}-(\d+)$", c)] if m]
    n = max(numeros + [base - 1]) + 1
    return f"{prefijo}-{n}"


RESPALDO_PATH_REPO = "data_backup/reportes_backup.json"
# Campos livianos para el respaldo — a propósito NO incluye FotoB64,
# NotaVozB64 ni FotosExtraB64 (pesan mucho en base64 y harían crecer el
# historial de git muy rápido). Si el contenedor se borra por completo,
# el respaldo recupera el 100% de la ubicación/estado/clasificación de
# cada reporte — solo se pierden las imágenes, no los datos operativos.
_CAMPOS_RESPALDO = ["Código","Sector","Referencia","Objetos","Peso (Kg)",
                    "Predominante","Clasificación","Lat","Lon","Fecha","Estado",
                    "Observaciones","CodigoResidente","Confirmaciones",
                    "FechaResuelto","FotoResueltaURL","ReportesFalsos",
                    "FotoURL","FotoClasificadaURL"]


def _github_config():
    """Lee la configuración del respaldo desde st.secrets. Si no está
    configurada, devuelve (None, None, None) — el respaldo queda
    simplemente desactivado, sin romper nada del resto de la app."""
    try:
        token = st.secrets.get("GITHUB_TOKEN", "").strip()
        repo = st.secrets.get("GITHUB_REPO", "").strip()
        branch = (str(st.secrets.get("GITHUB_BRANCH_DATOS", "")).strip()
                  or st.secrets.get("GITHUB_BRANCH", "main").strip() or "main")
        if token and repo:
            return token, repo, branch
    except Exception:
        pass
    return None, None, None


def respaldar_en_github(reportes: list):
    """Sube un respaldo liviano de los reportes (sin fotos/audio) a un
    archivo JSON dentro del propio repositorio de GitHub. Como Streamlit
    Cloud clona el repo desde cero en cada reinicio, este respaldo
    sobrevive aunque el disco del contenedor se borre por completo.

    Devuelve (True, "") si funcionó, o (False, "motivo del error") si
    no — antes esta función fallaba en silencio y el botón manual
    mostraba 'éxito' aunque el respaldo real hubiera fallado (ej. token
    inválido o sin permisos), lo cual ocultaba el problema real."""
    token, repo, branch = _github_config()
    if not token:
        return False, "El respaldo no está configurado (falta GITHUB_TOKEN o GITHUB_REPO en Secrets)."
    try:
        import requests
        reportes_ligeros = [
            {c: r.get(c) for c in _CAMPOS_RESPALDO} for r in reportes
        ]
        # PRIVACIDAD: el repositorio puede ser público, así que el teléfono
        # nunca se sube en claro: se sube una huella irreversible (o nada,
        # si falta BACKUP_SALT en Secrets).
        for _rl in reportes_ligeros:
            _rl["CodigoResidente"] = pseudonimo_residente(_rl.get("CodigoResidente", ""))
        contenido = json.dumps(reportes_ligeros, ensure_ascii=False, indent=2)
        contenido_b64 = base64.b64encode(contenido.encode("utf-8")).decode("utf-8")

        url = f"https://api.github.com/repos/{repo}/contents/{RESPALDO_PATH_REPO}"
        headers = {"Authorization": f"token {token}",
                   "Accept": "application/vnd.github+json"}

        r_get = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
        sha = r_get.json().get("sha") if r_get.status_code == 200 else None

        payload = {
            "message": f"Respaldo automático EcoCom2 — {datetime.now():%Y-%m-%d %H:%M} [skip ci]",
            "content": contenido_b64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        r_put = requests.put(url, headers=headers, json=payload, timeout=10)
        if r_put.status_code in (200, 201):
            return True, ""
        detalle = ""
        try:
            detalle = r_put.json().get("message", "")
        except Exception:
            pass
        return False, f"GitHub respondió {r_put.status_code}: {detalle or 'error desconocido'}"
    except Exception as e:
        return False, f"Error de conexión: {e}"


def subir_foto_evidencia_github(imagen_bytes: bytes, nombre_archivo: str,
                                 carpeta: str = "evidencias_resueltos"):
    """Sube una foto (bytes JPEG) al repo de GitHub, bajo la carpeta
    indicada, y devuelve la URL pública en raw.githubusercontent.com.

    Esto existe por DOS motivos:
    1. WhatsApp no permite adjuntar una imagen automáticamente en un link
       wa.me — solo texto — así que la única forma de que el residente
       vea la foto con un toque es mandarle un link directo a una imagen
       ya alojada en algún lugar público.
    2. El disco del contenedor de Streamlit Cloud se borra por completo
       en cada reinicio — las fotos guardadas SOLO en la base SQLite
       local se pierden ahí, aunque el resto de los datos del reporte
       sobreviva gracias al respaldo liviano en GitHub. Subir también la
       foto como archivo (no solo como base64 en la base de datos) hace
       que la evidencia sea permanente de verdad, sin depender del disco
       efímero del contenedor.

    Devuelve (url, error)."""
    token, repo, branch = _github_config()
    if not token:
        return None, "El respaldo en GitHub no está configurado (falta GITHUB_TOKEN o GITHUB_REPO en Secrets)."
    if not imagen_bytes:
        return None, "No hay imagen para subir."
    try:
        import requests
        contenido_b64 = base64.b64encode(imagen_bytes).decode("utf-8")
        ruta_repo = f"{nombre_archivo_seguro(carpeta)}/{nombre_archivo_seguro(nombre_archivo)}"
        url_api = f"https://api.github.com/repos/{repo}/contents/{ruta_repo}"
        headers = {"Authorization": f"token {token}",
                   "Accept": "application/vnd.github+json"}

        r_get = requests.get(url_api, headers=headers, params={"ref": branch}, timeout=10)
        sha = r_get.json().get("sha") if r_get.status_code == 200 else None

        payload = {
            "message": f"Evidencia — {ruta_repo} [skip ci]",
            "content": contenido_b64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        r_put = requests.put(url_api, headers=headers, json=payload, timeout=15)
        if r_put.status_code in (200, 201):
            return f"https://raw.githubusercontent.com/{repo}/{branch}/{ruta_repo}", ""
        detalle = ""
        try:
            detalle = r_put.json().get("message", "")
        except Exception:
            pass
        return None, f"GitHub respondió {r_put.status_code}: {detalle or 'error desconocido'}"
    except Exception as e:
        return None, f"Error de conexión: {e}"


def restaurar_desde_github_si_vacio():
    """Si la app arrancó con la base de datos local vacía (señal de que
    el contenedor se reinició y se borró el disco), intenta recuperar
    el último respaldo guardado en GitHub para no perder el historial
    completo de reportes de la comunidad."""
    if st.session_state.get("reportes"):
        return
    token, repo, branch = _github_config()
    if not token:
        return
    try:
        import requests
        url = f"https://api.github.com/repos/{repo}/contents/{RESPALDO_PATH_REPO}"
        headers = {"Authorization": f"token {token}",
                   "Accept": "application/vnd.github+json"}
        r = requests.get(url, headers=headers, params={"ref": branch}, timeout=10)
        if r.status_code != 200:
            return
        contenido_b64 = r.json().get("content", "")
        contenido = base64.b64decode(contenido_b64).decode("utf-8")
        reportes_restaurados = json.loads(contenido)
        if reportes_restaurados:
            for _r in reportes_restaurados:
                for _k in ("Estado", "Clasificación", "Predominante"):
                    if _k in _r:
                        _r[_k] = sin_emojis(_r[_k])
            st.session_state.reportes = reportes_restaurados
            _guardar_sqlite(reportes_restaurados)
    except Exception:
        pass


def guardar_reportes_disco(reportes, eliminados=None, borrar_todo=False):
    """Guarda en SQLite local (rápido, para uso normal de la app) Y
    respalda en GitHub (lento pero sobrevive a un reinicio completo del
    contenedor de Streamlit Cloud). 'eliminados' son los códigos que hay
    que borrar de verdad; 'borrar_todo' vacía la tabla (solo admin)."""
    if not borrar_todo:
        _sincronizar_con_db(reportes, eliminados)
    ok = _guardar_sqlite(reportes, eliminados=eliminados, borrar_todo=borrar_todo)
    if not ok:
        try:
            st.warning("No se pudo guardar en la base local. Tu reporte sigue en "
                       "pantalla, pero avísale a la administración si se repite.")
        except Exception:
            pass
    respaldar_en_github(reportes)

# ====================================================================
# 1. CONFIGURACIÓN
# ====================================================================
st.set_page_config(page_title="EcoCom2 Circular IA", page_icon=":material/recycling:", layout="wide")

st.markdown("""
<style>
    .stApp {
        background-color: #f0fdf4;
        color: #1a2e1a;
        font-family: 'Segoe UI', Arial, sans-serif;
    }
    .block-container { padding-top: 1rem; max-width: 1200px; }

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

    [data-testid="stSidebar"] input[type="text"],
    [data-testid="stSidebar"] input[type="password"],
    [data-testid="stSidebar"] input {
        background: #f0fdf4 !important;
        color: #14532d !important;
        border: 1px solid #4ade80 !important;
        border-radius: 6px !important;
    }
    /* Placeholder del campo "Pregunta:" del chatbot — antes heredaba
       el gris muy claro por defecto del navegador, casi invisible
       sobre el fondo crema del campo. */
    [data-testid="stSidebar"] input[type="text"]::placeholder {
        color: #6b7280 !important;
        opacity: 1 !important;
    }

    [data-testid="stSidebar"] .ecocom2-footer {
        background: rgba(0, 30, 15, 0.55) !important;
        border: 1px solid rgba(74,222,128,0.35) !important;
        border-radius: 6px !important;
    }

    h1 { color: #166534 !important; font-size: 2rem !important; font-weight: 800 !important; }
    h2 { color: #15803d !important; font-weight: 700 !important; }
    h3 { color: #16a34a !important; font-weight: 600 !important; }

    header { 
        background-color: transparent !important; 
            }
    .badge-ok {
        background: #dcfce7; border: 2px solid #16a34a;
        border-radius: 10px; padding: 12px 16px;
        color: #14532d; font-weight: 700; font-size: 14px;
        box-shadow: 0 2px 8px rgba(22,163,74,0.15);
    }
    .badge-warn {
        background: #fefce8; border: 2px solid #ca8a04;
        border-radius: 10px; padding: 12px 16px;
        color: #713f12; font-weight: 700; font-size: 14px;
        box-shadow: 0 2px 8px rgba(202,138,4,0.15);
    }
    .badge-err {
        background: #fef2f2; border: 2px solid #dc2626;
        border-radius: 10px; padding: 12px 16px;
        color: #7f1d1d; font-weight: 700; font-size: 14px;
        box-shadow: 0 2px 8px rgba(220,38,38,0.15);
    }

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

    div[data-testid="stTextInput"] input {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; font-size: 15px !important;
        background: #ffffff !important; color: #1a2e1a !important;
        padding: 10px 14px !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #16a34a !important;
        box-shadow: 0 0 0 3px rgba(22,163,74,0.15) !important;
    }

    div[data-testid="stTextArea"] textarea {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; font-size: 15px !important;
        background: #ffffff !important; color: #14532d !important;
        padding: 10px 14px !important;
    }
    div[data-testid="stTextArea"] textarea::placeholder {
        color: #9ca3af !important;
    }
    div[data-testid="stTextArea"] textarea:focus {
        border-color: #16a34a !important;
        box-shadow: 0 0 0 3px rgba(22,163,74,0.15) !important;
    }
    div[data-testid="stTextInput"] label,
    div[data-testid="stTextArea"] label,
    div[data-testid="stSelectbox"] label,
    div[data-testid="stFileUploader"] label {
        color: #14532d !important;
        font-weight: 600 !important;
    }

    div[data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p,
    .stApp small {
        color: #4b5563 !important;
        opacity: 1 !important;
    }

    div[data-testid="stSelectbox"] > div > div {
        border: 2px solid #86efac !important;
        border-radius: 10px !important; background: #ffffff !important;
    }
    /* Texto del valor seleccionado (ej. "La Frontera") — heredaba el
       color claro del tema, invisible sobre el fondo blanco de arriba.
       El "*" cubre el value-container y cualquier span interno que
       use BaseWeb (la librería de componentes de Streamlit). */
    div[data-testid="stSelectbox"] * {
        color: #14532d !important;
    }
    /* La flecha del desplegable es un ícono SVG, no texto — se pinta
       con "fill", no con "color", así que necesita su propia regla. */
    div[data-testid="stSelectbox"] svg {
        fill: #14532d !important;
    }
    /* La LISTA de opciones (al hacer clic para desplegar) se pinta en
       un popover aparte, fuera del contenedor del selectbox — por eso
       necesita su propia regla, si no, tendría el mismo problema de
       texto invisible en cuanto el usuario la abriera. */
    div[data-baseweb="popover"] li,
    div[data-baseweb="menu"] * {
        color: #14532d !important;
        background: #ffffff !important;
    }

    [data-baseweb="tab-list"] {
        background: #dcfce7 !important; border-radius: 10px !important; padding: 4px !important;
        gap: 4px !important;
    }
    [data-baseweb="tab"] {
        background: transparent !important; border-radius: 8px !important;
        font-weight: 600 !important;
        padding: 8px 14px !important;
    }
    /* El texto de cada pestaña vive en un <p> anidado dentro del botón,
       no directamente en el botón — por eso el "color" de arriba no
       alcanzaba a pintarlo. El "*" cubre ese <p> y cualquier otro hijo. */
    [data-baseweb="tab"] * {
        color: #166534 !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        background: #16a34a !important;
        border-radius: 8px !important;
    }
    [data-baseweb="tab"][aria-selected="true"] * {
        color: #ffffff !important;
    }

    div[data-testid="stExpander"] {
        border: 1px solid #bbf7d0 !important;
        border-radius: 10px !important;
        background: #ffffff !important;
        margin-bottom: 8px !important;
    }
    /* El encabezado clickeable (el "summary") es un elemento aparte
       dentro del expander — no heredaba el fondo blanco de arriba,
       por eso se veía con el fondo oscuro del tema por defecto y el
       texto casi invisible encima. */
    div[data-testid="stExpander"] summary {
        background: #ffffff !important;
    }
    div[data-testid="stExpander"] summary * {
        color: #14532d !important;
    }

    div[data-testid="stDataFrameContainer"] {
        border: 2px solid #bbf7d0;
        border-radius: 10px; overflow: hidden;
    }

    div[data-testid="stInfo"] {
        background: #eff6ff !important; border-left: 4px solid #3b82f6 !important;
        color: #1e3a5f !important; border-radius: 8px !important;
    }
    div[data-testid="stInfo"] * { color: #1e3a5f !important; }
    div[data-testid="stWarning"] {
        background: #fefce8 !important; border-left: 4px solid #f59e0b !important;
        color: #713f12 !important; border-radius: 8px !important;
    }
    div[data-testid="stWarning"] * { color: #713f12 !important; }
    div[data-testid="stSuccess"] {
        background: #f0fdf4 !important; border-left: 4px solid #16a34a !important;
        color: #14532d !important; border-radius: 8px !important;
    }
    div[data-testid="stSuccess"] * { color: #14532d !important; }
    div[data-testid="stError"] {
        background: #fef2f2 !important; border-left: 4px solid #dc2626 !important;
        color: #7f1d1d !important; border-radius: 8px !important;
    }
    div[data-testid="stError"] * { color: #7f1d1d !important; }

    div[data-testid="stFileUploader"] {
        background: #f0fdf4 !important; border: 2px dashed #4ade80 !important;
        border-radius: 12px !important; padding: 16px !important;
    }
    /* "Drag and drop file here / Limit 200MB per file..." es texto
       técnico de Streamlit que no le sirve a alguien reportando desde
       el celular — lo ocultamos y dejamos solo el botón "Browse files"
       junto con la instrucción propia que ya ponemos en cada campo. */
    div[data-testid="stFileUploaderDropzoneInstructions"] div span,
    div[data-testid="stFileUploaderDropzoneInstructions"] small {
        display: none !important;
    }
    div[data-testid="stFileUploaderDropzoneInstructions"]::before {
        content: "Toca para tomar o subir una foto";
        color: #14532d;
        font-size: 14px;
        font-weight: 600;
    }

.chat-burbuja-bot {
    background: #99FFFF !important;
    color: #064e3b !important;
    border: 2px solid #4ade80 !important;
    border-radius: 12px !important;
    padding: 12px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    margin-bottom: 10px !important;
}

.chat-burbuja-user {
    background: #e2e8f0 !important;
    color: #1e293b !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 12px !important;
    padding: 12px !important;
    margin-bottom: 10px !important;
    text-align: right !important;
}

/* Burbujas del chat EcoBot — usamos [data-testid="stSidebar"] + clase
   (más específico que el "[data-testid=stSidebar] *" de arriba) para
   garantizar que el texto SIEMPRE gane esa pelea de especificidad y
   no vuelva a quedar invisible sobre el fondo. */
[data-testid="stSidebar"] .ecobot-bubble-bot,
[data-testid="stSidebar"] .ecobot-bubble-bot * {
    color: #14532d !important;
    background: #f0fdf4 !important;
}
[data-testid="stSidebar"] .ecobot-bubble-user,
[data-testid="stSidebar"] .ecobot-bubble-user * {
    color: #166534 !important;
    background: #dcfce7 !important;
}

.chat-container{
    background: #ffffff !important;
    border: 2px solid #86efac !important;
    border-radius: 12px !important;
    padding: 12px !important;
}

.chat-container *{
    color:#14532d !important;
}

.chat-container textarea,
.chat-container input{
    background:#ffffff !important;
    color:#14532d !important;
    border:2px solid #86efac !important;
}

.chat-container textarea::placeholder,
.chat-container input::placeholder{
    color:#6b7280 !important;
}

[data-testid="stSidebar"] .stButton button {
    background-color: #ffffff !important;
    border: 2px solid #86efac !important;
    border-radius: 8px !important;
}

[data-testid="stSidebar"] .stButton button p {
    color: #14532d !important;
    font-weight: 500 !important;
}

[data-testid="stSidebar"] .stButton button:hover {
    background-color: #f0fdf4 !important;
    border-color: #16a34a !important;
}
</style>
""", unsafe_allow_html=True)

# ====================================================================
# 2. POLÍGONO COMUNA 2 — SANTA CRUZ, MEDELLÍN
# ====================================================================
POLIGONO_COMUNA2 = Polygon([
    (-75.5613, 6.2933),
    (-75.5608, 6.2965),
    (-75.5598, 6.3005),
    (-75.5585, 6.3055),
    (-75.5560, 6.3098),
    (-75.5540, 6.3100),
    (-75.5500, 6.3032),
    (-75.5498, 6.2980),
    (-75.5500, 6.2935),
    (-75.5500, 6.2895),
    (-75.5555, 6.2890),
    (-75.5590, 6.2895),
    (-75.5613, 6.2933)
])

BARRIOS = [
    "La Isla", "Playón de los Comuneros", "Pablo VI", "La Frontera",
    "La Francia", "Andalucía", "Villa del Socorro", "Villa Niza",
    "Moscú No. 1", "Santa Cruz", "La Rosa",
]

# Horarios oficiales de recolección de residuos ordinarios — Comuna 2 Santa
# Cruz. Fuente: Emvarias, "Horarios y Frecuencias de Recolección 2024" (Zona
# 1, comunas 1-4), con la actualización de junio de 2026 (El Espectador,
# 30/05/2026) que angostó la franja horaria de La Rosa y Moscú N°1.
HORARIOS_RECOLECCION = {
    "La Rosa": {"dias": "Lunes y jueves", "horario": "7:00 p.m. – 9:00 p.m.",
                "nota": "Franja angostada desde el 4 de junio de 2026"},
    "Moscú No. 1": {"dias": "Lunes y jueves", "horario": "7:00 p.m. – 9:00 p.m.",
                     "nota": "Cambió de miércoles/sábado a lunes/jueves desde jun. 2026"},
    "Andalucía": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "Playón de los Comuneros": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "La Francia": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "La Frontera": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "La Isla": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "Pablo VI": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "Santa Cruz": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "Villa del Socorro": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
    "Villa Niza": {"dias": "Miércoles y sábado", "horario": "3:00 p.m. – 11:00 p.m.", "nota": ""},
}

LAT_C = 6.3104
LON_C = -75.5552

# ====================================================================
# 3. SESIÓN
# ====================================================================
for k, v in {
    "lat": None, "lon": None, "validado": False, "fuera": True,
    "direccion": "", "reporte_ok": False, "cache": None,
    "seccion": "info",
    "click_barrio": None,
    "mis_codigos": [],
    "gps_procesado": None,
    "gps_lat": None, "gps_lon": None,
    "gps_solicitado": False,
    "tutorial_visto": False,
    "tutorial_paso": 0,
    "mostrar_horarios": False,
    "dir_candidatos": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

if "reportes" not in st.session_state:
    st.session_state.reportes = cargar_reportes_disco()
    if st.session_state.reportes:
        # Ya hay datos en el disco local del contenedor — los respaldamos
        # de inmediato en vez de esperar a la próxima acción. Así, si el
        # contenedor se reinicia antes de que alguien publique algo
        # nuevo, esos reportes ya existentes NO se pierden.
        respaldar_en_github(st.session_state.reportes)
    else:
        restaurar_desde_github_si_vacio()

if "mis_estados_vistos" not in st.session_state:
    st.session_state.mis_estados_vistos = {}

# ====================================================================
# 4. MODELO YOLO — YOLOE (vocabulario abierto)
# ====================================================================
CLASES_DETECCION = [
    # ── Reciclables típicos (equivalentes a lo que ya cubría COCO) ──
    "plastic bottle", "plastic cup", "plastic chair", "plastic bench",
    "plastic bucket", "plastic bowl", "colorful plastic children toy", "frisbee",
    "garbage bag", "backpack", "suitcase", "book", "newspaper",
    "cardboard box", "glass bottle", "glass jar", "aluminum can",
    "knife", "fork", "spoon", "scissors", "cell phone", "laptop",
    "keyboard", "computer mouse", "remote control", "television",
    "clock", "banana", "apple", "orange", "broccoli", "carrot",
    "potted plant", "food waste", "wooden table", "couch", "bed",
    "umbrella", "tie",
    # ── Objetos que YOLOv8 clásico NO reconocía y son comunes en la comuna ──
    "wooden chair", "wooden stool", "broken wooden furniture",
    "mattress", "construction rubble", "pile of rubble",
    "pile of garbage bags", "scrap metal", "black rubber car tire",
    "broken appliance", "styrofoam waste", "pile of plastic bags",
    "wood planks", "broken glass", "electronic waste",
    "abandoned furniture", "cardboard boxes pile",
    # ── Distractores — para que NO se confundan con residuos ──
    "person", "dog", "cat", "car", "bus", "truck", "bicycle",
    "motorcycle", "traffic light", "stop sign", "bird", "toothbrush",
]

# Las clases distractoras casi nunca aparecen de verdad en una foto de
# residuos — si el modelo "cree verlas" con poca confianza, casi
# siempre es una alucinación sobre el fondo. Se define aquí (nivel de
# módulo) para que tanto procesar() como el dibujo de "Detecciones IA"
# usen exactamente el mismo criterio — antes cada uno filtraba distinto
# y por eso la imagen mostraba cosas que la tabla ya había descartado.
CLASES_DISTRACTORAS = {
    "person", "dog", "cat", "car", "bus", "truck", "bicycle",
    "motorcycle", "traffic light", "stop sign", "bird", "toothbrush",
}
UMBRAL_CONF_DISTRACTOR = 0.45
UMBRAL_CONF_CLASE_DESCONOCIDA = 0.40

@st.cache_resource
def cargar_modelo():
    m = YOLOE("yoloe-11s-seg.pt")
    embeddings = m.get_text_pe(CLASES_DETECCION)
    m.set_classes(CLASES_DETECCION, embeddings)
    return m
modelo = cargar_modelo()

# ====================================================================
# 5. MATERIALES
# ====================================================================
MAT = {
    # ── Reciclables típicos ──
    "plastic bottle":        ("Botella plástica",           "Plástico",    0.05, True),
    "plastic cup":           ("Vaso / Recipiente plástico", "Plástico",    0.03, True),
    "plastic chair":         ("Silla plástica",             "Plástico",    2.00, True),
    "plastic bench":         ("Banco plástico",             "Plástico",    2.50, True),
    "plastic bucket":        ("Balde plástico",             "Plástico",    0.50, True),
    "plastic bowl":          ("Recipiente plástico",        "Plástico",    0.15, True),
    "colorful plastic children toy": ("Juguete plástico",           "Plástico",    0.50, True),
    "frisbee":               ("Disco plástico",             "Plástico",    0.10, True),
    "garbage bag":           ("Bolsa de basura",            "Plástico",    0.40, True),
    "backpack":              ("Bolsa / Mochila",            "Textil",      0.50, True),
    "suitcase":              ("Bolsa grande / Maleta",      "Textil",      1.00, True),
    "book":                  ("Libro / Cuaderno",           "Papel",       0.30, True),
    "newspaper":             ("Periódico / Papel",          "Papel",       0.10, True),
    "cardboard box":         ("Caja de cartón",             "Cartón",      0.30, True),
    "glass bottle":          ("Botella de vidrio",          "Vidrio",      0.20, True),
    "glass jar":             ("Frasco de vidrio",           "Vidrio",      0.80, True),
    "aluminum can":          ("Lata de aluminio",           "Aluminio",    0.02, True),
    "knife":                 ("Cuchillo / Utensilio metal", "Metal",       0.10, True),
    "fork":                  ("Tenedor / Utensilio metal",  "Metal",       0.05, True),
    "spoon":                 ("Cuchara / Utensilio metal",  "Metal",       0.05, True),
    "scissors":              ("Tijeras",                    "Metal",       0.10, True),
    "cell phone":            ("Celular",                    "Electrónico", 0.20, True),
    "laptop":                ("Portátil",                   "Electrónico", 2.50, True),
    "keyboard":              ("Teclado",                    "Electrónico", 0.60, True),
    "computer mouse":        ("Ratón de computador",        "Electrónico", 0.10, True),
    "remote control":        ("Control remoto",             "Electrónico", 0.20, True),
    "television":            ("Televisor",                  "Electrónico", 8.00, True),
    "clock":                 ("Reloj",                      "Electrónico", 0.30, True),
    "banana":                ("Banano",                     "Orgánico",    0.10, True),
    "apple":                 ("Manzana",                    "Orgánico",    0.15, True),
    "orange":                ("Naranja",                    "Orgánico",    0.20, True),
    "broccoli":              ("Brócoli",                    "Orgánico",    0.25, True),
    "carrot":                ("Zanahoria",                  "Orgánico",    0.10, True),
    "potted plant":          ("Planta / Matero",            "Orgánico",    1.00, True),
    "food waste":            ("Residuo de comida",          "Orgánico",    0.25, True),
    "wooden table":          ("Mesa / Madera",              "Madera",     12.00, True),
    "couch":                 ("Sofá / Mueble",               "Mixto",     15.00, True),
    "bed":                   ("Cama / Colchón",             "Mixto",      20.00, True),
    "umbrella":              ("Paraguas",                   "Mixto",       0.50, True),
    "tie":                   ("Corbata / Textil",           "Textil",      0.10, True),
    # ── Antes invisibles para la IA — ahora reconocidos por texto libre ──
    "wooden chair":          ("Silla de madera",            "Madera",      3.00, True),
    "wooden stool":          ("Banco / Taburete de madera",  "Madera",     2.00, True),
    "broken wooden furniture":("Mueble de madera roto",      "Madera",     8.00, True),
    "mattress":              ("Colchón",                    "Mixto",      20.00, True),
    "construction rubble":   ("Escombros de construcción",  "Escombros",  15.00, False),
    "pile of rubble":        ("Montón de escombros",        "Escombros",  20.00, False),
    "pile of garbage bags":  ("Montón de bolsas de basura",  "Residuo mixto",5.00, False),
    "scrap metal":           ("Chatarra metálica",          "Metal",       2.00, True),
    "black rubber car tire":  ("Llanta usada",               "Caucho",      8.00, False),
    "broken appliance":      ("Electrodoméstico dañado",     "Electrónico",10.00, True),
    "styrofoam waste":       ("Icopor / Poliestireno",       "Plástico",   0.20, True),
    "pile of plastic bags":  ("Montón de bolsas plásticas",  "Plástico",   1.00, True),
    "wood planks":           ("Tablas / Madera suelta",      "Madera",     4.00, True),
    "broken glass":          ("Vidrio roto",                "Vidrio",      0.50, False),
    "electronic waste":      ("Chatarra electrónica",       "Electrónico", 3.00, True),
    "abandoned furniture":   ("Mueble abandonado",          "Mixto",      15.00, True),
    "cardboard boxes pile":  ("Montón de cajas de cartón",   "Cartón",     2.00, True),
    # ── Distractores (no cuentan como residuo) ──
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
_ABREVIATURAS_CO = {
    r"\bcra\.?\b": "Carrera", r"\bcr\.?\b": "Carrera",
    r"\bkra\.?\b": "Carrera", r"\bkr\.?\b": "Carrera",
    r"\bcl\.?\b": "Calle", r"\bcll\.?\b": "Calle", r"\bclle\.?\b": "Calle",
    r"\bdg\.?\b": "Diagonal",
    r"\btv\.?\b": "Transversal", r"\btrans\.?\b": "Transversal",
    r"\bcq\.?\b": "Circular",
    r"\bav\.?\b": "Avenida", r"\bavda\.?\b": "Avenida",
}

def _normalizar_direccion_co(direccion: str) -> str:
    """Expande abreviaturas típicas colombianas (Cra, Cll, Dg, Tv...)
    a su forma completa — Nominatim reconoce mejor 'Carrera' que 'Cra'."""
    txt = direccion.strip()
    for patron, reemplazo in _ABREVIATURAS_CO.items():
        txt = re.sub(patron, reemplazo, txt, flags=re.IGNORECASE)
    return txt


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar(direccion: str, max_resultados: int = 5):
    """Busca una dirección y devuelve una LISTA de candidatos (hasta
    max_resultados), no solo el primero — así el residente puede
    confirmar cuál es la correcta en vez de que la app adivine y el
    reporte quede mal ubicado sin que nadie lo note. Si la dirección
    completa no da resultados, reintenta sin el número de casa
    ('#107-62'), porque muchas calles de la Comuna 2 están mapeadas en
    OpenStreetMap solo a nivel de vía, sin numeración exacta."""
    from geopy.geocoders import Nominatim
    from geopy.exc import GeocoderTimedOut, GeocoderServiceError

    geo = Nominatim(user_agent="ecocom2_v5", timeout=8)
    viewbox = [(6.10, -75.70), (6.38, -75.45)]  # área metropolitana de Medellín

    def _buscar(txt):
        try:
            return geo.geocode(
                f"{txt}, Medellín, Antioquia, Colombia",
                exactly_one=False, limit=max_resultados,
                viewbox=viewbox, bounded=True,
            )
        except (GeocoderTimedOut, GeocoderServiceError, Exception):
            return None

    direccion_norm = _normalizar_direccion_co(direccion)
    resultados = _buscar(direccion_norm)

    if not resultados:
        sin_numero = re.sub(r"#\s*\d+\w*\s*-\s*\d+\w*.*", "", direccion_norm).strip()
        if sin_numero and sin_numero != direccion_norm:
            time.sleep(1.1)  # respeta el límite de 1 solicitud/seg de Nominatim
            resultados = _buscar(sin_numero)

    if not resultados:
        return []

    return [(r.latitude, r.longitude, r.address) for r in resultados]


def _normalizar_txt(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"\s+", " ", txt)  # colapsa espacios dobles que quedan al quitar emojis
    return txt.lower().strip()


_PALABRAS_INTENCION_REPORTAR = [
    "reportar", "reporto", "denunciar", "hay basura", "tengo basura",
    "como reporto", "ayudame a reportar", "subir foto", "punto critico",
    "quiero reportar",
]


def _detectar_intencion_reportar(texto: str) -> bool:
    """Revisa si el mensaje del usuario suena a que quiere reportar un
    residuo — para que EcoBot le ofrezca un botón que lo lleve DIRECTO a
    la sección de reportar, en vez de solo explicarle los pasos por
    texto. Pensado para personas que no saben navegar la app solas."""
    texto_n = _normalizar_txt(texto)
    return any(p in texto_n for p in _PALABRAS_INTENCION_REPORTAR)


# Respuestas ya redactadas y completas para las preguntas más importantes
# de la app — así EcoBot nunca improvisa algo corto o vago (ej. "¡Es muy
# fácil!" y nada más) en temas donde alguien que no sabe usar la app de
# verdad necesita el paso a paso completo. Si la pregunta no coincide con
# ninguna de estas, se recurre a Gemini como respaldo "inteligente".
_FAQ_ECOBOT = [
    (["como reporto", "reportar basura", "quiero reportar", "denunciar",
      "como hago un reporte", "como se reporta"],
     "Para reportar es sencillo:\n"
     "1 Verifica tu dirección (botón GPS o escríbela a mano)\n"
     "2 Toca el punto exacto del residuo en el mapa\n"
     "3 Presiona 'Reportar Residuo' o 'Punto Crítico'\n"
     "4 Sube una foto — la IA la analiza sola\n"
     "5 Revisa el resultado y presiona 'Publicar'\n\n"
     "¿Quieres que te lleve directo? Usa el botón Reportar residuo de arriba"),
    (["que significa rojo", "punto critico que es", "color rojo"],
     "Rojo = Punto crítico: o hay muy pocos reciclables (menos del 30%), "
     "o el montón es tan grande que necesita recolección urgente, sin importar "
     "qué tan buen material tenga."),
    (["que significa amarillo", "color amarillo"],
     "Amarillo = Residuos mixtos: una mezcla de reciclable y no reciclable, "
     "o buen material pero en un volumen considerable."),
    (["que significa verde", "color verde"],
     "Verde = Alta valorización: al menos 60% de lo que hay es reciclable "
     "y el volumen es manejable — el mejor escenario posible."),
    (["como verifico mi direccion", "como pongo mi direccion", "gps no funciona",
      "no tengo gps"],
     "Para verificar tu dirección: presiona el botón grande 'Usar mi ubicación "
     "(GPS)' y acepta el permiso del navegador. Si prefieres, abre '¿No tienes GPS "
     "o prefieres escribir tu dirección?' y escríbela a mano. También puedes tocar "
     "directamente el punto en el mapa."),
    (["para que sirve la ia", "que hace la inteligencia artificial", "que es gemini",
      "que es yolo", "como analiza la ia"],
     "La IA analiza tu foto y clasifica los residuos por categoría (orgánico, "
     "plástico, vidrio, cartón, papel). Puedes elegir entre Gemini (más detallado, "
     "por categoría de material) o YOLO (funciona sin internet, por tipo exacto "
     "de objeto) justo antes de analizar tu foto."),
    (["ya se resolvio", "como se si se soluciono", "estado de mi reporte"],
     "Cuando la administración marca tu reporte como 'Resuelto', te llega un aviso "
     "en 'Mi Historial' — a veces con una foto de cómo quedó el punto. Si dejaste "
     "tu número, también te llega por WhatsApp."),
    (["como confirmo", "sigue ahi", "todavia esta la basura"],
     "Si pasas por un punto ya reportado y el residuo sigue ahí, ve a 'Mi "
     "Historial' → 'Confirmar reportes activos de la comunidad' y presiona '"
     "Confirmar' — eso ayuda a la administración a priorizar dónde limpiar primero."),
    (["reporte falso", "no es basura", "esto no es un residuo"],
     "Si ves un reporte que en realidad no muestra basura (por ejemplo, un negocio "
     "o una vivienda), ve a 'Mi Historial' → 'Confirmar reportes activos' y usa el "
     "botón 'No es basura'. Eso ayuda a que la administración lo revise."),
    (["cuantos reportes puedo hacer", "limite de reportes", "ya no me deja reportar"],
     "Hay un límite de 8 reportes por día por persona, para evitar abuso de la "
     "app. Si dejaste tu número/código al reportar, el conteo es más preciso; si no, "
     "se cuenta por sesión del navegador."),
]


def _responder_faq_ecobot(pregunta: str):
    """Busca una respuesta ya redactada para preguntas frecuentes clave —
    si encuentra coincidencia, la devuelve de inmediato (sin gastar una
    llamada a la IA, y sin arriesgarse a una respuesta corta o vaga). Si
    no hay coincidencia, devuelve None para que se use Gemini."""
    for texto_n in (_normalizar_txt(pregunta), _preparar_texto_bot(pregunta)):
        for palabras_clave, respuesta in _FAQ_ECOBOT:
            if any(_normalizar_txt(p) in texto_n for p in palabras_clave):
                return respuesta
    return None


def adivinar_barrio(texto_nominatim: str):
    if not texto_nominatim:
        return None
    objetivo = _normalizar_txt(texto_nominatim)
    for b in BARRIOS:
        nb = _normalizar_txt(b)
        if nb in objetivo or objetivo in nb:
            return b
    normalizados = {_normalizar_txt(b): b for b in BARRIOS}
    match = difflib.get_close_matches(objetivo, normalizados.keys(), n=1, cutoff=0.6)
    return normalizados[match[0]] if match else None


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar_inversa(lat: float, lon: float):
    from geopy.geocoders import Nominatim
    try:
        geo = Nominatim(user_agent="ecocom2_v4_rev", timeout=6)
        r = geo.reverse(f"{lat}, {lon}", language="es")
        if r and r.raw.get("address"):
            a = r.raw["address"]
            partes = []
            calle  = a.get("road") or a.get("pedestrian") or a.get("path") or ""
            num    = a.get("house_number", "")
            barrio_raw = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
            if calle:
                partes.append(calle + (f" #{num}" if num else ""))
            if barrio_raw:
                partes.append(barrio_raw)
            partes.append("Medellín")
            direccion = ", ".join(partes) if partes else r.address
            return direccion, adivinar_barrio(barrio_raw)
        return f"{lat:.5f}, {lon:.5f}", None
    except Exception:
        return f"{lat:.5f}, {lon:.5f}", None


def marcar_zona_critica(img_pil, texto="ZONA CRÍTICA — revisar acumulación completa"):
    from PIL import ImageDraw, ImageFont
    img = img_pil.convert("RGB").copy()
    draw = ImageDraw.Draw(img)
    w, h = img.size
    grosor = max(6, int(min(w, h) * 0.02))
    for i in range(grosor):
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=(220, 38, 38))
    alto_franja = max(30, int(h * 0.09))
    draw.rectangle([0, h - alto_franja, w, h], fill=(220, 38, 38))
    try:
        fuente = ImageFont.load_default(size=max(14, int(alto_franja * 0.45)))
    except TypeError:
        fuente = ImageFont.load_default()
    draw.text((12, h - alto_franja + alto_franja * 0.25), texto,
              fill=(255, 255, 255), font=fuente)
    return img


def img_a_b64(img_pil, max_px=200) -> str:
    try:
        thumb = img_pil.copy()
        thumb.thumbnail((max_px, max_px))
        buf = BytesIO()
        thumb.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def fuente_imagen(b64_val: str, url_val: str) -> str:
    """Devuelve una fuente de imagen usable en <img src="..."> — prioriza
    el thumbnail local en base64 (rápido, no depende de internet), y si
    no existe (ej. el contenedor se reinició y se perdió el disco local),
    cae al link público de GitHub para que la foto no desaparezca del
    todo. Devuelve "" si no hay ninguna de las dos fuentes disponibles."""
    if b64_val:
        # solo caracteres válidos de base64 — nada que rompa el atributo src
        return "data:image/jpeg;base64," + solo_b64(b64_val)
    if url_val and str(url_val).startswith("https://"):
        return esc(url_val)
    return ""


def fotos_extra_a_json(imgs_pil: list, max_px=200) -> str:
    try:
        if not imgs_pil:
            return ""
        miniaturas = [img_a_b64(img, max_px=max_px) for img in imgs_pil]
        miniaturas = [m for m in miniaturas if m]
        return json.dumps(miniaturas) if miniaturas else ""
    except Exception:
        return ""


def json_a_fotos_extra(fotos_json: str) -> list:
    try:
        if not fotos_json:
            return []
        datos = json.loads(fotos_json)
        return datos if isinstance(datos, list) else []
    except Exception:
        return []


def galeria_html(fotos_extra_json: str, ancho_px: int = 90) -> str:
    fotos = json_a_fotos_extra(fotos_extra_json)
    if not fotos:
        return ""
    imgs = "".join(
        f'<img src="data:image/jpeg;base64,{solo_b64(f)}" '
        f'style="width:{ancho_px}px;height:{ancho_px}px;object-fit:cover;'
        f'border-radius:6px;margin:3px 3px 0 0;">'
        for f in fotos
    )
    return (f'<div style="margin-top:6px;">'
            f'<span style="font-size:11px;color:#9ca3af;">Fotos de apoyo:</span><br>'
            f'{imgs}</div>')


def audio_a_b64(audio_uploadedfile) -> str:
    try:
        if audio_uploadedfile is None:
            return ""
        datos_audio = audio_uploadedfile.getvalue()
        if len(datos_audio) > 5 * 1024 * 1024:   # tope de 5 MB por nota de voz
            return ""
        return base64.b64encode(datos_audio).decode("utf-8")
    except Exception:
        return ""


def campo_codigo_residente(key: str) -> str:
    valor = st.text_input(
        "Tu código o teléfono (opcional):",
        value=st.session_state.get("mi_codigo_residente", ""),
        placeholder="Ej. tu número de celular — para recuperar tus reportes después",
        key=key, max_chars=30,
        help="No es una contraseña: sirve para que más adelante puedas buscar "
             "tus propios reportes en el Historial, incluso si cierras el "
             "navegador. Cualquiera que conozca este código podría ver esos "
             "reportes, así que no escribas datos sensibles."
    )
    if valor.strip():
        st.session_state.mi_codigo_residente = valor.strip()
    st.caption("Ver el aviso completo de tratamiento de datos en "
               "Información → 'Aviso de Tratamiento de Datos Personales'.")
    return valor.strip()


def tamano_bd_mb() -> float:
    try:
        return round(DB_PATH.stat().st_size / (1024 * 1024), 2)
    except Exception:
        return 0.0


def generar_excel_reportes(reportes: list, incluir_contacto: bool = False) -> bytes:
    """Genera un archivo Excel (.xlsx) con aspecto de informe corporativo
    (sin emojis, colores sobrios, tipografía formal) y gráficas reales de
    Excel (barras y torta) en la hoja de Resumen, además de la hoja de
    detalle con cada reporte — reemplaza el CSV crudo por algo listo para
    entregar en un informe oficial."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.chart import BarChart, DoughnutChart, Reference
    from openpyxl.chart.series import DataPoint
    from openpyxl.chart.shapes import GraphicalProperties

    def _agregar_gauge(ws, anchor, valor_pct, titulo, fila_datos, col_datos, color_hex):
        """Dibuja un gauge (velocímetro de media torta) con un DoughnutChart
        de 3 segmentos: el valor, lo que falta, y una mitad invisible — es
        el truco estándar para simular un semicírculo en un gráfico de
        Excel que normalmente solo dibuja círculos completos."""
        valor_pct = max(0.0, min(100.0, valor_pct))
        restante = 100.0 - valor_pct

        ws.cell(row=fila_datos, column=col_datos, value=valor_pct)
        ws.cell(row=fila_datos + 1, column=col_datos, value=restante)
        ws.cell(row=fila_datos + 2, column=col_datos, value=100)  # mitad invisible

        chart = DoughnutChart()
        chart.firstSliceAng = 270
        chart.holeSize = 60
        chart.title = f"{titulo}: {valor_pct:.1f}%"
        chart.height = 6.5
        chart.width = 8.5
        chart.legend = None

        datos = Reference(ws, min_col=col_datos, min_row=fila_datos, max_row=fila_datos + 2)
        chart.add_data(datos, titles_from_data=False)

        serie = chart.series[0]
        pt_valor = DataPoint(idx=0)
        pt_valor.graphicalProperties = GraphicalProperties(solidFill=color_hex)
        pt_resto = DataPoint(idx=1)
        pt_resto.graphicalProperties = GraphicalProperties(solidFill="E5E7EB")
        pt_oculto = DataPoint(idx=2)
        pt_oculto.graphicalProperties = GraphicalProperties(noFill=True)
        serie.data_points = [pt_valor, pt_resto, pt_oculto]

        ws.add_chart(chart, anchor)

    wb = Workbook()

    AZUL_OSCURO   = "1F2937"
    VERDE_ACENTO  = "166534"
    GRIS_TEXTO    = "6B7280"
    GRIS_CLARO    = "F3F4F6"

    HEADER_FILL = PatternFill("solid", fgColor=AZUL_OSCURO)
    HEADER_FONT = Font(color="FFFFFF", bold=True, size=11, name="Calibri")
    TITULO_FONT = Font(bold=True, size=16, color=AZUL_OSCURO, name="Calibri")
    SUBTITULO_FONT = Font(size=11, color=VERDE_ACENTO, name="Calibri")
    NOTA_FONT = Font(italic=True, color=GRIS_TEXTO, size=9, name="Calibri")
    SECCION_FONT = Font(bold=True, size=12, color=AZUL_OSCURO, name="Calibri")
    BORDE = Border(bottom=Side(style="thin", color="D1D5DB"))
    BORDE_CAJA = Border(
        left=Side(style="thin", color="D1D5DB"), right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"), bottom=Side(style="thin", color="D1D5DB"))
    CENTRO = Alignment(horizontal="center", vertical="center", wrap_text=True)
    IZQ = Alignment(horizontal="left", vertical="center", wrap_text=True)

    COLOR_NIVEL = {"Rojo": "FEE2E2", "Amarillo": "FEF9C3", "Verde": "DCFCE7"}

    # ── HOJA 1: Resumen ──────────────────────────────────────────────
    ws_r = wb.active
    ws_r.title = "Resumen"
    ws_r.sheet_view.showGridLines = False

    total = len(reportes)
    criticos  = sum(1 for r in reportes if semaforo(r.get("Clasificación","")) == "rojo")
    amarillos = sum(1 for r in reportes if semaforo(r.get("Clasificación","")) == "amarillo")
    verdes    = sum(1 for r in reportes if semaforo(r.get("Clasificación","")) == "verde")
    pendientes= sum(1 for r in reportes if "Pendiente" in r.get("Estado",""))
    proceso   = sum(1 for r in reportes if "proceso" in r.get("Estado",""))
    resueltos = sum(1 for r in reportes if "Resuelto" in r.get("Estado",""))
    peso_total= sum(float(r.get("Peso (Kg)", 0) or 0) for r in reportes)

    ws_r["B2"] = "EcoCom2 Circular IA"
    ws_r["B2"].font = TITULO_FONT
    ws_r["B3"] = "Informe de Gestión de Residuos Sólidos — Comuna 2, Santa Cruz"
    ws_r["B3"].font = SUBTITULO_FONT
    ws_r["B4"] = f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')}"
    ws_r["B4"].font = NOTA_FONT

    # ── Tabla de indicadores clave ──
    fila_kpi_inicio = 6
    ws_r.cell(row=fila_kpi_inicio, column=2, value="Indicador").font = HEADER_FONT
    ws_r.cell(row=fila_kpi_inicio, column=2).fill = HEADER_FILL
    ws_r.cell(row=fila_kpi_inicio, column=3, value="Valor").font = HEADER_FONT
    ws_r.cell(row=fila_kpi_inicio, column=3).fill = HEADER_FILL
    fila = fila_kpi_inicio + 1
    for etiqueta, valor in [
        ("Total de reportes", total),
        ("Puntos críticos", criticos),
        ("Puntos amarillos", amarillos),
        ("Puntos verdes", verdes),
        ("Pendientes", pendientes),
        ("En proceso", proceso),
        ("Resueltos", resueltos),
        ("Peso total estimado (kg)", round(peso_total, 1)),
    ]:
        c_lbl = ws_r.cell(row=fila, column=2, value=etiqueta)
        c_val = ws_r.cell(row=fila, column=3, value=valor)
        c_lbl.border = BORDE_CAJA
        c_val.border = BORDE_CAJA
        c_lbl.alignment = IZQ
        c_val.alignment = CENTRO
        if fila % 2 == 0:
            c_lbl.fill = PatternFill("solid", fgColor=GRIS_CLARO)
            c_val.fill = PatternFill("solid", fgColor=GRIS_CLARO)
        fila += 1
    fila_kpi_fin = fila - 1

    # ── Datos de apoyo para las gráficas (Estado y Nivel) ──
    fila_estado_inicio = fila_kpi_inicio
    ws_r.cell(row=fila_estado_inicio, column=5, value="Estado").font = HEADER_FONT
    ws_r.cell(row=fila_estado_inicio, column=5).fill = HEADER_FILL
    ws_r.cell(row=fila_estado_inicio, column=6, value="Cantidad").font = HEADER_FONT
    ws_r.cell(row=fila_estado_inicio, column=6).fill = HEADER_FILL
    for i, (nombre, val) in enumerate([("Pendientes", pendientes), ("En proceso", proceso),
                                        ("Resueltos", resueltos)], start=1):
        ws_r.cell(row=fila_estado_inicio + i, column=5, value=nombre).border = BORDE_CAJA
        ws_r.cell(row=fila_estado_inicio + i, column=6, value=val).border = BORDE_CAJA
    fila_estado_fin = fila_estado_inicio + 3

    fila_nivel_inicio = fila_estado_fin + 2
    ws_r.cell(row=fila_nivel_inicio, column=5, value="Nivel de criticidad").font = HEADER_FONT
    ws_r.cell(row=fila_nivel_inicio, column=5).fill = HEADER_FILL
    ws_r.cell(row=fila_nivel_inicio, column=6, value="Cantidad").font = HEADER_FONT
    ws_r.cell(row=fila_nivel_inicio, column=6).fill = HEADER_FILL
    for i, (nombre, val) in enumerate([("Críticos", criticos), ("Amarillos", amarillos),
                                        ("Verdes", verdes)], start=1):
        ws_r.cell(row=fila_nivel_inicio + i, column=5, value=nombre).border = BORDE_CAJA
        ws_r.cell(row=fila_nivel_inicio + i, column=6, value=val).border = BORDE_CAJA
    fila_nivel_fin = fila_nivel_inicio + 3

    # ── Reportes por barrio ──
    fila = fila_kpi_fin + 3
    ws_r.cell(row=fila, column=2, value="Reportes por barrio").font = SECCION_FONT
    fila += 1
    fila_barrio_header = fila
    ws_r.cell(row=fila, column=2, value="Barrio").font = HEADER_FONT
    ws_r.cell(row=fila, column=2).fill = HEADER_FILL
    ws_r.cell(row=fila, column=3, value="Reportes").font = HEADER_FONT
    ws_r.cell(row=fila, column=3).fill = HEADER_FILL
    fila += 1
    fila_barrio_inicio = fila
    conteo_barrio = Counter(r.get("Sector", "—") for r in reportes)
    for idx, (barrio, cant) in enumerate(sorted(conteo_barrio.items(), key=lambda x: -x[1])):
        c_b = ws_r.cell(row=fila, column=2, value=barrio)
        c_c = ws_r.cell(row=fila, column=3, value=cant)
        c_b.border = BORDE_CAJA
        c_c.border = BORDE_CAJA
        c_b.alignment = IZQ
        c_c.alignment = CENTRO
        if idx % 2 == 1:
            c_b.fill = PatternFill("solid", fgColor=GRIS_CLARO)
            c_c.fill = PatternFill("solid", fgColor=GRIS_CLARO)
        fila += 1
    fila_barrio_fin = max(fila - 1, fila_barrio_inicio)

    ws_r.column_dimensions["A"].width = 3
    ws_r.column_dimensions["B"].width = 30
    ws_r.column_dimensions["C"].width = 14
    ws_r.column_dimensions["D"].width = 3
    ws_r.column_dimensions["E"].width = 18
    ws_r.column_dimensions["F"].width = 12

    # ── Gauges (velocímetros de media torta) + barra por barrio ──
    if total > 0:
        pct_resueltos = (resueltos / total) * 100
        pct_criticos  = (criticos  / total) * 100
        pct_verdes    = (verdes    / total) * 100

        # Columnas de datos ocultos (20-22), lejos de las tablas visibles
        _agregar_gauge(ws_r, "H6",  pct_resueltos, "Resueltos",   fila_kpi_inicio, 20, "16A34A")
        _agregar_gauge(ws_r, "H21", pct_criticos,  "Críticos",    fila_kpi_inicio, 21, "DC2626")
        _agregar_gauge(ws_r, "H36", pct_verdes,    "Reciclables", fila_kpi_inicio, 22, "2563EB")

        if fila_barrio_fin >= fila_barrio_inicio:
            barras_barrio = BarChart()
            barras_barrio.type = "col"
            barras_barrio.title = "Reportes por barrio"
            barras_barrio.height, barras_barrio.width = 8, 16
            barras_barrio.y_axis.title = "Cantidad de reportes"
            datos_barrio = Reference(ws_r, min_col=3, min_row=fila_barrio_header,
                                      max_row=fila_barrio_fin)
            etiquetas_barrio = Reference(ws_r, min_col=2, min_row=fila_barrio_inicio,
                                          max_row=fila_barrio_fin)
            barras_barrio.add_data(datos_barrio, titles_from_data=True)
            barras_barrio.set_categories(etiquetas_barrio)
            barras_barrio.legend = None
            ws_r.add_chart(barras_barrio, "H51")

    # ── HOJA 2: Reportes ─────────────────────────────────────────────
    ws = wb.create_sheet("Reportes")

    columnas = [
        ("Código", 12), ("Fecha", 16), ("Estado", 22), ("Nivel", 8),
        ("Barrio", 20), ("Dirección", 32), ("Clasificación", 38),
        ("Objetos reciclables", 10), ("Peso (kg)", 10), ("Material predominante", 18),
        ("Observaciones", 40),
    ]
    if incluir_contacto:
        columnas.append(("Teléfono de quien reportó", 20))
    columnas += [("Latitud", 12), ("Longitud", 12)]

    for i, (nombre, ancho) in enumerate(columnas, start=1):
        c = ws.cell(row=1, column=i, value=nombre)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = CENTRO
        ws.column_dimensions[get_column_letter(i)].width = ancho
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"

    fila = 2
    for r in reportes:
        niv = r.get("Clasificación", "")
        niv_emoji = {"rojo": "Rojo", "amarillo": "Amarillo", "verde": "Verde"}[semaforo(niv)]
        clasif_txt = sin_emojis(niv)

        try:
            fecha_dt = datetime.strptime(r.get("Fecha", ""), "%Y-%m-%d %H:%M")
        except Exception:
            fecha_dt = r.get("Fecha", "")

        valores = [
            r.get("Código", ""), fecha_dt, r.get("Estado", "").strip(), niv_emoji,
            r.get("Sector", ""), r.get("Referencia", ""), clasif_txt,
            r.get("Objetos", 0), float(r.get("Peso (Kg)", 0) or 0), r.get("Predominante", ""),
            r.get("Observaciones", ""),
        ]
        if incluir_contacto:
            valores.append(contacto_visible(r.get("CodigoResidente", "")))
        valores += [r.get("Lat", ""), r.get("Lon", "")]
        valores = [seguro_excel(v) for v in valores]  # neutraliza =, +, -, @ al inicio

        color = COLOR_NIVEL.get(niv_emoji, "FFFFFF")
        for col_i, val in enumerate(valores, start=1):
            c = ws.cell(row=fila, column=col_i, value=val)
            c.alignment = IZQ if col_i in (6, 7, 11) else CENTRO
            c.border = BORDE
            c.fill = PatternFill("solid", fgColor=color)
            if col_i == 2 and isinstance(val, datetime):
                c.number_format = "DD/MM/YYYY HH:MM"
            if col_i == 9:
                c.number_format = "0.0"
        fila += 1

    ws.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{fila - 1}"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def difuminar_personas(img_pil, resultados_yolo, nombre_clase="person"):
    try:
        img = img_pil.convert("RGB").copy()
        hubo_personas = False
        for r in resultados_yolo:
            nombres = r.names if hasattr(r, "names") else modelo.names
            for box in r.boxes:
                idx = int(box.cls[0])
                if nombres.get(idx) != nombre_clase:
                    continue
                hubo_personas = True
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img.width, x2), min(img.height, y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                region = img.crop((x1, y1, x2, y2))
                radio = max(10, (x2 - x1) // 5)
                region = region.filter(ImageFilter.GaussianBlur(radius=radio))
                img.paste(region, (x1, y1))
        return img, hubo_personas
    except Exception:
        return img_pil, False


def calcular_phash(img_pil) -> str:
    try:
        return str(imagehash.phash(img_pil.convert("RGB")))
    except Exception:
        return ""


def distancia_hash(hash_a: str, hash_b: str) -> int:
    try:
        return imagehash.hex_to_hash(hash_a) - imagehash.hex_to_hash(hash_b)
    except Exception:
        return 999


def distancia_metros(lat1, lon1, lat2, lon2) -> float:
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def optimizar_ruta_recoleccion(reportes_lista: list, origen=None):
    """MEJORA 5 — Ordena reportes por proximidad usando un heurístico de
    vecino más cercano (greedy): en cada paso salta al punto no visitado
    más cercano al actual. No es la ruta matemáticamente más corta posible
    (eso es un problema NP-difícil — el "problema del viajante"), pero da
    un orden razonable para no cruzar la comuna de un extremo a otro sin
    necesidad, que es justo lo que pasa hoy si el camión sigue el orden en
    que llegaron los reportes.

    'origen' es una tupla (lat, lon) desde donde arranca el recorrido (por
    ejemplo, la base de operaciones); si no se da, arranca desde el primer
    reporte de la lista."""
    pendientes = [r for r in reportes_lista
                  if r.get("Lat") is not None and r.get("Lon") is not None]
    if not pendientes:
        return []

    ruta = []
    if origen:
        actual_lat, actual_lon = origen
    else:
        primero = pendientes.pop(0)
        ruta.append(primero)
        actual_lat, actual_lon = primero["Lat"], primero["Lon"]

    while pendientes:
        mas_cercano = min(
            pendientes,
            key=lambda r: distancia_metros(actual_lat, actual_lon, r["Lat"], r["Lon"])
        )
        pendientes.remove(mas_cercano)
        ruta.append(mas_cercano)
        actual_lat, actual_lon = mas_cercano["Lat"], mas_cercano["Lon"]

    return ruta


def generar_link_google_maps_ruta(ruta: list, origen=None) -> str:
    """MEJORA 5 — Arma un link de Google Maps con paradas encadenadas,
    formato https://www.google.com/maps/dir/lat1,lon1/lat2,lon2/... — a
    diferencia del formato con '?api=1&waypoints=' (limitado a pocas
    paradas), este formato de navegador soporta muchas más, así que sirve
    aunque la ruta del día tenga más de 10 puntos críticos."""
    puntos = []
    if origen:
        puntos.append(f"{origen[0]},{origen[1]}")
    puntos += [f"{r['Lat']},{r['Lon']}" for r in ruta]
    if len(puntos) < 2:
        return ""
    return "https://www.google.com/maps/dir/" + "/".join(puntos)


LIMITE_REPORTES_DIA = 8

def contar_reportes_hoy(codigo_residente: str) -> int:
    hoy = datetime.now().strftime("%Y-%m-%d")
    if codigo_residente.strip():
        return sum(
            1 for r in st.session_state.reportes
            if coincide_residente(r.get("CodigoResidente", ""), codigo_residente)
            and r.get("Fecha", "").startswith(hoy)
        )
    return st.session_state.get("reportes_hoy_sesion", 0)


def verificar_limite_reportes(codigo_residente: str) -> bool:
    n = contar_reportes_hoy(codigo_residente)
    if n >= LIMITE_REPORTES_DIA:
        if codigo_residente.strip():
            st.error(
                f"Ya alcanzaste el límite de {LIMITE_REPORTES_DIA} reportes hoy "
                f"con este código/teléfono. Si es una emergencia real, contacta "
                f"directamente a la administración."
            )
        else:
            st.error(
                f"Ya publicaste {LIMITE_REPORTES_DIA} reportes en esta sesión. "
                f"Espera a mañana, o escribe tu código/teléfono arriba para un "
                f"conteo más preciso en vez de por sesión del navegador."
            )
        return False
    return True


def verificar_fecha_exif(img_pil, dias_max=20):
    try:
        exif = img_pil._getexif()
        if not exif:
            return None
        fecha_str = exif.get(36867) or exif.get(306)  # DateTimeOriginal / DateTime
        if not fecha_str:
            return None
        fecha_foto = datetime.strptime(fecha_str, "%Y:%m:%d %H:%M:%S")
        dias = (datetime.now() - fecha_foto).days
        if dias > dias_max:
            return fecha_foto, dias
        return None
    except Exception:
        return None


def buscar_foto_reciclada(lat, lon, phash_nuevo, radio_max_valido_m=40, umbral_hash=6):
    if not phash_nuevo or lat is None or lon is None:
        return None
    for r in st.session_state.reportes:
        if not r.get("PHash") or r.get("Lat") is None:
            continue
        d_hash = distancia_hash(phash_nuevo, r["PHash"])
        if d_hash > umbral_hash:
            continue
        try:
            d_m = distancia_metros(lat, lon, r["Lat"], r["Lon"])
        except Exception:
            continue
        if d_m > radio_max_valido_m:
            return r, round(d_m, 1), d_hash
    return None


def buscar_posible_duplicado(lat, lon, phash_nuevo, radio_m=30, umbral_hash=10):
    if not phash_nuevo or lat is None or lon is None:
        return None
    mejor = None
    for r in st.session_state.reportes:
        if "Resuelto" in r.get("Estado", ""):
            continue
        if not r.get("PHash") or r.get("Lat") is None:
            continue
        try:
            d_m = distancia_metros(lat, lon, r["Lat"], r["Lon"])
        except Exception:
            continue
        if d_m > radio_m:
            continue
        d_hash = distancia_hash(phash_nuevo, r["PHash"])
        if d_hash <= umbral_hash and (mejor is None or d_hash < mejor[2]):
            mejor = (r, round(d_m, 1), d_hash)
    return mejor


def aviso_foto_reciclada(resultado) -> bool:
    if not resultado:
        return True
    rep_existente, d_m, _ = resultado
    st.error(
        f"**Esta foto ya se usó en el reporte {rep_existente['Código']}, "
        f"a {d_m}m de aquí** ({rep_existente.get('Sector','')}, "
        f"{rep_existente.get('Fecha','')}). Un mismo residuo no puede estar "
        f"en dos puntos distintos del mapa — sube una foto tomada en ESTE "
        f"punto para poder publicar."
    )
    return False


def aviso_duplicado(resultado, key_confirmar: str) -> bool:
    if not resultado:
        return True
    rep_existente, d_m, d_hash = resultado
    st.warning(
        f"**Posible reporte duplicado.** Encontré el reporte "
        f"**{rep_existente['Código']}** a solo {d_m}m de aquí, publicado el "
        f"{rep_existente.get('Fecha','')} ({rep_existente.get('Estado','')}), "
        f"con una foto muy parecida a la que acabas de subir."
    )
    return st.checkbox(
        "Sé que es un punto o residuo distinto — publicar de todas formas",
        key=key_confirmar
    )



def extraer_telefono_whatsapp(codigo_residente: str):
    if not codigo_residente or str(codigo_residente).startswith("h:"):
        return None
    digitos = "".join(c for c in codigo_residente if c.isdigit())
    if len(digitos) == 10 and digitos.startswith(("3",)):
        return "57" + digitos
    if len(digitos) == 12 and digitos.startswith("57"):
        return digitos
    return None


def link_whatsapp(telefono: str, mensaje: str) -> str:
    return f"https://wa.me/{telefono}?text={url_quote(mensaje)}"


def boton_whatsapp_html(url: str, texto: str) -> str:
    return (f'<a href="{url}" target="_blank" style="display:inline-block;'
            f'background:#25D366;color:white !important;text-decoration:none;'
            f'padding:10px 16px;border-radius:8px;font-weight:700;font-size:14px;'
            f'text-align:center;width:100%;box-sizing:border-box;">{texto}</a>')


DURACION_SESION_ADMIN_SEG = 60 * 60   # la sesión de admin caduca a la hora


def verificar_credenciales_admin(password_ingresada: str):
    """Verifica la contraseña de administrador SIN que exista en el código.
    ANTES la clave "ecocom2admin2026" estaba escrita a la vista en este
    archivo (y en el repositorio de GitHub): cualquiera podía leerla y entrar
    al panel para borrar o editar reportes. AHORA:
      - Se lee de st.secrets (ADMIN_PASS_SHA256 = hash, o ADMIN_PASSWORD) o de
        la variable de entorno ECOCOM2_ADMIN_HASH.
      - Se compara en tiempo constante (hmac.compare_digest).
      - Tras MAX_INTENTOS_ADMIN fallos se bloquea el login por 5 minutos.
      - Si no hay nada configurado, el panel queda CERRADO (no hay clave por
        defecto).
    Devuelve (ok, mensaje)."""
    ahora = time.time()
    bloqueado_hasta = st.session_state.get("admin_bloqueado_hasta", 0.0)
    if ahora < bloqueado_hasta:
        return False, (f"Demasiados intentos fallidos. Intenta de nuevo en "
                       f"{int(bloqueado_hasta - ahora)} segundos.")
    if not password_ingresada:
        return False, "Ingresa la contraseña de administrador."

    hash_ingresado = hashlib.sha256(password_ingresada.encode("utf-8")).hexdigest()
    hash_configurado = ""
    try:
        if "ADMIN_PASS_SHA256" in st.secrets:
            hash_configurado = str(st.secrets["ADMIN_PASS_SHA256"]).strip().lower()
        elif "ADMIN_PASSWORD" in st.secrets:
            hash_configurado = hashlib.sha256(
                str(st.secrets["ADMIN_PASSWORD"]).encode("utf-8")).hexdigest()
    except Exception:
        pass
    if not hash_configurado:
        hash_configurado = os.environ.get("ECOCOM2_ADMIN_HASH", "").strip().lower()
    if not hash_configurado:
        return False, ("El acceso de administrador no está configurado. Agrega "
                       "ADMIN_PASS_SHA256 (o ADMIN_PASSWORD) en Settings → Secrets.")

    if hmac.compare_digest(hash_ingresado, hash_configurado):
        st.session_state.admin_intentos = 0
        st.session_state.admin_login_ts = ahora
        return True, "Sesión iniciada"

    intentos = st.session_state.get("admin_intentos", 0) + 1
    st.session_state.admin_intentos = intentos
    _log.warning("Intento fallido de acceso admin (%s/%s)", intentos, MAX_INTENTOS_ADMIN)
    if intentos >= MAX_INTENTOS_ADMIN:
        st.session_state.admin_bloqueado_hasta = ahora + BLOQUEO_ADMIN_SEGUNDOS
        st.session_state.admin_intentos = 0
        return False, "Acceso bloqueado 5 minutos por demasiados intentos fallidos."
    return False, f"Contraseña incorrecta. Intentos restantes: {MAX_INTENTOS_ADMIN - intentos}."


def ecobot_cupo_disponible() -> bool:
    """Limita cuántas veces por hora una sesión puede llamar a Gemini desde
    EcoBot. Sin esto, cualquiera podía automatizar mensajes y gastar el cupo
    gratuito de la GEMINI_API_KEY (que también usa el análisis de fotos),
    dejando la app sin IA para el resto de los vecinos. Las respuestas ya
    redactadas (FAQ) no cuentan porque no llaman a Gemini."""
    ahora = time.time()
    marcas = [t for t in st.session_state.get("ecobot_marcas", []) if ahora - t < 3600]
    if len(marcas) >= MAX_MENSAJES_BOT_HORA:
        st.session_state.ecobot_marcas = marcas
        return False
    marcas.append(ahora)
    st.session_state.ecobot_marcas = marcas
    return True


def admin_sesion_vigente() -> bool:
    """True si hay sesión admin y no ha caducado. Si caducó, la cierra."""
    if not st.session_state.get("admin_ok", False):
        return False
    inicio = st.session_state.get("admin_login_ts", 0.0)
    if time.time() - inicio > DURACION_SESION_ADMIN_SEG:
        st.session_state.admin_ok = False
        return False
    return True


def es_residente():
    return st.session_state.validado and not st.session_state.fuera


def set_ubicacion(lat, lon, direccion=""):
    st.session_state.lat = lat
    st.session_state.lon = lon
    st.session_state.validado = True
    st.session_state.fuera = not POLIGONO_COMUNA2.contains(Point(lon, lat))
    st.session_state.direccion = direccion
    # Al verificar, se identifica el barrio para avisar el horario del camión
    st.session_state.barrio_usuario = barrio_desde_direccion(direccion)


Image.MAX_IMAGE_PIXELS = MAX_PIXELES_FOTO  # Pillow avisa/rechaza imágenes gigantes


def validar_foto_subida(uploaded_file):
    """Revisa una foto ANTES de procesarla: tamaño en bytes, formato real
    (no solo la extensión) y cantidad de píxeles. Evita que alguien suba un
    archivo disfrazado de .jpg, o una imagen diminuta en bytes pero enorme en
    píxeles que agote la memoria del servidor al abrirla."""
    try:
        datos = uploaded_file.getvalue()
        if len(datos) > MAX_BYTES_FOTO:
            return False, f"pesa más de {MAX_BYTES_FOTO // (1024*1024)} MB"
        im = Image.open(BytesIO(datos))
        if im.format not in ("JPEG", "PNG"):
            return False, "no es una imagen JPG o PNG válida"
        ancho, alto = im.size
        if ancho * alto > MAX_PIXELES_FOTO:
            return False, "tiene una resolución demasiado grande"
        im.verify()
        return True, ""
    except Exception:
        return False, "no se pudo leer como imagen"


def filtrar_fotos_validas(lista_archivos):
    """Devuelve solo las fotos que pasan validar_foto_subida y avisa por cada
    una rechazada."""
    validas = []
    for f in (lista_archivos or []):
        ok, motivo = validar_foto_subida(f)
        if ok:
            validas.append(f)
        else:
            st.error(f"La foto '{esc(getattr(f, 'name', 'sin nombre'))}' se descartó: {motivo}.")
    return validas


@st.cache_data(show_spinner=False, max_entries=12, ttl=900)
def _optimizar_foto_bytes(datos: bytes) -> bytes:
    """Reduce una foto de cámara (que puede pesar varios MB y tener 12-50
    megapíxeles) a un JPEG de máx. MAX_LADO_FOTO px por lado antes de analizarla.
    Así YOLO, Gemini y la pantalla trabajan con una imagen liviana y el
    servidor no se queda sin memoria. Endereza la foto según el EXIF, conserva
    la fecha de captura (para detectar fotos viejas) y borra el GPS del
    fotógrafo. Si algo falla, devuelve la foto original sin tocar."""
    try:
        im = Image.open(BytesIO(datos))
        formato = im.format
        if formato == "JPEG":
            try:
                im.draft("RGB", (MAX_LADO_FOTO * 2, MAX_LADO_FOTO * 2))  # decodifica ya reducida
            except Exception:
                pass
        if formato == "JPEG" and len(datos) <= 400 * 1024 and max(im.size) <= MAX_LADO_FOTO:
            return datos   # ya es liviana: no se recomprime
        im = ImageOps.exif_transpose(im)
        exif_bytes = b""
        try:
            ex = im.getexif()
            if 0x8825 in ex:          # GPS del fotógrafo: no hace falta y es privado
                del ex[0x8825]
            exif_bytes = ex.tobytes()
        except Exception:
            exif_bytes = b""
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            im = im.convert("RGBA")
            fondo = Image.new("RGB", im.size, (255, 255, 255))
            fondo.paste(im, mask=im.split()[-1])
            im = fondo
        else:
            im = im.convert("RGB")
        im.thumbnail((MAX_LADO_FOTO, MAX_LADO_FOTO), Image.LANCZOS)
        buf = BytesIO()
        kwargs = {"format": "JPEG", "quality": 85, "optimize": True}
        if exif_bytes:
            kwargs["exif"] = exif_bytes
        im.save(buf, **kwargs)
        out = buf.getvalue()
        return out if len(out) < len(datos) or formato != "JPEG" else datos
    except Exception as e:
        _log.warning("No se pudo optimizar la foto: %s", e)
        return datos


def _abrir_img_subida(uploaded_file) -> Image.Image:
    """Abre la foto subida ya optimizada (ver _optimizar_foto_bytes)."""
    return Image.open(BytesIO(_optimizar_foto_bytes(uploaded_file.getvalue())))


def _hash_imagen(img_pil) -> str:
    """MEJORA 4 — Genera una huella única y rápida de una imagen ya abierta,
    para saber si es LA MISMA foto que ya se analizó (y así no relanzar el
    análisis en cada rerun de Streamlit) o si el usuario subió una foto
    distinta (y entonces sí hay que re-analizar automáticamente)."""
    try:
        buf = BytesIO()
        img_pil.save(buf, format="JPEG")
        return hashlib.md5(buf.getvalue()).hexdigest()
    except Exception:
        return ""


# ====================================================================
# 6.1 CLASIFICADOR GEMINI (Google) — detección por categoría de material
# ====================================================================
def _gemini_config():
    """Lee GEMINI_API_KEY desde st.secrets. Si no está configurada,
    devuelve None — el motor Gemini queda simplemente desactivado sin
    romper nada del resto de la app (se puede seguir usando YOLO)."""
    try:
        api_key = st.secrets.get("GEMINI_API_KEY", "").strip()
        if api_key:
            return api_key
    except Exception:
        pass
    return None


def verificar_gemini_key() -> bool:
    return bool(_gemini_config())


# Categorías que reconoce el clasificador de Gemini — cada una con su
# color de caja fijo (así la foto anotada siempre se ve igual, sin
# importar la confianza del modelo), su etiqueta en español y un peso
# promedio aproximado por objeto. A diferencia de YOLO, Gemini no nos
# da el tipo exacto de objeto (ej. "botella"), solo la categoría de
# material — por eso el peso aquí es un promedio por categoría, no por
# tipo de objeto como en el diccionario MAT.
CATEGORIAS_GEMINI = {
    "Organicos": {"color": "#92400e", "etiqueta": "Orgánicos",              "etiqueta_dibujo": "Organicos", "peso_kg": 0.20, "reciclable": True},
    "Plasticos": {"color": "#3b82f6", "etiqueta": "Plásticos",              "etiqueta_dibujo": "Plasticos", "peso_kg": 0.15, "reciclable": True},
    "Vidrio":    {"color": "#a855f7", "etiqueta": "Vidrio",                 "etiqueta_dibujo": "Vidrio",    "peso_kg": 0.35, "reciclable": True},
    "Carton":    {"color": "#16a34a", "etiqueta": "Cartón",                 "etiqueta_dibujo": "Carton",    "peso_kg": 0.30, "reciclable": True},
    "Papel":     {"color": "#eab308", "etiqueta": "Papel",                  "etiqueta_dibujo": "Papel",     "peso_kg": 0.10, "reciclable": True},
    "Otros":     {"color": "#ef4444", "etiqueta": "Otros / no identificado", "etiqueta_dibujo": "Otros",     "peso_kg": 0.20, "reciclable": False},
}

_PROMPT_GEMINI_RESIDUOS = """Eres un clasificador de residuos sólidos para una app de gestión de basura comunitaria, y también un filtro contra reportes falsos o de mala fe — por ejemplo, alguien fotografiando un negocio legítimo en funcionamiento (como un puesto de comida), una vivienda, un vehículo, una mascota, u otra persona, e intentando hacerlo pasar como un punto de basura para molestar o perjudicar a alguien.

PASO 1: Evalúa si la imagen realmente muestra una acumulación de residuos
sólidos en un espacio público (basura, escombros, bolsas, objetos
desechados, etc.). Responde "es_residuos": false si la imagen muestra, por
ejemplo: un negocio o puesto de comida en funcionamiento, una vivienda o
fachada normal, personas, vehículos, mascotas, o cualquier escena sin una
acumulación real de residuos.

PASO 2: Si "es_residuos" es true, detecta CADA objeto o bolsa de residuo
visible por separado. Si hay un montón, separa los objetos identificables
dentro del montón en vez de encerrar todo el montón en una sola caja.
Si el montón es tan homogéneo o está tan mezclado que de verdad no puedes
distinguir objetos individuales, NO devuelvas una lista vacía — en su
lugar, encierra en cajas más grandes las zonas visibles agrupadas por
material predominante (ej. una caja cubriendo toda la zona de escombros,
otra la zona de bolsas plásticas), para dar al menos una estimación
aproximada en vez de ningún resultado.

IMPORTANTE: no dejes NINGÚN residuo visible sin encerrar en una caja. Si
un objeto no encaja claramente en ninguna categoría de material, ponlo en
"Otros" — pero siempre debe quedar dentro de alguna caja, nunca fuera de
todas. Los escombros o montones de construcción SIEMPRE van en cajas
separadas del resto (categoría "Otros"), nunca mezclados con bolsas de
material reciclable en la misma caja.

REGLA CLAVE — clasifica por CONTENIDO, no por el empaque: si ves un
costal, bulto o bolsa cuyo material exterior es plástico pero claramente
está lleno de escombros, piedras, tierra o material de construcción (se
nota por la forma abultada, irregular y pesada, o porque el contenido se
asoma), clasifícalo como "Otros" — NUNCA como "Plasticos". Un costal
lleno de piedras no es plástico reciclable solo porque su envoltura lo
sea; lo que se recicla es el residuo real que contiene, no la bolsa que
lo envuelve. Solo clasifica como "Plasticos" el plástico limpio y suelto
(botellas, bolsas vacías, envases, empaques) cuyo contenido visible es
efectivamente plástico o está vacío.

Clasifica cada objeto o zona detectada en UNA sola de estas categorías
EXACTAS (usa el texto tal cual, sin tildes ni cambios):
- "Organicos"  (comida, restos vegetales, madera en descomposición)
- "Plasticos"  (botellas, bolsas, envases, empaques plásticos — vacíos o con residuo plástico real)
- "Vidrio"     (botellas o frascos de vidrio)
- "Carton"     (cajas, cartón)
- "Papel"      (papel, periódico, revistas)
- "Otros"      (escombros, piedras, tierra, costales llenos de material de construcción, metal, ropa, o cualquier cosa que no encaje arriba)

Si "es_residuos" es false, deja "detecciones" como una lista vacía. Si
"es_residuos" es true, "detecciones" debe tener AL MENOS un elemento.

Responde ÚNICAMENTE con un objeto JSON (sin texto adicional ni marcado
markdown), con este formato exacto:
{"es_residuos": true, "motivo": "breve explicación de una frase", "detecciones": [{"label": "Plasticos", "box_2d": [ymin, xmin, ymax, xmax]}, ...]}

Las coordenadas box_2d deben estar normalizadas en una escala de 0 a 1000,
en el orden [ymin, xmin, ymax, xmax]. Detecta como máximo 40 objetos."""


# Modelos de Gemini a probar, en orden. Ordenados de MAYOR a MENOR cupo
# gratuito disponible (RPM = solicitudes por minuto), según el panel de
# Google AI Studio — así la app gasta primero el cupo de los modelos que
# menos se usan, en vez de agotar siempre el mismo (gemini-3.6-flash, que
# ya estaba casi al tope: 4/5). Solo se incluyen modelos "de texto de
# salida" que aceptan imagen + texto y devuelven JSON — no las variantes
# Pro (0/0 de cupo en tu cuenta), ni las de imagen/TTS/agentes, que no
# sirven para este clasificador.
MODELOS_GEMINI_RESPALDO = [
    "gemini-3.1-flash-lite",  # 15 RPM — el de más cupo libre
    "gemini-2.5-flash-lite",  # 10 RPM
    "gemini-2.5-flash",       # 5 RPM
    "gemini-3-flash",         # 5 RPM
    "gemini-3.6-flash",       # 5 RPM — último, porque ya se satura más rápido
]


@st.cache_resource
def _contador_tokens() -> dict:
    """Consumo de IA acumulado por día (se reinicia si la app se reinicia)."""
    return {}


def _sumar_tokens(data, categoria: str = "texto"):
    """Suma los tokens que Gemini informa haber gastado en una llamada."""
    try:
        uso = (data or {}).get("usageMetadata", {}) or {}
        total = int(uso.get("totalTokenCount", 0) or 0)
        dia = _hoy_colombia().strftime("%Y-%m-%d")
        c = _contador_tokens().setdefault(
            dia, {"texto_llamadas": 0, "texto_tokens": 0, "voz_llamadas": 0, "voz_tokens": 0})
        c[f"{categoria}_llamadas"] += 1
        c[f"{categoria}_tokens"] += total
    except Exception:
        pass


@st.cache_resource
def _estado_modelos_gemini() -> dict:
    """Memoria compartida por todas las sesiones: qué modelos están caídos
    o sin cupo y hasta cuándo conviene saltárselos."""
    return {}


def _llamar_gemini_con_respaldo(payload, timeout=30, reintentos_por_modelo=1):
    """Prueba varios modelos de Gemini en orden hasta que uno responda.
    503/429 (saturado o sin cupo) o 404 (modelo inexistente en tu cuenta)
    -> pasa al siguiente. Devuelve (respuesta_json, modelo_usado, error)."""
    import requests
    api_key = _gemini_config()
    if not api_key:
        return None, None, "Falta configurar GEMINI_API_KEY en Secrets."

    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    ultimo_error = "error desconocido"

    # RAPIDEZ: si un modelo acaba de fallar (sin cupo, saturado o inexistente)
    # se omite un rato, en vez de perder segundos intentándolo en cada mensaje.
    _caidos = _estado_modelos_gemini()
    _ahora = time.time()
    _candidatos = [m for m in MODELOS_GEMINI_RESPALDO if _caidos.get(m, 0) <= _ahora] \
        or list(MODELOS_GEMINI_RESPALDO)
    for nombre_modelo in _candidatos:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{nombre_modelo}:generateContent")
        resp = None
        for intento in range(reintentos_por_modelo):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
            except Exception as e:
                ultimo_error = f"Error de conexión ({nombre_modelo}): {e}"
                resp = None
                break
            if resp.status_code not in (503, 429):
                break
            if intento < reintentos_por_modelo - 1:
                time.sleep(2)

        if resp is None:
            continue
        if resp.status_code == 200:
            _datos = resp.json()
            _sumar_tokens(_datos, "texto")
            return _datos, nombre_modelo, None

        try:
            detalle = resp.json().get("error", {}).get("message", "")
        except Exception:
            detalle = ""
        ultimo_error = f"{nombre_modelo} respondió {resp.status_code}: {detalle or 'error desconocido'}"
        _pausa = {404: 3600, 429: 60, 503: 20}.get(resp.status_code, 0)
        if _pausa:
            _caidos[nombre_modelo] = time.time() + _pausa

        if resp.status_code not in (503, 429, 404):
            break  # 401/400: error real, no sirve probar otro modelo

    return None, None, ultimo_error


def analizar_con_gemini(img_pil, modelo_gemini=None):
    """Envía la imagen a la API de Gemini (Google) para que primero evalúe
    si la foto realmente muestra una acumulación de residuos (filtro
    contra reportes falsos o de mala fe — ej. fotografiar un negocio o a
    una persona para hacerlo pasar por basura), y si es así, detecte y
    clasifique cada residuo visible en Orgánicos / Plásticos / Vidrio /
    Cartón / Papel / Otros con una caja delimitadora por objeto.

    Usa una cadena de modelos de respaldo (MODELOS_GEMINI_RESPALDO), así
    que si uno se queda sin cupo se prueba el siguiente automáticamente.

    Devuelve (detecciones, error, es_valido, motivo):
    - detecciones: lista de dicts con 'categoria' y 'box' en píxeles.
    - error: mensaje de error si la llamada falló, o None si todo bien.
    - es_valido: True/False según si Gemini considera que es un reporte
      real de residuos; None si no se pudo determinar (ej. hubo error).
    - motivo: breve explicación de Gemini, útil para mostrarle al usuario
      por qué se rechazó su foto."""
    if not _gemini_config():
        return None, "Falta configurar GEMINI_API_KEY en Secrets.", None, ""
    try:
        img_rgb = img_pil.convert("RGB")
        w, h = img_rgb.size
        buf = BytesIO()
        img_rgb.save(buf, format="JPEG", quality=85)
        img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        payload = {
            "contents": [{
                "parts": [
                    {"text": _PROMPT_GEMINI_RESIDUOS},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
                ]
            }],
            "generationConfig": {
                "temperature": 0.2,
                "response_mime_type": "application/json",
            },
        }

        data, _modelo_usado, error = _llamar_gemini_con_respaldo(payload, timeout=45)
        if error:
            return None, error, None, ""

        texto = data["candidates"][0]["content"]["parts"][0]["text"]
        texto_limpio = texto.replace("```json", "").replace("```", "").strip()
        resultado = json.loads(texto_limpio)
        if not isinstance(resultado, dict):
            return [], None, True, ""

        es_valido = resultado.get("es_residuos", True)  # si falta el campo, no bloquear por precaución
        motivo = resultado.get("motivo", "")
        crudos = resultado.get("detecciones", [])
        if not isinstance(crudos, list):
            crudos = []

        detecciones = []
        for item in crudos:
            box = item.get("box_2d")
            label = item.get("label", "Otros")
            if label not in CATEGORIAS_GEMINI:
                label = "Otros"
            if not box or len(box) != 4:
                continue
            ymin, xmin, ymax, xmax = box
            x1 = max(0, int(xmin / 1000 * w))
            y1 = max(0, int(ymin / 1000 * h))
            x2 = min(w, int(xmax / 1000 * w))
            y2 = min(h, int(ymax / 1000 * h))
            if x2 <= x1 or y2 <= y1:
                continue
            detecciones.append({"categoria": label, "box": [x1, y1, x2, y2]})
        detecciones = _deduplicar_detecciones_gemini(detecciones)
        return detecciones, None, es_valido, motivo
    except Exception as e:
        return None, f"Error de conexión con Gemini: {e}", None, ""


def _deduplicar_detecciones_gemini(detecciones, iou_umbral=0.45):
    """Gemini a veces marca el mismo objeto dos o tres veces muy cerca en
    montones densos — fusiona cajas de la MISMA categoría que se solapan
    mucho (igual criterio que ya se usa para las detecciones de YOLO), así
    la imagen anotada no queda saturada de cajas repetidas sobre un mismo
    objeto y el conteo de reciclables no se infla artificialmente."""
    def _area(d):
        x1, y1, x2, y2 = d["box"]
        return (x2 - x1) * (y2 - y1)

    ordenados = sorted(detecciones, key=_area, reverse=True)
    conservados = []
    for d in ordenados:
        if any(d["categoria"] == c["categoria"] and _iou(d["box"], c["box"]) >= iou_umbral
               for c in conservados):
            continue
        conservados.append(d)
    return conservados


def dibujar_detecciones_gemini(img_pil, detecciones):
    """Dibuja las cajas devueltas por Gemini sobre la imagen, con un
    color fijo por categoría (igual en toda la app) y la etiqueta en
    español encima de cada caja — el mismo estilo visual que se usa
    para revisar el análisis antes de publicar el reporte."""
    from PIL import ImageDraw, ImageFont
    img = img_pil.convert("RGB").copy()
    if not detecciones:
        return img
    draw = ImageDraw.Draw(img)
    try:
        fuente = ImageFont.load_default(size=15)
    except TypeError:
        fuente = ImageFont.load_default()
    for d in detecciones:
        cat = CATEGORIAS_GEMINI.get(d["categoria"], CATEGORIAS_GEMINI["Otros"])
        x1, y1, x2, y2 = d["box"]
        draw.rectangle([x1, y1, x2, y2], outline=cat["color"], width=2)
        etiqueta = cat["etiqueta_dibujo"]
        ancho_etq = 8 * len(etiqueta) + 8
        y_etq = max(0, y1 - 18)
        draw.rectangle([x1, y_etq, x1 + ancho_etq, y_etq + 16], fill=cat["color"])
        draw.text((x1 + 3, y_etq), etiqueta, fill=(255, 255, 255), font=fuente)

    img = _dibujar_resumen_gemini(img, detecciones)
    return img


def _hex_a_rgb(color_hex):
    color_hex = color_hex.lstrip("#")
    return tuple(int(color_hex[i:i + 2], 16) for i in (0, 2, 4))


def _dibujar_resumen_gemini(img_pil, detecciones):
    """Agrega una franja semitransparente en la esquina inferior izquierda
    con el conteo total por categoría (ej. 'Plasticos: 17') — para que de
    un vistazo, sin contar cajas una por una, se entienda qué hay en el
    reporte. Va abajo (no arriba) porque las cajas de detección suelen
    concentrarse en la mitad/parte alta de la foto (donde está el montón),
    así se reduce que el resumen tape alguna caja. Solo lista las
    categorías que sí aparecieron en la foto."""
    from PIL import ImageDraw, ImageFont
    conteo = Counter(d["categoria"] for d in detecciones)
    if not conteo:
        return img_pil

    orden = ["Plasticos", "Organicos", "Carton", "Papel", "Vidrio", "Otros"]
    filas = [(cat, conteo[cat]) for cat in orden if conteo.get(cat)]
    if not filas:
        return img_pil

    img_rgba = img_pil.convert("RGBA")
    w, h = img_rgba.size
    overlay = Image.new("RGBA", img_rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    try:
        fuente = ImageFont.load_default(size=16)
    except TypeError:
        fuente = ImageFont.load_default()

    pad, alto_fila, lado_caja, ancho_panel = 10, 22, 14, 190
    alto_panel = pad * 2 + alto_fila * len(filas)
    x0, y0 = 10, h - alto_panel - 10
    draw.rectangle([x0, y0, x0 + ancho_panel, y0 + alto_panel], fill=(0, 0, 0, 170))

    y = y0 + pad
    for cat, cant in filas:
        info = CATEGORIAS_GEMINI.get(cat, CATEGORIAS_GEMINI["Otros"])
        color_rgb = _hex_a_rgb(info["color"])
        x = x0 + pad
        draw.rectangle([x, y + 3, x + lado_caja, y + 3 + lado_caja], fill=color_rgb + (255,))
        draw.text((x + lado_caja + 8, y), f"{info['etiqueta_dibujo']}: {cant}",
                   fill=(255, 255, 255, 255), font=fuente)
        y += alto_fila

    return Image.alpha_composite(img_rgba, overlay).convert("RGB")


def procesar_gemini(detecciones):
    """Convierte las detecciones de Gemini (categoría + caja) al MISMO
    formato de salida que procesar() usa para YOLO — así el resto de la
    app (metricas(), guardado del reporte, tabla de resultados, etc.)
    no necesita saber qué motor de IA se usó para generar el análisis."""
    if not detecciones:
        return [], 0, 0.0, "N/D", "Sin residuos detectados", 0

    conteo = Counter(d["categoria"] for d in detecciones)
    tabla, peso_total, residuos, no_rec = [], 0.0, 0, 0
    cnt_mat = Counter()

    for cat, cant in conteo.items():
        info = CATEGORIAS_GEMINI.get(cat, CATEGORIAS_GEMINI["Otros"])
        p = round(info["peso_kg"] * cant, 2)
        peso_total += p
        if info["reciclable"]:
            residuos += cant
            cnt_mat[cat] += cant
            tabla.append({"Objeto": info["etiqueta"], "Material": cat,
                          "Cant.": cant, "Peso (kg)": p,
                          "Confianza": "IA Gemini", "Reciclable": "Sí"})
        else:
            no_rec += cant
            tabla.append({"Objeto": info["etiqueta"], "Material": "—",
                          "Cant.": cant, "Peso (kg)": p,
                          "Confianza": "IA Gemini", "Reciclable": "No"})

    tipo  = cnt_mat.most_common(1)[0][0] if cnt_mat else "Mixto"
    total = residuos + no_rec
    ratio = residuos / total if total > 0 else 0

    ESCALA_ALERTA_OBJ, ESCALA_CRITICA_OBJ = 15, 30
    PESO_ALERTA_KG,    PESO_CRITICA_KG    = 20.0, 50.0
    gran_volumen    = residuos >= ESCALA_ALERTA_OBJ  or peso_total >= PESO_ALERTA_KG
    volumen_critico = residuos >= ESCALA_CRITICA_OBJ or peso_total >= PESO_CRITICA_KG

    if volumen_critico:
        nivel = "Punto crítico — Gran acumulación, recolección urgente"
    elif total <= 2 and ratio >= 0.5:
        nivel = "Residuo puntual"
    elif ratio < 0.30:
        nivel = "Punto crítico — Acumulación sin valorización"
    elif gran_volumen:
        nivel = "Punto amarillo — Buen material, pero gran volumen"
    elif ratio >= 0.60:
        nivel = "Punto verde — Alta valorización reciclable"
    else:
        nivel = "Punto amarillo — Residuos mixtos"

    return tabla, residuos, round(peso_total, 2), tipo, nivel, total


def analizar(img, imgsz=640):
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            img.save(tmp.name)
            tmp_path = tmp.name
        # conf más bajo (antes 0.25): captura objetos que el modelo detecta
        # con menos certeza, como una segunda botella parcialmente oculta.
        # iou más alto (antes por defecto ~0.7 sin control explícito):
        # evita que el NMS interno del modelo fusione dos objetos de la
        # misma clase que están físicamente cerca (ej. botellas juntas).
        # agnostic_nms=False asegura que esa fusión solo compare objetos
        # de la MISMA clase, nunca clases distintas entre sí.
        return modelo(tmp_path, conf=0.15, iou=0.8, agnostic_nms=False, imgsz=imgsz)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


def _iou(caja_a, caja_b):
    xa1, ya1, xa2, ya2 = caja_a
    xb1, yb1, xb2, yb2 = caja_b
    ix1, iy1 = max(xa1, xb1), max(ya1, yb1)
    ix2, iy2 = min(xa2, xb2), min(ya2, yb2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, xa2 - xa1) * max(0.0, ya2 - ya1)
    area_b = max(0.0, xb2 - xb1) * max(0.0, yb2 - yb1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _deduplicar_detecciones(objetos, iou_umbral=0.55):
    """Fusiona cajas que se solapan mucho — pero SOLO si son del mismo
    tipo de objeto (ej. dos cajas de 'plastic bottle' casi idénticas,
    señal de que la IA detectó la MISMA botella dos veces). Antes esto
    también fusionaba objetos DISTINTOS que estaban cerca (ej. dos
    botellas juntas), y por eso una de las dos 'desaparecía' del
    conteo aunque la IA sí la hubiera detectado correctamente."""
    ordenados = sorted(objetos, key=lambda o: o[1], reverse=True)
    conservados = []
    for nombre, conf, caja in ordenados:
        if any(nombre == c[0] and _iou(caja, c[2]) >= iou_umbral for c in conservados):
            continue
        conservados.append((nombre, conf, caja))
    return conservados


def _extraer_detecciones_filtradas(resultados):
    """Extrae las detecciones del modelo y aplica el filtro de confianza
    (más estricto para clases distractoras como persona/carro/bici) y la
    deduplicación por clase — esta es la ÚNICA fuente de verdad sobre
    qué detecciones cuentan de verdad. Tanto procesar() (para la tabla)
    como dibujar_detecciones_filtradas() (para la imagen) usan esta
    misma función, así los dos SIEMPRE muestran lo mismo."""
    objetos = []
    for r in resultados:
        for box in r.boxes:
            nombre = modelo.names[int(box.cls[0])]
            conf   = float(box.conf[0])
            caja   = box.xyxy[0].tolist()
            objetos.append((nombre, conf, caja))

    if not objetos:
        return []

    objetos = [
        (nombre, conf, caja) for nombre, conf, caja in objetos
        if (nombre in CLASES_DISTRACTORAS and conf >= UMBRAL_CONF_DISTRACTOR)
        or (nombre not in CLASES_DISTRACTORAS and (nombre in MAT or conf >= UMBRAL_CONF_CLASE_DESCONOCIDA))
    ]
    return _deduplicar_detecciones(objetos)


def dibujar_detecciones_filtradas(img_pil, resultados):
    """Dibuja SOLO las cajas que sobrevivieron el filtro de confianza —
    las mismas que cuenta la tabla de resultados. Reemplaza a
    res[0].plot(), que dibujaba TODAS las detecciones crudas del
    modelo (incluidas las de baja confianza que la tabla ya descarta),
    lo cual hacía parecer que el filtro 'no funcionaba' cuando en
    realidad sí actuaba, solo que no sobre esta imagen."""
    from PIL import ImageDraw, ImageFont
    objetos = _extraer_detecciones_filtradas(resultados)
    img = img_pil.convert("RGB").copy()
    if not objetos:
        return img
    draw = ImageDraw.Draw(img)
    try:
        fuente = ImageFont.load_default(size=14)
    except TypeError:
        fuente = ImageFont.load_default()
    for nombre, conf, caja in objetos:
        x1, y1, x2, y2 = [int(v) for v in caja]
        draw.rectangle([x1, y1, x2, y2], outline=(22, 163, 74), width=3)
        etiqueta = f"{nombre} {conf:.2f}"
        ancho_etq = 7 * len(etiqueta) + 6
        y_etq = max(0, y1 - 18)
        draw.rectangle([x1, y_etq, x1 + ancho_etq, y_etq + 18], fill=(22, 163, 74))
        draw.text((x1 + 3, y_etq + 1), etiqueta, fill=(255, 255, 255), font=fuente)
    return img


def procesar(resultados):
    objetos = _extraer_detecciones_filtradas(resultados)

    if not objetos:
        return [], 0, 0.0, "N/D", "Sin residuos detectados", 0

    conteo = Counter(o[0] for o in objetos)
    mejor  = {n: max(c for nn, c, _ in objetos if nn == n) for n in conteo}

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
                          "Confianza": conf, "Reciclable": "Sí"})
        else:
            no_rec += cant
            tabla.append({"Objeto": nom, "Material": "—",
                          "Cant.": cant, "Peso (kg)": 0,
                          "Confianza": conf, "Reciclable": "No"})

    tipo  = cnt_mat.most_common(1)[0][0] if cnt_mat else "Mixto"
    total = residuos + no_rec
    ratio = residuos / total if total > 0 else 0

    ESCALA_ALERTA_OBJ, ESCALA_CRITICA_OBJ = 15, 30
    PESO_ALERTA_KG,    PESO_CRITICA_KG    = 20.0, 50.0
    gran_volumen    = residuos >= ESCALA_ALERTA_OBJ  or peso_total >= PESO_ALERTA_KG
    volumen_critico = residuos >= ESCALA_CRITICA_OBJ or peso_total >= PESO_CRITICA_KG

    if volumen_critico:
        nivel = "Punto crítico — Gran acumulación, recolección urgente"
    elif total <= 2 and ratio >= 0.5:
        nivel = "Residuo puntual"
    elif ratio < 0.30:
        nivel = "Punto crítico — Acumulación sin valorización"
    elif gran_volumen:
        nivel = "Punto amarillo — Buen material, pero gran volumen"
    elif ratio >= 0.60:
        nivel = "Punto verde — Alta valorización reciclable"
    else:
        nivel = "Punto amarillo — Residuos mixtos"

    return tabla, residuos, round(peso_total, 2), tipo, nivel, total


def badge(txt, tipo="ok"):
    cls = {"ok":"badge-ok","warn":"badge-warn","err":"badge-err"}[tipo]
    st.markdown(f'<div class="{cls}">{txt}</div><br>', unsafe_allow_html=True)


def progreso_pasos(paso_actual: int, labels=None):
    labels = labels or ["Dirección", "Punto en mapa", "Foto", "Publicar"]
    total = len(labels)
    cols = st.columns(total)
    for i, (col, label) in enumerate(zip(cols, labels), start=1):
        with col:
            if i < paso_actual:
                st.markdown(
                    f'<div style="text-align:center;color:#16a34a;font-weight:700;'
                    f'font-size:12px;padding:4px 2px;border-bottom:3px solid #16a34a;">'
                    f'{label}</div>', unsafe_allow_html=True)
            elif i == paso_actual:
                st.markdown(
                    f'<div style="text-align:center;color:#16a34a;font-weight:700;'
                    f'font-size:12px;padding:4px 2px;border-bottom:3px solid #4ade80;">'
                    f'{label}</div>', unsafe_allow_html=True)
            else:
                st.markdown(
                    f'<div style="text-align:center;color:#9ca3af;font-weight:500;'
                    f'font-size:12px;padding:4px 2px;border-bottom:3px solid #e5e7eb;">'
                    f'{label}</div>', unsafe_allow_html=True)


import math

def gauge_svg_aguja(valor: float, titulo: str, sufijo: str = "%") -> str:
    """Medidor de aguja con 3 bandas de 60° (rojo/amarillo/verde) — mismo
    estilo semáforo que el dashboard de Excel, calculado en vivo con
    Python, sin fórmulas ni macros."""
    valor_clamp = max(0, min(100, valor))
    angulo = math.radians(180 - (valor_clamp / 100) * 180)
    cx, cy, r = 100, 95, 80
    x_aguja = cx + r * 0.85 * math.cos(angulo)
    y_aguja = cy - r * 0.85 * math.sin(angulo)

    def arc(deg_ini, deg_fin):
        a0, a1 = math.radians(deg_ini), math.radians(deg_fin)
        x0, y0 = cx + r * math.cos(a0), cy - r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy - r * math.sin(a1)
        return f"M {x0:.1f} {y0:.1f} A {r} {r} 0 0 0 {x1:.1f} {y1:.1f}"

    return f'''<div style="text-align:center;background:#ffffff;border:1px solid #bbf7d0;
border-radius:12px;padding:10px;">
<svg viewBox="0 0 200 120" style="width:100%;max-width:180px;">
<path d="{arc(180,120)}" stroke="#dc2626" stroke-width="18" fill="none"/>
<path d="{arc(120,60)}" stroke="#eab308" stroke-width="18" fill="none"/>
<path d="{arc(60,0)}" stroke="#16a34a" stroke-width="18" fill="none"/>
<line x1="{cx}" y1="{cy}" x2="{x_aguja:.1f}" y2="{y_aguja:.1f}"
      stroke="#111827" stroke-width="3" stroke-linecap="round"/>
<circle cx="{cx}" cy="{cy}" r="5" fill="#111827"/>
<text x="{cx}" y="115" text-anchor="middle" font-size="16" font-weight="700"
      fill="#14532d">{valor_clamp:.0f}{sufijo}</text>
</svg>
<p style="font-size:12px;color:#166534;margin:2px 0 0;font-weight:600;">{titulo}</p>
</div>'''


def explicar_deteccion_ia(tabla, nivel, peso=None, motor="yolo"):
    """Arma, en palabras simples, QUÉ detectó la IA y POR QUÉ dio esa prioridad.
    Devuelve (frase_principal, detalle). Los porcentajes son sobre la cantidad
    de objetos detectados (no sobre el peso)."""
    from collections import Counter as _C
    grupos, recicl, total = _C(), 0, 0
    for fila in tabla or []:
        cant = int(fila.get("Cant.", 1) or 1)
        etiqueta = (fila.get("Material") if fila.get("Reciclable") == "Sí"
                    else fila.get("Objeto")) or "otros"
        grupos[str(etiqueta).strip().lower()] += cant
        total += cant
        if fila.get("Reciclable") == "Sí":
            recicl += cant
    if not total:
        return "", ""
    orden = grupos.most_common()
    principales, resto = orden[:3], sum(c for _, c in orden[3:])
    if resto:
        principales.append(("otros", resto))
    pcts = [round(c * 100 / total) for _, c in principales]
    pcts[0] += 100 - sum(pcts)          # que siempre sumen 100
    partes = [f"{p}% {n}" for p, (n, _) in zip(pcts, principales) if p > 0]
    prioridad = {"rojo": "Alta", "amarillo": "Media", "verde": "Baja"}[semaforo(nivel)]
    frase = f"IA detectó: {', '.join(partes)} — Prioridad {prioridad}"

    n = str(nivel or "").lower()
    if "gran acumulación" in n:
        razon = "hay una gran cantidad de residuos acumulados"
    elif "sin valorización" in n:
        razon = "casi nada de lo que se ve se puede reciclar"
    elif "gran volumen" in n:
        razon = "el material sirve, pero hay mucho volumen"
    elif "alta valorización" in n:
        razon = "la mayoría es material reciclable"
    elif "puntual" in n:
        razon = "son pocos objetos"
    else:
        razon = "hay una mezcla de materiales reciclables y no reciclables"
    motor_txt = "Gemini (IA de Google)" if motor == "gemini" else "YOLO (IA local)"
    peso_txt = f" Peso estimado: {peso} kg." if peso not in (None, "") else ""
    detalle = (f"Prioridad {prioridad.lower()} porque {razon}. Se identificaron {total} objetos "
               f"({recicl} reciclables).{peso_txt} Los porcentajes son sobre la cantidad de "
               f"objetos, no sobre el peso. Motor: {motor_txt}. Es una estimación automática: "
               f"si no coincide con lo que ves, anótalo en las observaciones.")
    return frase, detalle


def mostrar_explicacion_ia(tabla, nivel, peso=None, motor="yolo"):
    frase, detalle = explicar_deteccion_ia(tabla, nivel, peso, motor)
    if not frase:
        return
    {"rojo": st.error, "amarillo": st.warning, "verde": st.success}[semaforo(nivel)](f"**{frase}**")
    st.caption(detalle)


def metricas(residuos, peso, nivel):
    c1, c2, c3 = st.columns(3)
    color = {"verde": "#4ade80", "amarillo": "#fbbf24", "rojo": "#f87171"}[semaforo(nivel)]
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


def _img_tutorial(b64: str) -> str:
    return (f'<img src="data:image/jpeg;base64,{b64}" '
            f'style="max-width:100%;border-radius:12px;border:2px solid #4ade80;'
            f'box-shadow:0 4px 14px rgba(22,163,74,0.20);">')


PASOS_TUTORIAL = [
    {
        "visual_html": "",
        "titulo": "¡Bienvenido a EcoCom2 Circular IA!",
        "texto": "Entre todos podemos mantener la Comuna 2 más limpia. Te mostramos "
                 "en 4 pasos rápidos cómo funciona — toma 30 segundos.",
    },
    {
        "visual_html": "",
        "titulo": "1. Verifica tu dirección",
        "texto": "Usa el botón grande de GPS, o escribe tu dirección si prefieres. "
                 "Solo residentes DENTRO de la Comuna 2 pueden publicar reportes — "
                 "cualquiera puede ver el mapa.",
    },
    {
        "visual_html": "",
        "titulo": "2. Reporta un residuo",
        "texto": "Toca el mapa donde está el residuo, sube una foto, y la IA la "
                 "analiza sola — te dice si es reciclable y qué tan urgente es "
                 "().",
    },
    {
        "visual_html": "",
        "titulo": "3. Confirma los reportes de tus vecinos",
        "texto": "Si pasas por un punto ya reportado y el residuo sigue ahí, "
                 "confírmalo desde 'Mi Historial' — ayuda a la administración "
                 "a priorizar dónde actuar primero.",
    },
]


def mostrar_tutorial():
    paso = st.session_state.get("tutorial_paso", 0)
    paso = max(0, min(paso, len(PASOS_TUTORIAL) - 1))
    info = PASOS_TUTORIAL[paso]

    st.markdown(
        f'<div style="background:linear-gradient(135deg,rgba(74,222,128,0.15),rgba(22,163,74,0.08));'
        f'border:2px solid #4ade80;border-radius:16px;padding:28px 24px;'
        f'text-align:center;margin-bottom:10px;">'
        f'<div style="margin-bottom:10px;">{info["visual_html"]}</div>'
        f'<div style="font-size:19px;font-weight:800;color:#166534;margin-bottom:8px;">'
        f'{info["titulo"]}</div>'
        f'<div style="font-size:14px;color:#374151;max-width:480px;margin:0 auto;'
        f'line-height:1.5;">{info["texto"]}</div>'
        f'</div>', unsafe_allow_html=True)

    puntos = "".join(
        "●" if i == paso else "○" for i in range(len(PASOS_TUTORIAL))
    )
    st.markdown(
        f'<div style="text-align:center;color:#4ade80;font-size:16px;'
        f'letter-spacing:6px;margin-bottom:10px;">{puntos}</div>',
        unsafe_allow_html=True)

    tb1, tb2, tb3 = st.columns([1, 1, 1])
    with tb1:
        if paso > 0:
            if st.button("Anterior", use_container_width=True, key="tut_prev"):
                st.session_state.tutorial_paso = paso - 1
                st.rerun()
    with tb2:
        if st.button("Saltar tutorial", use_container_width=True, key="tut_skip"):
            st.session_state.tutorial_visto = True
            st.session_state.guardar_cookie_tutorial = True
            st.rerun()
    with tb3:
        if paso < len(PASOS_TUTORIAL) - 1:
            if st.button("Siguiente", type="primary",
                         use_container_width=True, key="tut_next"):
                st.session_state.tutorial_paso = paso + 1
                st.rerun()
        else:
            if st.button("¡Entendido, empezar!", type="primary",
                         use_container_width=True, key="tut_finish"):
                st.session_state.tutorial_visto = True
                st.session_state.guardar_cookie_tutorial = True
                st.rerun()
    st.markdown("---")


def _escribir_cookie(nombre: str, valor: str, segundos: int):
    """Escribe (o borra, con segundos=0) una cookie en el navegador. Si el
    navegador la bloquea, la preferencia solo dura la sesión actual."""
    import streamlit.components.v1 as components
    components.html(
        f"<script>var c='{nombre}={valor}; max-age={int(segundos)}; path=/; SameSite=Lax';"
        "try{document.cookie=c;}catch(e){}"
        "try{window.parent.document.cookie=c;}catch(e){}</script>", height=0)


def _guardar_cookie_tutorial():
    """Recuerda en el navegador (1 año) que la persona ya vio el tutorial."""
    _escribir_cookie("ecocom2_tutorial", "1", 31536000)


def datos_ubicacion_aceptados() -> bool:
    """True si la persona aceptó el tratamiento de sus datos de ubicación
    (Ley 1581 de 2012). Se recuerda en una cookie de 1 año para no preguntar
    en cada visita; puede revocarse en cualquier momento."""
    if st.session_state.get("acepta_datos_ubicacion") is None:
        try:
            st.session_state.acepta_datos_ubicacion = (
                st.context.cookies.get("ecocom2_habeas") == "1")
        except Exception:
            st.session_state.acepta_datos_ubicacion = False
    return bool(st.session_state.acepta_datos_ubicacion)


_CLAVES_UBICACION = ["validado", "lat", "lon", "fuera", "direccion", "barrio_usuario",
                     "click_lat", "click_lon", "click_dir", "click_barrio",
                     "punto_lat", "punto_lon", "cache",
                     "gps_lat", "gps_lon", "gps_procesado", "gps_solicitado",
                     "dir_candidatos"]


def revocar_datos_ubicacion():
    """Retira la autorización: borra la ubicación de esta sesión y la cookie."""
    st.session_state.acepta_datos_ubicacion = False
    st.session_state._habeas_cookie_borrar = True
    st.session_state.pop("chk_habeas", None)
    st.session_state.pop("modo_demo", None)
    st.session_state.barrio_recordado = ""          # también olvida el barrio recordado
    st.session_state._barrio_cookie_borrar = True
    for k in _CLAVES_UBICACION:
        st.session_state.pop(k, None)


# --- Modo demostración: residencia simulada para que evaluadores prueben sin GPS ---
DEMO_LAT, DEMO_LON = 6.2985, -75.5570
DEMO_DIRECCION = "Calle 102 # 49-22, Santa Cruz, Medellín"


# Pon esto en False cuando terminen las pruebas de los evaluadores: el botón
# desaparece para todos (o, sin tocar el código, MODO_DEMO = "false" en Secrets).
MOSTRAR_DEMO_SIEMPRE = True


def demo_habilitado() -> bool:
    """Si el botón de demostración se muestra en la barra lateral. Con
    MOSTRAR_DEMO_SIEMPRE = True lo ve todo el mundo; con False solo aparece
    con ?demo=1, con sesión de administrador o con MODO_DEMO = "true"."""
    try:
        valor = str(st.secrets.get("MODO_DEMO", "")).strip().lower()
    except Exception:
        valor = ""
    if valor in ("0", "false", "no"):      # apagado explícito desde Secrets
        return False
    if MOSTRAR_DEMO_SIEMPRE or valor in ("1", "true", "si", "sí"):
        return True
    try:
        if str(st.query_params.get("demo", "")) == "1":
            return True
    except Exception:
        pass
    return admin_sesion_vigente()


def activar_modo_demo():
    """Deja la sesión como residente verificado en Santa Cruz. No escribe la
    cookie de autorización: la aceptación de datos vale solo en esta sesión."""
    set_ubicacion(DEMO_LAT, DEMO_LON, DEMO_DIRECCION)
    st.session_state.click_lat = DEMO_LAT
    st.session_state.click_lon = DEMO_LON
    st.session_state.click_dir = DEMO_DIRECCION
    st.session_state.click_barrio = "Santa Cruz"
    st.session_state.gps_solicitado = False
    st.session_state.acepta_datos_ubicacion = True
    st.session_state.modo_demo = True


def vaciar_cookies_habeas():
    """Escribe/borra la cookie de autorización cuando hay un cambio pendiente."""
    if st.session_state.pop("_habeas_cookie_escribir", False):
        _escribir_cookie("ecocom2_habeas", "1", 31536000)
    if st.session_state.pop("_habeas_cookie_borrar", False):
        _escribir_cookie("ecocom2_habeas", "", 0)
    _slug = st.session_state.pop("_barrio_cookie_escribir", None)
    if _slug:
        _escribir_cookie("ecocom2_barrio", _slug, 31536000)
    if st.session_state.pop("_barrio_cookie_borrar", False):
        _escribir_cookie("ecocom2_barrio", "", 0)


def mostrar_horarios_recoleccion(con_cierre: bool = True):
    """Panel con los horarios oficiales de recolección de los 11 barrios de
    la Comuna 2, con un botón para cerrarlo — mismo patrón que el tutorial."""
    st.markdown(
        '<div style="background:linear-gradient(135deg,rgba(74,222,128,0.15),rgba(22,163,74,0.08));'
        'border:2px solid #4ade80;border-radius:16px;padding:20px 24px;margin-bottom:10px;">'
        '<div style="font-size:18px;font-weight:800;color:#166534;margin-bottom:10px;">'
        'Horarios de recolección — Comuna 2 Santa Cruz</div>',
        unsafe_allow_html=True)

    for barrio in BARRIOS:
        info = HORARIOS_RECOLECCION.get(barrio)
        if not info:
            continue
        nota_html = (f'<br><span style="font-size:11px;color:#a16207;">{info["nota"]}</span>'
                     if info["nota"] else "")
        st.markdown(
            f'<div style="background:#ffffff;border:1px solid #bbf7d0;border-radius:10px;'
            f'padding:10px 14px;margin-bottom:6px;">'
            f'<b style="color:#166534;">{barrio}</b><br>'
            f'<span style="font-size:13px;color:#374151;">{info["dias"]} · {info["horario"]}</span>'
            f'{nota_html}</div>',
            unsafe_allow_html=True)

    st.markdown(
        '<p style="font-size:11px;color:#6b7280;margin-top:8px;">'
        'Fuente: Emvarias, Horarios y Frecuencias de Recolección 2024 (Zona 1) '
        '+ actualización de junio de 2026. Verifica el mapa interactivo de Emvarias '
        'si tu calle no aparece angostada aquí, ya que la franja horaria se sigue '
        'ajustando barrio por barrio.</p></div>',
        unsafe_allow_html=True)

    if con_cierre:
        if st.button("Cerrar horarios", key="cerrar_horarios", use_container_width=True):
            st.session_state.mostrar_horarios = False
            st.rerun()
        st.markdown("---")


def nav_tabs(seccion_actual, puede_reportar=True):
    if not puede_reportar:
        # Sin ubicación todavía: no se muestran los botones de reportar, solo
        # los pasos para llegar a ellos y el historial.
        st.info("Para reportar, primero indica dónde está el residuo: "
                "1) usa el GPS o escribe tu dirección y 2) toca el punto exacto en el "
                "mapa. Cuando lo hagas aparecerán aquí los botones para reportar.")
        col_h, _col_vacia = st.columns([1, 2])
        with col_h:
            if st.button("Mi Historial", key="nav_historial", use_container_width=True,
                         type="primary" if seccion_actual == "historial" else "secondary"):
                st.session_state.seccion = "historial"
                st.rerun()
        return
    SECCIONES = [
        ("residuo",   "Reportar Residuo"),
        ("critico",   "Punto Crítico"),
        ("historial", "Mi Historial"),
    ]
    cols = st.columns(len(SECCIONES))
    for col, (key, label) in zip(cols, SECCIONES):
        with col:
            es_activa = seccion_actual == key
            btn_type = "primary" if es_activa else "secondary"
            if st.button(label, key=f"nav_{key}",
                         use_container_width=True, type=btn_type):
                st.session_state.seccion = key
                st.rerun()

# ====================================================================
# ECOBOT VISIBLE — botón flotante con el logo, y acciones automáticas
# (crear/prellenar reportes hablando, analizar fotos, confirmar por
# código y avisar horarios de recolección)
# ====================================================================
LOGO_PATH = Path(__file__).resolve().parent / "logo.png"


@st.cache_data(show_spinner=False)
def _logo_b64() -> str:
    try:
        return base64.b64encode(LOGO_PATH.read_bytes()).decode("utf-8")
    except Exception:
        return ""


def avatar_ecobot():
    """Avatar del bot: el logo de EcoCom2 si existe logo.png, si no."""
    return str(LOGO_PATH) if LOGO_PATH.exists() else ":material/recycling:"


def inyectar_css_ecobot():
    """Convierte el panel del bot en un botón FLOTANTE (abajo a la derecha,
    siempre visible, con el logo y una animación suave) en vez de un
    desplegable escondido en la barra lateral."""
    logo = _logo_b64()
    fondo = f"url(data:image/png;base64,{logo})" if logo else "none"
    st.markdown(f"""<style>
.st-key-ecobot_flotante {{
    position: fixed; bottom: 80px; right: 28px; z-index: 999990; width: auto !important;
    max-width: calc(100vw - 40px);
}}
.st-key-ecobot_flotante button {{
    background: #16a34a !important; border: 3px solid #ffffff !important;
    border-radius: 999px !important; padding: 6px 18px 6px 8px !important;
    box-shadow: 0 6px 18px rgba(22,163,74,.55) !important;
    animation: ecobotPulso 2.4s infinite;
}}
.st-key-ecobot_flotante button::before {{
    content: ""; display: inline-block; width: 40px; height: 40px; margin-right: 8px;
    border-radius: 50%; vertical-align: middle;
    background: #ffffff {fondo} center/cover no-repeat;
}}
.st-key-ecobot_flotante button p {{ color: #ffffff !important; font-weight: 800 !important; }}
@keyframes ecobotPulso {{
    0%   {{ box-shadow: 0 0 0 0 rgba(22,163,74,.55); }}
    70%  {{ box-shadow: 0 0 0 14px rgba(22,163,74,0); }}
    100% {{ box-shadow: 0 0 0 0 rgba(22,163,74,0); }}
}}
div[data-testid="stPopoverBody"] {{
    width: min(430px, 92vw) !important; max-height: 78vh; overflow-y: auto;
    background: #f0fdf4 !important; border: 2px solid #4ade80 !important;
}}
div[data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"] p,
div[data-testid="stPopoverBody"] label {{ color: #14532d !important; }}
div[data-testid="stPopoverBody"] button[kind="primary"] p {{ color: #ffffff !important; }}
</style>""", unsafe_allow_html=True)


@contextmanager
def _ecobot_panel():
    inyectar_css_ecobot()
    with st.container(key="ecobot_flotante"):
        with st.popover("EcoBot"):
            yield


# ---------- Horarios de recolección (calcula si HOY pasa el camión) ----------
_DIAS_ES = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
            "viernes": 4, "sabado": 5, "domingo": 6}


def _hoy_colombia():
    """Fecha/hora en Colombia (UTC-5) aunque el servidor esté en otra zona."""
    from datetime import timedelta as _td
    return datetime.utcnow() - _td(hours=5)


def camion_pasa_hoy(barrio: str) -> bool:
    info = HORARIOS_RECOLECCION.get(barrio)
    if not info:
        return False
    dias_n = _normalizar_txt(info["dias"])
    nums = [n for d, n in _DIAS_ES.items() if d in dias_n]
    return _hoy_colombia().weekday() in nums


_NOMBRES_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def dias_para_proximo_paso(barrio: str):
    """Cuántos días faltan para el próximo recorrido (0 = hoy). None si no hay datos."""
    info = HORARIOS_RECOLECCION.get(barrio)
    if not info:
        return None
    dias_n = _normalizar_txt(info["dias"])
    nums = [n for d, n in _DIAS_ES.items() if d in dias_n]
    if not nums:
        return None
    hoy = _hoy_colombia().weekday()
    return next((d for d in range(8) if (hoy + d) % 7 in nums), None)


def mensaje_horario(barrio: str) -> str:
    """Horario del camión en el barrio, diciendo si pasa hoy o cuándo es el próximo."""
    info = HORARIOS_RECOLECCION.get(barrio)
    if not info:
        return ""

    def _frase(txt):   # termina en punto sin duplicarlo ("p.m." ya lo trae)
        return txt if txt.endswith(".") else txt + "."

    delta = dias_para_proximo_paso(barrio)
    if delta == 0:
        msg = f"Hoy pasa el camión por **{barrio}**, de {info['horario']}"
    else:
        msg = (f"En **{barrio}** el camión pasa **{info['dias'].lower()}**, "
               f"de {info['horario']}")
        if delta is not None:
            dia = (_hoy_colombia().weekday() + delta) % 7
            cuando = "mañana" if delta == 1 else f"el {_NOMBRES_DIAS[dia]}"
            msg = _frase(msg) + f" El próximo recorrido es {cuando}"
    if info.get("nota"):
        msg = _frase(msg) + f" Nota: {info['nota']}"
    return _frase(msg)


def barrio_desde_direccion(direccion: str):
    """Barrio a partir del texto de una dirección. Ignora 'Comuna 2 - Santa Cruz',
    que es el nombre de la comuna y no el barrio, para no dar un horario equivocado."""
    t = re.sub(r"comuna\s*2\s*[-–,]?\s*santa\s*cruz", " ", direccion or "", flags=re.IGNORECASE)
    t = re.sub(r"comuna\s*2", " ", t, flags=re.IGNORECASE)
    return detectar_barrio_en_texto(t)


def _slug_barrio(b: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _normalizar_txt(b)).strip("_")


def barrio_recordado():
    """Barrio que la persona pidió recordar (cookie de su navegador, 1 año)."""
    b = st.session_state.get("barrio_recordado")
    if b is None:                      # primera vez en esta sesión: leer la cookie
        b = ""
        try:
            slug = st.context.cookies.get("ecocom2_barrio", "")
            b = next((x for x in HORARIOS_RECOLECCION if _slug_barrio(x) == slug), "")
        except Exception:
            pass
        st.session_state.barrio_recordado = b
    return b or None


def recordar_barrio(barrio: str):
    """Guarda el barrio solo si la persona lo pide (por chat o eligiéndolo)."""
    if barrio not in HORARIOS_RECOLECCION:
        return
    st.session_state.barrio_recordado = barrio
    st.session_state.barrio_usuario = barrio
    st.session_state._barrio_cookie_escribir = _slug_barrio(barrio)


def barrio_para_horario(preferir_propio: bool = False):
    """Barrio sobre el que hay que mostrar el horario. En pantalla: el punto
    tocado en el mapa, o el barrio detectado/recordado. Con preferir_propio
    (lo usa EcoBot): primero el barrio de la persona y después el punto del mapa."""
    click = st.session_state.get("click_barrio")
    propio = (st.session_state.get("barrio_usuario"), barrio_recordado())
    orden = (propio + (click,)) if preferir_propio else ((click,) + propio)
    for b in orden + (st.session_state.get("prefill_barrio"),):
        if b in HORARIOS_RECOLECCION:
            return b
    return None


# ---------- Entender lenguaje natural ----------
_ALIAS_BARRIOS = {
    "moscu": "Moscú No. 1", "moscu 1": "Moscú No. 1", "moscu n1": "Moscú No. 1",
    "moscu numero 1": "Moscú No. 1", "playon": "Playón de los Comuneros",
    "el playon": "Playón de los Comuneros", "comuneros": "Playón de los Comuneros",
    "socorro": "Villa del Socorro", "villa socorro": "Villa del Socorro",
    "niza": "Villa Niza", "pablo 6": "Pablo VI", "pablo sexto": "Pablo VI",
    "frontera": "La Frontera", "francia": "La Francia", "isla": "La Isla",
}

_RESIDUOS_BOT = [
    (["escombro", "rcd", "cascajo", "demolicion", "obra", "cemento", "ladrillo", "arena",
      "bloque", "teja", "concreto", "mamposteria", "material de construccion"],
     "Escombros / residuos de construcción", True),
    (["colchon", "sofa", "sillon", "mueble", "nevera", "lavadora", "electrodomestico",
      "voluminoso", "estufa", "televisor", "tv", "computador", "closet", "armario",
      "inodoro", "puerta", "ventana"],
     "Voluminosos (colchones, muebles, electrodomésticos)", True),
    (["llanta", "neumatico"], "Llantas", True),
    (["bolsa", "basura", "costal", "saco", "basurero", "mugre", "porqueria", "cochinada",
      "desecho", "desperdicio", "bulto", "regada", "regado"],
     "Bolsas de basura", False),
    (["organico", "comida", "poda", "vegetacion", "ramas", "hojas", "pasto", "guadua",
      "tronco", "arbol", "fruta", "verdura", "cascara", "sobras"],
     "Residuos orgánicos / poda", False),
    (["botella", "carton", "plastico", "vidrio", "lata", "papel", "periodico", "reciclable",
      "tarro", "caja"],
     "Materiales reciclables", False),
]
_PALABRAS_URGENTE = ["urgente", "critico", "bloquea", "bloqueado", "bloqueando", "olor",
                     "huele feo", "maluco", "plaga", "rata", "mosca", "montana", "montaña",
                     "grande", "mucho", "mucha", "desbordad", "peligro", "semanas",
                     "hace dias", "tapando"]

# Verbos y frases con los que la gente cuenta que hay residuos
_REGEX_REPORTE = (
    r"\b(hay|tengo|vi|veo|encontre|encuentro|reportar|reporto|reportarlo|denunciar|acumulado|"
    r"acumulada|acumulan|acumulacion|dejaron|botaron|tiraron|tiran|arrojaron|regaron|regada|"
    r"regado|amontonado|amontonada|desbordado|desbordada|rebosando|lleno|llena|tirada|"
    r"tirado|abandonado|abandonada|sacaron|dejan|botan|queman|huele feo|mal olor|maluco)\b")
_REGEX_NEGACION_REPORTE = (
    r"\b(no hay|ya no hay|sin basura|nada de basura|ya recogieron|ya la recogieron|"
    r"ya se llevaron|ya limpiaron)\b")

# Abreviaturas y escritura "de chat" -> palabra completa
_ABREVIATURAS_BOT = {
    "q": "que", "k": "que", "ke": "que", "xq": "porque", "pq": "porque", "porq": "porque",
    "tmb": "tambien", "tbn": "tambien", "xfa": "por favor", "pfa": "por favor",
    "plis": "por favor", "d": "de", "x": "por", "bn": "bien", "dnd": "donde",
    "cdo": "cuando", "cra": "carrera", "kra": "carrera", "cll": "calle", "grax": "gracias",
    "gracia": "gracias", "ola": "hola", "buenas": "buenas",
}
# Frases de la calle -> palabra que el bot sí entiende
_FRASES_BOT = [
    ("carro de la basura", "camion"), ("carro de basura", "camion"),
    ("camion de la basura", "camion"), ("camion de basura", "camion"),
    ("carro recolector", "camion"), ("el recolector", "camion"), ("la volqueta", "camion"),
    ("el compactador", "camion"), ("sacar la basura", "sacar basura"),
    ("se rego", "regada"), ("se desbordo", "desbordada"),
]
_VOCAB_BASE_BOT = [
    "basura", "basuras", "camion", "horario", "horarios", "reporte", "reportes", "reportar",
    "recoleccion", "recogieron", "recogen", "recoge", "resuelto", "resolvieron", "limpiaron",
    "atendieron", "escombros", "colchon", "llantas", "denunciar", "acumulada", "acumulado",
    "dejaron", "botaron", "tiraron", "gracias", "hola", "buenas", "barrio", "carrera", "calle",
    "pasa", "pasan", "paso", "todavia", "sigue", "confirmo", "confirmar", "urgente",
    "critico", "plaga", "ratas", "olor", "cuando", "reciclar", "reciclaje", "bolsas",
    "organico", "orgánico", "vidrio", "plastico", "carton", "papel", "residuos", "regada",
    "desbordada", "comuna", "direccion", "ubicacion", "foto", "mapa", "estado", "seguimiento",
]


def _vocab_bot() -> set:
    voc = set(_VOCAB_BASE_BOT)
    for palabras, _e, _c in _RESIDUOS_BOT:
        voc.update(_normalizar_txt(p) for p in palabras)
    for alias in _ALIAS_BARRIOS:
        voc.update(alias.split())
    for bb in BARRIOS:
        voc.update(w for w in _normalizar_txt(bb).split() if len(w) >= 5)
    return {v for v in voc if len(v) >= 4}


def _preparar_texto_bot(texto: str) -> str:
    """Deja el mensaje en una forma fácil de entender: sin tildes ni signos,
    sin letras repetidas ('holaaaa'), con abreviaturas completas ('xq' ->
    'porque'), frases de la calle traducidas ('el carro de la basura' ->
    'camion') y errores de tipeo corregidos ('escomros' -> 'escombros')."""
    n = _normalizar_txt(texto)
    n = re.sub(r"[^\w\s-]", " ", n)
    n = re.sub(r"([a-z])\1{2,}", r"\1", n)          # holaaaa -> hola
    for frase, canon in _FRASES_BOT:
        n = n.replace(_normalizar_txt(frase), canon)
    voc = _vocab_bot()
    salida = []
    for tok in n.split():
        tok = _ABREVIATURAS_BOT.get(tok, tok)
        if (len(tok) >= 5 and tok not in voc and not any(c.isdigit() for c in tok)
                and tok.isalpha()):
            cerca = [v for v in difflib.get_close_matches(tok, voc, n=1, cutoff=0.85)
                     if v[0] == tok[0]]
            if cerca:
                tok = cerca[0]
        salida.append(tok)
    return re.sub(r"\s+", " ", " ".join(salida)).strip()


def detectar_barrio_en_texto(texto: str, difuso: bool = False):
    """Barrio mencionado en un texto. Con difuso=True también acepta errores de
    escritura ('andalusia', 'la frontea', 'santacruz'); se usa solo en el chat,
    no con direcciones, para no confundir números ni calles con un barrio."""
    n = _normalizar_txt(texto)
    for b in BARRIOS:
        if _normalizar_txt(b) in n:
            return b
    for alias, b in _ALIAS_BARRIOS.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", n):
            return b
    if not difuso:
        return None
    n2 = re.sub(r"([a-z])\1{2,}", r"\1", re.sub(r"[^\w\s]", " ", n))
    toks = n2.split()
    nombres = {_normalizar_txt(b): b for b in BARRIOS}
    nombres.update({a: b for a, b in _ALIAS_BARRIOS.items()})
    mejor, mejor_r = None, 0.0
    for k in (3, 2, 1):
        for i in range(len(toks) - k + 1):
            ventana = " ".join(toks[i:i + k])
            for nombre, b in nombres.items():
                for v, nm in ((ventana, nombre), (ventana.replace(" ", ""), nombre.replace(" ", ""))):
                    if len(v) < 6 or v[0] != nm[0]:
                        continue
                    r = difflib.SequenceMatcher(None, v, nm).ratio()
                    if r >= 0.88 and r > mejor_r:
                        mejor, mejor_r = b, r
    return mejor


def _detectar_tipo_residuo(n: str):
    for palabras, etiqueta, critico in _RESIDUOS_BOT:
        if any(re.search(r"\b" + re.escape(p), n) for p in palabras):
            return etiqueta, critico
    return None, False


def limpiar_prefill_bot():
    for k in ("prefill_obs", "prefill_barrio"):
        st.session_state.pop(k, None)


def reiniciar_flujo_reporte():
    """Deja la página como queda después de publicar un reporte con el
    formulario: sin punto elegido en el mapa, sin foto analizada y sin texto
    prellenado, y lleva a Mi Historial. Antes, al publicar desde EcoBot el
    reporte sí llegaba al mapa, pero el formulario de abajo se quedaba
    'colgado' en el paso Foto con la dirección anterior. Ahora, para el
    siguiente reporte hay que elegir de nuevo el punto a reportar."""
    limpiar_prefill_bot()
    for k in list(st.session_state.keys()):
        if str(k).startswith("cache"):
            st.session_state[k] = None
    for k in ("click_lat", "click_lon", "click_dir", "click_barrio", "punto_para_reporte"):
        st.session_state.pop(k, None)
    st.session_state.seccion = "historial"


def _estado_reporte_texto(rep: dict) -> str:
    txt = (f"**{rep.get('Código')}** · {rep.get('Sector','')}\n"
           f"- Estado: {rep.get('Estado','')}\n"
           f"- Clasificación: {rep.get('Clasificación','')}\n"
           f"- Fecha: {rep.get('Fecha','')}\n"
           f"- Confirmaciones: {rep.get('Confirmaciones', 0) or 0}")
    if "Resuelto" in rep.get("Estado", "") and rep.get("FechaResuelto"):
        txt += f"\n- Resuelto el {rep['FechaResuelto']}"
    return txt


def mis_reportes_bot() -> list:
    """Reportes de esta persona: los de la sesión y los que recupera con su
    código o teléfono. El más reciente primero."""
    mis = set(st.session_state.get("mis_codigos", []))
    cod_res = st.session_state.get("mi_codigo_residente", "")
    out = [r for r in st.session_state.reportes
           if r.get("Código") in mis
           or (cod_res and coincide_residente(r.get("CodigoResidente"), cod_res))]
    out.sort(key=lambda r: str(r.get("Fecha", "")), reverse=True)
    return out


def _horas_desde(fecha_txt):
    try:
        d = datetime.strptime(str(fecha_txt)[:16], "%Y-%m-%d %H:%M")
        return (datetime.now() - d).total_seconds() / 3600
    except Exception:
        return None


def _hace_texto(horas: float) -> str:
    if horas < 1:
        return "hace menos de 1 hora"
    if horas < 24:
        return f"hace {int(horas)} h"
    d = int(horas // 24)
    return "hace 1 día" if d == 1 else f"hace {d} días"


def _con_punto(txt: str) -> str:
    """Termina en punto sin duplicarlo ('p.m.' ya lo trae)."""
    return txt if txt.endswith(".") else txt + "."


def _fmt_hora(h: float) -> str:
    hh, mm = int(h), int(round((h - int(h)) * 60))
    return f"{hh % 12 or 12}:{mm:02d} {'p.m.' if hh >= 12 else 'a.m.'}"


def _franja_horas(barrio: str):
    """(hora_inicio, hora_fin) del recorrido, en horas decimales de 24 h."""
    info = HORARIOS_RECOLECCION.get(barrio)
    if not info:
        return None
    horas = []
    for h, m, ap in re.findall(r"(\d{1,2}):(\d{2})\s*([ap])\.?\s*m", info["horario"].lower()):
        horas.append(int(h) % 12 + (12 if ap == "p" else 0) + int(m) / 60)
    return (horas[0], horas[1]) if len(horas) >= 2 else None


def confirmar_reporte_bot(cod: str):
    """Suma una confirmación ('sigue ahí') a un reporte. Devuelve (ok, mensaje)."""
    rep = next((r for r in st.session_state.reportes
                if str(r.get("Código", "")).upper() == cod), None)
    if not rep:
        return False, (f"No encontré ningún reporte con el código **{cod}**. "
                       f"Revisa que esté bien escrito (ejemplo: REP-205).")
    if "Resuelto" in rep.get("Estado", ""):
        return False, f"El reporte **{cod}** ya figura como resuelto, no necesita confirmación."
    conf = st.session_state.setdefault("confirmados_sesion", set())
    if cod in conf:
        return False, f"Ya habías confirmado **{cod}** en esta sesión. ¡Gracias!"
    rep["Confirmaciones"] = (rep.get("Confirmaciones", 0) or 0) + 1
    conf.add(cod)
    guardar_reportes_disco(st.session_state.reportes)
    st.session_state.bot_accion_global = True   # el mapa debe refrescarse
    return True, (f"¡Confirmación registrada para **{cod}** ({rep.get('Sector','')})! "
                  f"Ahora tiene {rep['Confirmaciones']} confirmaciones y la administración "
                  f"lo prioriza más.")


def _resumen_mis_reportes() -> str:
    mis = mis_reportes_bot()
    if not mis:
        return ("Todavía no veo reportes tuyos en esta sesión. Si ya habías reportado antes, "
                "escribe tu código o teléfono en el formulario o en Mi Historial y los recupero.")
    lineas = []
    for r in mis[:5]:
        est = r.get("Estado", "")
        h = _horas_desde(r.get("Fecha"))
        cuando = f" ({_hace_texto(h)})" if h is not None else ""
        if "Resuelto" in est:
            nota = "ya lo resolvieron"
        elif "proceso" in est.lower():
            nota = "ya lo están atendiendo"
        else:
            nota = "sigue pendiente"
        lineas.append(f"- **{r.get('Código')}** · {r.get('Sector','')}{cuando}: {nota}")
    extra = f"\n(Te muestro los 5 más recientes de {len(mis)}.)" if len(mis) > 5 else ""
    return ("Así van tus reportes:\n" + "\n".join(lineas) + extra +
            "\n\nEn **Tus reportes**, arriba en este chat, puedes confirmar con un toque que "
            "sigue ahí o compartir los que ya se resolvieron.")


def _preparar_reporte_bot(texto, barrio, etiqueta, critico, intro="¡Entendido! Ya preparé tu reporte:"):
    """Deja listo el formulario con lo que la persona contó y devuelve el
    mensaje con los pasos que faltan."""
    for k in ("r_obs", "cr_obs", "r_barrio", "cr_barrio"):
        st.session_state.pop(k, None)      # para que el formulario tome el prellenado
    st.session_state.prefill_obs = limpiar_texto_libre(texto, 300)
    if barrio:
        st.session_state.prefill_barrio = barrio
        st.session_state.click_barrio = barrio
    st.session_state.seccion = "critico" if critico else "residuo"
    st.session_state.ir_a_inicio = True
    st.session_state.bot_accion_global = True   # hay que cambiar de página

    partes = [intro]
    partes.append(f"- Barrio: **{barrio}**" if barrio else "- Barrio: elígelo en el formulario")
    partes.append(f"- Tipo: **{etiqueta or 'Residuos'}**")
    partes.append("- Lo marqué como **punto crítico**" if critico else "- Lo dejé como reporte de residuo")
    if not es_residente():
        partes.append("\n Falta verificar tu dirección: acepta el uso de tus datos de ubicación y usa el botón **Usar mi ubicación (GPS)**.")
    elif st.session_state.get("click_lat") is None:
        partes.append("\n Ahora toca el **punto exacto** del residuo en el mapa.")
    else:
        partes.append("\n Solo sube la foto en el formulario (o mándamela aquí abajo).")
    if barrio and etiqueta == "Bolsas de basura" and not critico and camion_pasa_hoy(barrio):
        info_h = HORARIOS_RECOLECCION[barrio]
        partes.append(
            f"\n**Ojo:** hoy pasa el camión en {barrio} ({info_h['horario']}). "
            f"Si son bolsas domiciliarias, sácalas poco antes de esa hora y quizá "
            f"ni necesites reportar. Si llevan días ahí, sigue con el reporte.")
    return "\n".join(partes)


def _es_pregunta_horario(n: str) -> bool:
    if re.search(r"\bhorarios?\b", n):
        return True
    if (re.search(r"\b(cuando|que dia|que dias|a que hora|cada cuanto|hasta que hora|desde que hora)\b", n)
            and re.search(r"\b(camion|basura|recole\w*|recog\w*|pasa|pasan|sacar|saco)\b", n)):
        return True
    return bool(re.search(r"\b(pasa|pasan|viene|vienen|llega|llegan)\b.{0,12}\bcamion\b", n)
                or re.search(r"\b(hay camion|hoy pasa|pasa hoy|manana pasa|pasa manana)\b", n))


def _estado_camion_hoy(barrio: str, reclamo: bool = False):
    """Dice, según la hora de ahora, en qué punto del recorrido de hoy va el
    camión en el barrio. Devuelve (texto, franja_terminada)."""
    info = HORARIOS_RECOLECCION[barrio]
    if dias_para_proximo_paso(barrio) != 0:
        return f"Hoy no le toca a **{barrio}**. " + mensaje_horario(barrio), False
    franja = _franja_horas(barrio)
    if not franja:
        return mensaje_horario(barrio), False
    ahora = _hoy_colombia()
    h_ahora = ahora.hour + ahora.minute / 60
    if h_ahora < franja[0]:
        return (f"Todavía no es la hora: hoy el camión pasa por **{barrio}** de "
                f"{_con_punto(info['horario'])} Saca tus bolsas poco antes."), False
    if h_ahora < franja[1]:
        txt = (f"Hoy sí le toca a **{barrio}** y está dentro de su franja "
               f"({info['horario']}). Puede pasar hasta las {_con_punto(_fmt_hora(franja[1]))}")
        if reclamo:
            txt += " Si no pasa, avísame y lo reportamos."
        return txt, False
    return f"La franja de hoy en **{barrio}** ya terminó ({info['horario']}).", True


def router_ecobot(texto: str):
    """Entiende lo que la persona pide en lenguaje natural y ACTÚA (sin
    gastar una llamada a Gemini). Tolera errores de escritura, abreviaturas y
    frases de la calle ('el carro de la basura', 'xq no pasó'). Devuelve la
    respuesta, o None si no es algo que sepa resolver localmente (entonces se
    usa FAQ / Gemini)."""
    n = _preparar_texto_bot(texto)
    cuenta_algo = bool(re.search(_REGEX_REPORTE, n))

    # 0) Saludos y agradecimientos: se contestan sin gastar IA
    if len(n.split()) <= 5 and not cuenta_algo:
        if re.match(r"^(hola|buenas|buen dia|buenos dias|buenas tardes|buenas noches|hey|saludos|"
                    r"epa|quiubo|que mas|holi)\b", n):
            return ("¡Hola! Cuéntame qué necesitas: puedo preparar un reporte, decirte cómo van "
                    "tus reportes o cuándo pasa el camión.")
        if re.match(r"^((muchas |mil )?gracias|chao|adios|hasta luego|listo gracias|ok gracias|"
                    r"vale gracias|perfecto gracias)\b", n):
            return "¡Con gusto! Aquí estoy cuando me necesites."

    # 1) Código de reporte: consultar estado o confirmar
    m = re.search(r"\b(rep|crit)[-_ ]?(\d{2,5})\b", n)
    if m:
        cod = f"{m.group(1).upper()}-{m.group(2)}"
        rep = next((r for r in st.session_state.reportes
                    if str(r.get("Código", "")).upper() == cod), None)
        if not rep:
            return (f"No encontré ningún reporte con el código **{cod}**. "
                    f"Revisa que esté bien escrito (ejemplo: REP-205).")
        if any(p in n for p in ["confirmo", "confirmar", "sigue ahi", "todavia esta", "sigue alli"]):
            return confirmar_reporte_bot(cod)[1]
        return _estado_reporte_texto(rep)

    # 2) "El camión no pasó" / "¿ya pasó el camión?": mira si de verdad ya le tocaba
    no_paso = bool(re.search(r"\b(no|nunca|todavia no|aun no|ni)\b.{0,40}\b(paso|pasa|pasado|pasaron|vino|"
                             r"viene|recogio|recogieron|recoge|recogen|llego|llegado)\b", n)
                   and any(w in n for w in ("camion", "basura", "recole")))
    ya_paso = bool(re.search(r"\bya (paso|vino|llego|pasaron)\b", n) and "camion" in n)
    if no_paso or ya_paso:
        barrio = detectar_barrio_en_texto(texto, difuso=True) or barrio_para_horario(True)
        if not barrio:
            return ("Cuéntame en qué barrio estás (por ejemplo: *vivo en La Rosa*) y te digo "
                    "si ya le tocaba pasar al camión.")
        if re.search(r"\b(vivo en|vivo por|soy de|resido en|vivimos en)\b", n):
            recordar_barrio(barrio)                  # lo dijo de paso: también lo recuerda
            st.session_state.bot_accion_global = True
        txt, terminada = _estado_camion_hoy(barrio, reclamo=no_paso)
        if no_paso and terminada:
            return _preparar_reporte_bot(
                "El camión no pasó en la franja de hoy", barrio, "Bolsas de basura", False,
                intro=f"La franja de hoy en {barrio} ya terminó y dices que no recogieron. "
                      f"Ya preparé un reporte:")
        return txt

    # 3) "Vivo en X": recuerda el barrio (solo si lo pide) y avisa del camión
    if re.search(r"\b(vivo en|vivo por|soy de|mi barrio es|resido en|vivimos en)\b", n) and not cuenta_algo:
        b = detectar_barrio_en_texto(texto, difuso=True)
        if b:
            recordar_barrio(b)
            st.session_state.bot_accion_global = True    # para guardar la cookie
            return (f"Listo, recordaré que vives en **{b}**. {mensaje_horario(b)} "
                    f"Te aviso aquí cuando el camión pase hoy o mañana.")

    # 4) "¿Cómo van mis reportes?" / "¿ya recogieron?"
    if (re.search(r"\b(mis reportes|mi reporte|mis reclamos|mis denuncias|seguimiento|estado de mis|"
                  r"como van mis|como va mi|como esta mi|como estan mis|"
                  r"que (paso|ha pasado) con (mi|mis)|reportes que (hice|he hecho|envie|mande|puse))\b", n)
            or re.search(r"\bya (lo |la |los |las )?(recogieron|resolvieron|limpiaron|atendieron|"
                         r"vinieron|arreglaron|llevaron|solucionaron)\b", n)):
        return _resumen_mis_reportes()
    if re.search(r"\b(sigue ahi|sigue alli|todavia esta|aun esta|sigue sin recoger|"
                 r"siguen sin recoger|no han recogido)\b", n):
        pend = [r for r in mis_reportes_bot() if "Resuelto" not in r.get("Estado", "")]
        if pend:
            return (f"Tienes {len(pend)} reporte(s) sin resolver. En **Tus reportes**, arriba en "
                    f"este chat, toca **Sigue ahí** en el que corresponda y la administración lo "
                    f"prioriza más.")
        return ("Para confirmar que un reporte sigue ahí, escríbeme su código (por ejemplo: "
                "*confirmo REP-205*) o toca el punto en el mapa.")

    # 5) Horarios de recolección
    if _es_pregunta_horario(n):
        barrio = detectar_barrio_en_texto(texto, difuso=True) or barrio_para_horario(True)
        if barrio:
            return mensaje_horario(barrio)
        return ("Dime tu barrio y te digo cuándo pasa el camión (por ejemplo: *vivo en La Rosa*). "
                "En general: **La Rosa y Moscú No. 1** → lunes y jueves, 7–9 p.m.; "
                "**los demás barrios** → miércoles y sábado, 3–11 p.m.")

    # 6) Quiere reportar algo: entiende barrio + tipo y prellena el formulario
    n_inicio = n
    for _ in range(3):   # quita muletillas del principio: "ay", "oiga", "parce", "hola"...
        n_inicio = re.sub(r"^(ay|oiga|oye|mire|parce|parcero|veci|vecino|hola|buenas|"
                          r"buenos dias|buenas tardes|buenas noches|disculpe|una pregunta)\s+", "", n_inicio)
    es_pregunta_datos = (
        any(p in n for p in ["cuantos", "cuantas", "estado de", "resumen", "total de"])
        # preguntas tipo "¿Cómo reporto...?" las responde la FAQ con el paso a paso
        or bool(re.match(r"^(como|que|para que|cual|cuales|cuanto|donde|por que)\b", n_inicio))
    )
    if (re.search(_REGEX_NEGACION_REPORTE, n) and "camion" not in n
            and not es_pregunta_datos):
        return "¡Qué bueno que ya quedó limpio! Gracias por avisar."
    intencion = cuenta_algo and not re.search(_REGEX_NEGACION_REPORTE, n)
    barrio = detectar_barrio_en_texto(texto, difuso=True)
    etiqueta, critico_tipo = _detectar_tipo_residuo(n)
    if intencion and (etiqueta or barrio) and not es_pregunta_datos:
        critico = critico_tipo or any(p in n for p in _PALABRAS_URGENTE)
        return _preparar_reporte_bot(texto, barrio, etiqueta, critico)

    return None


# ---------- Foto en el chat: analizar y publicar sin formularios ----------
def analizar_foto_para_bot(img):
    """Misma tubería que el formulario (difuminar personas → Gemini o YOLO →
    clasificación), pero devuelve todo en un diccionario para que el bot lo
    muestre y pida confirmación. OJO: las cajas se dibujan sobre la imagen
    YA difuminada, nunca sobre la original."""
    res = analizar(img)
    img_blur, hubo_personas = difuminar_personas(img, res)
    motor, nota = "yolo", ""
    if verificar_gemini_key():
        det, error_g, es_valido, motivo = analizar_con_gemini(img_blur)
        if error_g:
            nota = "Gemini no respondió; usé la IA local."
            tabla, residuos, peso, tipo, nivel, total = procesar(res)
            img_det = dibujar_detecciones_filtradas(img_blur, res)
        elif es_valido is False:
            return {"valido": False, "motivo": motivo}
        else:
            motor = "gemini"
            tabla, residuos, peso, tipo, nivel, total = procesar_gemini(det)
            img_det = dibujar_detecciones_gemini(img_blur, det)
    else:
        tabla, residuos, peso, tipo, nivel, total = procesar(res)
        img_det = dibujar_detecciones_filtradas(img_blur, res)
    return {
        "valido": True, "motivo": "", "tabla": tabla, "residuos": residuos,
        "peso": peso, "tipo": tipo, "nivel": nivel, "total": total,
        "ia_detecto": bool(tabla), "img_blur": img_blur, "img_det": img_det,
        "hubo_personas": hubo_personas, "motor": motor, "nota": nota,
        "phash": calcular_phash(img_blur),
        "id": __import__("uuid").uuid4().hex,
        "publicado": False,
    }


def publicar_desde_chat(an: dict, barrio: str, obs: str):
    """Publica el reporte que el bot analizó, con TODAS las protecciones del
    formulario: residente verificado, punto dentro de la Comuna 2, límite
    diario, foto reciclada y duplicados. Devuelve (ok, mensaje)."""
    # ANTI DOBLE PUBLICACIÓN: cada análisis solo se puede publicar una vez,
    # aunque la persona toque "Publicar" dos veces seguidas.
    if an.get("publicado"):
        return False, "Este reporte ya se publicó. Para hacer otro, mándame una foto nueva."
    _ph = an.get("phash", "")
    _mis = st.session_state.get("mis_codigos", [])
    if _ph and any(r.get("PHash") == _ph and r.get("Código") in _mis
                   for r in st.session_state.reportes):
        return False, "Ya publicaste esta misma foto. Para otro reporte, toma una foto nueva."
    clat, clon = st.session_state.get("click_lat"), st.session_state.get("click_lon")
    if (not es_residente() or clat is None
            or not POLIGONO_COMUNA2.contains(Point(clon, clat))):
        return False, "Verifica tu dirección y toca un punto dentro de la Comuna 2 en el mapa."
    cod_res = st.session_state.get("mi_codigo_residente", "")
    if not verificar_limite_reportes(cod_res):
        return False, "Llegaste al límite de reportes de hoy."
    rec = buscar_foto_reciclada(clat, clon, an.get("phash", ""))
    if rec:
        return False, (f"Esa foto ya se usó en **{rec[0]['Código']}**, a {rec[1]} m de aquí. "
                       f"Toma una foto nueva de ESTE punto.")
    dup = buscar_posible_duplicado(clat, clon, an.get("phash", ""))
    if dup:
        return False, (f"Ya existe **{dup[0]['Código']}** a {dup[1]} m con una foto muy parecida. "
                       f"Si el residuo sigue ahí, escríbeme: *confirmo {dup[0]['Código']}*.")

    an["publicado"] = True   # se marca ANTES de subir las fotos (lo lento)
    try:
        return _publicar_reporte_bot(an, barrio, obs, clat, clon, cod_res)
    except Exception as e:
        an["publicado"] = False
        _log.error("Falló la publicación desde el bot: %s", e)
        return False, "No se pudo publicar el reporte. Inténtalo de nuevo en un momento."


def _publicar_reporte_bot(an, barrio, obs, clat, clon, cod_res):
    critico = semaforo(an["nivel"]) == "rojo"
    codigo = generar_codigo("CRIT" if critico else "REP", 500 if critico else 200)
    buf_o, buf_c = BytesIO(), BytesIO()
    an["img_blur"].convert("RGB").save(buf_o, format="JPEG", quality=82)
    an["img_det"].convert("RGB").save(buf_c, format="JPEG", quality=82)
    nuevo = {
        "Código": codigo, "Sector": barrio,
        "Referencia": limpiar_texto_libre(st.session_state.get("click_dir", ""), 200),
        "Objetos": an["total"] if critico else an["residuos"],
        "Peso (Kg)": round(an["peso"], 2), "Predominante": an["tipo"] or "Mixto",
        "Clasificación": an["nivel"], "Lat": clat, "Lon": clon,
        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "Estado": "Pendiente",
        "FotoB64": img_a_b64(an["img_blur"]),
        "FotoClasificadaB64": img_a_b64(an["img_det"], max_px=350),
        "Observaciones": limpiar_texto_libre(obs), "NotaVozB64": "", "FotosExtraB64": "",
        "CodigoResidente": cod_res, "PHash": an.get("phash", ""), "Confirmaciones": 0,
    }
    url_o, _ = subir_foto_evidencia_github(buf_o.getvalue(), f"{codigo}.jpg",
                                           carpeta="evidencias_reportes")
    if url_o:
        nuevo["FotoURL"] = url_o
    url_c, _ = subir_foto_evidencia_github(buf_c.getvalue(), f"{codigo}.jpg",
                                           carpeta="evidencias_clasificadas")
    if url_c:
        nuevo["FotoClasificadaURL"] = url_c
    st.session_state.reportes.append(nuevo)
    st.session_state.mis_codigos.append(codigo)
    st.session_state.mis_estados_vistos[codigo] = nuevo["Estado"]
    st.session_state.reportes_hoy_sesion = st.session_state.get("reportes_hoy_sesion", 0) + 1
    guardar_reportes_disco(st.session_state.reportes)
    reiniciar_flujo_reporte()
    return True, (f"¡Listo! Publiqué tu reporte **{codigo}** en **{barrio}** "
                  f"({an['nivel']}). Ya lo ves en el mapa y en Mi Historial. "
                  f"Para el siguiente reporte, toca de nuevo el punto exacto en el mapa.")


# ---------- Voz: hablarle al bot ----------
MAX_BYTES_AUDIO_BOT = 4 * 1024 * 1024   # ~2 minutos de grabación


def transcribir_audio_gemini(audio_bytes: bytes, mime: str = "audio/wav"):
    """Convierte un mensaje de voz en texto usando Gemini (entiende español
    colombiano, incluso con ruido de calle). Devuelve (texto, error)."""
    if not audio_bytes:
        return "", "No se recibió audio."
    if len(audio_bytes) > MAX_BYTES_AUDIO_BOT:
        return "", "El audio es muy largo. Intenta un mensaje de menos de 1 minuto."
    payload = {
        "contents": [{"parts": [
            {"inline_data": {"mime_type": mime or "audio/wav",
                             "data": base64.b64encode(audio_bytes).decode("utf-8")}},
            {"text": ("Transcribe este mensaje de voz de un vecino de la Comuna 2 "
                      "(Santa Cruz, Medellín, Colombia). Escribe SOLO lo que dijo, en español, "
                      "sin comillas ni comentarios. Si no hay voz o no se entiende nada, "
                      "responde exactamente: [inaudible]")},
        ]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 400},
    }
    data, _modelo, error = _llamar_gemini_con_respaldo(payload, timeout=45)
    if error or not data:
        return "", error or "No se pudo transcribir el audio."
    try:
        texto = "".join(p.get("text", "") for p in
                        data["candidates"][0]["content"]["parts"]).strip()
    except Exception:
        return "", "Gemini no devolvió una transcripción."
    if not texto or "[inaudible]" in texto.lower():
        return "", "No logré escuchar bien el audio."
    return limpiar_texto_libre(texto, MAX_LARGO_MENSAJE_BOT), None


# ---------- Voz de EcoBot: voz natural de Gemini + respaldo del navegador ----------
# Modelos de voz de Gemini, del más nuevo al más antiguo. Los 3.8 usan el esquema
# nuevo (speech_metadata + voiceConfig.voice); el 3.1 usa el esquema anterior.
MODELOS_TTS = [
    ("gemini-3.8-flash-lite-tts", "nuevo"),
    ("gemini-3.8-flash-tts", "nuevo"),
    ("gemini-3.1-flash-tts-preview", "anterior"),
]
VOZ_RESPALDO_GEMINI = "Sulafat"      # voz 'cálida' del catálogo de Gemini
MAX_VOCES_HORA = 12                  # respuestas con voz natural por sesión y hora


@st.cache_resource
def _cache_respuestas_bot() -> dict:
    """Respuestas de IA ya generadas para preguntas generales (compartidas)."""
    return {}


def _necesita_herramientas(texto: str) -> bool:
    """True si la pregunta depende de datos reales de la app (un código de
    reporte, cantidades, estados...). Si no, no hace falta mandar las
    herramientas a Gemini."""
    n = _normalizar_txt(texto)
    if re.search(r"\b(rep|crit)[-_ ]?\d", n):
        return True
    return any(p in n for p in ["cuantos", "cuantas", "cuanto", "estado", "mis reportes",
                                "resumen", "total", "hay en", "activos", "pendiente",
                                "resuelto", "telefono", "mi codigo"])


def _primeras_oraciones(texto: str, max_chars: int = 260) -> str:
    """Recorta a las primeras oraciones que quepan en max_chars (para no pagar
    por sintetizar en voz un texto largo)."""
    oraciones = re.split(r"(?<=[.!?])\s+", texto.strip())
    salida = ""
    for o in oraciones:
        if salida and len(salida) + len(o) + 1 > max_chars:
            break
        salida = (salida + " " + o).strip()
    return salida[:max_chars + 80]


_NUM_HABLADO = {1: "una", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete",
                8: "ocho", 9: "nueve", 10: "diez", 11: "once", 12: "doce"}


def _momento_del_dia(h12: int, ap: str) -> str:
    if ap == "a":
        return "de la medianoche" if h12 == 12 else "de la mañana"
    if h12 == 12:
        return "del mediodía"
    return "de la tarde" if h12 <= 6 else "de la noche"


def _hora_hablada(h: str, m: str, ap: str, con_momento: bool = True) -> str:
    """'3', '00', 'p' -> 'las tres de la tarde'; '1', '30', 'a' -> 'la una y media de la mañana'."""
    h12 = int(h) if 1 <= int(h) <= 12 else 12
    txt = ("la " if h12 == 1 else "las ") + _NUM_HABLADO[h12]
    mm = int(m or 0)
    if mm == 30:
        txt += " y media"
    elif mm:
        txt += f" y {mm}"
    return txt + (f" {_momento_del_dia(h12, ap)}" if con_momento else "")


def _horas_a_palabras(t: str) -> str:
    """Convierte horarios escritos ('3:00 p.m. – 11:00 p.m.') a como se dicen
    ('de las tres de la tarde a las once de la noche')."""
    pm = r"\s*([ap])\.?\s*m\b(\.?)"

    def _punto(m, grupo):   # conserva el punto si cierra la oración
        resto = m.string[m.end():]
        cierra = not resto.strip() or re.match(r"\s+[A-ZÁÉÍÓÚÑ¡¿]", resto)
        return "." if (m.group(grupo) == "." and cierra) else ""

    def _rango(m):
        h1, m1, a1, _p1, h2, m2, a2, _p2 = m.groups()
        a1, a2 = a1.lower(), a2.lower()
        mom1 = _momento_del_dia(int(h1) if 1 <= int(h1) <= 12 else 12, a1)
        mom2 = _momento_del_dia(int(h2) if 1 <= int(h2) <= 12 else 12, a2)
        primero = _hora_hablada(h1, m1, a1, con_momento=(mom1 != mom2))
        return f"de {primero} a {_hora_hablada(h2, m2, a2)}" + _punto(m, 8)

    t = re.sub(r"(?:de\s+)?(\d{1,2}):(\d{2})" + pm + r"\s*[–-]\s*(\d{1,2}):(\d{2})" + pm,
               _rango, t, flags=re.IGNORECASE)

    def _rango_corto(m):
        h1, h2, ap = m.group(1), m.group(2), m.group(3).lower()
        mom1 = _momento_del_dia(int(h1) if 1 <= int(h1) <= 12 else 12, ap)
        mom2 = _momento_del_dia(int(h2) if 1 <= int(h2) <= 12 else 12, ap)
        return (f"de {_hora_hablada(h1, '0', ap, con_momento=(mom1 != mom2))} a "
                f"{_hora_hablada(h2, '0', ap)}" + _punto(m, 4))

    t = re.sub(r"(?:de\s+)?(\d{1,2})\s*[–-]\s*(\d{1,2})" + pm, _rango_corto, t, flags=re.IGNORECASE)
    t = re.sub(r"(\d{1,2}):(\d{2})" + pm,
               lambda m: _hora_hablada(m.group(1), m.group(2), m.group(3).lower()) + _punto(m, 4),
               t, flags=re.IGNORECASE)
    return re.sub(r"\b(las|la) (las|la) ", r"\1 ", t)     # "a las las seis" -> "a las seis"


def texto_para_voz(texto: str) -> str:
    """Prepara el texto para que se escuche como habla una persona: sin
    símbolos de formato ni enlaces, deletreando los códigos (REP-207 -> R E P
    207) y diciendo las horas, números y unidades con palabras ('3:00 p.m.'
    -> 'las tres de la tarde', '12 kg' -> '12 kilos')."""
    t = texto or ""
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[*_`#>]", "", t)
    t = _horas_a_palabras(t)
    t = re.sub(r"\b(REP|CRIT)-(\d+)\b", lambda m: " ".join(m.group(1)) + " " + m.group(2), t)
    t = re.sub(r"\bNo\.\s*(\d+)", r"número \1", t)
    t = re.sub(r"(\d+)[.,](\d+)\s*kg\b", r"\1 coma \2 kilos", t, flags=re.IGNORECASE)
    t = re.sub(r"(\d+)\s*kg\b", r"\1 kilos", t, flags=re.IGNORECASE)
    t = re.sub(r"(\d+)\s*m\b(?!\w)", r"\1 metros", t)
    t = re.sub(r"(\d+)\s*%", r"\1 por ciento", t)
    t = re.sub(r"(\d+)\s*h\b(?!\w)", r"\1 horas", t)
    t = re.sub(r"(?m)^\s*-\s+", "", t)
    t = t.replace("–", " a ").replace("—", ", ").replace("→", ", ").replace("·", ", ")
    t = re.sub(r"\s*\(([^)]*)\)", r", \1,", t)          # (paréntesis) -> pausa con comas
    t = re.sub(r"\s*\n+\s*", ". ", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*([.,;:!?])", r"\1", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()[:600]


def _pcm_a_wav(pcm: bytes, rate: int = 24000) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


@st.cache_data(show_spinner=False, ttl=86400)
def _voz_colombiana() -> str:
    """Busca en la Biblioteca de Voces de Gemini una voz femenina con acento
    colombiano. Si no hay o falla, devuelve '' y se usa la voz de respaldo."""
    try:
        import requests
        api_key = _gemini_config()
        if not api_key:
            return ""
        r = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/voices",
            headers={"x-goog-api-key": api_key},
            params={"language_code": "es-CO", "gender": "female", "type": "prebuilt",
                    "page_size": 20}, timeout=15)
        if r.status_code != 200:
            return ""
        voces = r.json().get("voices", [])
        for v in voces:   # prefiere una descrita como cálida/amable
            desc = (str(v.get("description", "")) + str(v.get("persona", ""))).lower()
            if any(k in desc for k in ("warm", "friendly", "cálid", "amable")) and v.get("id"):
                return v["id"]
        return voces[0].get("id", "") if voces else ""
    except Exception:
        return ""


@st.cache_data(show_spinner=False, max_entries=60, ttl=3600)
def _sintetizar_cache(texto: str, voz_config: str) -> bytes:
    """Convierte texto en audio WAV con voz natural. Lanza RuntimeError si
    ningún modelo responde (los errores no se guardan en caché)."""
    import requests
    api_key = _gemini_config()
    if not api_key:
        raise RuntimeError("Falta GEMINI_API_KEY")
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}
    estilo = ("warm, close and natural, like a kind neighbor from Medellin speaking Colombian "
              "Spanish, with a gentle smile in the voice, a relaxed and slightly slow pace, "
              "short natural pauses at commas, never robotic and never like a news announcer")
    voces = [v for v in (voz_config, _voz_colombiana(), VOZ_RESPALDO_GEMINI) if v]
    ultimo = "sin respuesta"
    for modelo, esquema in MODELOS_TTS:
        for voz in dict.fromkeys(voces):          # sin repetir
            if esquema == "nuevo":
                payload = {
                    "contents": [{"role": "user", "parts": [
                        {"text": texto, "speech_metadata": {"style": estilo}}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"],
                                         "speechConfig": {"voiceConfig": {"voice": voz}}},
                }
            else:
                payload = {
                    "contents": [{"parts": [{"text": "Dilo como una vecina paisa muy amable de Medellín: "
                                                     "voz cálida y cercana, con una sonrisa, ritmo "
                                                     "tranquilo y pausas cortas en las comas, nada "
                                                     "robótico: " + texto}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}},
                }
            url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
                   f"{modelo}:generateContent")
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=40)
            except Exception as e:
                ultimo = f"conexión: {e}"
                break                              # sin red: no sirve probar otras voces
            if resp.status_code != 200:
                ultimo = f"{modelo} respondió {resp.status_code}"
                if resp.status_code in (429, 503, 404):
                    break                          # cambiar de modelo
                continue                           # 400: probar la siguiente voz
            try:
                _json_tts = resp.json()
                _sumar_tokens(_json_tts, "voz")
                parte = _json_tts["candidates"][0]["content"]["parts"][0]
                inline = parte.get("inlineData") or parte.get("inline_data") or {}
                audio = base64.b64decode(inline["data"])
                mime = inline.get("mimeType") or inline.get("mime_type") or ""
            except Exception:
                ultimo = f"{modelo} no devolvió audio"
                continue
            if audio[:4] == b"RIFF":
                return audio
            m = re.search(r"rate=(\d+)", mime)
            return _pcm_a_wav(audio, int(m.group(1)) if m else 24000)
    raise RuntimeError(ultimo)


def _elevenlabs_config():
    """(api_key, voice_id) si en Secrets están ELEVENLABS_API_KEY y
    ELEVENLABS_VOICE_ID (la voz clonada). Si falta alguno, devuelve None."""
    try:
        k = str(st.secrets.get("ELEVENLABS_API_KEY", "")).strip()
        v = str(st.secrets.get("ELEVENLABS_VOICE_ID", "")).strip()
    except Exception:
        k = v = ""
    k = k or os.environ.get("ELEVENLABS_API_KEY", "").strip()
    v = v or os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
    return (k, v) if k and re.fullmatch(r"[A-Za-z0-9]{10,40}", v or "") else None


@st.cache_data(show_spinner=False, max_entries=60, ttl=3600)
def _sintetizar_elevenlabs(texto: str) -> bytes:
    """Lee el texto con la voz clonada de ElevenLabs. Devuelve MP3. Lanza
    RuntimeError si falla (los errores no se guardan en caché)."""
    import requests
    cfg = _elevenlabs_config()
    if not cfg:
        raise RuntimeError("Falta ELEVENLABS_API_KEY o ELEVENLABS_VOICE_ID")
    api_key, voice_id = cfg
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": api_key, "Content-Type": "application/json",
                 "Accept": "audio/mpeg"},
        json={"text": texto, "model_id": "eleven_multilingual_v2",
              "voice_settings": {"stability": 0.45, "similarity_boost": 0.85,
                                 "style": 0.25, "use_speaker_boost": True}},
        timeout=40)
    if r.status_code != 200 or not r.content:
        raise RuntimeError(f"ElevenLabs respondió {r.status_code}")
    return r.content


def tts_cupo_disponible() -> bool:
    ahora = time.time()
    marcas = [t for t in st.session_state.get("tts_marcas", []) if ahora - t < 3600]
    if len(marcas) >= MAX_VOCES_HORA:
        st.session_state.tts_marcas = marcas
        return False
    marcas.append(ahora)
    st.session_state.tts_marcas = marcas
    return True


def hablar_en_voz_alta(texto: str):
    """Respaldo sin costo: la voz del navegador, eligiendo la más natural
    que tenga instalada en español (las 'Natural'/'Online' o las de Google)."""
    import json as _json
    import streamlit.components.v1 as components
    js_texto = _json.dumps(texto_para_voz(texto), ensure_ascii=False).replace("</", "<\\/")
    components.html("""<script>
(function(){
  const texto = """ + js_texto + """;
  const S = window.speechSynthesis; if(!S) return;
  function puntaje(v){
    let p = 0;
    if(/natural|neural|online/i.test(v.name)) p += 4;
    if(/google/i.test(v.name)) p += 3;
    if(/es[-_]CO/i.test(v.lang)) p += 2;
    else if(/es[-_](MX|US|419)/i.test(v.lang)) p += 1;
    return p;
  }
  function hablar(){
    const vs = S.getVoices().filter(v => /^es/i.test(v.lang));
    const u = new SpeechSynthesisUtterance(texto);
    u.lang = 'es-CO'; u.rate = 0.97; u.pitch = 1.03;
    if(vs.length){ vs.sort((a,b)=>puntaje(b)-puntaje(a)); u.voice = vs[0]; u.lang = vs[0].lang; }
    S.cancel(); S.speak(u);
  }
  try {
    if(S.getVoices().length){ hablar(); }
    else { S.onvoiceschanged = function(){ S.onvoiceschanged = null; hablar(); }; }
  } catch(e) {}
})();
</script>""", height=0)


def reproducir_respuesta(texto: str):
    """Lee la respuesta del bot en voz alta. Primero intenta la voz natural
    de Gemini; si no está disponible (sin cupo, sin red, etc.) usa la del
    navegador para que nunca se quede mudo."""
    voz_cfg = ""
    try:
        voz_cfg = str(st.secrets.get("ECOBOT_VOZ", "")).strip()
    except Exception:
        pass
    limpio = texto_para_voz(texto)
    if not limpio:
        return
    # Para apagar la voz de pago y usar siempre la del navegador (gratis):
    # ECOBOT_VOZ_NATURAL = false en Secrets.
    try:
        natural = str(st.secrets.get("ECOBOT_VOZ_NATURAL", "true")).strip().lower() != "false"
    except Exception:
        natural = True
    hay_voz_propia = _elevenlabs_config() is not None
    if natural and (hay_voz_propia or verificar_gemini_key()) and tts_cupo_disponible():
        principal = _primeras_oraciones(limpio)   # solo lo principal: es lo que se factura
        # 1) Tu voz clonada (si está configurada)
        if hay_voz_propia:
            try:
                with st.spinner("Preparando la voz..."):
                    mp3 = _sintetizar_elevenlabs(principal)
                try:
                    st.audio(mp3, format="audio/mp3", autoplay=True)
                except TypeError:                  # versión sin autoplay
                    st.audio(mp3, format="audio/mp3")
                return
            except Exception as e:
                _log.warning("Voz clonada no disponible, pruebo la de Gemini: %s", e)
        # 2) Voz natural de Gemini
        if verificar_gemini_key():
            try:
                with st.spinner("Preparando la voz..."):
                    wav = _sintetizar_cache(principal, voz_cfg)
                try:
                    st.audio(wav, format="audio/wav", autoplay=True)
                except TypeError:
                    st.audio(wav, format="audio/wav")
                return
            except Exception as e:
                _log.warning("Voz natural no disponible, uso la del navegador: %s", e)
    # 3) Voz del navegador (gratis)
    hablar_en_voz_alta(texto)


def _chat_acepta_audio() -> bool:
    """True si esta versión de Streamlit trae st.chat_input con micrófono
    integrado (junto al botón de enviar)."""
    try:
        import inspect
        return "accept_audio" in inspect.signature(st.chat_input).parameters
    except Exception:
        return False


def _marca_msgs(msgs) -> tuple:
    """Huella del último mensaje del chat, para no leer dos veces lo mismo."""
    if not msgs:
        return (0, "")
    return (len(msgs), hashlib.md5(str(msgs[-1].get("content", "")).encode()).hexdigest()[:10])


def leer_ultima_respuesta_si_corresponde():
    """Si 'Leer las respuestas en voz alta' está activo, lee en voz alta cada
    respuesta nueva de EcoBot, venga de un mensaje escrito, de un audio, de
    una pregunta rápida o de una foto. Con el interruptor apagado no lee nada
    y deja marcado lo ya existente, para que al encenderlo no lea lo viejo."""
    msgs = st.session_state.get("agente_msgs") or []
    activo = bool(st.session_state.get("bot_voz_salida"))
    marca = _marca_msgs(msgs)
    if st.session_state.pop("_voz_confirmar", False) and activo:
        st.session_state.bot_ultimo_leido = marca
        hablar_en_voz_alta("Lectura en voz alta activada.")   # confirma con voz gratis
        return
    if not activo:
        st.session_state.bot_ultimo_leido = marca
        return
    if not msgs or msgs[-1].get("role") != "assistant":
        return
    if st.session_state.get("bot_ultimo_leido") == marca:
        return
    st.session_state.bot_ultimo_leido = marca
    reproducir_respuesta(str(msgs[-1].get("content", "")))


def bloque_avisos_bot(refrescar):
    """Lo que EcoBot cuenta por iniciativa propia al abrir el chat: si hoy o
    mañana pasa el camión por tu barrio, novedades de tus reportes, y tus
    reportes con acciones de un toque. Todo local: no gasta IA."""
    from urllib.parse import quote
    # --- 1) Aviso del camión (solo si pasa hoy o mañana) ---
    b = barrio_para_horario(True)
    if b:
        info = HORARIOS_RECOLECCION[b]
        delta = dias_para_proximo_paso(b)
        franja = _franja_horas(b)
        ahora = _hoy_colombia()
        if delta == 0 and (not franja or ahora.hour + ahora.minute / 60 < franja[1]):
            st.success(f"Aviso del camión: hoy pasa por **{b}**, de {_con_punto(info['horario'])} "
                       f"Saca tus bolsas poco antes.")
        elif delta == 1:
            st.info(f"Aviso del camión: mañana pasa por **{b}**, de {_con_punto(info['horario'])}")

    # --- 2) Recordar mi barrio, con un toque ---
    cand = st.session_state.get("barrio_usuario")
    if cand in HORARIOS_RECOLECCION and cand != barrio_recordado():
        if st.button(f"Recordar {cand} como mi barrio", key="bot_recordar_barrio",
                     use_container_width=True,
                     help="Guarda solo el nombre del barrio en tu navegador para avisarte del camión."):
            recordar_barrio(cand)
            st.session_state.agente_msgs.append({"role": "assistant", "content":
                f"Listo, recordaré que vives en **{cand}**. Te aviso cuando el camión pase hoy o mañana."})
            st.session_state.bot_accion_global = True      # para guardar la cookie
            refrescar()

    mis = mis_reportes_bot()
    if not mis:
        return

    # --- 3) Novedades: reportes que cambiaron de estado ---
    vistos = st.session_state.setdefault("bot_avisos_vistos", set())
    novedades = []
    for r in mis:
        est = r.get("Estado", "")
        clave = f"{r.get('Código')}:{est}"
        if clave in vistos:
            continue
        if "Resuelto" in est:
            novedades.append(("ok", r, clave))
        elif "proceso" in est.lower():
            novedades.append(("info", r, clave))
    for tipo, r, clave in novedades[:3]:
        if tipo == "ok":
            st.success(f"Tu reporte **{r.get('Código')}** ({r.get('Sector','')}) ya fue resuelto. "
                       f"Gracias por reportarlo.")
        else:
            st.info(f"Tu reporte **{r.get('Código')}** ({r.get('Sector','')}) ya lo están atendiendo.")
        if st.button("Entendido", key=f"bot_visto_{clave}"):
            vistos.add(clave)
            refrescar()

    # --- 4) Tus reportes, con acciones de un toque ---
    pendientes = [r for r in mis if "Resuelto" not in r.get("Estado", "")]
    with st.expander(f"Tus reportes ({len(mis)}) — {len(pendientes)} sin resolver",
                     expanded=bool(novedades)):
        conf = st.session_state.get("confirmados_sesion", set())
        for r in mis[:5]:
            cod, est = r.get("Código"), r.get("Estado", "")
            h = _horas_desde(r.get("Fecha"))
            cuando = f" · {_hace_texto(h)}" if h is not None else ""
            st.markdown(f"**{cod}** · {r.get('Sector','')}{cuando}  \n{est}")
            if "Resuelto" in est:
                txt = (f"Mi reporte {cod} en {r.get('Sector','')} (Comuna 2) ya fue resuelto "
                       f"gracias a EcoCom2 Circular IA.")
                st.link_button("Compartir en WhatsApp", f"https://wa.me/?text={quote(txt)}",
                               use_container_width=True)
            elif cod in conf:
                st.caption("Ya confirmaste que sigue ahí. ¡Gracias!")
            elif h is not None and h < 24:
                st.caption("Podrás confirmar que sigue ahí pasadas 24 horas del reporte.")
            elif st.button("Sigue ahí", key=f"bot_sigue_{cod}", use_container_width=True,
                           help="Avisa a la administración que el residuo continúa."):
                ok, msg = confirmar_reporte_bot(cod)
                st.session_state.agente_msgs.append({"role": "assistant", "content": msg})
                refrescar()


def renderizar_foto_ecobot():
    st.markdown("**Mándame una foto y yo la analizo**")
    _aviso = st.session_state.get("bot_aviso")
    if _aviso:
        (st.success if _aviso[0] == "ok" else st.error)(_aviso[1])
    clat, clon = st.session_state.get("click_lat"), st.session_state.get("click_lon")
    punto_ok = (es_residente() and clat is not None
                and POLIGONO_COMUNA2.contains(Point(clon, clat)))
    if not punto_ok:
        st.caption("Para publicar desde aquí primero verifica tu dirección (GPS) y "
                   "toca el punto exacto del residuo en el mapa. Luego vuelve y mándame la foto.")
        return

    n_up = st.session_state.get("bot_foto_n", 0)
    foto = st.file_uploader("Foto del residuo", type=["jpg", "jpeg", "png"],
                            key=f"bot_foto_{n_up}", label_visibility="collapsed")

    def _terminar():
        st.session_state.bot_analisis = None
        st.session_state.bot_hash = None
        st.session_state.bot_foto_n = n_up + 1

    if foto is None:
        st.session_state.bot_analisis = None
        return
    ok, motivo = validar_foto_subida(foto)
    if not ok:
        st.error(f"La foto se descartó: {motivo}.")
        return
    img = _abrir_img_subida(foto)
    h = _hash_imagen(img)
    if h != st.session_state.get("bot_hash"):
        if not ecobot_cupo_disponible():
            st.warning("Muchas consultas seguidas. Espera un rato e inténtalo de nuevo.")
            return
        st.session_state.pop("bot_aviso", None)   # empieza un reporte nuevo
        with st.spinner("Analizando tu foto..."):
            st.session_state.bot_analisis = analizar_foto_para_bot(img)
        st.session_state.bot_hash = h

    an = st.session_state.get("bot_analisis")
    if not an:
        return
    if an.get("publicado"):
        st.info("Este reporte ya fue publicado.")
        return
    if not an["valido"]:
        st.error("Esta foto no parece mostrar residuos reales. "
                 f"{esc(an.get('motivo', ''))} Sube otra donde se vea la acumulación.")
        return
    if an.get("hubo_personas"):
        st.info("Había personas en la foto y las difuminé para proteger su privacidad.")
    st.image(an["img_det"], use_container_width=True)
    if not an["ia_detecto"]:
        st.warning("No logré identificar objetos en esta foto. Usa el formulario para "
                   "clasificarla manualmente.")
        if st.button("Ir al formulario", key="bot_ir_form", use_container_width=True):
            st.session_state.seccion = "residuo"
            _terminar()
            st.rerun()
        return
    mostrar_explicacion_ia(an["tabla"], an["nivel"], an["peso"], an.get("motor", "yolo"))
    if an.get("nota"):
        st.caption(an["nota"])

    sug = (st.session_state.get("prefill_barrio") or st.session_state.get("click_barrio"))
    barrio_sel = st.selectbox("Barrio:", BARRIOS,
                              index=BARRIOS.index(sug) if sug in BARRIOS else 0,
                              key="bot_barrio")
    obs_sel = st.text_area("Observaciones (opcional):",
                           value=st.session_state.get("prefill_obs", ""),
                           key="bot_obs", height=70, max_chars=MAX_LARGO_TEXTO_LIBRE)
    cb1, cb2 = st.columns(2)
    with cb1:
        if st.button("Publicar", type="primary", key="bot_publicar", use_container_width=True):
            ok_p, msg_p = publicar_desde_chat(an, barrio_sel, obs_sel)
            st.session_state.agente_msgs.append({"role": "assistant", "content": msg_p})
            st.session_state.bot_aviso = ("ok" if ok_p else "err",
                                          msg_p.split("\n\n")[0].replace("**", ""))
            if ok_p:
                _terminar()
            st.rerun()
    with cb2:
        if st.button("Descartar", key="bot_descartar", use_container_width=True):
            _terminar()
            st.rerun()


def generar_resumen_semanal(reportes: list) -> str:
    """Texto listo para copiar/enviar por WhatsApp con el estado de los
    últimos 7 días: lo que antes había que armar a mano mirando el panel."""
    from collections import Counter
    from datetime import timedelta as _td
    ahora = datetime.now()
    limite = ahora - _td(days=7)

    def _f(txt):
        try:
            return datetime.strptime(txt or "", "%Y-%m-%d %H:%M")
        except Exception:
            return None

    nuevos = [r for r in reportes if (_f(r.get("Fecha")) or datetime.min) >= limite]
    resueltos_sem = [r for r in reportes if "Resuelto" in r.get("Estado", "")
                     and (_f(r.get("FechaResuelto")) or datetime.min) >= limite]
    activos = [r for r in reportes if "Resuelto" not in r.get("Estado", "")]
    criticos = [r for r in activos if "crítico" in r.get("Clasificación", "").lower()]
    viejos = [r for r in criticos if "Pendiente" in r.get("Estado", "")
              and (_f(r.get("Fecha")) or ahora) < ahora - _td(hours=48)]
    top = Counter(r.get("Sector", "—") for r in nuevos).most_common(3)
    kg = sum(float(r.get("Peso (Kg)", 0) or 0) for r in nuevos)

    lineas = [
        f"*EcoCom2 — Resumen semanal* ({limite:%d/%m} al {ahora:%d/%m/%Y})",
        "",
        f"Reportes nuevos: *{len(nuevos)}*",
        f"Resueltos esta semana: *{len(resueltos_sem)}*",
        f"Puntos críticos pendientes: *{len(criticos)}*",
        f"Críticos con más de 48 h sin atender: *{len(viejos)}*",
        f"Peso estimado reportado: *{kg:.1f} kg*",
    ]
    if top:
        lineas += ["", "Barrios con más reportes:"]
        lineas += [f"  {i}. {b} — {c}" for i, (b, c) in enumerate(top, 1)]
    if viejos:
        lineas += ["", "Atender primero: " + ", ".join(r["Código"] for r in viejos[:6])]
    return "\n".join(lineas)


def alertas_automaticas(reportes: list) -> list:
    """Revisión automática para la administración: marca lo que requiere
    atención sin que nadie tenga que buscarlo a mano."""
    alertas = []
    activos = [r for r in reportes if "Resuelto" not in r.get("Estado", "")]
    sospechosos = [r["Código"] for r in activos if (r.get("ReportesFalsos") or 0) >= 3]
    if sospechosos:
        alertas.append(("err", f"{len(sospechosos)} reporte(s) marcados como 'no es basura' "
                               f"por 3+ vecinos — revisa la foto: {', '.join(sospechosos[:8])}"))
    ahora = datetime.now()
    viejos, recientes = [], 0
    for r in activos:
        try:
            f = datetime.strptime(r.get("Fecha", ""), "%Y-%m-%d %H:%M")
        except Exception:
            continue
        horas = (ahora - f).total_seconds() / 3600
        if "crítico" in r.get("Clasificación", "").lower() and horas > 48 \
                and "Pendiente" in r.get("Estado", ""):
            viejos.append(r["Código"])
        if horas <= 1:
            recientes += 1
    if viejos:
        alertas.append(("err", f"{len(viejos)} punto(s) crítico(s) llevan más de 48 h "
                               f"sin atención: {', '.join(viejos[:8])}"))
    if recientes >= 10:
        alertas.append(("warn", f"Pico inusual: {recientes} reportes en la última hora. "
                                f"Revisa que no sea spam."))
    if not _github_config()[0]:
        alertas.append(("warn", "El respaldo en GitHub no está configurado: si el servidor "
                                "se reinicia se pierden los reportes."))
    elif not _sal_respaldo():
        alertas.append(("warn", "Falta BACKUP_SALT en Secrets: el respaldo se sube SIN los "
                                "teléfonos, así que tras un reinicio los vecinos no verán su "
                                "historial. Agrégalo para conservarlo de forma segura."))
    return alertas


# ====================================================================
# 7. BARRA LATERAL
# ====================================================================
try:
    st.sidebar.image("logo.png", use_container_width=True)
except Exception:
    st.sidebar.markdown("## EcoCom2")

if demo_habilitado():
    if st.session_state.get("modo_demo") and st.session_state.validado:
        st.sidebar.info("Modo demostración: ubicación simulada en Santa Cruz.")
        if st.sidebar.button("Salir del modo demostración", key="salir_demo",
                             use_container_width=True):
            st.session_state.pop("modo_demo", None)
            st.session_state.pop("acepta_datos_ubicacion", None)
            for k in _CLAVES_UBICACION:
                st.session_state.pop(k, None)
            st.rerun()
    elif st.sidebar.button("Probar con residencia simulada (Santa Cruz)", key="activar_demo",
                           type="primary", use_container_width=True,
                           help="Simula una residencia verificada en Calle 102 # 49-22, Santa Cruz."):
        activar_modo_demo()
        st.session_state.menu_extra = None
        st.rerun()

if st.session_state.validado:
    if not st.session_state.fuera:
        st.sidebar.markdown(
            f'<div class="badge-ok" style="font-size:12px;">Dentro de la Comuna 2<br>'
            f'<span style="font-weight:normal">{esc(st.session_state.direccion[:55])}</span></div>',
            unsafe_allow_html=True)
    else:
        st.sidebar.markdown(
            '<div class="badge-err" style="font-size:12px;">Fuera de la Comuna 2<br>'
            '<span style="font-weight:normal">Solo lectura del mapa</span></div>',
            unsafe_allow_html=True)
else:
    st.sidebar.markdown(
        '<div class="badge-warn" style="font-size:12px;">Sin verificar<br>'
        '<span style="font-weight:normal">Ingresa tu dirección abajo</span></div>',
        unsafe_allow_html=True)

st.sidebar.markdown("---")

PAGINAS = ["Reportar y Ver Mapa", "Información"]
if st.session_state.pop("ir_a_inicio", False):
    st.session_state.menu_radio = PAGINAS[0]   # el bot nos lleva a reportar
    st.session_state.menu_extra = None
menu_elegido = st.sidebar.radio("Menú", PAGINAS, key="menu_radio")

es_admin = admin_sesion_vigente()

# Todo lo secundario va junto en un solo desplegable: la barra lateral queda limpia.
with st.sidebar.expander("Más opciones"):
    if st.button("Comuna en Cifras", use_container_width=True, key="ir_cifras"):
        st.session_state.menu_extra = "Comuna en Cifras"
        st.rerun()
    if st.button("Ver tutorial de nuevo", use_container_width=True, key="ver_tutorial_de_nuevo"):
        st.session_state.tutorial_visto = False
        st.session_state.tutorial_paso = 0
        st.session_state.menu_extra = None
        st.rerun()
    if datos_ubicacion_aceptados() and st.button(
            "Revocar autorización de datos", use_container_width=True, key="revocar_habeas",
            help="Retira tu autorización y borra tu ubicación de esta sesión."):
        revocar_datos_ubicacion()
        st.session_state.menu_extra = None
        st.rerun()
    # El acceso al panel de administración solo existe para quien ya inició sesión
    if es_admin and st.button("Panel Admin", use_container_width=True, key="ir_admin"):
        st.session_state.menu_extra = "Panel Admin"
        st.rerun()
    if st.session_state.get("menu_extra") and st.button(
            "Volver al inicio", use_container_width=True, key="ir_inicio"):
        st.session_state.menu_extra = None
        st.rerun()

vaciar_cookies_habeas()
menu = st.session_state.get("menu_extra") or menu_elegido
if menu == "Reportar y Ver Mapa":
    menu = "Inicio y Mapa"  # nombre interno sin cambiar el resto de la lógica

st.sidebar.markdown("---")

# El login de administrador NO se muestra a los ciudadanos. El personal entra con
# la dirección de la app terminada en  ?admin=1  (la contraseña sigue siendo
# necesaria, con bloqueo tras varios intentos fallidos).
_admin_en_url = str(st.query_params.get("admin", "")).strip().lower() in ("1", "true", "si")

if not es_admin:
    if _admin_en_url:
        with st.sidebar.expander("Acceso Administrador", expanded=True):
            pwd = st.text_input("Contraseña:", type="password", key="adm_pwd",
                                placeholder="Ingresa la contraseña")
            if st.button("Ingresar", key="adm_login", type="primary",
                         use_container_width=True):
                ok_adm, msg_adm = verificar_credenciales_admin(pwd)
                if ok_adm:
                    st.session_state.admin_ok = True
                    st.success(msg_adm)
                    st.rerun()
                else:
                    st.error(msg_adm)
else:
    st.sidebar.markdown(
        '<div class="badge-ok" style="font-size:12px;margin-bottom:6px;">'
        'Admin activo<br>'
        '<span style="font-weight:normal">Brandon Duque · ITM</span></div>',
        unsafe_allow_html=True)
    if st.sidebar.button("Cerrar sesión", key="adm_logout",
                         use_container_width=True):
        st.session_state.admin_ok = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div class="ecocom2-footer" style="font-size:11px;padding:8px;background:rgba(16,185,129,0.06);
border-radius:6px;border:1px solid rgba(74,222,128,0.15);">
<b style="color:#16a34a">EcoCom2 v7.0</b><br>
Territorio INN 2026 | ITM Medellín<br>
Dev: <b style="color:#16a34a">Brandon Duque</b>
</div>""", unsafe_allow_html=True)

# ====================================================================
# ECOBOT EN TODAS LAS PANTALLAS (menos el Panel Admin, para no tapar
# los controles de administración)
# ====================================================================
if menu != "Panel Admin":
    if "agente_msgs" not in st.session_state:
        st.session_state.agente_msgs = [
            {"role": "assistant",
             "content": "¡Hola! Soy EcoBot, el asistente de EcoCom2.\n\n"
                        "Puedes escribirme cosas como *\"hay escombros en La Frontera\"* y preparo "
                        "el reporte por ti, grabarme un **audio**, mandarme una **foto**, o decirme un código "
                        "(*confirmo REP-205*). También te cuento *cómo van mis reportes* y cuándo "
                        "pasa el camión. ¿Qué necesitas?"}
        ]
    if "agente_pendiente" not in st.session_state:
        st.session_state.agente_pendiente = False

    # ----------------------------------------------------------------
    # MEJORA 4 — Herramientas de "function calling" para EcoBot: le dan
    # acceso a datos REALES de la app (estado de un reporte, cuántos
    # tiene un residente, cuántos activos hay en un barrio, resumen
    # general), en vez de que solo pueda responder con texto genérico.
    # ----------------------------------------------------------------
    def _herramientas_ecobot_definiciones():
        """Declara, en el formato que exige la API de Gemini, qué funciones
        puede 'pedir ejecutar' el modelo durante la conversación. Cada una
        describe su propósito y sus parámetros en lenguaje natural — Gemini
        usa esa descripción para decidir cuándo llamarlas."""
        return [{
            "functionDeclarations": [
                {
                    "name": "consultar_estado_reporte",
                    "description": ("Consulta el estado actual de un reporte de EcoCom2 "
                                     "dado su código exacto (ej. REP-203 o CRIT-510)."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "codigo": {"type": "string",
                                       "description": "Código del reporte, ej. REP-203"}
                        },
                        "required": ["codigo"],
                    },
                },
                {
                    "name": "contar_reportes_de_residente",
                    "description": ("Cuenta cuántos reportes ha hecho un residente dado su "
                                     "código o teléfono, y cuántos de esos siguen pendientes, "
                                     "en proceso o ya resueltos."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "codigo_residente": {"type": "string",
                                                  "description": "El código o teléfono que la persona usó al reportar"}
                        },
                        "required": ["codigo_residente"],
                    },
                },
                {
                    "name": "reportes_activos_en_barrio",
                    "description": ("Devuelve cuántos reportes activos (no resueltos) hay "
                                     "ahora mismo en un barrio específico de la Comuna 2, y "
                                     "cuántos de esos son puntos críticos."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "barrio": {"type": "string",
                                       "description": "Nombre del barrio, ej. 'La Frontera' o 'Andalucía'"}
                        },
                        "required": ["barrio"],
                    },
                },
                {
                    "name": "resumen_general_comuna",
                    "description": ("Da el resumen general de TODOS los reportes de la "
                                     "Comuna 2 hasta ahora: total, pendientes, en proceso, "
                                     "resueltos y el peso acumulado estimado."),
                    "parameters": {"type": "object", "properties": {}},
                },
            ]
        }]

    def _ejecutar_herramienta_ecobot(nombre_funcion: str, argumentos: dict) -> dict:
        """Ejecuta LOCALMENTE (sin salir de tu servidor) la función que
        Gemini pidió invocar, leyendo directamente de
        st.session_state.reportes — la misma fuente de verdad que usa el
        resto de la app. Gemini nunca toca tus datos directamente, solo
        recibe el resultado ya calculado."""
        reportes = st.session_state.get("reportes", [])

        if nombre_funcion == "consultar_estado_reporte":
            codigo = (argumentos.get("codigo") or "").strip().upper()
            for r in reportes:
                if r.get("Código", "").strip().upper() == codigo:
                    return {
                        "encontrado": True,
                        "estado": r.get("Estado", ""),
                        "sector": r.get("Sector", ""),
                        "clasificacion": r.get("Clasificación", ""),
                        "fecha": r.get("Fecha", ""),
                    }
            return {"encontrado": False}

        if nombre_funcion == "contar_reportes_de_residente":
            cod = (argumentos.get("codigo_residente") or "").strip().lower()
            propios = [r for r in reportes
                       if cod and coincide_residente(r.get("CodigoResidente", ""), cod)]
            return {
                "total": len(propios),
                "pendientes": sum(1 for r in propios if "Pendiente" in r.get("Estado", "")),
                "en_proceso": sum(1 for r in propios if "proceso" in r.get("Estado", "")),
                "resueltos": sum(1 for r in propios if "Resuelto" in r.get("Estado", "")),
            }

        if nombre_funcion == "reportes_activos_en_barrio":
            barrio_solicitado = argumentos.get("barrio", "")
            barrio = adivinar_barrio(barrio_solicitado) or barrio_solicitado
            activos = [r for r in reportes
                       if r.get("Sector") == barrio and "Resuelto" not in r.get("Estado", "")]
            criticos = sum(1 for r in activos if "crítico" in r.get("Clasificación", "").lower())
            return {"barrio": barrio, "reportes_activos": len(activos), "criticos": criticos}

        if nombre_funcion == "resumen_general_comuna":
            total = len(reportes)
            return {
                "total": total,
                "pendientes": sum(1 for r in reportes if "Pendiente" in r.get("Estado", "")),
                "en_proceso": sum(1 for r in reportes if "proceso" in r.get("Estado", "")),
                "resueltos": sum(1 for r in reportes if "Resuelto" in r.get("Estado", "")),
                "peso_total_kg": round(sum(float(r.get("Peso (Kg)", 0) or 0) for r in reportes), 1),
            }

        return {"error": f"Función desconocida: {nombre_funcion}"}

    def llamar_ecobot(mensajes_historial: list) -> str:
        ultimo_mensaje = mensajes_historial[-1]["content"] if mensajes_historial else ""
        respuesta_local = router_ecobot(ultimo_mensaje)   # actúa sin gastar Gemini
        if respuesta_local:
            return respuesta_local
        respuesta_faq = _responder_faq_ecobot(ultimo_mensaje)
        if respuesta_faq:
            return respuesta_faq

        SISTEMA_AGENTE = """Eres EcoBot, asistente de EcoCom2 Circular IA (app para reportar \
residuos en la Comuna 2 - Santa Cruz, Medellín). Responde en español, claro y \
breve (máximo 3 oraciones), sin emojis y con tono cercano. Si la pregunta \
depende de datos actuales (estado de un reporte, cantidades, barrios, resumen) \
usa las herramientas y nunca inventes cifras. Pasos para reportar: 1) verificar \
la dirección, 2) tocar el punto en el mapa, 3) elegir Reportar Residuo o Punto \
Crítico, 4) subir la foto (el análisis es automático), 5) publicar. Colores: \
verde = 60% o más reciclable, amarillo = mezcla, rojo = sin valorizar. Si la \
pregunta no es de residuos, redirige con amabilidad."""

        # AHORRO DE TOKENS: respuestas repetidas (sin datos personales ni
        # conversación previa) se reutilizan en vez de volver a pagar a Gemini.
        _cache_resp = _cache_respuestas_bot()
        _clave_cache = _normalizar_txt(ultimo_mensaje)
        _previos = [m for m in mensajes_historial[:-1] if m["role"] == "user"]
        _cacheable = (not _previos) and (not _necesita_herramientas(ultimo_mensaje))
        if _cacheable and _clave_cache in _cache_resp:
            _txt, _ts = _cache_resp[_clave_cache]
            if time.time() - _ts < 6 * 3600:
                return _txt
        if not ecobot_cupo_disponible():
            return ("Has hecho muchas preguntas seguidas. Espera un rato y "
                    "vuelve a intentarlo — mientras tanto, las preguntas rápidas "
                    "de abajo siguen funcionando.")
        if not verificar_gemini_key():
            return ("El asistente con IA no está disponible en este momento "
                    "(falta configuración del administrador). Aquí va la ayuda "
                    "rápida: 1 Verifica dirección 2 Toca el mapa "
                    "3 Sube foto 4 Publica.")
        try:
            # AHORRO: solo los últimos 4 mensajes, sin el saludo inicial, y cada
            # uno recortado (antes se reenviaban 12 mensajes completos).
            _recientes = [m for m in mensajes_historial[1:]][-4:] or mensajes_historial[-1:]
            contenidos = [
                {"role": "model" if m["role"] == "assistant" else "user",
                 "parts": [{"text": m["content"][:350]}]}
                for m in _recientes
            ]
            payload = {
                "systemInstruction": {"parts": [{"text": SISTEMA_AGENTE}]},
                "contents": contenidos,
                # 600: suficiente para 3 oraciones sin dejar que el modelo gaste de más
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 600},
            }
            # Las herramientas pesan cientos de tokens: solo se envían cuando la
            # pregunta realmente necesita datos de la app.
            _usa_herr = _necesita_herramientas(ultimo_mensaje)
            if _usa_herr:
                payload["tools"] = _herramientas_ecobot_definiciones()

            # Hasta 3 rondas de "pregunta → ejecuta función → responde"
            # antes de rendirnos y pedirle a la persona que reformule.
            for _ in range(3):
                data, _modelo_usado, error = _llamar_gemini_con_respaldo(payload, timeout=15)
                if error:
                    return ("No pude conectarme ahora. "
                            "Pasos: 1 Verifica dirección 2 Toca el mapa "
                            "3 Sube foto 4 Publica.")

                partes = data["candidates"][0]["content"]["parts"]
                llamadas = [p["functionCall"] for p in partes if "functionCall" in p]

                if not llamadas:
                    textos = [p.get("text", "") for p in partes if "text" in p]
                    _resp_final = "\n".join(t for t in textos if t) or "No tengo una respuesta clara para eso."
                    if _cacheable and textos:
                        _cache_resp[_clave_cache] = (_resp_final, time.time())
                    return _resp_final

                # Anexamos el turno del modelo (con sus llamadas) y
                # ejecutamos cada función localmente contra los datos
                # reales de la app.
                payload["contents"].append({"role": "model", "parts": partes})
                partes_respuesta_funciones = []
                for llamada in llamadas:
                    resultado = _ejecutar_herramienta_ecobot(
                        llamada["name"], llamada.get("args", {}) or {})
                    partes_respuesta_funciones.append({
                        "functionResponse": {"name": llamada["name"], "response": resultado}
                    })
                payload["contents"].append({"role": "user", "parts": partes_respuesta_funciones})

            return "Tuve dificultades procesando esa consulta en varios pasos. ¿Puedes reformularla?"
        except Exception:
            return ("Sin conexión al asistente. "
                    "Pasos: 1 Verifica dirección 2 Toca el mapa "
                    "3 Sube foto 4 Publica.")

    # RAPIDEZ: el panel es un "fragmento": al chatear solo se vuelve a dibujar
    # el panel, no toda la página (mapa, formularios, etc.). Antes cada mensaje
    # recargaba todo dos veces.
    @st.fragment
    def _panel_ecobot_fragment():
        def _refrescar_bot():
            """Refresco liviano del panel; completo solo si el bot cambió la página."""
            if st.session_state.pop("bot_accion_global", False):
                st.rerun()
            st.rerun(scope="fragment")

        if st.session_state.agente_pendiente:
            st.session_state.agente_pendiente = False
            with st.spinner("EcoBot está pensando..."):
                respuesta = llamar_ecobot(st.session_state.agente_msgs)
            st.session_state.agente_msgs.append({"role": "assistant", "content": respuesta})
            if st.session_state.pop("bot_accion_global", False):
                st.rerun()          # el bot cambió algo de la página: recarga completa

        with _ecobot_panel():
            _logo_hdr = _logo_b64()
            _img_hdr = (f'<img src="data:image/png;base64,{_logo_hdr}" style="width:46px;height:46px;'
                        f'border-radius:50%;background:#fff;margin-right:10px;vertical-align:middle;">'
                        if _logo_hdr else "")
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#16a34a,#15803d);color:#ffffff;'
                f'border-radius:12px;padding:10px 14px;font-weight:800;font-size:15px;'
                f'margin-bottom:10px;display:flex;align-items:center;">{_img_hdr}'
                f'<div>Hola, soy EcoBot<br><span style="font-weight:400;font-size:12px">'
                f'Escríbeme, háblame o mándame una foto</span></div></div>',
                unsafe_allow_html=True)

            bloque_avisos_bot(_refrescar_bot)

            for msg in st.session_state.agente_msgs[-8:]:
                if msg["role"] == "assistant":
                    with st.chat_message("assistant", avatar=avatar_ecobot()):
                        st.markdown(msg["content"].replace("\n", "  \n"))
                else:
                    with st.chat_message("user"):
                        st.markdown(msg["content"].replace("\n", "  \n"))

            leer_ultima_respuesta_si_corresponde()

            ultimo_usuario = next(
                (m["content"] for m in reversed(st.session_state.agente_msgs) if m["role"] == "user"),
                "")
            if _detectar_intencion_reportar(ultimo_usuario):
                if st.button("Sí, llévame a reportar ahora", key="ecobot_ir_reportar",
                             type="primary", use_container_width=True):
                    st.session_state.seccion = "residuo"
                    st.session_state.ir_a_inicio = True
                    st.rerun()

            def _responder_con_audio(audio_in, texto_extra=""):
                """Transcribe el audio grabado y devuelve el texto (o None si falló)."""
                if not verificar_gemini_key():
                    st.session_state.agente_msgs.append({"role": "assistant", "content":
                        "La entrada por voz necesita la clave de Gemini configurada. "
                        "Puedes escribirme tu mensaje."})
                    return None
                if not ecobot_cupo_disponible():
                    st.session_state.agente_msgs.append({"role": "assistant", "content":
                        "Has enviado muchos mensajes seguidos. Espera un rato e inténtalo de nuevo."})
                    return None
                with st.spinner("Escuchando tu mensaje..."):
                    _texto_aud, _err_aud = transcribir_audio_gemini(
                        audio_in.getvalue(), getattr(audio_in, "type", "audio/wav"))
                if _err_aud or not _texto_aud:
                    st.session_state.agente_msgs.append({"role": "assistant", "content":
                        f"{_err_aud or 'No logré entender el audio.'} Puedes intentarlo "
                        f"de nuevo o escribirme tu mensaje."})
                    return None
                return (texto_extra + " " + _texto_aud).strip()

            if _chat_acepta_audio():
                # Caja de chat con el micrófono pegado al botón de enviar. Sirve
                # igual para escribir que para hablar.
                entrada = st.chat_input("Escribe o toca el micrófono para hablar",
                                        accept_audio=True, key="agente_chat",
                                        max_chars=MAX_LARGO_MENSAJE_BOT)
                if entrada:
                    texto_in = (entrada.text or "").strip()
                    if entrada.audio is not None:
                        texto_in = _responder_con_audio(entrada.audio, texto_in) or ""
                    if texto_in:
                        st.session_state.agente_msgs.append(
                            {"role": "user", "content": texto_in[:MAX_LARGO_MENSAJE_BOT]})
                        st.session_state.agente_pendiente = True
                    _refrescar_bot()
            else:
                # Respaldo para versiones antiguas de Streamlit: formulario y grabadora aparte.
                with st.form("form_agente", clear_on_submit=True, border=False):
                    col_in, col_send = st.columns([4, 2])
                    with col_in:
                        pregunta = st.text_input(
                            "Pregunta:", placeholder="Escribe tu mensaje",
                            key="agente_input", label_visibility="collapsed",
                            max_chars=MAX_LARGO_MENSAJE_BOT)
                    with col_send:
                        enviar = st.form_submit_button("Enviar", type="primary",
                                                       use_container_width=True)
                if enviar and pregunta.strip():
                    st.session_state.agente_msgs.append(
                        {"role": "user", "content": pregunta.strip()[:MAX_LARGO_MENSAJE_BOT]})
                    st.session_state.agente_pendiente = True
                    _refrescar_bot()
                if verificar_gemini_key():
                    _n_aud = st.session_state.get("bot_audio_n", 0)
                    st.caption("Prefieres hablar: toca el micrófono, di tu mensaje y detén la grabación.")
                    audio_bot = st.audio_input("Hablar con EcoBot", key=f"agente_audio_{_n_aud}",
                                               label_visibility="collapsed")
                    if audio_bot is not None:
                        _h_aud = hashlib.md5(audio_bot.getvalue()).hexdigest()
                        if _h_aud != st.session_state.get("bot_audio_hash"):
                            st.session_state.bot_audio_hash = _h_aud
                            _t = _responder_con_audio(audio_bot)
                            if _t:
                                st.session_state.agente_msgs.append({"role": "user", "content": _t})
                                st.session_state.agente_pendiente = True
                            st.session_state.bot_audio_n = _n_aud + 1   # limpia la grabadora
                            _refrescar_bot()

            # ---- Leer en voz alta (accesibilidad): siempre visible, vale para escribir y hablar ----
            def _al_cambiar_voz():
                activo = bool(st.session_state.get("bot_voz_salida"))
                st.session_state._voz_cookie_pendiente = "1" if activo else "0"
                if activo:
                    st.session_state._voz_confirmar = True

            if "bot_voz_salida" not in st.session_state:   # recuerda la preferencia entre visitas
                try:
                    st.session_state.bot_voz_salida = (st.context.cookies.get("ecocom2_voz") == "1")
                except Exception:
                    st.session_state.bot_voz_salida = False
            col_voz, col_rep = st.columns([3, 2])
            with col_voz:
                st.toggle("Leer las respuestas en voz alta", key="bot_voz_salida",
                          on_change=_al_cambiar_voz,
                          help="Para personas con baja visión: EcoBot lee cada respuesta, "
                               "ya sea que escribas o hables. Se recuerda en este navegador.")
            with col_rep:
                if st.session_state.get("bot_voz_salida"):
                    if st.button("Repetir", key="bot_repetir_voz", use_container_width=True,
                                 help="Vuelve a leer la última respuesta"):
                        _ultima_resp = next((m["content"] for m in reversed(st.session_state.agente_msgs)
                                             if m["role"] == "assistant"), "")
                        if _ultima_resp:
                            reproducir_respuesta(_ultima_resp)
            _voz_cookie = st.session_state.pop("_voz_cookie_pendiente", None)
            if _voz_cookie is not None:
                _escribir_cookie("ecocom2_voz", _voz_cookie, 31536000)
            if st.button("Limpiar conversación", key="agente_limpiar", use_container_width=True):
                st.session_state.agente_msgs = [st.session_state.agente_msgs[0]]
                st.session_state.bot_ultimo_leido = _marca_msgs(st.session_state.agente_msgs)
                _refrescar_bot()

            st.markdown("---")
            renderizar_foto_ecobot()
            st.markdown("---")
            preguntas_rapidas = [
                "¿Cómo van mis reportes?",
                "¿Cuándo pasa el camión?",
                "¿Cómo reporto basura?",
                "¿Qué significa rojo?",
                "¿Qué significa amarillo?",
                "¿Qué significa verde?",
                "¿Cómo verifico mi dirección?",
                "¿Para qué sirve la IA?",
                "¿Cómo sé si ya se resolvió?",
                "¿Cómo confirmo que sigue ahí?",
                "Veo un reporte falso, ¿qué hago?",
                "¿Cuántos reportes puedo hacer?",
            ]
            with st.expander("Preguntas rápidas"):
                for idx_pq, pq in enumerate(preguntas_rapidas):
                    if st.button(pq, key=f"pq_{idx_pq}", use_container_width=True):
                        st.session_state.agente_msgs.append({"role": "user", "content": pq})
                        st.session_state.agente_pendiente = True
                        _refrescar_bot()

    _panel_ecobot_fragment()


# ====================================================================
# 8. INICIO Y MAPA
# ====================================================================
if menu == "Inicio y Mapa":
    st.title("EcoCom2 Circular IA")
    st.caption("Gestión inteligente de residuos — Solo residentes de la **Comuna 2** pueden publicar reportes.")

    # --- Tutorial: solo la primera vez ---
    if not st.session_state.get("_tut_cookie_leida"):
        st.session_state._tut_cookie_leida = True
        try:
            if st.context.cookies.get("ecocom2_tutorial") == "1":
                st.session_state.tutorial_visto = True      # ya lo vio en otra visita
        except Exception:
            pass
    if st.session_state.get("validado") and not st.session_state.get("_tut_auto_cerrado"):
        st.session_state._tut_auto_cerrado = True            # ya verificó: ya sabe cómo se usa
        st.session_state.tutorial_visto = True
        st.session_state.guardar_cookie_tutorial = True
    if st.session_state.pop("guardar_cookie_tutorial", False):
        _guardar_cookie_tutorial()

    if not st.session_state.get("tutorial_visto", False):
        mostrar_tutorial()

    # --- Horario del camión: UN solo lugar, justo después de verificar la dirección ---
    _b_hor = barrio_para_horario()
    if _b_hor:
        (st.success if dias_para_proximo_paso(_b_hor) == 0 else st.info)(mensaje_horario(_b_hor))
        st.caption("Horario oficial por barrio (Emvarias). En calles angostas o de difícil "
                   "acceso la franja puede ajustarse.")
    with st.expander("No es mi barrio / ver horarios de todos los barrios" if _b_hor
                     else "Horarios de recolección por barrio"):
        _opciones_b = ["(elige tu barrio)"] + list(HORARIOS_RECOLECCION.keys())
        _sel_b = st.selectbox("Mi barrio:", _opciones_b,
                              index=_opciones_b.index(_b_hor) if _b_hor else 0,
                              key=f"barrio_horario_sel_{_b_hor}")
        if _sel_b != "(elige tu barrio)" and _sel_b != _b_hor:
            recordar_barrio(_sel_b)
            st.session_state.click_barrio = _sel_b
            st.rerun()
        mostrar_horarios_recoleccion(con_cierre=False)

    dir_auto = st.session_state.get("click_dir") or st.session_state.get("direccion") or ""

    _acepta = datos_ubicacion_aceptados()
    if not _acepta:
        with st.container(border=True):
            st.markdown("**Antes de verificar tu ubicación**")
            st.caption(
                "EcoCom2 usa tu ubicación (GPS o la dirección que escribas) solo para comprobar "
                "que estás en la Comuna 2 y ubicar tu reporte en el mapa. Para mostrar la "
                "dirección se consulta el servicio público OpenStreetMap (Nominatim). Puedes "
                "retirar tu autorización cuando quieras desde el menú, en \"Más opciones\". "
                "Detalles y derechos: Información, Aviso de Tratamiento de Datos Personales "
                "(Ley 1581 de 2012).")
            if st.checkbox("Acepto el tratamiento de mis datos de ubicación únicamente para "
                           "fines de validación comunitaria.", key="chk_habeas"):
                st.session_state.acepta_datos_ubicacion = True
                st.session_state._habeas_cookie_escribir = True
                st.rerun()

    if st.button("Usar mi ubicación (GPS)", key="btn_gps",
                 type="primary", use_container_width=True, disabled=not _acepta):
        st.session_state.gps_solicitado = True

    with st.expander("¿No tienes GPS o prefieres escribir tu dirección?"):
        with st.form(key="form_direccion", clear_on_submit=False):
            c_inp, c_btn = st.columns([5, 1])
            with c_inp:
                dir_inp = st.text_input(
                    "Dirección:",
                    value=dir_auto,
                    placeholder="Ej. Cra 50 #107-62, Andalucía",
                    label_visibility="collapsed",
                    key="dir_campo",
                )
            with c_btn:
                verificar_clicked = st.form_submit_button(
                    "Verificar", type="primary", use_container_width=True)
            st.caption("También puedes tocar directamente el mapa de abajo.")

        if verificar_clicked:
            if not _acepta:
                st.warning("Marca primero la casilla de autorización de datos de ubicación.")
            elif dir_inp.strip():
                with st.spinner("Buscando..."):
                    candidatos = geocodificar(dir_inp.strip())
                if len(candidatos) == 1:
                    lat, lon, addr = candidatos[0]
                    set_ubicacion(lat, lon, addr)
                    st.session_state.dir_candidatos = None
                    st.rerun()
                elif len(candidatos) > 1:
                    st.session_state.dir_candidatos = candidatos
                    st.rerun()
                else:
                    st.session_state.dir_candidatos = None
                    st.error(
                        "No encontré esa dirección. Prueba:\n\n"
                        "- Sin el número de casa (ej. 'Carrera 50, Andalucía')\n"
                        "- Solo el nombre del barrio (ej. 'Andalucía, Medellín')\n"
                        "- O usa GPS / toca directamente el mapa de abajo — "
                        "en varias calles de la Comuna 2 esa es la forma más confiable."
                    )
            else:
                st.warning("Escribe o toca el mapa para obtener una dirección.")

        if st.session_state.get("dir_candidatos"):
            st.markdown("**Encontré varias coincidencias — ¿cuál es la correcta?**")
            opciones = [c[2] for c in st.session_state.dir_candidatos]
            sel = st.radio("Elige la dirección correcta:", opciones,
                           key="dir_candidato_sel", label_visibility="collapsed")
            if st.button("Usar esta dirección", type="primary", key="confirmar_candidato"):
                idx = opciones.index(sel)
                lat, lon, addr = st.session_state.dir_candidatos[idx]
                set_ubicacion(lat, lon, addr)
                st.session_state.dir_candidatos = None
                st.rerun()

    if st.session_state.get("gps_solicitado"):
        with st.spinner("Obteniendo tu ubicación (acepta el permiso del navegador)..."):
            loc = get_geolocation()

        if loc is None:
            pass
        elif loc.get("error"):
            st.session_state.gps_solicitado = False
            cod_err = loc["error"].get("code")
            msg = "No pudimos obtener tu ubicación."
            if cod_err == 1:
                msg = "Permiso de ubicación denegado. Actívalo en tu navegador si quieres usar esta opción."
            elif cod_err == 2:
                msg = "Ubicación no disponible en este dispositivo."
            elif cod_err == 3:
                msg = "Se agotó el tiempo de espera obteniendo tu ubicación."
            st.warning(msg + " Busca tu dirección manualmente o toca el mapa.")
        else:
            coords = loc.get("coords", {})
            glat, glon = coords.get("latitude"), coords.get("longitude")
            clave_gps = f"{glat:.6f},{glon:.6f}" if glat is not None else None
            if clave_gps and clave_gps != st.session_state.get("gps_procesado"):
                st.session_state.gps_procesado = clave_gps
                st.session_state.gps_lat = glat
                st.session_state.gps_lon = glon
                st.session_state.gps_solicitado = False
                dentro_gps = POLIGONO_COMUNA2.contains(Point(glon, glat))
                if dentro_gps:
                    with st.spinner("Estás dentro de la Comuna 2 — verificando dirección..."):
                        dir_gps, barrio_gps = geocodificar_inversa(glat, glon)
                    set_ubicacion(glat, glon, dir_gps)
                    st.session_state.click_barrio = barrio_gps
                    st.session_state.click_lat = glat
                    st.session_state.click_lon = glon
                    st.session_state.click_dir = dir_gps
                    st.success(f"¡Verificado por GPS! Estás en: {dir_gps}")
                else:
                    st.warning(
                        "Tu GPS indica que estás **fuera** de la Comuna 2. "
                        "Puedes ver tu posición en el mapa (pin morado), pero para "
                        "reportar necesitas buscar tu dirección o tocar el punto "
                        "manualmente dentro del área piloto."
                    )
                st.rerun()

    if st.session_state.validado:
        if not st.session_state.fuera:
            badge(f"<b>Dentro de la Comuna 2</b> — {esc(st.session_state.direccion[:80])}", "ok")
        else:
            badge(f"Fuera de la Comuna 2 — {esc(st.session_state.direccion[:70])}<br>"
                  f"<span style='font-weight:normal;font-size:12px'>"
                  f"Puedes usar el analizador de materiales, pero no publicar reportes.</span>", "err")
        if st.button("Cambiar dirección", key="cambiar_dir"):
            for k in _CLAVES_UBICACION:
                st.session_state.pop(k, None)
            st.rerun()

    st.markdown("---")
    st.markdown("### Toca el punto exacto del residuo en el mapa")
    st.caption("Al tocar, la dirección aparece automáticamente arriba y puedes reportar directo.")

    vista_mapa = st.radio(
        "Vista del mapa:", ["Puntos individuales", "Mapa de calor"],
        horizontal=True, key="vista_mapa_principal",
        help="El mapa de calor te ayuda a ver de un vistazo las zonas con más "
             "problemas, sin tener que contar puntos uno por uno."
    )

    lat_c = st.session_state.get("lat") or st.session_state.get("gps_lat") or LAT_C
    lon_c = st.session_state.get("lon") or st.session_state.get("gps_lon") or LON_C

    mapa = folium.Map(location=[lat_c, lon_c], zoom_start=14, tiles="OpenStreetMap")

    coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
    folium.Polygon(
        locations=coords_p, color="#4ade80", weight=2,
        fill=True, fill_color="#4ade80", fill_opacity=0.07,
        tooltip="Área piloto — Comuna 2 Santa Cruz (Acevedo → Villa del Socorro)"
    ).add_to(mapa)

    def _mismo_punto(a, b, tol=0.00003):
        return (a[0] is not None and b[0] is not None
                and abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol)

    _lat_home = st.session_state.get("lat")
    _lon_home = st.session_state.get("lon")
    _clat_ss  = st.session_state.get("click_lat")
    _clon_ss  = st.session_state.get("click_lon")
    _glat_ss  = st.session_state.get("gps_lat")
    _glon_ss  = st.session_state.get("gps_lon")

    if st.session_state.get("validado") and _lat_home:
        col_pin = "blue" if not st.session_state.fuera else "gray"
        folium.Marker(
            location=[_lat_home, _lon_home],
            popup=f"{esc(st.session_state.direccion)}",
            tooltip="Tu dirección verificada",
            icon=folium.Icon(color=col_pin, icon="home", prefix="fa")
        ).add_to(mapa)

    if _clat_ss and not _mismo_punto((_clat_ss, _clon_ss), (_lat_home, _lon_home)):
        folium.Marker(
            location=[_clat_ss, _clon_ss],
            popup=f"{esc(st.session_state.get('click_dir','Punto seleccionado'))}",
            tooltip="Punto seleccionado",
            icon=folium.Icon(color="red", icon="map-marker", prefix="fa")
        ).add_to(mapa)

    if (_glat_ss
            and not _mismo_punto((_glat_ss, _glon_ss), (_lat_home, _lon_home))
            and not _mismo_punto((_glat_ss, _glon_ss), (_clat_ss, _clon_ss))):
        folium.Marker(
            location=[_glat_ss, _glon_ss],
            popup="Tu posición GPS actual",
            tooltip="Tu ubicación en tiempo real",
            icon=folium.Icon(color="purple", icon="crosshairs", prefix="fa")
        ).add_to(mapa)

    if vista_mapa == "Mapa de calor":
        PESO_CALOR = {"rojo": 1.0, "amarillo": 0.6, "verde": 0.3}
        datos_calor = []
        for rep in st.session_state.reportes:
            niv = rep.get("Clasificación", "")
            p = PESO_CALOR[semaforo(niv)]
            if "Resuelto" in rep.get("Estado", ""):
                p *= 0.25  # los resueltos casi no pesan, pero no desaparecen del mapa
            if rep.get("Lat") is not None and rep.get("Lon") is not None:
                datos_calor.append([rep["Lat"], rep["Lon"], p])
        if datos_calor:
            HeatMap(datos_calor, radius=24, blur=20, max_zoom=16,
                    gradient={0.2: "#4ade80", 0.5: "#fbbf24", 0.8: "#f87171", 1.0: "#dc2626"}
                    ).add_to(mapa)
        else:
            st.info("Aún no hay reportes para mostrar en el mapa de calor.")
        st.caption("Zonas rojas = más puntos críticos concentrados. Los reportes "
                   "ya resueltos pesan mucho menos, así que no distorsionan el mapa.")
    else:
        for rep in st.session_state.reportes:
            niv = rep.get("Clasificación", "")
            col = {"rojo": "red", "amarillo": "orange", "verde": "green"}[semaforo(niv)]
            foto_src_popup = fuente_imagen(rep.get("FotoB64", ""), rep.get("FotoURL", ""))
            img_html = (f'<br><img src="{foto_src_popup}" '
                        f'style="width:180px;border-radius:6px;margin-top:6px;">'
                        if foto_src_popup else "")
            obs_txt = rep.get("Observaciones", "")
            obs_html = f"{esc(obs_txt[:80])}<br>" if obs_txt else ""
            audio_b64 = rep.get("NotaVozB64", "")
            audio_html = (f'<br><audio controls style="width:180px;margin-top:4px;">'
                          f'<source src="data:audio/wav;base64,{solo_b64(audio_b64)}"></audio>'
                          if audio_b64 else "")
            galeria_extra_html = galeria_html(rep.get("FotosExtraB64", ""), ancho_px=60)
            popup_html = (
                f"<div style='font-family:sans-serif;min-width:190px;'>"
                f"<b style='color:{col}'>{esc(niv)}</b><br>"
                f"<b>{esc(rep['Código'])}</b><br>"
                f"{esc(rep['Sector'])}<br>"
                f"{esc(rep.get('Referencia','')[:40])}<br>"
                f"{obs_html}"
                f"{esc(rep['Objetos'])} obj | {esc(rep['Peso (Kg)'])} kg<br>"
                f"{esc(rep.get('Fecha',''))}<br>"
                f"{esc(rep.get('Estado',''))}"
                f"{img_html}{audio_html}{galeria_extra_html}</div>"
            )
            folium.CircleMarker(
                location=[rep["Lat"], rep["Lon"]], radius=12,
                color=col, fill=True, fill_color=col, fill_opacity=0.85,
                popup=folium.Popup(popup_html, max_width=220),
                tooltip=f"{esc(rep['Código'])} — {esc(niv)}"
            ).add_to(mapa)

    mapa_data = st_folium(mapa, width="100%", height=340,
                          returned_objects=["last_clicked"])

    if mapa_data and mapa_data.get("last_clicked") and not datos_ubicacion_aceptados():
        st.warning("Para usar el mapa y reportar, primero marca la casilla de autorización "
                   "de datos de ubicación, arriba en esta pantalla.")
    elif mapa_data and mapa_data.get("last_clicked"):
        clk = mapa_data["last_clicked"]
        lat_clk = round(clk["lat"], 7)
        lon_clk = round(clk["lng"], 7)
        if (lat_clk != st.session_state.get("click_lat") or
                lon_clk != st.session_state.get("click_lon")):
            st.session_state.click_lat = lat_clk
            st.session_state.click_lon = lon_clk
            with st.spinner("Detectando dirección..."):
                dir_obtenida, barrio_obtenido = geocodificar_inversa(lat_clk, lon_clk)
            st.session_state.click_dir = dir_obtenida
            st.session_state.click_barrio = barrio_obtenido
            if not st.session_state.get("validado"):
                set_ubicacion(lat_clk, lon_clk, dir_obtenida)
            st.rerun()

    clat       = st.session_state.get("click_lat")
    clon       = st.session_state.get("click_lon")
    cdir       = st.session_state.get("click_dir", "")
    dentro_clk = POLIGONO_COMUNA2.contains(Point(clon, clat)) if clat else False

    if clat:
        st.markdown("")
        color_card = "#4ade80" if dentro_clk else "#ef4444"
        estado_txt = "Dentro de la Comuna 2" if dentro_clk else "Fuera del área piloto"
        st.markdown(
            f'<div style="background:rgba(16,185,129,0.08);border:1px solid {color_card};'
            f'border-radius:10px;padding:12px 16px;margin-bottom:10px;">'
            f'<span style="color:{color_card};font-weight:bold;font-size:14px;">{esc(cdir)}</span><br>'
            f'<span style="color:#9ca3af;font-size:12px;">{estado_txt} · {clat:.5f}, {clon:.5f}</span>'
            f'</div>',
            unsafe_allow_html=True)

        if dentro_clk and es_residente():
            st.session_state.punto_para_reporte = {
                "lat": clat, "lon": clon, "dir": cdir
            }
            if st.button("Quitar punto seleccionado", key="btn_quit"):
                for k in ["click_lat","click_lon","click_dir","click_barrio",
                           "cache","punto_para_reporte"]:
                    st.session_state.pop(k, None)
                st.rerun()
        elif clat and not es_residente():
            badge("Verifica tu dirección arriba para reportar en este punto.", "warn")

    st.markdown("")
    st.markdown("")
    seccion = st.session_state.get("seccion", "info")

    nav_tabs(seccion, puede_reportar=bool(es_residente() and clat and dentro_clk))
    st.markdown("")

    if seccion == "info":
        pass  # la guía de pasos ya aparece arriba, junto a los botones

    # ── SECCIÓN: Reportar Residuo ──────────────────────────────────────
    elif seccion == "residuo":
        st.markdown("### Reportar Residuo")

        _paso_r = 1
        if es_residente(): _paso_r = 2
        if clat and dentro_clk: _paso_r = 3
        if st.session_state.get("cache"): _paso_r = 4
        progreso_pasos(_paso_r)
        st.markdown("")

        if not es_residente():
            badge("Verifica tu dirección para reportar.", "warn")
        elif not clat or not dentro_clk:
            badge("Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"{esc(pdir)}", "ok")

            r1, r2 = st.columns(2)
            with r1:
                _barrio_sugerido = st.session_state.get("click_barrio")
                r_barrio = st.selectbox(
                    "Barrio:", BARRIOS,
                    index=BARRIOS.index(_barrio_sugerido) if _barrio_sugerido in BARRIOS else 0,
                    key="r_barrio"
                )
                if _barrio_sugerido:
                    st.caption(f"Detectado automáticamente: {_barrio_sugerido} · puedes cambiarlo si no es correcto")
                if r_barrio != barrio_para_horario():   # si es el mismo, ya se mostró arriba
                    st.caption(mensaje_horario(r_barrio))
            with r2:
                r_ref = st.text_input("Referencia (edita si quieres):",
                                      value=pdir, key="r_ref", max_chars=200)
                r_codigo = campo_codigo_residente("r_codigo_residente")

            r_obs = st.text_area(
                "Observaciones por texto (opcional):",
                placeholder="Describe lo que ves en la foto: hace cuánto está ahí, "
                            "si bloquea el paso, olores, riesgos, etc.",
                key="r_obs", height=80, max_chars=MAX_LARGO_TEXTO_LIBRE,
                value=st.session_state.get("prefill_obs", ""),
            )
            r_audio = st.audio_input("O deja solo una nota de voz:", key="r_audio")
            if r_audio:
                st.caption("Nota de voz grabada — se guardará junto con el reporte.")

            r_imgs = st.file_uploader(
                "Foto(s) del residuo (hasta 3, ej. distintos ángulos):",
                type=["jpg","jpeg","png"], key="r_imgs",
                accept_multiple_files=True)
            st.caption("Evita incluir personas en la foto. Si aparecen, las "
                       "difuminamos automáticamente antes de publicar. "
                       "Las fotos se reducen de tamaño automáticamente; si tienes pocos "
                       "datos, toma la foto en resolución media desde los ajustes de tu cámara.")

            img = None
            r_imgs_extra_pil = []
            r_imgs = filtrar_fotos_validas(r_imgs)
            if r_imgs:
                if len(r_imgs) > 3:
                    st.warning("Solo se usarán las primeras 3 fotos que subiste.")
                    r_imgs = r_imgs[:3]

                if len(r_imgs) == 1:
                    img = _abrir_img_subida(r_imgs[0])
                else:
                    st.caption("Son varias fotos del mismo residuo — elige la que lo "
                               "muestre MEJOR completo. Solo esa la analiza la IA; las "
                               "demás quedan guardadas como evidencia adicional.")
                    cols_mini = st.columns(len(r_imgs))
                    for i, (col_m, f) in enumerate(zip(cols_mini, r_imgs)):
                        with col_m:
                            st.image(_abrir_img_subida(f), use_container_width=True,
                                     caption=f"Foto {i+1}")
                    opciones_ppal = [f"Foto {i+1}" for i in range(len(r_imgs))]
                    sel_ppal = st.radio("Foto principal (la que analiza la IA):",
                                        opciones_ppal, horizontal=True, key="r_sel_ppal")
                    idx_ppal = opciones_ppal.index(sel_ppal)
                    img = _abrir_img_subida(r_imgs[idx_ppal])
                    r_imgs_extra_pil = [_abrir_img_subida(f) for i, f in enumerate(r_imgs)
                                        if i != idx_ppal]

                if img is not None:
                    exif_r = verificar_fecha_exif(img)
                    if exif_r:
                        fecha_foto_r, dias_r = exif_r
                        st.warning(f"Esta foto parece haber sido tomada el "
                                   f"{fecha_foto_r:%d/%m/%Y} — hace {dias_r} días. "
                                   f"Si el residuo ya cambió, sube una foto más reciente.")

            if img is not None:
                r_motor = st.radio(
                    "Motor de clasificación de imagen:",
                    ["Gemini — IA externa (Google Cloud)",
                     "YOLO — IA local del sistema"],
                    key="r_motor_ia", horizontal=True,
                    index=0 if verificar_gemini_key() else 1,
                    help="Gemini es un servicio externo de Google que clasifica por "
                         "categoría de material (Orgánicos, Plásticos, Vidrio, Cartón, "
                         "Papel). YOLO es la IA integrada en el programa: detecta el "
                         "tipo exacto de objeto (botella, silla, etc.) sin depender de "
                         "una conexión externa."
                )
                usar_gemini_r = r_motor.startswith("Gemini")
                if usar_gemini_r and not verificar_gemini_key():
                    st.warning("Gemini no está configurado (falta GEMINI_API_KEY "
                               "en Secrets); se usará YOLO local en su lugar.")
                    usar_gemini_r = False

                # ------------------------------------------------------
                # MEJORA 4 — Análisis automático al subir foto: en vez de
                # esperar a que alguien toque el botón, comparamos un hash
                # de la foto actual contra la última que ya se analizó. Si
                # es una foto nueva, el análisis corre solo. El botón
                # sigue ahí para forzar un reanálisis (ej. si cambian de
                # motor Gemini/YOLO con la misma foto).
                # ------------------------------------------------------
                hash_actual_r = _hash_imagen(img)
                ya_analizada_r = hash_actual_r == st.session_state.get("r_ultimo_hash_analizado")
                disparar_analisis_r = (
                    st.button("Analizar con IA", type="primary",
                             use_container_width=True, key="r_analizar")
                    or not ya_analizada_r
                )

                if disparar_analisis_r:
                    st.session_state.r_ultimo_hash_analizado = hash_actual_r
                    with st.spinner("Analizando imagen..."):
                        # El modelo YOLO local siempre corre, aunque el motor de
                        # clasificación sea Gemini — solo para difuminar personas
                        # y proteger la privacidad, sin importar qué IA clasifica.
                        res = analizar(img)
                        img_blur, hubo_personas_r = difuminar_personas(img, res)

                        reporte_invalido = False
                        motivo_invalido = ""
                        error_g = None

                        if usar_gemini_r:
                            detecciones_g, error_g, es_valido_g, motivo_g = analizar_con_gemini(img_blur)
                            if error_g:
                                st.error(f"No se pudo usar Gemini: {error_g} "
                                         f"Se usó YOLO local en su lugar.")
                                tabla, residuos, peso, tipo, nivel, _ = procesar(res)
                                img_detecciones = dibujar_detecciones_filtradas(img_blur, res)
                            elif es_valido_g is False:
                                reporte_invalido = True
                                motivo_invalido = motivo_g
                                tabla, residuos, peso, tipo, nivel = [], 0, 0.0, "N/D", "Sin residuos detectados"
                                img_detecciones = img_blur
                            else:
                                tabla, residuos, peso, tipo, nivel, _ = procesar_gemini(detecciones_g)
                                img_detecciones = dibujar_detecciones_gemini(img_blur, detecciones_g)
                        else:
                            tabla, residuos, peso, tipo, nivel, _ = procesar(res)
                            img_detecciones = dibujar_detecciones_filtradas(img_blur, res)

                    if reporte_invalido:
                        st.error(
                            f"**Esta foto no parece mostrar un punto de residuos reales.** "
                            f"{motivo_invalido}\n\nSi crees que es un error, sube una foto "
                            f"donde se vea claramente la acumulación de basura. Los reportes "
                            f"que no correspondan a residuos reales (negocios, viviendas, "
                            f"personas, vehículos) pueden ser eliminados por la administración."
                        )
                        st.session_state.cache_analisis_r = None
                    else:
                        st.session_state.cache_analisis_r = {
                            "res_plot": img_detecciones,
                            "tabla": tabla,
                            "residuos": residuos,
                            "peso": peso,
                            "tipo": tipo,
                            "nivel": nivel,
                            "ia_detecto": not (residuos == 0 and len(tabla) == 0),
                            "img_blur": img_blur,
                            "hubo_personas": hubo_personas_r,
                            "motor": "gemini" if (usar_gemini_r and not error_g) else "yolo",
                        }

                if st.session_state.get("cache_analisis_r"):
                    ca = st.session_state.cache_analisis_r
                    img_mostrar = ca.get("img_blur", img)
                    if ca.get("hubo_personas"):
                        st.info("Detectamos personas en la foto y las difuminamos "
                                 "automáticamente antes de guardarla, para proteger su privacidad.")
                    co, cd = st.columns(2)
                    with co:
                        st.markdown("**Original**")
                        st.image(img_mostrar, use_container_width=True)
                    with cd:
                        st.markdown("**Detecciones IA**")
                        st.image(ca["res_plot"], use_container_width=True)

                    if ca["tabla"]:
                        mostrar_explicacion_ia(ca["tabla"], ca["nivel"], ca["peso"], ca.get("motor", "yolo"))
                        df_t = pd.DataFrame(ca["tabla"])
                        df_si = df_t[df_t["Reciclable"] == "Sí"]
                        df_no = df_t[df_t["Reciclable"] == "No"]
                        if not df_si.empty:
                            st.markdown("**Reciclables:**")
                            st.dataframe(df_si, use_container_width=True, hide_index=True)
                        if not df_no.empty:
                            st.markdown("**No aprovechables:**")
                            st.dataframe(df_no, use_container_width=True, hide_index=True)

                    img_foto_final = img_mostrar
                    residuos_f, peso_f, tipo_f, nivel_f = (
                        ca["residuos"], ca["peso"], ca["tipo"], ca["nivel"])

                    if not ca["ia_detecto"]:
                        if ca.get("motor") == "gemini":
                            st.warning(
                                "Gemini no logró separar objetos individuales en esta "
                                "foto (pasa con montones muy homogéneos o mezclados, donde "
                                "es difícil distinguir un objeto de otro). Clasifica manualmente:"
                            )
                        else:
                            st.warning(
                                "YOLO no reconoció objetos específicos. "
                                "Esto ocurre con escombros, basura mezclada o bolsas oscuras. "
                                "Clasifica manualmente:"
                            )
                        tipo_manual = st.selectbox(
                            "¿Qué tipo de residuo observas en la imagen?",
                            [
                                "Escombros / Residuos de construcción",
                                "Basura doméstica mezclada / bolsas",
                                "Residuos orgánicos (comida, vegetación)",
                                "Materiales reciclables sin identificar",
                                "Mezcla de varios tipos",
                            ],
                            key="r_tipo_manual"
                        )
                        cant_manual = st.slider(
                            "Cantidad aproximada de residuos visibles:",
                            1, 20, 5, key="r_cant_manual"
                        )
                        MAP_MANUAL = {
                            "Escombros / Residuos de construcción":
                                ("Punto crítico — Acumulación sin valorización",
                                 "Escombros", round(cant_manual * 5.0, 1)),
                            "Basura doméstica mezclada / bolsas":
                                ("Punto crítico — Acumulación sin valorización",
                                 "Residuo mixto", round(cant_manual * 0.5, 1)),
                            "Residuos orgánicos (comida, vegetación)":
                                ("Punto amarillo — Residuos mixtos",
                                 "Orgánico", round(cant_manual * 0.3, 1)),
                            "Materiales reciclables sin identificar":
                                ("Punto verde — Alta valorización reciclable",
                                 "Reciclable", round(cant_manual * 0.4, 1)),
                            "Mezcla de varios tipos":
                                ("Punto amarillo — Residuos mixtos",
                                 "Mixto", round(cant_manual * 1.0, 1)),
                        }
                        nivel_f, tipo_f, peso_f = MAP_MANUAL[tipo_manual]
                        residuos_f = cant_manual if "reciclable" in tipo_manual.lower() else 0
                        if semaforo(nivel_f) == "rojo":
                            img_foto_final = marcar_zona_critica(img_mostrar)
                            st.caption("La foto se marcará con un aviso de zona crítica "
                                       "para que el administrador la identifique fácil en el mapa.")
                        metricas(residuos_f, peso_f, nivel_f)
                    else:
                        metricas(residuos_f, peso_f, nivel_f)

                    st.session_state.cache = {
                        "Código":        generar_codigo("REP", 200),
                        "Sector":        r_barrio,
                        "Referencia":    limpiar_texto_libre(r_ref, 200),
                        "Objetos":       residuos_f,
                        "Peso (Kg)":     peso_f,
                        "Predominante":  tipo_f,
                        "Clasificación": nivel_f,
                        "Lat": plat, "Lon": plon,
                        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        "Estado": "Pendiente",
                        "FotoB64": img_a_b64(img_foto_final),
                        "FotoClasificadaB64": img_a_b64(ca["res_plot"], max_px=350),
                        "Observaciones": limpiar_texto_libre(r_obs),
                        "NotaVozB64": audio_a_b64(r_audio),
                        "FotosExtraB64": fotos_extra_a_json(r_imgs_extra_pil),
                        "CodigoResidente": r_codigo,
                        "PHash": calcular_phash(img_mostrar),
                        "Confirmaciones": 0,
                    }
                    buf_foto_full = BytesIO()
                    img_foto_final.convert("RGB").save(buf_foto_full, format="JPEG", quality=82)
                    st.session_state.cache_foto_bytes = buf_foto_full.getvalue()
                    buf_clasif_full = BytesIO()
                    ca["res_plot"].convert("RGB").save(buf_clasif_full, format="JPEG", quality=82)
                    st.session_state.cache_foto_clasif_bytes = buf_clasif_full.getvalue()

            if st.session_state.get("cache"):
                r = st.session_state.cache
                st.markdown(f"**Listo:** {r['Clasificación']} · {r['Objetos']} reciclables · {r['Peso (Kg)']} kg")
                if r.get("Observaciones"):
                    st.markdown(f"**Observaciones:** {r['Observaciones']}")
                if r.get("NotaVozB64"):
                    st.markdown("**Nota de voz adjunta:**")
                    st.audio(base64.b64decode(r["NotaVozB64"]), format="audio/wav")
                if r.get("FotosExtraB64"):
                    st.markdown(galeria_html(r["FotosExtraB64"]), unsafe_allow_html=True)

                ok_limite_r = verificar_limite_reportes(r_codigo)
                foto_recic_r = buscar_foto_reciclada(r["Lat"], r["Lon"], r.get("PHash", ""))
                if foto_recic_r:
                    ok_publicar_r = aviso_foto_reciclada(foto_recic_r)
                else:
                    dup_r = buscar_posible_duplicado(r["Lat"], r["Lon"], r.get("PHash", ""))
                    ok_publicar_r = aviso_duplicado(dup_r, "r_confirmar_duplicado")
                ok_publicar_r = ok_publicar_r and ok_limite_r

                cp, cc = st.columns(2)
                with cp:
                    if st.button("PUBLICAR EN EL MAPA", type="primary",
                                 use_container_width=True, key="r_publicar",
                                 disabled=not ok_publicar_r):
                        r["Código"] = generar_codigo("REP", 200)  # por si otra sesión tomó este número
                        with st.spinner("Guardando copia permanente de las fotos..."):
                            url_o, _ = subir_foto_evidencia_github(
                                st.session_state.get("cache_foto_bytes", b""),
                                f"{r['Código']}.jpg", carpeta="evidencias_reportes")
                            if url_o:
                                r["FotoURL"] = url_o
                            url_c, _ = subir_foto_evidencia_github(
                                st.session_state.get("cache_foto_clasif_bytes", b""),
                                f"{r['Código']}.jpg", carpeta="evidencias_clasificadas")
                            if url_c:
                                r["FotoClasificadaURL"] = url_c
                        st.session_state.reportes.append(r)
                        st.session_state.mis_codigos.append(r["Código"])
                        st.session_state.mis_estados_vistos[r["Código"]] = r["Estado"]
                        st.session_state.reportes_hoy_sesion = st.session_state.get("reportes_hoy_sesion", 0) + 1
                        guardar_reportes_disco(st.session_state.reportes)
                        st.session_state.cache = None
                        st.session_state.cache_analisis_r = None
                        st.session_state.cache_foto_bytes = None
                        st.session_state.cache_foto_clasif_bytes = None
                        limpiar_prefill_bot()
                        st.session_state.seccion = "historial"
                        for k in ["click_lat","click_lon","click_dir","click_barrio"]:
                            st.session_state.pop(k, None)
                        st.success("¡Publicado! Guardado permanentemente en el mapa.")
                        st.rerun()
                with cc:
                    if st.button("Cancelar", use_container_width=True, key="r_cancelar"):
                        st.session_state.cache = None
                        st.session_state.cache_analisis_r = None
                        st.session_state.cache_foto_bytes = None
                        st.session_state.cache_foto_clasif_bytes = None
                        st.rerun()

    # ── SECCIÓN: Punto Crítico ─────────────────────────────────────────
    elif seccion == "critico":
        st.markdown("### Registrar Punto Crítico")

        _paso_c = 1
        if es_residente(): _paso_c = 2
        if clat and dentro_clk: _paso_c = 3
        if st.session_state.get("cache_critico"): _paso_c = 4
        progreso_pasos(_paso_c, labels=["Dirección", "Punto en mapa", "Foto", "Registrar"])
        st.markdown("")

        if not es_residente():
            badge("Verifica tu dirección para registrar alertas.", "warn")
        elif not clat or not dentro_clk:
            badge("Selecciona un punto dentro de la Comuna 2 en el mapa.", "warn")
        else:
            plat = clat; plon = clon; pdir = cdir
            badge(f"{esc(pdir)}", "err")

            cr1, cr2 = st.columns(2)
            with cr1:
                _barrio_sugerido_cr = st.session_state.get("click_barrio")
                cr_barrio = st.selectbox(
                    "Barrio:", BARRIOS,
                    index=BARRIOS.index(_barrio_sugerido_cr) if _barrio_sugerido_cr in BARRIOS else 0,
                    key="cr_barrio"
                )
                if _barrio_sugerido_cr:
                    st.caption(f"Detectado automáticamente: {_barrio_sugerido_cr} · puedes cambiarlo si no es correcto")
            with cr2:
                cr_ref = st.text_input("Referencia:", value=pdir, key="cr_ref", max_chars=200)
                cr_codigo = campo_codigo_residente("cr_codigo_residente")

            cr_obs = st.text_area(
                "Observaciones por texto (opcional):",
                placeholder="Describe la acumulación: hace cuánto está ahí, si genera "
                            "olores, si bloquea el paso, riesgos para la salud, etc.",
                key="cr_obs", height=80, max_chars=MAX_LARGO_TEXTO_LIBRE,
                value=st.session_state.get("prefill_obs", ""),
            )
            cr_audio = st.audio_input("O deja solo una nota de voz:", key="cr_audio")
            if cr_audio:
                st.caption("Nota de voz grabada — se guardará junto con la alerta.")

            cr_imgs = st.file_uploader(
                "Foto(s) del punto crítico (hasta 3 ángulos del mismo montón):",
                type=["jpg","jpeg","png"], key="cr_imgs",
                accept_multiple_files=True)
            st.caption("Evita incluir personas en la foto. Si aparecen, las "
                       "difuminamos automáticamente antes de publicar. "
                       "Las fotos se reducen de tamaño automáticamente; si tienes pocos "
                       "datos, toma la foto en resolución media desde los ajustes de tu cámara.")

            img2 = None
            cr_imgs_extra_pil = []
            cr_imgs = filtrar_fotos_validas(cr_imgs)
            if cr_imgs:
                if len(cr_imgs) > 3:
                    st.warning("Solo se usarán las primeras 3 fotos que subiste.")
                    cr_imgs = cr_imgs[:3]

                if len(cr_imgs) == 1:
                    img2 = _abrir_img_subida(cr_imgs[0])
                else:
                    st.caption("Son varios ángulos del MISMO montón — elige la foto "
                               "que mejor muestre toda la acumulación completa. Solo esa "
                               "la analiza la IA (así no se cuentan los mismos objetos "
                               "varias veces); las demás quedan como evidencia adicional.")
                    cols_mini2 = st.columns(len(cr_imgs))
                    for i, (col_m, f) in enumerate(zip(cols_mini2, cr_imgs)):
                        with col_m:
                            st.image(_abrir_img_subida(f), use_container_width=True,
                                     caption=f"Foto {i+1}")
                    opciones_ppal2 = [f"Foto {i+1}" for i in range(len(cr_imgs))]
                    sel_ppal2 = st.radio("Foto principal (la que analiza la IA):",
                                         opciones_ppal2, horizontal=True, key="cr_sel_ppal")
                    idx_ppal2 = opciones_ppal2.index(sel_ppal2)
                    img2 = _abrir_img_subida(cr_imgs[idx_ppal2])
                    cr_imgs_extra_pil = [_abrir_img_subida(f) for i, f in enumerate(cr_imgs)
                                         if i != idx_ppal2]

                if img2 is not None:
                    exif_cr = verificar_fecha_exif(img2)
                    if exif_cr:
                        fecha_foto_cr, dias_cr = exif_cr
                        st.warning(f"Esta foto parece haber sido tomada el "
                                   f"{fecha_foto_cr:%d/%m/%Y} — hace {dias_cr} días. "
                                   f"Si la acumulación ya cambió, sube una foto más reciente.")

            if img2 is not None:

                cr_motor = st.radio(
                    "Motor de clasificación de imagen:",
                    ["Gemini — IA externa (Google Cloud)",
                     "YOLO — IA local del sistema"],
                    key="cr_motor_ia", horizontal=True,
                    index=0 if verificar_gemini_key() else 1,
                    help="Gemini es un servicio externo de Google que clasifica por "
                         "categoría de material (Orgánicos, Plásticos, Vidrio, Cartón, "
                         "Papel). YOLO es la IA integrada en el programa: detecta el "
                         "tipo exacto de objeto (botella, silla, etc.) sin depender de "
                         "una conexión externa."
                )
                usar_gemini_cr = cr_motor.startswith("Gemini")
                if usar_gemini_cr and not verificar_gemini_key():
                    st.warning("Gemini no está configurado (falta GEMINI_API_KEY "
                               "en Secrets); se usará YOLO local en su lugar.")
                    usar_gemini_cr = False

                # ------------------------------------------------------
                # MEJORA 4 — Mismo patrón de auto-análisis que en
                # Reportar Residuo, con claves propias de esta sección
                # para no pisar el estado del otro formulario.
                # ------------------------------------------------------
                hash_actual_cr = _hash_imagen(img2)
                ya_analizada_cr = hash_actual_cr == st.session_state.get("cr_ultimo_hash_analizado")
                disparar_analisis_cr = (
                    st.button("Evaluar con IA", type="primary",
                             use_container_width=True, key="cr_analizar")
                    or not ya_analizada_cr
                )

                if disparar_analisis_cr:
                    st.session_state.cr_ultimo_hash_analizado = hash_actual_cr
                    with st.spinner("Analizando imagen en alta resolución..."):
                        # El modelo YOLO local siempre corre, aunque el motor de
                        # clasificación sea Gemini — solo para difuminar personas
                        # y proteger la privacidad, sin importar qué IA clasifica.
                        res2 = analizar(img2, imgsz=960)
                        img2_blur, hubo_personas_cr = difuminar_personas(img2, res2)

                        reporte_invalido_cr = False
                        motivo_invalido_cr = ""
                        error_g2 = None

                        if usar_gemini_cr:
                            detecciones_g2, error_g2, es_valido_g2, motivo_g2 = analizar_con_gemini(img2_blur)
                            if error_g2:
                                st.error(f"No se pudo usar Gemini: {error_g2} "
                                         f"Se usó YOLO local en su lugar.")
                                tabla2, res2_r, peso2, tipo2, nivel2, total2 = procesar(res2)
                                img2_detecciones = dibujar_detecciones_filtradas(img2_blur, res2)
                            elif es_valido_g2 is False:
                                reporte_invalido_cr = True
                                motivo_invalido_cr = motivo_g2
                                tabla2, res2_r, peso2, tipo2, nivel2, total2 = [], 0, 0.0, "N/D", "Sin residuos detectados", 0
                                img2_detecciones = img2_blur
                            else:
                                tabla2, res2_r, peso2, tipo2, nivel2, total2 = procesar_gemini(detecciones_g2)
                                img2_detecciones = dibujar_detecciones_gemini(img2_blur, detecciones_g2)
                        else:
                            tabla2, res2_r, peso2, tipo2, nivel2, total2 = procesar(res2)
                            img2_detecciones = dibujar_detecciones_filtradas(img2_blur, res2)

                    if reporte_invalido_cr:
                        st.error(
                            f"**Esta foto no parece mostrar un punto de residuos reales.** "
                            f"{motivo_invalido_cr}\n\nSi crees que es un error, sube una foto "
                            f"donde se vea claramente la acumulación de basura. Los reportes "
                            f"que no correspondan a residuos reales (negocios, viviendas, "
                            f"personas, vehículos) pueden ser eliminados por la administración."
                        )
                        st.session_state.cache_critico = None
                    else:
                        st.session_state.cache_img_blur = img2_blur
                        st.session_state.hubo_personas_cr = hubo_personas_cr
                        st.session_state.cache_foto_b64 = img_a_b64(img2_blur)
                        st.session_state.cache_foto_clasificada_b64 = img_a_b64(img2_detecciones, max_px=350)
                        st.session_state.cache_phash = calcular_phash(img2_blur)
                        st.session_state.cache_fotos_extra_b64 = fotos_extra_a_json(cr_imgs_extra_pil)

                        buf_foto_full_cr = BytesIO()
                        img2_blur.convert("RGB").save(buf_foto_full_cr, format="JPEG", quality=82)
                        st.session_state.cache_foto_bytes_cr = buf_foto_full_cr.getvalue()
                        buf_clasif_full_cr = BytesIO()
                        img2_detecciones.convert("RGB").save(buf_clasif_full_cr, format="JPEG", quality=82)
                        st.session_state.cache_foto_clasif_bytes_cr = buf_clasif_full_cr.getvalue()

                        if hubo_personas_cr:
                            st.info("Detectamos personas en la foto y las difuminamos "
                                     "automáticamente antes de guardarla, para proteger su privacidad.")

                        co2, cd2 = st.columns(2)
                        with co2:
                            st.markdown("**Original**")
                            st.image(img2_blur, use_container_width=True)
                        with cd2:
                            st.markdown("**Detecciones IA**")
                            st.image(img2_detecciones, use_container_width=True)

                        if tabla2:
                            mostrar_explicacion_ia(tabla2, nivel2, peso2,
                                                   "gemini" if (usar_gemini_cr and not error_g2) else "yolo")
                            df_si2 = pd.DataFrame(tabla2)
                            df_si2 = df_si2[df_si2["Reciclable"] == "Sí"]
                            if not df_si2.empty:
                                st.dataframe(df_si2, use_container_width=True, hide_index=True)

                        st.session_state.cache_critico = {
                            "residuos":    res2_r,
                            "peso":        peso2,
                            "tipo":        tipo2,
                            "nivel":       nivel2,
                            "total":       total2,
                            "ia_detecto":  total2 > 0,
                            "Lat":         plat,
                            "Lon":         plon,
                            "motor":       "gemini" if (usar_gemini_cr and not error_g2) else "yolo",
                        }

                if st.session_state.get("cache_critico"):
                    cc = st.session_state.cache_critico

                    if not cc["ia_detecto"]:
                        if cc.get("motor") == "gemini":
                            st.warning(
                                "Gemini no logró separar objetos individuales en esta "
                                "foto (pasa con montones muy homogéneos o mezclados, donde "
                                "es difícil distinguir un objeto de otro). Clasifica manualmente:"
                            )
                        else:
                            st.warning(
                                "YOLO no reconoció objetos específicos "
                                "(escombros, bolsas oscuras, basura mezclada). "
                                "Clasifica manualmente:"
                            )
                        OPCIONES_MC = [
                            "Escombros / Residuos de construcción",
                            "Basura doméstica mezclada / bolsas",
                            "Residuos orgánicos (comida, vegetación)",
                            "Mezcla de varios tipos",
                        ]
                        tipo_mc = st.selectbox("¿Qué ves en la imagen?",
                                               OPCIONES_MC, key="cr_tipo_manual")
                        cant_mc = st.slider("Cantidad aproximada de residuos:", 1, 30, 8,
                                            key="cr_cant_manual")
                        MAP_MC = {
                            "Escombros / Residuos de construcción":
                                ("Punto crítico — Acumulación sin valorización",
                                 "Escombros", round(cant_mc * 5.0, 1)),
                            "Basura doméstica mezclada / bolsas":
                                ("Punto crítico — Acumulación sin valorización",
                                 "Residuo mixto", round(cant_mc * 0.8, 1)),
                            "Residuos orgánicos (comida, vegetación)":
                                ("Punto amarillo — Residuos mixtos",
                                 "Orgánico", round(cant_mc * 0.3, 1)),
                            "Mezcla de varios tipos":
                                ("Punto crítico — Acumulación sin valorización",
                                 "Mixto", round(cant_mc * 1.5, 1)),
                        }
                        nivel_f, tipo_f, peso_f = MAP_MC[tipo_mc]
                        total_f = cant_mc
                        residuos_f = 0
                        if semaforo(nivel_f) == "rojo":
                            st.session_state.cache_foto_b64 = img_a_b64(
                                marcar_zona_critica(st.session_state.get("cache_img_blur", img2)))
                            st.caption("La foto se marcará con un aviso de zona crítica "
                                       "para que el administrador la identifique fácil en el mapa.")
                    else:
                        nivel_f   = cc["nivel"]
                        tipo_f    = cc["tipo"]
                        peso_f    = cc["peso"]
                        total_f   = cc["total"]
                        residuos_f= cc["residuos"]

                    metricas(residuos_f, peso_f, nivel_f)
                    if cr_obs.strip():
                        st.markdown(f"**Observaciones:** {cr_obs.strip()}")
                    if cr_audio:
                        st.markdown("**Nota de voz adjunta:**")
                        st.audio(cr_audio)
                    if st.session_state.get("cache_fotos_extra_b64"):
                        st.markdown(galeria_html(st.session_state["cache_fotos_extra_b64"]),
                                    unsafe_allow_html=True)

                    ok_limite_cr = verificar_limite_reportes(cr_codigo)
                    foto_recic_cr = buscar_foto_reciclada(
                        cc["Lat"], cc["Lon"], st.session_state.get("cache_phash", ""))
                    if foto_recic_cr:
                        ok_publicar_cr = aviso_foto_reciclada(foto_recic_cr)
                    else:
                        dup_cr = buscar_posible_duplicado(
                            cc["Lat"], cc["Lon"], st.session_state.get("cache_phash", ""))
                        ok_publicar_cr = aviso_duplicado(dup_cr, "cr_confirmar_duplicado")
                    ok_publicar_cr = ok_publicar_cr and ok_limite_cr

                    st.markdown("")
                    cr_pub, cr_can = st.columns(2)
                    with cr_pub:
                        if st.button("REGISTRAR ALERTA EN EL MAPA",
                                     type="primary", use_container_width=True,
                                     key="cr_registrar", disabled=not ok_publicar_cr):
                            nuevo = {
                                "Código":        generar_codigo("CRIT", 500),
                                "Sector":        cr_barrio,
                                "Referencia":    limpiar_texto_libre(cr_ref, 200),
                                "Objetos":       total_f,
                                "Peso (Kg)":     round(peso_f, 2),
                                "Predominante":  tipo_f or "Mixto",
                                "Clasificación": nivel_f,
                                "Lat":           cc["Lat"],
                                "Lon":           cc["Lon"],
                                "Fecha":         datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "Estado":        "Pendiente",
                                "FotoB64": st.session_state.get("cache_foto_b64", ""),
                                "FotoClasificadaB64": st.session_state.get("cache_foto_clasificada_b64", ""),
                                "Observaciones": limpiar_texto_libre(cr_obs),
                                "NotaVozB64": audio_a_b64(cr_audio),
                                "FotosExtraB64": st.session_state.get("cache_fotos_extra_b64", ""),
                                "CodigoResidente": cr_codigo,
                                "PHash": st.session_state.get("cache_phash", ""),
                                "Confirmaciones": 0,
                            }
                            with st.spinner("Guardando copia permanente de las fotos..."):
                                url_o_cr, _ = subir_foto_evidencia_github(
                                    st.session_state.get("cache_foto_bytes_cr", b""),
                                    f"{nuevo['Código']}.jpg", carpeta="evidencias_reportes")
                                if url_o_cr:
                                    nuevo["FotoURL"] = url_o_cr
                                url_c_cr, _ = subir_foto_evidencia_github(
                                    st.session_state.get("cache_foto_clasif_bytes_cr", b""),
                                    f"{nuevo['Código']}.jpg", carpeta="evidencias_clasificadas")
                                if url_c_cr:
                                    nuevo["FotoClasificadaURL"] = url_c_cr
                            st.session_state.reportes.append(nuevo)
                            st.session_state.mis_codigos.append(nuevo["Código"])
                            st.session_state.mis_estados_vistos[nuevo["Código"]] = nuevo["Estado"]
                            st.session_state.reportes_hoy_sesion = st.session_state.get("reportes_hoy_sesion", 0) + 1
                            guardar_reportes_disco(st.session_state.reportes)
                            st.session_state.cache_critico = None
                            st.session_state.cache_fotos_extra_b64 = None
                            st.session_state.cache_phash = None
                            st.session_state.cache_img_blur = None
                            st.session_state.cache_foto_bytes_cr = None
                            st.session_state.cache_foto_clasif_bytes_cr = None
                            limpiar_prefill_bot()
                            st.session_state.seccion = "historial"
                            for k in ["click_lat","click_lon","click_dir","click_barrio"]:
                                st.session_state.pop(k, None)
                            st.success("¡Alerta registrada permanentemente!")
                            st.rerun()
                    with cr_can:
                        if st.button("Cancelar", use_container_width=True,
                                     key="cr_cancelar"):
                            st.session_state.cache_critico = None
                            st.session_state.cache_fotos_extra_b64 = None
                            st.session_state.cache_phash = None
                            st.session_state.cache_img_blur = None
                            st.rerun()

    # ── SECCIÓN: Historial ─────────────────────────────────────────────
    elif seccion == "historial":
        st.markdown("### Mi Historial")
        st.caption("Tus propios reportes. Para ver estadísticas de toda la Comuna 2, "
                   "usa la página **Comuna en Cifras** en el menú de la izquierda.")

        mis_reportes_actuales = [
            r for r in st.session_state.reportes
            if r["Código"] in st.session_state.mis_codigos
        ]
        avisos_cambio = []
        for r in mis_reportes_actuales:
            cod = r["Código"]
            estado_actual = r.get("Estado", "")
            estado_previo = st.session_state.mis_estados_vistos.get(cod)
            if estado_previo is not None and estado_previo != estado_actual:
                avisos_cambio.append((cod, estado_previo, estado_actual, r))
            st.session_state.mis_estados_vistos[cod] = estado_actual

        if avisos_cambio:
            for cod, previo, actual, r in avisos_cambio:
                if "Resuelto" in actual:
                    st.success(
                        f"¡Tu reporte **{cod}** ({r.get('Sector','')}) fue **resuelto**! "
                        f"Gracias por reportarlo — tu acción ayudó a limpiar tu barrio."
                    )
                    msg_logro = (
                        f"¡Reporté un punto de residuos en {r.get('Sector','')} - Comuna 2 "
                        f"con EcoCom2 Circular IA y ya lo resolvieron! Tú también puedes "
                        f"reportar en tu cuadra"
                    )
                    st.markdown(
                        boton_whatsapp_html(link_whatsapp("", msg_logro),
                                             "Compartir este logro"),
                        unsafe_allow_html=True)
                elif "proceso" in actual:
                    st.info(
                        f"Tu reporte **{cod}** ({r.get('Sector','')}) pasó a "
                        f"**en proceso de recolección**. Ya está siendo atendido."
                    )

        busq_codigo = st.text_input(
            "Si reportaste desde otro navegador o dispositivo, busca por "
            "código/teléfono (si lo escribiste al reportar):",
            value=st.session_state.get("mi_codigo_residente", ""),
            key="hist_busqueda_codigo",
            placeholder="Escribe el mismo código/teléfono que usaste al reportar"
        )

        # Freno al "barrido": como el código/teléfono no es una contraseña,
        # alguien podría probar números uno tras otro para ver reportes
        # ajenos. Se cuentan las búsquedas DISTINTAS por sesión y, pasado el
        # límite, se bloquean un rato (no frena a un atacante decidido que
        # abra sesiones nuevas, pero sí al curioso y a los scripts simples).
        _busq_limpia = busq_codigo.strip()
        _ahora_b = time.time()
        _marcas_b = [t for t in st.session_state.get("hist_busq_marcas", [])
                     if _ahora_b - t < 600]
        if (_busq_limpia
                and _busq_limpia != st.session_state.get("mi_codigo_residente", "")
                and _busq_limpia != st.session_state.get("_hist_ultima_busq")):
            _marcas_b.append(_ahora_b)
        st.session_state._hist_ultima_busq = _busq_limpia
        st.session_state.hist_busq_marcas = _marcas_b
        _busq_bloqueada = len(_marcas_b) > 10

        if _busq_bloqueada:
            st.error("Hiciste demasiadas búsquedas distintas seguidas. Espera unos "
                     "minutos para volver a buscar por código/teléfono.")
            reportes_mostrar = mis_reportes_actuales
        elif _busq_limpia:
            reportes_mostrar = [
                r for r in st.session_state.reportes
                if coincide_residente(r.get("CodigoResidente", ""), _busq_limpia)
            ]
        else:
            reportes_mostrar = mis_reportes_actuales

        if reportes_mostrar:
            n_total_mios = len(reportes_mostrar)
            n_resueltos_mios = sum(1 for r in reportes_mostrar if "Resuelto" in r.get("Estado",""))
            n_proceso_mios   = sum(1 for r in reportes_mostrar if "proceso"  in r.get("Estado",""))
            n_pend_mios      = n_total_mios - n_resueltos_mios - n_proceso_mios
            st.markdown(
                f'<div style="background:rgba(74,222,128,0.08);border:1px solid #4ade80;'
                f'border-radius:10px;padding:10px 16px;margin-bottom:10px;font-size:13px;">'
                f'<b>Tus reportes:</b> {n_total_mios} total · '
                f'{n_pend_mios} pendientes · {n_proceso_mios} en proceso · '
                f'{n_resueltos_mios} resueltos'
                f'</div>', unsafe_allow_html=True)

        if not reportes_mostrar:
            if busq_codigo.strip():
                st.info("No encontré reportes con ese código/teléfono. Revisa que esté "
                        "escrito igual a como lo pusiste al reportar.")
            else:
                st.info("Aún no has publicado ningún reporte. Toca el mapa y usa "
                        "'Reportar Residuo' para el primero.")
        else:
            df = pd.DataFrame(reportes_mostrar)

            h1, h2, h3, h4 = st.columns(4)
            pendientes = df.get("Estado", pd.Series([])).str.contains("Pendiente", na=False).sum() if "Estado" in df.columns else len(df)
            resueltos  = df.get("Estado", pd.Series([])).str.contains("Resuelto",  na=False).sum() if "Estado" in df.columns else 0
            crit = df["Clasificación"].str.contains("crítico", case=False, na=False).sum()
            with h1:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{len(df)}</h2><p>Total</p></div>', unsafe_allow_html=True)
            with h2:
                st.markdown(f'<div class="metric-card"><h2 style="color:#f87171">{crit}</h2><p>Críticos</p></div>', unsafe_allow_html=True)
            with h3:
                st.markdown(f'<div class="metric-card"><h2 style="color:#fbbf24">{pendientes}</h2><p>Pendientes</p></div>', unsafe_allow_html=True)
            with h4:
                st.markdown(f'<div class="metric-card"><h2 style="color:#4ade80">{resueltos}</h2><p>Resueltos</p></div>', unsafe_allow_html=True)

            st.markdown("")

            COLS = ["Código","Fecha","Estado","Sector","Referencia",
                    "Objetos","Peso (Kg)","Clasificación","Observaciones"]
            cols_ok = [c for c in COLS if c in df.columns]
            st.dataframe(df[cols_ok], use_container_width=True, hide_index=True)

            excel_mio = generar_excel_reportes(reportes_mostrar, incluir_contacto=False)
            st.download_button(
                "Exportar como Excel",
                data=excel_mio,
                file_name=f"ecocom2_mis_reportes_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        st.markdown("---")
        UMBRAL_REPORTES_FALSOS = 3
        with st.expander("Confirmar reportes activos de la comunidad"):
            st.caption(
                "Si pasaste por alguno de estos puntos y el residuo sigue ahí, "
                "confírmalo — ayuda a la administración a priorizar. Si ves un "
                "reporte que en realidad NO es basura (ej. un negocio o una "
                "vivienda), márcalo como falso. Cada persona solo puede confirmar "
                "o marcar un reporte una vez por sesión."
            )
            activos = [r for r in st.session_state.reportes if "Resuelto" not in r.get("Estado", "")]
            if "confirmados_sesion" not in st.session_state:
                st.session_state.confirmados_sesion = set()
            if "falsos_marcados_sesion" not in st.session_state:
                st.session_state.falsos_marcados_sesion = set()
            if not activos:
                st.info("No hay reportes activos en este momento.")
            for r in activos[-15:][::-1]:
                cod = r["Código"]
                n_falsos = r.get("ReportesFalsos", 0) or 0
                c_info, c_btn, c_btn_falso = st.columns([3, 1, 1.2])
                with c_info:
                    linea_info = (
                        f"**{cod}** · {r.get('Sector','')} · {r.get('Clasificación','')} · "
                        f"{r.get('Confirmaciones', 0)} confirmaciones"
                    )
                    if n_falsos > 0:
                        linea_info += f" · {n_falsos} marcado(s) como falso"
                    if n_falsos >= UMBRAL_REPORTES_FALSOS:
                        linea_info += " — **en revisión por la administración**"
                    st.markdown(linea_info)
                with c_btn:
                    ya_confirmado = cod in st.session_state.confirmados_sesion
                    if st.button("Confirmar", key=f"confirmar_{cod}",
                                 disabled=ya_confirmado, use_container_width=True):
                        for rep in st.session_state.reportes:
                            if rep["Código"] == cod:
                                rep["Confirmaciones"] = rep.get("Confirmaciones", 0) + 1
                                break
                        st.session_state.confirmados_sesion.add(cod)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.rerun()
                with c_btn_falso:
                    ya_marcado_falso = cod in st.session_state.falsos_marcados_sesion
                    if st.button("No es basura", key=f"falso_{cod}",
                                 disabled=ya_marcado_falso, use_container_width=True,
                                 help="Márcalo si esta foto no muestra un residuo real "
                                      "(ej. un negocio, una vivienda, o una persona)."):
                        for rep in st.session_state.reportes:
                            if rep["Código"] == cod:
                                rep["ReportesFalsos"] = rep.get("ReportesFalsos", 0) + 1
                                break
                        st.session_state.falsos_marcados_sesion.add(cod)
                        guardar_reportes_disco(st.session_state.reportes)
                        st.rerun()

# ====================================================================
# 8.5 COMUNA EN CIFRAS — Panel público, sin contraseña
# ====================================================================
elif menu == "Comuna en Cifras":
    st.title("Comuna 2 en Cifras")
    st.caption("Panel público — visible para cualquier persona, sin contraseña. "
               "Estos datos se actualizan en tiempo real con cada reporte y cada "
               "cambio de estado que hace la administración.")

    reportes_pub = st.session_state.reportes

    if not reportes_pub:
        st.info("Todavía no hay reportes publicados. Sé el primero en reportar un "
                "punto crítico desde Inicio y Mapa.")
    else:
        df_pub = pd.DataFrame(reportes_pub)

        total_pub      = len(df_pub)
        criticos_pub   = int(df_pub["Clasificación"].str.contains("crítico",  case=False, na=False).sum())
        amarillos_pub  = int(df_pub["Clasificación"].str.contains("amarillo", case=False, na=False).sum())
        verdes_pub     = int(df_pub["Clasificación"].str.contains("verde",    case=False, na=False).sum())
        peso_pub       = float(df_pub["Peso (Kg)"].sum()) if "Peso (Kg)" in df_pub.columns else 0.0
        pendientes_pub = int(df_pub["Estado"].str.contains("Pendiente", na=False).sum()) if "Estado" in df_pub.columns else total_pub
        proceso_pub    = int(df_pub["Estado"].str.contains("proceso",   na=False).sum()) if "Estado" in df_pub.columns else 0
        resueltos_pub  = int(df_pub["Estado"].str.contains("Resuelto",  na=False).sum()) if "Estado" in df_pub.columns else 0

        try:
            df_pub["_fecha_dt"] = pd.to_datetime(df_pub["Fecha"], errors="coerce")
            hoy = datetime.now()
            df_mes = df_pub[
                (df_pub["_fecha_dt"].dt.month == hoy.month) &
                (df_pub["_fecha_dt"].dt.year == hoy.year)
            ]
            resueltos_mes = int(df_mes["Estado"].str.contains("Resuelto", na=False).sum()) if "Estado" in df_mes.columns else 0
            nuevos_mes    = len(df_mes)
        except Exception:
            resueltos_mes, nuevos_mes = 0, 0

        st.markdown(
            f'<div style="background:linear-gradient(135deg,rgba(74,222,128,0.15),rgba(22,163,74,0.10));'
            f'border:1px solid #4ade80;border-radius:14px;padding:18px 22px;margin-bottom:16px;">'
            f'<span style="font-size:16px;font-weight:700;color:#166534;">'
            f'Gracias a los reportes de la comunidad, este mes se han resuelto '
            f'<span style="color:#16a34a;">{resueltos_mes}</span> punto(s) crítico(s) '
            f'y se registraron <span style="color:#16a34a;">{nuevos_mes}</span> reporte(s) nuevo(s).'
            f'</span></div>', unsafe_allow_html=True)

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        for col, val, label, color in [
            (k1, total_pub,     "Total reportes",  "#4ade80"),
            (k2, criticos_pub,  "Críticos",      "#f87171"),
            (k3, amarillos_pub, "Mixtos",        "#fbbf24"),
            (k4, verdes_pub,    "Reciclables",   "#4ade80"),
            (k5, proceso_pub,   "En proceso",    "#fb923c"),
            (k6, resueltos_pub, "Resueltos",     "#34d399"),
        ]:
            with col:
                st.markdown(
                    f'<div class="metric-card"><h2 style="color:{color};margin:0">{val}</h2>'
                    f'<p style="font-size:11px;margin:4px 0 0 0;">{label}</p></div>',
                    unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### Semáforo de indicadores")
        st.caption("Umbral fijo: 0-33 rojo · 33-66 amarillo · 66-100 verde (60° cada banda).")

        pct_resueltos_g = (resueltos_pub / total_pub * 100) if total_pub else 0
        pct_criticos_g = (criticos_pub / total_pub * 100) if total_pub else 0
        pct_verdes_g = (verdes_pub / total_pub * 100) if total_pub else 0

        g1, g2, g3 = st.columns(3)
        with g1:
            st.markdown(gauge_svg_aguja(pct_resueltos_g, "% Resueltos"), unsafe_allow_html=True)
        with g2:
            st.markdown(gauge_svg_aguja(pct_criticos_g, "% Críticos"), unsafe_allow_html=True)
        with g3:
            st.markdown(gauge_svg_aguja(pct_verdes_g, "% Reciclables"), unsafe_allow_html=True)

        st.markdown(
            f'<div style="background:rgba(167,139,250,0.10);border:1px solid #a78bfa;'
            f'border-radius:8px;padding:10px 16px;margin-top:14px;font-size:14px;">'
            f'<b style="color:#7c3aed">Carga total estimada reportada: {peso_pub:.1f} kg</b> '
            f'en {total_pub} reportes desde el inicio del proyecto.'
            f'</div>', unsafe_allow_html=True)

        msg_compartir = (
            f"¡La Comuna 2 - Santa Cruz está actuando! Entre todos hemos reportado "
            f"{total_pub} puntos de residuos y ya resolvimos {resueltos_pub}, con "
            f"{peso_pub:.0f} kg de carga identificada. Súmate en EcoCom2 Circular IA"
        )
        st.markdown(
            boton_whatsapp_html(link_whatsapp("", msg_compartir),
                                 "Compartir estas cifras por WhatsApp"),
            unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("#### Barrios más comprometidos")
        st.caption("Ranking por reportes RESUELTOS — el reconocimiento va para los "
                   "barrios que más han logrado limpiar, no solo reportar.")
        if "Sector" in df_pub.columns and "Estado" in df_pub.columns:
            df_resueltos_barrio = df_pub[df_pub["Estado"].str.contains("Resuelto", na=False)]
            if not df_resueltos_barrio.empty:
                ranking_pos = (df_resueltos_barrio.groupby("Sector").size()
                               .reset_index(name="Puntos resueltos")
                               .sort_values("Puntos resueltos", ascending=False))
                puestos = list(range(1, len(ranking_pos) + 1))
                ranking_pos.insert(0, "Puesto", puestos)
                st.dataframe(ranking_pos, use_container_width=True, hide_index=True)
            else:
                st.info("Todavía no hay puntos resueltos — ¡el primer barrio en lograrlo "
                        "aparecerá aquí como líder!")

        st.markdown("---")
        st.markdown("#### Puntos críticos activos por barrio")
        st.caption("Barrios con reportes / que aún no han sido marcados como resueltos — "
                   "útil para priorizar dónde enfocar la limpieza y la sensibilización.")

        if "Sector" in df_pub.columns and "Estado" in df_pub.columns:
            df_activos = df_pub[~df_pub["Estado"].str.contains("Resuelto", na=False)]
            if not df_activos.empty:
                ranking = (df_activos.groupby("Sector").size()
                           .reset_index(name="Puntos activos")
                           .sort_values("Puntos activos", ascending=False))
                ranking.insert(0, "Puesto", range(1, len(ranking) + 1))
                st.dataframe(ranking, use_container_width=True, hide_index=True)
            else:
                st.success("¡No hay puntos activos pendientes! Todos los reportes están resueltos.")

        st.markdown("---")
        st.markdown("#### Reportes acumulados en el tiempo")
        try:
            df_evol = df_pub.dropna(subset=["_fecha_dt"]).sort_values("_fecha_dt")
            if not df_evol.empty:
                df_evol["Acumulado"] = range(1, len(df_evol) + 1)
                st.line_chart(df_evol.set_index("_fecha_dt")["Acumulado"])
            else:
                st.caption("Sin fechas suficientes para mostrar la evolución todavía.")
        except Exception:
            st.caption("Sin datos suficientes para mostrar la evolución todavía.")

        st.markdown("---")
        st.caption(
            "Este panel es de solo lectura: los cambios de estado (Pendiente → En proceso → "
            "Resuelto) los hace la administración desde el Panel Admin. Si tú publicaste un "
            "reporte, puedes ver su seguimiento personal en Inicio y Mapa → Historial."
        )

# ====================================================================
# 9. PANEL ADMINISTRADOR — Gestión completa de reportes
# ====================================================================
elif menu == "Panel Admin":

    if not admin_sesion_vigente():
        st.markdown("")
        col_login = st.columns([1, 2, 1])[1]
        with col_login:
            st.markdown("""
<div style="background:rgba(16,185,129,0.08);border:1px solid #4ade80;
border-radius:14px;padding:32px 28px;text-align:center;">
<h2 style="color:#4ade80;margin-bottom:4px;">Panel Admin</h2>
<p style="color:#9ca3af;font-size:14px;margin-bottom:20px;">
EcoCom2 Circular IA · ITM Medellín</p>
</div>""", unsafe_allow_html=True)
            st.markdown("")
            pwd_input = st.text_input("Contraseña de administrador:",
                                      type="password", key="login_pwd",
                                      placeholder="Ingresa tu contraseña")
            if st.button("Iniciar sesión", type="primary",
                         use_container_width=True, key="login_btn"):
                ok_adm2, msg_adm2 = verificar_credenciales_admin(pwd_input)
                if ok_adm2:
                    st.session_state.admin_ok = True
                    st.rerun()
                else:
                    st.error(msg_adm2)
        st.stop()

    st.markdown("""
<div style="display:flex;align-items:center;justify-content:space-between;
margin-bottom:8px;">
<div>
  <h1 style="color:#4ade80;margin:0;">Panel de Administración</h1>
  <p style="color:#9ca3af;margin:0;font-size:13px;">
  EcoCom2 Circular IA · Comuna 2 Santa Cruz · ITM Medellín</p>
</div>
</div>""", unsafe_allow_html=True)

    accion = st.session_state.pop("adm_accion_pendiente", None)
    if accion and admin_sesion_vigente():
        cod_obj = accion["codigo"]
        tipo_acc = accion["tipo"]
        if tipo_acc == "estado":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj:
                    r["Estado"] = accion["valor"]
                    break
            guardar_reportes_disco(st.session_state.reportes)
        elif tipo_acc == "resuelto":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj:
                    r["Estado"] = "Resuelto"
                    break
            guardar_reportes_disco(st.session_state.reportes)
        elif tipo_acc == "eliminar":
            st.session_state.reportes = [
                r for r in st.session_state.reportes if r["Código"] != cod_obj
            ]
            guardar_reportes_disco(st.session_state.reportes, eliminados=[cod_obj])
        elif tipo_acc == "en_proceso":
            for r in st.session_state.reportes:
                if r["Código"] == cod_obj:
                    r["Estado"] = "En proceso de recolección"
                    break
            guardar_reportes_disco(st.session_state.reportes)
        st.rerun()

    reportes = st.session_state.reportes

    # MEJORA 5 — se agrega la pestaña "Ruta de recolección" entre
    # "Gestión de reportes" y "Exportar / Limpiar".
    tab_dash, tab_mapa, tab_lista, tab_ruta, tab_export = st.tabs([
        "Dashboard",
        "Mapa de control",
        "Gestión de reportes",
        "Ruta de recolección",
        "Exportar / Limpiar"
    ])

    with tab_dash:
        st.markdown("#### Alertas automáticas")
        _alertas_adm = alertas_automaticas(reportes)
        if not _alertas_adm:
            st.success("Sin alertas: nada requiere atención inmediata.")
        for _nivel_a, _msg_a in _alertas_adm:
            (st.error if _nivel_a == "err" else st.warning)(_msg_a)
        st.markdown("#### Resumen semanal (listo para enviar)")
        _txt_resumen = generar_resumen_semanal(reportes)
        st.code(_txt_resumen, language=None)   # el ícono de la esquina lo copia
        st.link_button("Enviar por WhatsApp",
                       f"https://wa.me/?text={url_quote(_txt_resumen)}",
                       use_container_width=True)
        _hoy_c = _contador_tokens().get(
            _hoy_colombia().strftime("%Y-%m-%d"),
            {"texto_llamadas": 0, "texto_tokens": 0, "voz_llamadas": 0, "voz_tokens": 0})
        st.markdown("#### Consumo de IA hoy")
        _c1, _c2, _c3, _c4 = st.columns(4)
        _c1.metric("Llamadas de texto", _hoy_c["texto_llamadas"])
        _c2.metric("Tokens de texto", f"{_hoy_c['texto_tokens']:,}")
        _c3.metric("Voces generadas", _hoy_c["voz_llamadas"])
        _c4.metric("Tokens de voz", f"{_hoy_c['voz_tokens']:,}")
        st.caption("Se cuenta desde el último reinicio de la app. Incluye chat, "
                   "transcripción de audios, análisis de fotos y voz.")
        st.markdown("#### Estado del sistema")
        est1, est2, est3, est4 = st.columns(4)
        with est1:
            if verificar_gemini_key():
                st.markdown(
                    '<div class="badge-ok" style="font-size:13px;">'
                    'EcoBot conectado a Gemini<br>'
                    '<span style="font-weight:normal">El chatbot puede responder con IA.</span></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div class="badge-err" style="font-size:13px;">'
                    'GEMINI_API_KEY no configurada<br>'
                    '<span style="font-weight:normal">EcoBot está en modo "sin conexión" — '
                    'configúrala en Settings → Secrets de tu hosting.</span></div>',
                    unsafe_allow_html=True)
        with est4:
            if verificar_gemini_key():
                st.markdown(
                    '<div class="badge-ok" style="font-size:13px;">'
                    'API key de Gemini configurada<br>'
                    '<span style="font-weight:normal">Clasificación por categoría '
                    '(Orgánicos/Plásticos/Vidrio/Cartón/Papel) disponible.</span></div>',
                    unsafe_allow_html=True)
            else:
                st.markdown(
                    '<div class="badge-err" style="font-size:13px;">'
                    'GEMINI_API_KEY no configurada<br>'
                    '<span style="font-weight:normal">Los residentes solo verán la '
                    'opción YOLO local — configúrala en Secrets para activar Gemini.</span></div>',
                    unsafe_allow_html=True)
        with est2:
            tam_mb = tamano_bd_mb()
            color_tam = "badge-ok" if tam_mb < 200 else ("badge-warn" if tam_mb < 500 else "badge-err")
            st.markdown(
                f'<div class="{color_tam}" style="font-size:13px;">'
                f'Base de datos: {tam_mb} MB<br>'
                f'<span style="font-weight:normal">Fotos y audio van codificados aquí adentro — '
                f'usa "Eliminar resueltos" si crece mucho.</span></div>',
                unsafe_allow_html=True)
        with est3:
            _tok_gh, _repo_gh, _branch_gh = _github_config()
            if _tok_gh:
                st.markdown(
                    f'<div class="badge-ok" style="font-size:13px;">'
                    f'Respaldo en GitHub activo<br>'
                    f'<span style="font-weight:normal">Repo: {_repo_gh} · rama {_branch_gh}. '
                    f'Los reportes sobreviven a un reinicio del contenedor.</span></div>',
                    unsafe_allow_html=True)
                if st.button("Respaldar ahora", use_container_width=True, key="respaldo_manual"):
                    with st.spinner("Subiendo respaldo a GitHub..."):
                        ok_resp, msg_resp = respaldar_en_github(st.session_state.reportes)
                    if ok_resp:
                        st.success("Respaldo actualizado en GitHub — revisa la carpeta "
                                   "'data_backup' en tu repositorio.")
                    else:
                        st.error(f"No se pudo respaldar: {msg_resp}")
            else:
                st.markdown(
                    '<div class="badge-err" style="font-size:13px;">'
                    'Sin respaldo en GitHub<br>'
                    '<span style="font-weight:normal">Si el contenedor se reinicia, se pierden '
                    'todos los reportes. Configura GITHUB_TOKEN y GITHUB_REPO en Secrets.</span></div>',
                    unsafe_allow_html=True)
        st.markdown("")

        if not reportes:
            st.info("Sin reportes aún. Los reportes de los residentes aparecerán aquí.")
        else:
            df_a = pd.DataFrame(reportes)

            total    = len(df_a)
            criticos = int(df_a["Clasificación"].str.contains("crítico",  case=False, na=False).sum())
            amarillos= int(df_a["Clasificación"].str.contains("amarillo", case=False, na=False).sum())
            verdes   = int(df_a["Clasificación"].str.contains("verde",    case=False, na=False).sum())
            peso_t   = float(df_a["Peso (Kg)"].sum())
            pendientes = int(df_a["Estado"].str.contains("Pendiente",  na=False).sum()) if "Estado" in df_a.columns else total
            en_proceso = int(df_a["Estado"].str.contains("proceso",    na=False).sum()) if "Estado" in df_a.columns else 0
            resueltos  = int(df_a["Estado"].str.contains("Resuelto",   na=False).sum()) if "Estado" in df_a.columns else 0

            k1,k2,k3,k4,k5,k6 = st.columns(6)
            for col, val, label, color in [
                (k1, total,       "Total",         "#4ade80"),
                (k2, criticos,    "Críticos",   "#f87171"),
                (k3, amarillos,   "Mixtos",     "#fbbf24"),
                (k4, verdes,      "Reciclables","#4ade80"),
                (k5, pendientes,  "Pendientes", "#fb923c"),
                (k6, resueltos,   "Resueltos",  "#34d399"),
            ]:
                with col:
                    st.markdown(
                        f'<div class="metric-card"><h2 style="color:{color};margin:0">{val}</h2>'
                        f'<p style="font-size:11px;margin:4px 0 0 0;color:#9ca3af">{label}</p></div>',
                        unsafe_allow_html=True)

            st.markdown(f"""
<div style="background:rgba(167,139,250,0.1);border:1px solid #a78bfa;border-radius:8px;
padding:10px 16px;margin-top:12px;font-size:14px;">
<b style="color:#a78bfa">Carga total acumulada: {peso_t:.1f} kg</b> en {total} reportes
</div>""", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("#### Reportes por Barrio")
            if "Sector" in df_a.columns:
                conteo_barrio = df_a["Sector"].value_counts().reset_index()
                conteo_barrio.columns = ["Barrio", "Reportes"]
                st.dataframe(conteo_barrio, use_container_width=True,
                             hide_index=True)

            st.markdown("#### Últimos reportes registrados")
            COLS_DASH = ["Código","Fecha","Estado","Sector","Clasificación","Peso (Kg)","Observaciones"]
            cols_ok = [c for c in COLS_DASH if c in df_a.columns]
            st.dataframe(df_a[cols_ok].tail(5).iloc[::-1],
                         use_container_width=True, hide_index=True)

    with tab_mapa:
        st.markdown("#### Todos los puntos reportados — mapa de control")

        if not reportes:
            st.info("Sin reportes aún.")
        else:
            fm1, fm2, fm3 = st.columns(3)
            with fm1:
                f_estado = st.selectbox("Filtrar por estado:",
                    ["Todos","Pendiente","En proceso","Resuelto"],
                    key="adm_f_estado")
            with fm2:
                f_nivel = st.selectbox("Filtrar por criticidad:",
                    ["Todos","Crítico","Amarillo","Verde"],
                    key="adm_f_nivel")
            with fm3:
                vista_mapa_adm = st.radio(
                    "Vista:", ["Puntos", "Mapa de calor"],
                    key="vista_mapa_admin", horizontal=True)

            mapa_adm = folium.Map(location=[LAT_C, LON_C],
                                  zoom_start=14, tiles="OpenStreetMap")

            coords_p = [(la, lo) for lo, la in POLIGONO_COMUNA2.exterior.coords]
            folium.Polygon(locations=coords_p, color="#4ade80", weight=2,
                           fill=True, fill_color="#4ade80", fill_opacity=0.06).add_to(mapa_adm)

            reportes_filtrados = []
            for rep in reportes:
                est = rep.get("Estado", "")
                niv = rep.get("Clasificación", "")
                if f_estado != "Todos":
                    if f_estado == "Pendiente"     and "Pendiente" not in est: continue
                    if f_estado == "En proceso"    and "proceso"   not in est: continue
                    if f_estado == "Resuelto"      and "Resuelto"  not in est: continue
                if f_nivel != "Todos":
                    if f_nivel == "Crítico"  and semaforo(niv) != "rojo": continue
                    if f_nivel == "Amarillo" and semaforo(niv) != "amarillo": continue
                    if f_nivel == "Verde"    and semaforo(niv) != "verde": continue
                reportes_filtrados.append(rep)

            total_mostrados = 0
            if vista_mapa_adm == "Mapa de calor":
                PESO_CALOR_ADM = {"rojo": 1.0, "amarillo": 0.6, "verde": 0.3}
                datos_calor_adm = []
                for rep in reportes_filtrados:
                    niv = rep.get("Clasificación", "")
                    p = PESO_CALOR_ADM[semaforo(niv)]
                    if "Resuelto" in rep.get("Estado", ""):
                        p *= 0.25
                    if rep.get("Lat") is not None and rep.get("Lon") is not None:
                        datos_calor_adm.append([rep["Lat"], rep["Lon"], p])
                        total_mostrados += 1
                if datos_calor_adm:
                    HeatMap(datos_calor_adm, radius=24, blur=20, max_zoom=16,
                            gradient={0.2: "#4ade80", 0.5: "#fbbf24", 0.8: "#f87171", 1.0: "#dc2626"}
                            ).add_to(mapa_adm)
            else:
                for rep in reportes_filtrados:
                    est = rep.get("Estado", "")
                    niv = rep.get("Clasificación", "")
                    col = {"rojo": "red", "amarillo": "orange", "verde": "green"}[semaforo(niv)]
                    if "Resuelto" in est:
                        col = "gray"

                    foto_src_adm = fuente_imagen(rep.get("FotoB64", ""), rep.get("FotoURL", ""))
                    img_html  = (f'<br><img src="{foto_src_adm}" '
                                  f'style="width:160px;border-radius:4px;margin-top:4px;">'
                                  if foto_src_adm else "")
                    obs_txt_adm = rep.get("Observaciones", "")
                    obs_html_adm = f"{esc(obs_txt_adm[:100])}<br>" if obs_txt_adm else ""
                    audio_b64_adm = rep.get("NotaVozB64", "")
                    audio_html_adm = (f'<br><audio controls style="width:160px;margin-top:4px;">'
                                      f'<source src="data:audio/wav;base64,{solo_b64(audio_b64_adm)}"></audio>'
                                      if audio_b64_adm else "")
                    galeria_adm_html = galeria_html(rep.get("FotosExtraB64", ""), ancho_px=55)
                    popup_adm = (
                        f"<div style='font-family:sans-serif;min-width:190px;'>"
                        f"<b style='color:{col}'>{esc(niv)}</b><br>"
                        f"<b>{esc(rep['Código'])}</b><br>"
                        f"{esc(rep.get('Sector',''))} · {esc(rep.get('Referencia','')[:35])}<br>"
                        f"{obs_html_adm}"
                        f"{esc(rep.get('Objetos',0))} obj | {esc(rep.get('Peso (Kg)',0))} kg<br>"
                        f"{esc(rep.get('Fecha',''))} | {esc(est)}"
                        f"{img_html}{audio_html_adm}{galeria_adm_html}</div>"
                    )
                    folium.CircleMarker(
                        location=[rep["Lat"], rep["Lon"]], radius=13,
                        color=col, fill=True, fill_color=col, fill_opacity=0.85,
                        popup=folium.Popup(popup_adm, max_width=220),
                        tooltip=f"{esc(rep['Código'])} | {esc(est)}"
                    ).add_to(mapa_adm)
                    total_mostrados += 1

            st_folium(mapa_adm, width="100%", height=480, returned_objects=[])
            st.caption(f"Mostrando {total_mostrados} de {len(reportes)} reportes")

    with tab_lista:
        st.markdown("#### Gestión individual de reportes")

        if not reportes:
            st.info("Sin reportes aún.")
        else:
            g1, g2, g3 = st.columns(3)
            with g1:
                g_sector = st.selectbox("Barrio:", ["Todos"]+BARRIOS, key="adm_g_sector")
            with g2:
                g_estado = st.selectbox("Estado:",
                    ["Todos","Pendiente","En proceso","Resuelto"],
                    key="adm_g_estado")
            with g3:
                g_tipo = st.selectbox("Tipo:",
                    ["Todos","Crítico","Mixto","Verde"],
                    key="adm_g_tipo")

            ESTADOS = ["Pendiente","En proceso de recolección","Resuelto"]

            for rep in list(reportes):
                codigo   = rep["Código"]
                key_safe = codigo.replace(" ","_").replace("/","_").replace("-","_")
                estado   = rep.get("Estado","Pendiente")
                nivel    = rep.get("Clasificación","")

                if g_sector != "Todos" and rep.get("Sector") != g_sector: continue
                if g_estado != "Todos":
                    if g_estado == "Pendiente"  and "Pendiente" not in estado: continue
                    if g_estado == "En proceso" and "proceso"   not in estado: continue
                    if g_estado == "Resuelto"   and "Resuelto"  not in estado: continue
                if g_tipo != "Todos":
                    if g_tipo == "Crítico" and semaforo(nivel) != "rojo": continue
                    if g_tipo == "Mixto"   and semaforo(nivel) != "amarillo": continue
                    if g_tipo == "Verde"   and semaforo(nivel) != "verde": continue

                icono = {"rojo": "[Crítico]", "amarillo": "[Mixto]", "verde": "[Verde]"}[semaforo(nivel)]

                n_falsos_adm = rep.get("ReportesFalsos", 0) or 0
                etiqueta_falso = f" · {n_falsos_adm} reportado(s) como falso" if n_falsos_adm > 0 else ""
                if n_falsos_adm >= 3:
                    etiqueta_falso = f" · REVISAR — {n_falsos_adm} vecinos dicen que no es basura"

                with st.expander(
                    f"{icono} {codigo} · {rep.get('Sector','?')} · "
                    f"{rep.get('Referencia','')[:30]} · {estado}{etiqueta_falso}",
                    expanded=False
                ):
                    if n_falsos_adm >= 3:
                        st.error(
                            f"**{n_falsos_adm} vecinos marcaron este reporte como "
                            f"'no es basura'.** Revisa la foto antes de confiar en esta "
                            f"clasificación — podría ser un reporte de mala fe (ej. contra "
                            f"un negocio o vivienda real). Si confirmas que no corresponde, "
                            f"usa el botón Eliminar más abajo."
                        )
                    foto_src = fuente_imagen(rep.get("FotoB64",""), rep.get("FotoURL",""))
                    if foto_src:
                        st.markdown("**Foto de evidencia (original):**")
                        st.markdown(
                            f'<img src="{foto_src}" '
                            f'style="max-width:320px;border-radius:8px;margin-bottom:10px;">',
                            unsafe_allow_html=True)
                    elif rep.get("Código"):
                        st.caption("La foto original de este reporte no está disponible "
                                   "(se perdió en un reinicio del servidor antes de que se "
                                   "activara el respaldo permanente de fotos).")
                    foto_clasif_src = fuente_imagen(rep.get("FotoClasificadaB64",""), rep.get("FotoClasificadaURL",""))
                    if foto_clasif_src:
                        st.markdown("**Foto clasificada por la IA:**")
                        st.markdown(
                            f'<img src="{foto_clasif_src}" '
                            f'style="max-width:320px;border-radius:8px;margin-bottom:10px;">',
                            unsafe_allow_html=True)
                    foto_resuelta_b64 = rep.get("FotoResueltaB64","")
                    foto_resuelta_src = fuente_imagen(foto_resuelta_b64, rep.get("FotoResueltaURL",""))
                    if foto_resuelta_src:
                        st.markdown(f"**Foto de evidencia de resolución** "
                                    f"({rep.get('FechaResuelto','')}):")
                        st.markdown(
                            f'<img src="{foto_resuelta_src}" '
                            f'style="max-width:320px;border-radius:8px;margin-bottom:10px;'
                            f'border:2px solid #16a34a;">',
                            unsafe_allow_html=True)
                    if rep.get("FotosExtraB64"):
                        st.markdown(galeria_html(rep["FotosExtraB64"], ancho_px=100),
                                    unsafe_allow_html=True)

                    i1, i2 = st.columns(2)
                    with i1:
                        st.markdown(
                            f"**Código:** {codigo}  \n"
                            f"**Barrio:** {rep.get('Sector','—')}  \n"
                            f"**Referencia:** {rep.get('Referencia','—')}  \n"
                            f"**Fecha:** {rep.get('Fecha','Sin fecha')}"
                        )
                    with i2:
                        st.markdown(
                            f"**Clasificación:** {nivel}  \n"
                            f"**Objetos:** {rep.get('Objetos',0)}  \n"
                            f"**Peso:** {rep.get('Peso (Kg)',0)} kg  \n"
                            f"**Material:** {rep.get('Predominante','—')}"
                        )
                    st.markdown(
                        f"Coordenadas: `{rep.get('Lat',0):.5f}, {rep.get('Lon',0):.5f}`"
                    )

                    obs_rep = rep.get("Observaciones", "")
                    if obs_rep:
                        st.markdown(
                            f'<div style="background:rgba(74,222,128,0.08);border-left:3px solid #4ade80;'
                            f'border-radius:6px;padding:8px 12px;margin:8px 0;font-size:13px;">'
                            f'<b>Observaciones del ciudadano:</b><br>{esc(obs_rep)}</div>',
                            unsafe_allow_html=True)

                    audio_rep = rep.get("NotaVozB64", "")
                    if audio_rep:
                        st.markdown("**Nota de voz del ciudadano:**")
                        try:
                            st.audio(base64.b64decode(audio_rep), format="audio/wav")
                        except Exception:
                            st.caption("No se pudo reproducir la nota de voz.")

                    st.markdown("**Cambiar estado:**")
                    idx_est = ESTADOS.index(estado) if estado in ESTADOS else 0
                    nuevo_estado = st.selectbox("",ESTADOS,index=idx_est,
                                                label_visibility="collapsed",
                                                key=f"sel_{key_safe}")

                    st.markdown("**Foto de evidencia al resolver (opcional, recomendado):**")
                    foto_resuelta_up = st.file_uploader(
                        "Sube una foto del punto ya limpio",
                        type=["jpg","jpeg","png"], key=f"foto_resuelta_{key_safe}",
                        label_visibility="collapsed",
                        help="Se guarda con el reporte y se incluye como enlace en el "
                             "mensaje de WhatsApp al residente, para que vea la prueba "
                             "de que su punto quedó atendido sin tener que entrar a la app."
                    )

                    b1,b2,b3,b4 = st.columns(4)
                    with b1:
                        if st.button("Guardar",key=f"grd_{key_safe}",
                                     use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"estado","valor":nuevo_estado}
                            st.rerun()
                    with b2:
                        if st.button("En proceso",key=f"proc_{key_safe}",
                                     use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"en_proceso"}
                            st.rerun()
                    with b3:
                        if st.button("Resuelto",key=f"res_{key_safe}",
                                     type="primary",use_container_width=True):
                            foto_resuelta_b64_nueva = ""
                            foto_resuelta_url_nueva = ""
                            if foto_resuelta_up is not None:
                                with st.spinner("Guardando foto de evidencia..."):
                                    img_resuelta = _abrir_img_subida(foto_resuelta_up).convert("RGB")
                                    foto_resuelta_b64_nueva = img_a_b64(img_resuelta, max_px=350)
                                    buf_evidencia = BytesIO()
                                    img_resuelta.save(buf_evidencia, format="JPEG", quality=80)
                                    url_pub, err_gh = subir_foto_evidencia_github(
                                        buf_evidencia.getvalue(), f"{codigo}.jpg")
                                    if url_pub:
                                        foto_resuelta_url_nueva = url_pub
                                    else:
                                        st.warning(f"Se marcó como resuelto, pero no se pudo "
                                                   f"subir la foto a GitHub para el enlace de "
                                                   f"WhatsApp: {err_gh}")
                            for r in st.session_state.reportes:
                                if r["Código"] == codigo:
                                    r["Estado"] = "Resuelto"
                                    r["FechaResuelto"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                                    if foto_resuelta_b64_nueva:
                                        r["FotoResueltaB64"] = foto_resuelta_b64_nueva
                                    if foto_resuelta_url_nueva:
                                        r["FotoResueltaURL"] = foto_resuelta_url_nueva
                                    break
                            guardar_reportes_disco(st.session_state.reportes)
                            st.success("Reporte marcado como resuelto.")
                            st.rerun()
                    with b4:
                        if st.button("Eliminar",key=f"del_{key_safe}",
                                     use_container_width=True):
                            st.session_state.adm_accion_pendiente={
                                "codigo":codigo,"tipo":"eliminar"}
                            st.rerun()

                    tel_wa = extraer_telefono_whatsapp(rep.get("CodigoResidente", ""))
                    if tel_wa:
                        msg_wa = (
                            f"Hola! Tu reporte {codigo} en {rep.get('Sector','')} "
                            f"({rep.get('Referencia','')[:40]}) está ahora: {estado}. "
                            f"— EcoCom2 Circular IA"
                        )
                        if "Resuelto" in estado and rep.get("FotoResueltaURL"):
                            msg_wa += (f"\n\n Así quedó el punto — mira la foto: "
                                       f"{rep['FotoResueltaURL']}")
                        st.markdown(
                            boton_whatsapp_html(link_whatsapp(tel_wa, msg_wa),
                                                 "Notificar al residente por WhatsApp"),
                            unsafe_allow_html=True)
                    else:
                        st.caption("Este residente no dejó un teléfono válido para notificar.")

    with tab_ruta:
        st.markdown("#### Ruta sugerida de recolección")
        st.caption(
            "Ordena los puntos activos por cercanía (vecino más próximo) para armar "
            "un recorrido razonable — no es matemáticamente la ruta más corta posible, "
            "pero evita saltos absurdos de un extremo a otro de la comuna."
        )

        rf1, rf2 = st.columns(2)
        with rf1:
            ruta_barrio = st.selectbox("Filtrar por barrio:", ["Todos"] + BARRIOS,
                                       key="ruta_barrio")
        with rf2:
            ruta_solo_criticos = st.checkbox("Solo puntos críticos",
                                             key="ruta_solo_criticos")

        activos_ruta = [r for r in st.session_state.reportes
                        if "Resuelto" not in r.get("Estado", "")]
        if ruta_barrio != "Todos":
            activos_ruta = [r for r in activos_ruta if r.get("Sector") == ruta_barrio]
        if ruta_solo_criticos:
            activos_ruta = [r for r in activos_ruta
                            if "crítico" in r.get("Clasificación", "").lower()]

        st.caption(f"{len(activos_ruta)} punto(s) activos con los filtros actuales.")

        if st.button("Generar ruta optimizada", type="primary",
                     key="btn_generar_ruta", disabled=len(activos_ruta) < 2):
            st.session_state.ruta_generada = optimizar_ruta_recoleccion(activos_ruta)

        if len(activos_ruta) < 2:
            st.info("Se necesitan al menos 2 puntos activos con los filtros actuales "
                    "para generar una ruta.")

        ruta_actual = st.session_state.get("ruta_generada")
        if ruta_actual:
            distancia_total_km = 0.0
            filas_ruta = []
            for i, r in enumerate(ruta_actual):
                if i > 0:
                    d = distancia_metros(ruta_actual[i-1]["Lat"], ruta_actual[i-1]["Lon"],
                                         r["Lat"], r["Lon"])
                    distancia_total_km += d / 1000
                filas_ruta.append({
                    "Parada": i + 1, "Código": r["Código"],
                    "Barrio": r.get("Sector", ""),
                    "Nivel": r.get("Clasificación", ""),
                    "Referencia": r.get("Referencia", "")[:40],
                })
            st.dataframe(pd.DataFrame(filas_ruta), use_container_width=True, hide_index=True)
            st.markdown(
                f"**Distancia aproximada en línea recta:** {distancia_total_km:.1f} km "
                f"({len(ruta_actual)} paradas — el recorrido real en carro será más largo, "
                f"esto es solo un estimado para priorizar)."
            )

            link_ruta = generar_link_google_maps_ruta(ruta_actual)
            st.markdown(
                f'<a href="{link_ruta}" target="_blank" style="display:inline-block;'
                f'background:#16a34a;color:white !important;text-decoration:none;'
                f'padding:10px 18px;border-radius:8px;font-weight:700;margin:8px 0;">'
                f'Abrir ruta completa en Google Maps</a>', unsafe_allow_html=True
            )

            mapa_ruta = folium.Map(
                location=[ruta_actual[0]["Lat"], ruta_actual[0]["Lon"]],
                zoom_start=14, tiles="OpenStreetMap"
            )
            coords_ruta = [(r["Lat"], r["Lon"]) for r in ruta_actual]
            folium.PolyLine(coords_ruta, color="#16a34a", weight=4, opacity=0.8).add_to(mapa_ruta)
            for i, r in enumerate(ruta_actual):
                folium.Marker(
                    location=[r["Lat"], r["Lon"]],
                    popup=f"{i+1}. {esc(r['Código'])} — {esc(r.get('Sector',''))}",
                    icon=folium.DivIcon(html=(
                        f'<div style="background:#16a34a;color:white;border-radius:50%;'
                        f'width:26px;height:26px;text-align:center;line-height:26px;'
                        f'font-weight:700;font-size:12px;">{i+1}</div>'
                    ))
                ).add_to(mapa_ruta)
            st_folium(mapa_ruta, width="100%", height=420, returned_objects=[])

            if st.button("Limpiar ruta generada", key="btn_limpiar_ruta"):
                st.session_state.ruta_generada = None
                st.rerun()
        else:
            st.info("Aplica los filtros y presiona 'Generar ruta optimizada'.")

    with tab_export:
        st.markdown("#### Exportar datos")

        if reportes:
            incluir_tel = st.checkbox(
                "Incluir teléfono/código de los residentes en el Excel",
                value=False, key="exp_incluir_contacto",
                help="Actívalo solo si vas a usar el archivo para contactar "
                     "residentes — evita compartirlo así con terceros."
            )

            excel_todos = generar_excel_reportes(reportes, incluir_contacto=incluir_tel)
            st.download_button(
                "Descargar Excel — todos los reportes",
                data=excel_todos,
                file_name=f"ecocom2_reportes_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            reportes_pend = [r for r in reportes if "Pendiente" in r.get("Estado", "")]
            if reportes_pend:
                excel_pend = generar_excel_reportes(reportes_pend, incluir_contacto=incluir_tel)
                st.download_button(
                    f"Descargar solo PENDIENTES ({len(reportes_pend)})",
                    data=excel_pend,
                    file_name=f"ecocom2_pendientes_{datetime.now().strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

        st.markdown("---")
        st.markdown("#### Operaciones en lote")

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button("Marcar TODOS pendientes como En Proceso",
                         use_container_width=True, key="adm_todos_proceso"):
                cambios = 0
                for r in st.session_state.reportes:
                    if "Pendiente" in r.get("Estado",""):
                        r["Estado"] = "En proceso de recolección"
                        cambios += 1
                guardar_reportes_disco(st.session_state.reportes)
                st.success(f"{cambios} reporte(s) marcados como En proceso.")
                st.rerun()

        with col_b2:
            if st.button("Marcar TODOS como Resueltos",
                         use_container_width=True, key="adm_todos_resuelto"):
                for r in st.session_state.reportes:
                    r["Estado"] = "Resuelto"
                guardar_reportes_disco(st.session_state.reportes)
                st.success(f"{len(st.session_state.reportes)} reportes marcados como resueltos.")
                st.rerun()

        st.markdown("")
        st.markdown("**Eliminar reportes resueltos** (libera espacio del mapa):")
        if st.button("ELIMINAR todos los Resueltos del mapa",
                     use_container_width=True, key="adm_limpiar_resueltos"):
            antes = len(st.session_state.reportes)
            _cods_resueltos = [r["Código"] for r in st.session_state.reportes
                               if "Resuelto" in r.get("Estado","")]
            st.session_state.reportes = [
                r for r in st.session_state.reportes
                if "Resuelto" not in r.get("Estado","")
            ]
            guardar_reportes_disco(st.session_state.reportes, eliminados=_cods_resueltos)
            eliminados = antes - len(st.session_state.reportes)
            st.success(f"{eliminados} reporte(s) resuelto(s) eliminados del mapa.")
            st.rerun()

        st.markdown("")
        with st.expander("ZONA DE PELIGRO — Eliminar todo"):
            st.warning("Esta acción elimina TODOS los reportes permanentemente. No se puede deshacer.")
            confirm = st.text_input("Escribe CONFIRMAR para continuar:",
                                    key="adm_confirm_borrar_todo")
            if st.button("BORRAR TODOS LOS REPORTES",
                         use_container_width=True, key="adm_borrar_todo"):
                if confirm == "CONFIRMAR":
                    st.session_state.reportes = []
                    guardar_reportes_disco([], borrar_todo=True)
                    st.success("Todos los reportes eliminados.")
                    st.rerun()
                else:
                    st.error("Escribe exactamente CONFIRMAR para continuar.")

elif menu == "Información":
    st.title("EcoCom2 Circular IA")
    st.markdown(
        '<div style="background:rgba(16,185,129,0.1);border:1px solid #4ade80;'
        'border-radius:10px;padding:16px;margin-bottom:20px;font-size:15px;">'
        '<b style="color:#4ade80">Plataforma de Gestión Inteligente de Residuos</b><br>'
        'Tecnología IA al servicio de una <b>Comuna 2 más limpia y sostenible</b>.'
        '</div>', unsafe_allow_html=True)

    st.markdown("## ¿Qué es la Economía Circular?")
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
<h2 style="color:#4ade80"></h2>
<b style="color:#4ade80">Reciclar</b><br>
<span style="font-size:13px;color:#9ca3af">Papel, plástico, vidrio,<br>
aluminio y electrónicos</span>
</div>""", unsafe_allow_html=True)
    with i2:
        st.markdown("""
<div style="background:rgba(251,191,36,0.1);border:1px solid #fbbf24;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#fbbf24"></h2>
<b style="color:#fbbf24">Reutilizar</b><br>
<span style="font-size:13px;color:#9ca3af">Muebles, ropa, aparatos<br>
que aún sirven</span>
</div>""", unsafe_allow_html=True)
    with i3:
        st.markdown("""
<div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;
border-radius:10px;padding:14px;text-align:center;">
<h2 style="color:#ef4444"></h2>
<b style="color:#ef4444">Compostar</b><br>
<span style="font-size:13px;color:#9ca3af">Residuos orgánicos que<br>
se convierten en abono</span>
</div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("## ¿Qué es un Punto Crítico de Residuos?")
    st.markdown("""
Un **punto crítico** es una zona donde se acumulan residuos de forma irregular, afectando la
salud pública, el medio ambiente y la calidad de vida del barrio. En la **Comuna 2 — Santa Cruz**
existen zonas donde los residuos se depositan en espacios públicos sin recolección oportuna.

### Sistema de Clasificación EcoCom2

La clasificación combina **dos factores**: qué tan reciclable es el material, y **qué tan grande**
es la acumulación. Un montón grande de material 100% reciclable (ej. 40 botellas) también cuenta
como punto crítico — el volumen es un problema aunque el material tenga valor.

| Color | Significado | Acción recomendada |
|---|---|---|
|**Verde** | ≥60% objetos reciclables y volumen pequeño | Ruta de reciclaje |
|**Amarillo** | 30-60% mixto, o buen material pero volumen considerable | Separación en origen |
|**Rojo** | <30% reciclable, o una acumulación grande sin importar el material | Recolección urgente |
""")

    st.markdown("---")
    st.markdown("## ¿Cómo funciona la IA?")
    st.markdown("""
EcoCom2 usa **YOLOv8** (You Only Look Once), un modelo de visión artificial que analiza imágenes
en tiempo real para detectar y clasificar objetos. El sistema:

1. **Detecta** todos los objetos visibles en la fotografía
2. **Clasifica** cada objeto en su tipo de material (Plástico, Papel, Vidrio, Metal, Electrónico, Orgánico)
3. **Calcula** el peso estimado y el ratio reciclable/no-reciclable
4. **Clasifica** el punto como Verde, Amarillo o Rojo

### Materiales que detecta la IA
""")

    mat_cols = st.columns(3)
    categorias = {
        "Plástico": ["Botellas", "Vasos", "Bolsas", "Baldes", "Sillas", "Juguetes"],
        "Papel/Cartón": ["Libros", "Periódicos", "Cajas", "Cuadernos"],
        "Vidrio": ["Botellas", "Frascos", "Jarrones", "Copas"],
        "Metal/Aluminio": ["Latas", "Cuchillos", "Tijeras", "Utensilios"],
        "Electrónicos": ["Celulares", "Portátiles", "Teclados", "Televisores", "Relojes"],
        "Orgánico": ["Frutas", "Verduras", "Comida", "Plantas"],
        "Textil": ["Ropa", "Mochilas", "Bolsos", "Maletas"],
        "Madera/Mixto": ["Mesas", "Sofás", "Camas", "Colchones"],
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
    st.markdown("## Cómo usar EcoCom2")
    st.markdown("""
1. **Verifica tu dirección** en Inicio y Mapa — usa tu GPS o escribe tu dirección y presiona Verificar
2. **Toca el mapa** en el punto exacto donde están los residuos (si no usaste el GPS)
3. **Presiona el botón** "Ir a Reportar Residuo" o "Ir a Punto Crítico"
4. **Sube una foto** del residuo y deja que la IA lo analice
5. **Agrega observaciones** por texto o deja una nota de voz si quieres contar detalles que la foto no muestra
6. **Publica el reporte** — quedará guardado en el mapa comunitario

> Solo residentes **dentro del polígono de la Comuna 2** pueden publicar reportes.
> Cualquier persona puede analizar imágenes con la IA.
""")

    st.markdown("---")
    st.markdown("## Los 11 barrios de la Comuna 2 — Santa Cruz")
    bc1, bc2 = st.columns(2)
    mitad = len(BARRIOS) // 2
    with bc1:
        for b in BARRIOS[:mitad+1]:
            st.markdown(f"-**{b}**")
    with bc2:
        for b in BARRIOS[mitad+1:]:
            st.markdown(f"-**{b}**")

    st.markdown("---")
    st.markdown("## Aviso de Tratamiento de Datos Personales")
    st.markdown("""
En cumplimiento de la **Ley 1581 de 2012 (Habeas Data)** y sus decretos reglamentarios,
EcoCom2 Circular IA informa lo siguiente sobre los datos que recoge:

**¿Qué datos recogemos?**
- Fotos que subes al reportar un residuo (pueden mostrar el sitio, objetos y, si no
  tienes cuidado, personas — por eso difuminamos automáticamente cualquier rostro/persona
  que la IA detecte antes de publicar la foto).
- Tu ubicación GPS o la dirección que escribas, **solo si aceptas** la casilla de autorización
  en la pantalla inicial. Se usa únicamente para validar que estás en la Comuna 2 y ubicar tu
  reporte. Para convertir coordenadas en dirección se consulta el servicio público
  Nominatim (OpenStreetMap). Puedes retirar tu autorización en cualquier momento desde
  "Más opciones" en el menú; al hacerlo se borra tu ubicación de esa sesión.
- Si activas **"Leer las respuestas en voz alta"**, el texto de la respuesta de EcoBot (no tus
  datos personales) se envía al servicio de voz (Google Gemini o, si está configurado, ElevenLabs).
  Tu preferencia de activar o no la lectura se guarda en una cookie de tu navegador.
- El nombre de tu barrio, **solo si le pides a EcoBot que lo recuerde** (o lo eliges en el
  horario del camión): se guarda únicamente en una cookie de tu navegador para avisarte cuándo
  pasa el camión. "Revocar autorización de datos" también la borra.
- Ubicación aproximada del punto reportado (coordenadas del mapa o la dirección que escribas).
- Código o teléfono, **solo si tú decides escribirlo** — es opcional.
- Observaciones de texto o notas de voz que agregues voluntariamente.

**¿Para qué los usamos?**
- Mostrar el reporte en el mapa comunitario, para que la administración y otros
  residentes puedan verlo y darle seguimiento.
- Si dejaste un teléfono, permitir que la administración te notifique por WhatsApp
  cuando el estado de tu reporte cambie, y que tú mismo puedas buscar tus reportes
  después desde otro dispositivo.

**¿Quién puede ver estos datos?**
La foto, el sector, la clasificación y el estado del reporte son **públicos** — cualquiera
que entre a la app puede verlos en el mapa. El código/teléfono que dejes **no se muestra
públicamente** en el mapa ni en las estadísticas, pero técnicamente cualquiera que lo
supiera podría usarlo para buscar tus reportes en "Mi Historial" — por eso te
recomendamos no usar información sensible ahí.

**¿Cuánto tiempo se guardan?**
Mientras el proyecto piloto esté activo. Puedes pedir que se elimine un reporte tuyo
(foto incluida) contactando a la administración.

**Tus derechos como titular de los datos**
Puedes conocer, actualizar, rectificar o solicitar la eliminación de tus datos en
cualquier momento, contactando al desarrollador del proyecto.

*Este es un aviso informativo básico para un proyecto piloto académico
(Territorio INN 2026, ITM Medellín) y no reemplaza una política de datos formal
revisada por un abogado — si el proyecto crece más allá de la fase piloto, se
recomienda formalizarla.*
""")

    st.markdown("---")
    st.markdown("## Respaldo de investigación — Comuna 2")
    st.caption("Datos verificados con fuentes oficiales (Emvarias, Alcaldía de Medellín, "
               "PGIRS), usados como sustento del proyecto. Cada indicador tiene su fuente.")

    def _gauge_svg(valor_txt: str, pct: float, color_hex: str = "#16a34a") -> str:
        """Dibuja un medidor de media torta (0-100%) en SVG puro, sin librerías
        externas — funciona igual en Streamlit Cloud sin instalar nada nuevo."""
        circunferencia = 251.2  # longitud del semicírculo (radio 80)
        offset = circunferencia * (1 - max(0, min(pct, 100)) / 100)
        return f'''
        <svg viewBox="0 0 200 120" style="width:100%;max-width:170px;">
            <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none"
                  stroke="#e5e7eb" stroke-width="16" stroke-linecap="round"/>
            <path d="M 20 100 A 80 80 0 0 1 180 100" fill="none"
                  stroke="{color_hex}" stroke-width="16" stroke-linecap="round"
                  stroke-dasharray="{circunferencia}" stroke-dashoffset="{offset}"/>
            <text x="100" y="88" text-anchor="middle"
                  style="font-size:24px;font-weight:700;fill:#14532d;">{valor_txt}</text>
        </svg>'''

    INDICADORES_COMUNA2 = [
        {"valor": "99.4%", "pct": 99.4, "color": "#16a34a",
         "titulo": "Cobertura de recolección", "fuente": "Meta 2026 · Emvarias 2025-2027"},
        {"valor": "100%", "pct": 100, "color": "#16a34a",
         "titulo": "Frecuencias cumplidas", "fuente": "Meta permanente · Emvarias"},
        {"valor": "0/7", "pct": 0, "color": "#dc2626",
         "titulo": "Puntos Naranja en la comuna", "fuente": "De los 7 oficiales en Medellín"},
        {"valor": "11/11", "pct": 100, "color": "#16a34a",
         "titulo": "Barrios con horario confirmado", "fuente": "Doc. oficial Emvarias 2024"},
    ]

    cols_gauge = st.columns(4)
    for col, ind in zip(cols_gauge, INDICADORES_COMUNA2):
        with col:
            st.markdown(
                f'<div style="background:#ffffff;border:1px solid #bbf7d0;border-radius:12px;'
                f'padding:12px;text-align:center;">'
                f'{_gauge_svg(ind["valor"], ind["pct"], ind["color"])}'
                f'<p style="font-size:13px;color:#166534;margin:4px 0 0;font-weight:600;">{ind["titulo"]}</p>'
                f'<p style="font-size:11px;color:#6b7280;margin:2px 0 0;">{ind["fuente"]}</p>'
                f'</div>', unsafe_allow_html=True)

    with st.expander("Ver hallazgos completos de la investigación"):
        st.markdown("""
- **Cobertura formal completa, pero actualización desigual**: los 11 barrios tienen horario
  oficial asignado; 9 de 11 siguen con franja amplia de 8h (miércoles y sábado, 3-11pm),
  solo La Rosa y Moscú N°1 tienen franja angostada a 2h (lunes y jueves, 7-9pm) desde jun. 2026.
- **Cero infraestructura oficial de reciclaje**: de los 7 Puntos Naranja de toda Medellín,
  ninguno está dentro de la comuna 2 (lista oficial Emvarias).
- **El aprovechamiento depende de actores informales**: recicladores de oficio y bodegas
  sin nombre propio verificado — no hay cooperativa ni Punto Naranja confirmado en la zona.
- **Comuna señalada oficialmente como zona de alto crecimiento de residuos**: comunas 1, 2,
  3 y 4 (nororiente) identificadas por la Secretaría de Medio Ambiente (2025-2026).
- **El problema ya estaba documentado desde 2016**: convenio Emvarias-Sec. Medio Ambiente
  para puntos críticos en comunas 2, 8, 9, 11 y 13 ($36,242,515 COP). Villa Niza estuvo
  activo 6 años antes de ser recuperado en 2026.
- **Condiciones socioeconómicas**: comuna más densamente poblada de Medellín (502 hab./ha,
  110,202 hab.), con parte del suelo clasificado como zona de riesgo.

*Fuentes: Emvarias (Horarios y Frecuencias 2024, Puntos Naranja, Programa de Prestación
del Servicio de Aseo 2025-2027), Alcaldía de Medellín, Seguimiento PGIRS 2016.*
""")

    st.markdown("---")
    st.markdown("""
<div style="background:rgba(16,185,129,0.06);border:1px solid rgba(74,222,128,0.2);
border-radius:10px;padding:16px;text-align:center;color:#9ca3af;font-size:13px;">
<b style="color:#4ade80">EcoCom2 Circular IA v7.0</b><br>
Proyecto <b style="color:#4ade80">Territorio INN 2026</b> · Instituto Tecnológico Metropolitano (ITM) · Medellín<br>
Desarrollado por: <b style="color:#4ade80">Brandon Duque</b> · Comuna 2 Santa Cruz
</div>
""", unsafe_allow_html=True)
