# -*- coding: utf-8 -*-
"""
EcoCom2 Circular IA — v8.0 (Edición Automatizada & Asistente Inteligente)
Gestión inteligente y participativa de residuos sólidos — Comuna 2 (Santa Cruz), Medellín.
Proyecto Territorio INN 2026 | ITM Medellín | Dev: Brandon Duque (stivenduque09)

Mejoras clave en v8.0:
1. Seguridad reforzada: Autenticación Admin mediante SHA-256 + hmac.compare_digest desde st.secrets y bloqueo anti-fuerza bruta.
2. Base de datos SQLite concurrente: Modo WAL (Write-Ahead Logging) + busy_timeout=30000ms + miniaturas persistentes en respaldo GitHub.
3. Persistencia Ciudadana en Navegador: Sincronización automática con localStorage (vía streamlit_js_eval) de ubicación y "Mi Historial".
4. Automatización en 1 Toque: Autoverificación al tocar el mapa dentro del polígono de la Comuna 2, detección de barrio por cercanía,
   alerta automática del horario de recolección de Emvarias y prellenado completo del formulario con Visión IA (YOLOE + Gemini fallback).
5. Asistente EcoBot IA 2.0 (Agente Conversacional y Accionable):
   - Crea o prellena reportes desde lenguaje natural (extrae barrio, tipo de residuo, criticidad y referencia).
   - Permite subir una foto directamente en el asistente para que EcoBot analice y publique el reporte sin llenar formularios.
   - Consulta el estado en vivo de cualquier código (ECO-...) y permite confirmar reportes desde el chat.
   - Informa horarios exactos de recolección Emvarias por barrio y rutas de economía circular / voluminosos.
6. Rendimiento Optimizado: Uso de @st.fragment, @st.dialog y carga diferida (@st.cache_resource) para evitar recargas completas.
"""

from __future__ import annotations

import base64
import difflib
import hashlib
import hmac
import json
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from io import BytesIO
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
import imagehash
import openpyxl
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pandas as pd
from folium.plugins import HeatMap
from PIL import ExifTags, Image, ImageDraw, ImageFilter
from shapely.geometry import Point, Polygon

import streamlit as st
from streamlit_folium import st_folium

try:
    from streamlit_js_eval import get_geolocation, streamlit_js_eval
    HAS_JS_EVAL = True
except ImportError:
    HAS_JS_EVAL = False
    def get_geolocation(*args, **kwargs):
        return None
    def streamlit_js_eval(*args, **kwargs):
        return None

# ==============================================================================
# 1. CONFIGURACIÓN DE PÁGINA Y CONSTANTES TERRITORIALES (COMUNA 2 - SANTA CRUZ)
# ==============================================================================
st.set_page_config(
    page_title="EcoCom2 Circular IA | Comuna 2 Santa Cruz",
    page_icon="♻️",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_VERSION = "v8.0"
LIMITE_REPORTES_DIA = 8
MAX_INTENTOS_ADMIN = 5
BLOQUEO_ADMIN_SEGUNDOS = 300  # 5 minutos de bloqueo tras intentos fallidos
LOCALSTORAGE_KEY = "ecocom2_ciudadano_v8"

# Polígono oficial aproximado de la Comuna 2 (Santa Cruz), Medellín (lon, lat)
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
    (-75.5613, 6.2933),
])

CENTRO_COMUNA2 = (6.2985, -75.5555)

BARRIOS: List[str] = [
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

# Coordenadas centrales de referencia para cada barrio de la Comuna 2 (lat, lon)
COORDENADAS_BARRIOS: Dict[str, Tuple[float, float]] = {
    "La Isla": (6.2968, -75.5582),
    "Playón de los Comuneros": (6.3045, -75.5558),
    "Pablo VI": (6.3018, -75.5545),
    "La Frontera": (6.3068, -75.5548),
    "La Francia": (6.2995, -75.5535),
    "Andalucía": (6.2975, -75.5568),
    "Villa del Socorro": (6.3012, -75.5572),
    "Villa Niza": (6.2938, -75.5585),
    "Moscú No. 1": (6.2918, -75.5532),
    "Santa Cruz": (6.2952, -75.5552),
    "La Rosa": (6.2935, -75.5522),
}

# Horarios oficiales de recolección por barrio (Emvarias - Comuna 2)
HORARIOS_RECOLECCION: Dict[str, Dict[str, Any]] = {
    "La Rosa": {
        "dias": "Lunes y jueves",
        "dias_num": [0, 3],  # 0=Lunes, 3=Jueves
        "franja": "7:00 p.m. – 9:00 p.m.",
        "nota": "Franja ajustada desde el 4 de junio de 2026. Saca los residuos máximo 1 hora antes.",
    },
    "Moscú No. 1": {
        "dias": "Lunes y jueves",
        "dias_num": [0, 3],
        "franja": "7:00 p.m. – 9:00 p.m.",
        "nota": "Cambió de miércoles/sábado a lunes/jueves desde junio de 2026.",
    },
    "Andalucía": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],  # 2=Miércoles, 5=Sábado
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna. Evita dejar bolsas en esquinas fuera de este horario.",
    },
    "Playón de los Comuneros": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna por vías principales y puntos de acopio.",
    },
    "La Francia": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
    "La Frontera": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
    "La Isla": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
    "Pablo VI": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
    "Santa Cruz": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
    "Villa del Socorro": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
    "Villa Niza": {
        "dias": "Miércoles y sábado",
        "dias_num": [2, 5],
        "franja": "3:00 p.m. – 11:00 p.m.",
        "nota": "Recolección vespertina/nocturna.",
    },
}

# ==============================================================================
# 2. CONSTANTES DE INTELIGENCIA ARTIFICIAL Y VISIÓN POR COMPUTADORA
# ==============================================================================
CLASES_DETECCION: List[str] = [
    # Reciclables típicos
    "plastic bottle", "plastic cup", "plastic chair", "plastic bench",
    "plastic bucket", "plastic bowl", "colorful plastic children toy", "frisbee",
    "garbage bag", "backpack", "suitcase", "book", "newspaper",
    "cardboard box", "glass bottle", "glass jar", "aluminum can",
    "knife", "fork", "spoon", "scissors", "cell phone", "laptop",
    "keyboard", "computer mouse", "remote control", "television",
    "clock", "banana", "apple", "orange", "broccoli", "carrot",
    "potted plant", "food waste", "wooden table", "couch", "bed",
    "umbrella", "tie",
    # Objetos comunes en la comuna
    "wooden chair", "wooden stool", "broken wooden furniture",
    "mattress", "construction rubble", "pile of rubble",
    "pile of garbage bags", "scrap metal", "black rubber car tire",
    "broken appliance", "styrofoam waste", "pile of plastic bags",
    "wood planks", "broken glass", "electronic waste",
    "abandoned furniture", "cardboard boxes pile",
    # Distractores
    "person", "dog", "cat", "car", "bus", "truck", "bicycle",
    "motorcycle", "traffic light", "stop sign", "bird", "toothbrush",
]

CLASES_DISTRACTORAS = {
    "person", "dog", "cat", "car", "bus", "truck", "bicycle",
    "motorcycle", "traffic light", "stop sign", "bird", "toothbrush",
}

MAPA_MATERIALES_ES: Dict[str, Tuple[str, float, bool]] = {
    # clase_en: (Nombre en español, peso estimado unitario en kg, es_reciclable)
    "plastic bottle": ("Botellas plásticas (PET)", 0.15, True),
    "plastic cup": ("Vasos y envases plásticos", 0.08, True),
    "plastic bucket": ("Baldes / recipientes plásticos", 0.8, True),
    "pile of plastic bags": ("Bolsas plásticas acumuladas", 2.5, True),
    "cardboard box": ("Cajas de cartón", 0.9, True),
    "cardboard boxes pile": ("Pila de cartón reciclable", 4.5, True),
    "newspaper": ("Papel y periódico", 0.4, True),
    "book": ("Papel / libros", 0.6, True),
    "glass bottle": ("Botellas de vidrio", 0.4, True),
    "glass jar": ("Frascos de vidrio", 0.35, True),
    "broken glass": ("Vidrio roto", 1.2, True),
    "aluminum can": ("Latas de aluminio / chatarra ligera", 0.1, True),
    "scrap metal": ("Chatarra metálica", 6.0, True),
    "garbage bag": ("Bolsas de basura domiciliaria", 3.5, False),
    "pile of garbage bags": ("Acumulación de bolsas de basura", 14.0, False),
    "food waste": ("Residuos orgánicos / comida", 2.0, False),
    "mattress": ("Colchón abandonado (Voluminoso)", 22.0, False),
    "couch": ("Sofá / mueble abandonado (Voluminoso)", 28.0, False),
    "bed": ("Base de cama / madera (Voluminoso)", 25.0, False),
    "abandoned furniture": ("Muebles abandonados (Voluminoso)", 20.0, False),
    "broken wooden furniture": ("Muebles de madera rotos", 15.0, False),
    "wood planks": ("Tablas y residuos de madera", 8.0, False),
    "construction rubble": ("Escombros de construcción (RCD)", 35.0, False),
    "pile of rubble": ("Acumulación crítica de escombros (RCD)", 55.0, False),
    "black rubber car tire": ("Llantas abandonadas", 9.0, False),
    "broken appliance": ("Electrodomésticos / RAEE", 12.0, True),
    "electronic waste": ("Residuos electrónicos (RAEE)", 5.0, True),
    "television": ("Televisor / pantalla abandonada (RAEE)", 10.0, True),
    "styrofoam waste": ("Icopor / poliestireno", 1.0, False),
}

MODELOS_GEMINI_RESPALDO: List[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
]

# ==============================================================================
# 3. ESTILOS CSS MODERNOS Y RESPONSIVOS (MOBILE-FIRST)
# ==============================================================================
def inyectar_estilos_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --eco-green: #10b981;
            --eco-dark: #065f46;
            --eco-bg: #f0fdf4;
            --eco-red: #ef4444;
            --eco-yellow: #f59e0b;
        }
        .block-container {
            padding-top: 1.2rem !important;
            padding-bottom: 2.5rem !important;
            max-width: 1280px;
        }
        .eco-hero {
            background: linear-gradient(135deg, #064e3b 0%, #047857 60%, #10b981 100%);
            color: white;
            padding: 1.1rem 1.4rem;
            border-radius: 16px;
            margin-bottom: 1rem;
            box-shadow: 0 6px 18px rgba(6, 78, 59, 0.15);
        }
        .eco-hero h1 {
            margin: 0;
            font-size: 1.65rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }
        .eco-hero p {
            margin: 0.3rem 0 0 0;
            font-size: 0.95rem;
            opacity: 0.92;
        }
        .badge-ok {
            display: inline-block;
            background: #d1fae5;
            color: #065f46;
            padding: 0.28rem 0.75rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.84rem;
            border: 1px solid #6ee7b7;
        }
        .badge-warn {
            display: inline-block;
            background: #fef3c7;
            color: #92400e;
            padding: 0.28rem 0.75rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.84rem;
            border: 1px solid #fcd34d;
        }
        .badge-err {
            display: inline-block;
            background: #fee2e2;
            color: #991b1b;
            padding: 0.28rem 0.75rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.84rem;
            border: 1px solid #fca5a5;
        }
        .eco-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 14px;
            padding: 1rem 1.15rem;
            margin-bottom: 0.85rem;
            box-shadow: 0 2px 6px rgba(15, 23, 42, 0.04);
        }
        .schedule-banner {
            background: #ecfdf5;
            border-left: 5px solid #10b981;
            padding: 0.75rem 1rem;
            border-radius: 10px;
            margin: 0.5rem 0 0.9rem 0;
            font-size: 0.92rem;
            color: #064e3b;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ==============================================================================
# 4. CAPA DE BASE DE DATOS SQLITE (MODO WAL + CONCURRENCIA) Y RESPALDO GITHUB
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "ecocom2.db"

EVIDENCIAS_DIR = BASE_DIR / "evidencias_reportes"
EVIDENCIAS_CLASIFICADAS_DIR = BASE_DIR / "evidencias_clasificadas"
BACKUP_DIR = BASE_DIR / "data_backup"
for _folder in (EVIDENCIAS_DIR, EVIDENCIAS_CLASIFICADAS_DIR, BACKUP_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

RESPALDO_PATH_REPO = "data_backup/reportes_backup.json"
RESPALDO_LOCAL_PATH = BACKUP_DIR / "reportes_backup.json"

_CAMPOS_RESPALDO = [
    "codigo", "sector", "referencia", "objetos", "peso_kg",
    "predominante", "clasificacion", "lat", "lon", "fecha",
    "estado", "observaciones", "residente_codigo", "phash",
    "confirmaciones", "fecha_resuelto", "reportes_falsos",
    "foto_url", "foto_clasificada_url", "foto_resuelta_url",
    "foto_b64",  # En v8 guardamos una miniatura JPEG ultra-ligera (<18KB) para no perder evidencia visual
]


def _conectar_db() -> sqlite3.Connection:
    """Conexión SQLite segura ante concurrencia en Streamlit Cloud usando WAL."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except sqlite3.Error:
        pass
    return conn


def _crear_tabla() -> None:
    conn = _conectar_db()
    with conn:
        conn.execute(
            """
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
            """
        )
        columnas_extra = {
            "nota_voz_b64": "TEXT DEFAULT ''",
            "fotos_extra_b64": "TEXT DEFAULT '[]'",
            "residente_codigo": "TEXT DEFAULT ''",
            "phash": "TEXT DEFAULT ''",
            "confirmaciones": "INTEGER DEFAULT 1",
            "foto_clasificada_b64": "TEXT DEFAULT ''",
            "foto_resuelta_b64": "TEXT DEFAULT ''",
            "foto_resuelta_url": "TEXT DEFAULT ''",
            "fecha_resuelto": "TEXT DEFAULT ''",
            "reportes_falsos": "TEXT DEFAULT 0",
            "foto_url": "TEXT DEFAULT ''",
            "foto_clasificada_url": "TEXT DEFAULT ''",
        }
        existentes = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(reportes)").fetchall()
        }
        for col, tipo in columnas_extra.items():
            if col not in existentes:
                try:
                    conn.execute(f"ALTER TABLE reportes ADD COLUMN {col} {tipo}")
                except sqlite3.Error:
                    pass
    conn.close()


def cargar_reportes_db() -> List[Dict[str, Any]]:
    _crear_tabla()
    conn = _conectar_db()
    rows = conn.execute("SELECT * FROM reportes ORDER BY fecha DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def guardar_reporte_sqlite(rep: Dict[str, Any]) -> None:
    _crear_tabla()
    conn = _conectar_db()
    columnas = [
        "codigo", "sector", "referencia", "objetos", "peso_kg",
        "predominante", "clasificacion", "lat", "lon", "fecha",
        "estado", "foto_b64", "observaciones", "nota_voz_b64",
        "fotos_extra_b64", "residente_codigo", "phash", "confirmaciones",
        "foto_clasificada_b64", "foto_resuelta_b64", "foto_resuelta_url",
        "fecha_resuelto", "reportes_falsos", "foto_url", "foto_clasificada_url",
    ]
    valores = [
        rep.get(
            c,
            "" if c not in ("objetos", "peso_kg", "lat", "lon", "confirmaciones", "reportes_falsos") else 0,
        )
        for c in columnas
    ]
    placeholders = ", ".join(["?"] * len(columnas))
    cols_sql = ", ".join(columnas)
    with conn:
        conn.execute(
            f"INSERT OR REPLACE INTO reportes ({cols_sql}) VALUES ({placeholders})",
            valores,
        )
    conn.close()


def eliminar_reporte_sqlite(codigo: str) -> None:
    conn = _conectar_db()
    with conn:
        conn.execute("DELETE FROM reportes WHERE codigo = ?", (codigo,))
    conn.close()


def _github_config() -> Tuple[Optional[str], Optional[str], str]:
    try:
        token = st.secrets.get("GITHUB_TOKEN")
        repo = st.secrets.get("GITHUB_REPO")
        branch = st.secrets.get("GITHUB_BRANCH", "main")
        return token, repo, branch
    except Exception:
        return None, None, "main"


def comprimir_imagen_b64(img_b64: str, max_px: int = 360, quality: int = 60) -> str:
    """Genera una miniatura muy liviana (<18 KB) para conservar evidencia en el JSON de respaldo."""
    if not img_b64:
        return ""
    try:
        raw = base64.b64decode(img_b64)
        im = Image.open(BytesIO(raw)).convert("RGB")
        im.thumbnail((max_px, max_px))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception:
        return ""


def respaldar_en_github(reportes: List[Dict[str, Any]]) -> bool:
    """Guarda el respaldo local en JSON y, si hay credenciales configuradas, sincroniza con GitHub usando [skip ci]."""
    datos_limpios = []
    for r in reportes:
        item = {k: r.get(k, "") for k in _CAMPOS_RESPALDO if k != "foto_b64"}
        item["foto_b64"] = comprimir_imagen_b64(r.get("foto_b64", ""))
        datos_limpios.append(item)

    contenido_json = json.dumps(datos_limpios, ensure_ascii=False, indent=2)
    try:
        RESPALDO_LOCAL_PATH.write_text(contenido_json, encoding="utf-8")
    except Exception:
        pass

    token, repo, branch = _github_config()
    if not token or not repo:
        return False

    url = f"https://api.github.com/repos/{repo}/contents/{RESPALDO_PATH_REPO}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "EcoCom2-Circular-IA",
    }
    sha_actual = None
    try:
        req_get = urllib.request.Request(f"{url}?ref={branch}", headers=headers)
        with urllib.request.urlopen(req_get, timeout=8) as resp:
            data_get = json.loads(resp.read().decode("utf-8"))
            sha_actual = data_get.get("sha")
    except Exception:
        sha_actual = None

    payload: Dict[str, Any] = {
        "message": f"🤖 Respaldo automático EcoCom2 ({len(datos_limpios)} reportes) [skip ci]",
        "content": base64.b64encode(contenido_json.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha_actual:
        payload["sha"] = sha_actual

    try:
        req_put = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="PUT",
        )
        with urllib.request.urlopen(req_put, timeout=10) as resp:
            return resp.status in (200, 201)
    except Exception:
        return False


def restaurar_desde_github_si_vacio() -> List[Dict[str, Any]]:
    """Si SQLite está vacío tras un reinicio del contenedor, restaura desde el archivo local o GitHub."""
    actuales = cargar_reportes_db()
    if actuales:
        return actuales

    # 1. Intentar desde data_backup/reportes_backup.json local en el repositorio clonado
    if RESPALDO_LOCAL_PATH.exists():
        try:
            datos = json.loads(RESPALDO_LOCAL_PATH.read_text(encoding="utf-8"))
            if isinstance(datos, list) and datos:
                for rep in datos:
                    guardar_reporte_sqlite(rep)
                return cargar_reportes_db()
        except Exception:
            pass

    # 2. Intentar desde la API de GitHub
    token, repo, branch = _github_config()
    if token and repo:
        url = f"https://api.github.com/repos/{repo}/contents/{RESPALDO_PATH_REPO}?ref={branch}"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "EcoCom2-Circular-IA",
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                info = json.loads(resp.read().decode("utf-8"))
                raw_json = base64.b64decode(info["content"]).decode("utf-8")
                datos = json.loads(raw_json)
                if isinstance(datos, list):
                    for rep in datos:
                        guardar_reporte_sqlite(rep)
                    return cargar_reportes_db()
        except Exception:
            pass
    return []


# ==============================================================================
# 5. GEOLOCALIZACIÓN, AUTODETECCIÓN DE BARRIO Y HORARIOS AUTOMÁTICOS
# ==============================================================================
def distancia_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2.0) ** 2
    return 2.0 * R * atan2(sqrt(a), sqrt(1.0 - a))


def esta_en_comuna2(lat: float, lon: float) -> bool:
    """Verifica si el punto (lat, lon) cae dentro del polígono de la Comuna 2 (con margen de tolerancia de 120m)."""
    punto = Point(lon, lat)
    if POLIGONO_COMUNA2.contains(punto):
        return True
    return POLIGONO_COMUNA2.buffer(0.0011).contains(punto)


def detectar_barrio_cercano(lat: float, lon: float) -> str:
    """Devuelve el barrio de la Comuna 2 más cercano a las coordenadas dadas."""
    mejor_barrio = "Santa Cruz"
    menor_dist = float("inf")
    for barrio, (blat, blon) in COORDENADAS_BARRIOS.items():
        d = distancia_metros(lat, lon, blat, blon)
        if d < menor_dist:
            menor_dist = d
            mejor_barrio = barrio
    return mejor_barrio


def info_horario_barrio(barrio: str) -> Dict[str, Any]:
    """Obtiene el horario de recolección del barrio e indica si hoy pasa el camión."""
    info = HORARIOS_RECOLECCION.get(
        barrio,
        {
            "dias": "Miércoles y sábado",
            "dias_num": [2, 5],
            "franja": "3:00 p.m. – 11:00 p.m.",
            "nota": "Horario general Comuna 2.",
        },
    )
    hoy_num = datetime.now().weekday()
    pasa_hoy = hoy_num in info["dias_num"]
    return {
        **info,
        "barrio": barrio,
        "pasa_hoy": pasa_hoy,
        "mensaje_hoy": (
            f"🚛 ¡HOY pasa el camión recolector en **{barrio}** ({info['franja']})!"
            if pasa_hoy
            else f"📅 Próxima recolección en **{barrio}**: **{info['dias']}** de **{info['franja']}**."
        ),
    }


def geocodificar_direccion_comuna2(texto: str) -> Tuple[Optional[float], Optional[float], str, bool]:
    """
    Geocodifica una dirección o nombre de barrio en la Comuna 2.
    Primero intenta coincidencia inteligente con barrios y nomenclatura local (Calles 98 a 126, Carreras 49 a 56),
    y como respaldo consulta Nominatim restringido a Medellín.
    """
    texto_limpio = texto.strip()
    if not texto_limpio:
        return None, None, "", False

    norm = unicodedata.normalize("NFKD", texto_limpio.lower()).encode("ascii", "ignore").decode("utf-8")

    # 1. Detectar si menciona directamente alguno de los 11 barrios
    barrio_detectado = None
    for b in BARRIOS:
        b_norm = unicodedata.normalize("NFKD", b.lower()).encode("ascii", "ignore").decode("utf-8")
        if b_norm in norm or difflib.SequenceMatcher(None, b_norm, norm).ratio() > 0.78:
            barrio_detectado = b
            break

    # 2. Extraer números de Calle (cll/calle 97 a 127) y Carrera (cra/kr 48 a 58) típicos de Comuna 2
    patron_cll = re.search(r"(?:calle|cll|cl|c)\s*(\d{2,3})", norm)
    patron_cra = re.search(r"(?:carrera|cra|kr|cr|k|#)\s*(\d{2,3})", norm)
    if patron_cll:
        num_calle = int(patron_cll.group(1))
        num_cra = int(patron_cra.group(1)) if patron_cra else 52
        if 96 <= num_calle <= 128 and 46 <= num_cra <= 60:
            lat_est = 6.2895 + ((num_calle - 96) / 32.0) * (6.3095 - 6.2895)
            lon_est = -75.5498 - ((num_cra - 46) / 14.0) * (75.5610 - 75.5498)
            barrio_est = barrio_detectado or detectar_barrio_cercano(lat_est, lon_est)
            return round(lat_est, 6), round(lon_est, 6), barrio_est, True

    if barrio_detectado:
        lat_b, lon_b = COORDENADAS_BARRIOS[barrio_detectado]
        return lat_b, lon_b, barrio_detectado, True

    # 3. Consulta Nominatim (OpenStreetMap) acotada a Medellín
    try:
        query = urllib.parse.quote(f"{texto_limpio}, Santa Cruz, Medellín, Colombia")
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "EcoCom2-Circular-IA/8.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            resultados = json.loads(resp.read().decode("utf-8"))
            if resultados:
                lat_n = float(resultados[0]["lat"])
                lon_n = float(resultados[0]["lon"])
                dentro = esta_en_comuna2(lat_n, lon_n)
                barrio_n = detectar_barrio_cercano(lat_n, lon_n) if dentro else "Fuera de Comuna 2"
                return lat_n, lon_n, barrio_n, dentro
    except Exception:
        pass

    return None, None, "", False


# ==============================================================================
# 6. PERSISTENCIA EN NAVEGADOR (LOCALSTORAGE) Y SEGURIDAD ADMIN
# ==============================================================================
def sincronizar_estado_localstorage(guardar: bool = False) -> None:
    """Guarda o recupera la verificación del vecino y sus códigos de reporte en el navegador."""
    if not HAS_JS_EVAL:
        return
    try:
        if guardar:
            payload = json.dumps({
                "validado": bool(st.session_state.get("validado", False)),
                "lat": st.session_state.get("lat", CENTRO_COMUNA2[0]),
                "lon": st.session_state.get("lon", CENTRO_COMUNA2[1]),
                "direccion": st.session_state.get("direccion", ""),
                "barrio_actual": st.session_state.get("barrio_actual", "Santa Cruz"),
                "mis_codigos": st.session_state.get("mis_codigos", []),
                "residente_codigo": st.session_state.get("residente_codigo", ""),
                "tutorial_visto": bool(st.session_state.get("tutorial_visto", False)),
            })
            js_code = f"localStorage.setItem('{LOCALSTORAGE_KEY}', JSON.stringify({payload}));"
            streamlit_js_eval(js_expressions=js_code, key=f"ls_save_{int(time.time() * 1000) % 100000}")
        elif not st.session_state.get("ls_cargado", False):
            st.session_state.ls_cargado = True
            raw = streamlit_js_eval(
                js_expressions=f"localStorage.getItem('{LOCALSTORAGE_KEY}')",
                key="ls_load_init",
            )
            if raw and isinstance(raw, str):
                datos = json.loads(raw)
                if isinstance(datos, dict):
                    if datos.get("validado"):
                        st.session_state.validado = True
                        st.session_state.fuera = False
                        st.session_state.lat = float(datos.get("lat", CENTRO_COMUNA2[0]))
                        st.session_state.lon = float(datos.get("lon", CENTRO_COMUNA2[1]))
                        st.session_state.direccion = datos.get("direccion", "")
                        st.session_state.barrio_actual = datos.get("barrio_actual", "Santa Cruz")
                    if datos.get("mis_codigos"):
                        st.session_state.mis_codigos = list(set(st.session_state.mis_codigos + datos["mis_codigos"]))
                    if datos.get("residente_codigo"):
                        st.session_state.residente_codigo = datos["residente_codigo"]
                    if datos.get("tutorial_visto"):
                        st.session_state.tutorial_visto = True
    except Exception:
        pass


def verificar_credenciales_admin(password_ingresada: str) -> Tuple[bool, str]:
    """
    Verifica la contraseña de administrador sin exponer texto plano en el código fuente.
    Soporta `ADMIN_PASS_SHA256` o `ADMIN_PASSWORD` en `st.secrets` o variable de entorno,
    con protección contra fuerza bruta.
    """
    ahora = time.time()
    bloqueado_hasta = st.session_state.get("admin_bloqueado_hasta", 0.0)
    if ahora < bloqueado_hasta:
        restante = int(bloqueado_hasta - ahora)
        return False, f"⏳ Demasiados intentos fallidos. Intenta de nuevo en {restante} segundos."

    if not password_ingresada:
        return False, "Ingresa la contraseña de administrador."

    hash_ingresado = hashlib.sha256(password_ingresada.encode("utf-8")).hexdigest()

    hash_configurado = ""
    try:
        if "ADMIN_PASS_SHA256" in st.secrets:
            hash_configurado = str(st.secrets["ADMIN_PASS_SHA256"]).strip().lower()
        elif "ADMIN_PASSWORD" in st.secrets:
            pwd_sec = str(st.secrets["ADMIN_PASSWORD"])
            hash_configurado = hashlib.sha256(pwd_sec.encode("utf-8")).hexdigest()
    except Exception:
        pass

    if not hash_configurado:
        env_hash = os.environ.get("ECOCOM2_ADMIN_HASH", "").strip().lower()
        if env_hash:
            hash_configurado = env_hash

    if not hash_configurado:
        return (
            False,
            "⚠️ Configura `ADMIN_PASS_SHA256` o `ADMIN_PASSWORD` en `.streamlit/secrets.toml` para habilitar el Panel Admin de forma segura.",
        )

    es_valido = hmac.compare_digest(hash_ingresado, hash_configurado)
    if es_valido:
        st.session_state.admin_intentos = 0
        return True, "✅ Acceso administrativo concedido."
    else:
        intentos = st.session_state.get("admin_intentos", 0) + 1
        st.session_state.admin_intentos = intentos
        if intentos >= MAX_INTENTOS_ADMIN:
            st.session_state.admin_bloqueado_hasta = ahora + BLOQUEO_ADMIN_SEGUNDOS
            return False, "🚫 Cuenta bloqueada temporalmente por 5 minutos tras múltiples intentos fallidos."
        restantes = MAX_INTENTOS_ADMIN - intentos
        return False, f"❌ Contraseña incorrecta. Intentos restantes: {restantes}."


# ==============================================================================
# 7. MOTOR DE VISIÓN IA (YOLOE + GEMINI FALLBACK) Y ANONIMIZACIÓN DE PERSONAS
# ==============================================================================
@st.cache_resource(show_spinner=False)
def cargar_modelo_yolo():
    """Carga diferida y en caché del modelo YOLOE/YOLO para no saturar la RAM de Streamlit Cloud."""
    try:
        from ultralytics import YOLOE
        modelo = YOLOE("yoloe-11s-seg.pt")
        modelo.set_classes(CLASES_DETECCION, modelo.get_text_pe(CLASES_DETECCION))
        return modelo
    except Exception:
        try:
            from ultralytics import YOLO
            return YOLO("yolov8n.pt")
        except Exception:
            return None


def preparar_imagen_memoria(archivo_bytes: bytes, max_dim: int = 1024) -> Tuple[Image.Image, Dict[str, Any]]:
    """Extrae EXIF antes de redimensionar y optimiza el tamaño en memoria para inferencia rápida."""
    img_original = Image.open(BytesIO(archivo_bytes))
    exif_info: Dict[str, Any] = {"tiene_exif": False, "dias_antiguedad": 0, "reciente": True}
    try:
        raw_exif = img_original._getexif()
        if raw_exif:
            for tag_id, valor in raw_exif.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                if tag in ("DateTimeOriginal", "DateTime"):
                    fecha_foto = datetime.strptime(str(valor)[:19], "%Y:%m:%d %H:%M:%S")
                    dias = (datetime.now() - fecha_foto).days
                    exif_info["tiene_exif"] = True
                    exif_info["dias_antiguedad"] = max(0, dias)
                    exif_info["reciente"] = dias <= 20
                    break
    except Exception:
        pass

    img_rgb = img_original.convert("RGB")
    img_rgb.thumbnail((max_dim, max_dim))
    return img_rgb, exif_info


def difuminar_personas(img: Image.Image, cajas_personas: List[Tuple[int, int, int, int]]) -> Image.Image:
    """Aplica desenfoque gaussiano intenso sobre cualquier persona detectada para proteger su privacidad."""
    if not cajas_personas:
        return img
    copia = img.copy()
    for (x1, y1, x2, y2) in cajas_personas:
        x1, y1 = max(0, int(x1)), max(0, int(y1))
        x2, y2 = min(copia.width, int(x2)), min(copia.height, int(y2))
        if x2 > x1 and y2 > y1:
            recorte = copia.crop((x1, y1, x2, y2))
            recorte_blur = recorte.filter(ImageFilter.GaussianBlur(radius=18))
            copia.paste(recorte_blur, (x1, y1))
    return copia


def clasificar_nivel_criticidad(objetos: int, peso_kg: float, ratio_reciclable: float, tiene_escombros_o_voluminosos: bool) -> str:
    """Determina el nivel del semáforo ambiental de EcoCom2."""
    if tiene_escombros_o_voluminosos or objetos >= 30 or peso_kg >= 50.0 or (objetos >= 8 and ratio_reciclable < 0.30):
        return "🔴 Punto Crítico"
    if ratio_reciclable >= 0.60 and peso_kg < 25.0:
        return "🟢 Punto Verde (Aprovechable)"
    return "🟡 Punto Amarillo (Acumulación Moderada)"


def analizar_imagen_con_gemini_fallback(img: Image.Image) -> Optional[Dict[str, Any]]:
    """Respaldo automático con la API de Gemini si YOLOE no está disponible o no detecta objetos claros."""
    api_key = None
    try:
        api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
    except Exception:
        api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return None

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=80)
    b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

    prompt = (
        "Analiza esta fotografía tomada en la Comuna 2 de Medellín para gestión de residuos sólidos. "
        "Responde ÚNICAMENTE con un objeto JSON válido con las siguientes claves exactas: "
        '{"objetos": int, "peso_kg": float, "predominante": str, "ratio_reciclable": float, '
        '"es_critico": bool, "recomendacion_ciudadana": str}.'
    )

    for modelo in MODELOS_GEMINI_RESPALDO:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1},
        }
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                texto_resp = data["candidates"][0]["content"]["parts"][0]["text"]
                match_json = re.search(r"\{.*\}", texto_resp, re.DOTALL)
                if match_json:
                    parsed = json.loads(match_json.group(0))
                    return parsed
        except Exception:
            continue
    return None


def procesar_evidencia_ia(img: Image.Image) -> Dict[str, Any]:
    """
    Ejecuta el pipeline completo de Visión IA:
    1. Detecta objetos y personas con YOLOE.
    2. Anonimiza personas automáticamente (`difuminar_personas`).
    3. Calcula peso estimado, material predominante y clasificación semafórica.
    4. Si no detecta objetos con YOLOE, consulta Gemini Vision como respaldo.
    """
    modelo = cargar_modelo_yolo()
    cajas_personas: List[Tuple[int, int, int, int]] = []
    conteo_clases: Counter = Counter()
    img_anotada = img.copy()

    if modelo is not None:
        try:
            resultados = modelo.predict(img, conf=0.25, verbose=False)
            if resultados and len(resultados) > 0:
                res = resultados[0]
                nombres = res.names
                boxes = res.boxes
                draw = ImageDraw.Draw(img_anotada)
                if boxes is not None:
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        nombre_clase = nombres.get(cls_id, "unknown")
                        coords = box.xyxy[0].tolist()
                        x1, y1, x2, y2 = [int(v) for v in coords]
                        if nombre_clase == "person":
                            cajas_personas.append((x1, y1, x2, y2))
                        elif nombre_clase not in CLASES_DISTRACTORAS:
                            conteo_clases[nombre_clase] += 1
                            draw.rectangle([x1, y1, x2, y2], outline="#10b981", width=3)
        except Exception:
            pass

    img_privada = difuminar_personas(img, cajas_personas)
    img_anotada = difuminar_personas(img_anotada, cajas_personas)

    if sum(conteo_clases.values()) > 0:
        total_obj = sum(conteo_clases.values())
        peso_total = 0.0
        reciclables_cnt = 0
        pesos_por_material: Counter = Counter()
        tiene_criticos = False

        for clase_en, cantidad in conteo_clases.items():
            nombre_es, peso_unit, es_recic = MAPA_MATERIALES_ES.get(
                clase_en, ("Residuos mixtos domiciliarios", 1.5, False)
            )
            peso_item = round(cantidad * peso_unit, 2)
            peso_total += peso_item
            pesos_por_material[nombre_es] += peso_item
            if es_recic:
                reciclables_cnt += cantidad
            if clase_en in ("mattress", "construction rubble", "pile of rubble", "couch", "abandoned furniture", "black rubber car tire"):
                tiene_criticos = True

        predominante = pesos_por_material.most_common(1)[0][0]
        ratio_recic = reciclables_cnt / max(1, total_obj)
        clasificacion = clasificar_nivel_criticidad(total_obj, peso_total, ratio_recic, tiene_criticos)
        recomendacion = (
            "Material con alto potencial de aprovechamiento circular. Separa seco y limpio para los recuperadores del sector."
            if "Verde" in clasificacion
            else (
                "Punto de alta prioridad (escombros/voluminosos). Requiere recolección especial de Emvarias (Línea Amiga 604 444 56 36)."
                if "Crítico" in clasificacion
                else "Acumulación mixta. Evita sacar bolsas fuera de la franja horaria oficial de tu barrio."
            )
        )
    else:
        res_gemini = analizar_imagen_con_gemini_fallback(img_privada)
        if res_gemini:
            total_obj = max(1, int(res_gemini.get("objetos", 4)))
            peso_total = round(float(res_gemini.get("peso_kg", 8.5)), 1)
            predominante = str(res_gemini.get("predominante", "Bolsas de basura domiciliaria"))
            ratio_recic = float(res_gemini.get("ratio_reciclable", 0.35))
            es_crit = bool(res_gemini.get("es_critico", False))
            clasificacion = clasificar_nivel_criticidad(total_obj, peso_total, ratio_recic, es_crit)
            recomendacion = str(res_gemini.get("recomendacion_ciudadana", "Verifica el horario de recolección de tu barrio."))
        else:
            total_obj = 5
            peso_total = 11.5
            predominante = "Bolsas de basura domiciliaria / Residuos mixtos"
            clasificacion = "🟡 Punto Amarillo (Acumulación Moderada)"
            recomendacion = "Clasificación automática base completada. Puedes ajustar el material predominante si lo deseas."

    buf_priv = BytesIO()
    img_privada.save(buf_priv, format="JPEG", quality=82)
    b64_privada = base64.b64encode(buf_priv.getvalue()).decode("utf-8")

    buf_anot = BytesIO()
    img_anotada.save(buf_anot, format="JPEG", quality=82)
    b64_anotada = base64.b64encode(buf_anot.getvalue()).decode("utf-8")

    phash_str = str(imagehash.phash(img_privada))

    return {
        "objetos": total_obj,
        "peso_kg": round(peso_total, 1),
        "predominante": predominante,
        "clasificacion": clasificacion,
        "recomendacion": recomendacion,
        "personas_difuminadas": len(cajas_personas),
        "foto_b64": b64_privada,
        "foto_clasificada_b64": b64_anotada,
        "phash": phash_str,
    }


def buscar_posible_duplicado(phash_nuevo: str, lat: float, lon: float, reportes: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Detecta si la foto ya fue subida en el mismo sitio (duplicado) o en otro lugar (>40m, foto reciclada)."""
    if not phash_nuevo:
        return None, ""
    try:
        h_new = imagehash.hex_to_hash(phash_nuevo)
    except Exception:
        return None, ""

    for rep in reportes:
        if rep.get("estado") == "Resuelto":
            continue
        ph_rep = rep.get("phash", "")
        if not ph_rep:
            continue
        try:
            dist_hash = h_new - imagehash.hex_to_hash(ph_rep)
            dist_geo = distancia_metros(lat, lon, float(rep.get("lat", 0)), float(rep.get("lon", 0)))
            if dist_hash <= 6:
                if dist_geo <= 40.0:
                    return rep, "duplicado_cercano"
                else:
                    return rep, "foto_reciclada"
        except Exception:
            continue
    return None, ""


# ==============================================================================
# 8. OPTIMIZACIÓN LOGÍSTICA DE RUTAS (TSP) Y EXPORTACIÓN EXCEL
# ==============================================================================
def optimizar_ruta_recoleccion(reportes_pendientes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Algoritmo Nearest-Neighbor dando prioridad inicial a los Puntos Críticos (🔴)."""
    if not reportes_pendientes:
        return []
    restantes = list(reportes_pendientes)
    restantes.sort(key=lambda r: (0 if "Crítico" in str(r.get("clasificacion", "")) else 1, -float(r.get("peso_kg", 0))))
    ruta = [restantes.pop(0)]
    while restantes:
        actual = ruta[-1]
        lat_a, lon_a = float(actual.get("lat", CENTRO_COMUNA2[0])), float(actual.get("lon", CENTRO_COMUNA2[1]))
        sig_idx = min(
            range(len(restantes)),
            key=lambda i: distancia_metros(lat_a, lon_a, float(restantes[i].get("lat", 0)), float(restantes[i].get("lon", 0))),
        )
        ruta.append(restantes.pop(sig_idx))
    return ruta


def generar_link_google_maps_ruta(ruta: List[Dict[str, Any]]) -> str:
    if not ruta:
        return "https://www.google.com/maps"
    puntos = [f"{r['lat']},{r['lon']}" for r in ruta[:10]]
    if len(puntos) == 1:
        return f"https://www.google.com/maps/search/?api=1&query={puntos[0]}"
    origen = puntos[0]
    destino = puntos[-1]
    waypoints = "|".join(puntos[1:-1])
    url = f"https://www.google.com/maps/dir/?api=1&origin={origen}&destination={destino}&travelmode=driving"
    if waypoints:
        url += f"&waypoints={urllib.parse.quote(waypoints)}"
    return url


def generar_excel_ejecutivo(reportes: List[Dict[str, Any]]) -> bytes:
    """Genera un informe Excel profesional con openpyxl y gráficos integrados."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Reportes Comuna 2"

    header_fill = PatternFill(start_color="065F46", end_color="065F46", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    columnas = [
        "Código", "Fecha", "Barrio / Sector", "Referencia", "Clasificación",
        "Material Predominante", "Objetos", "Peso Estimado (kg)", "Estado",
        "Confirmaciones", "Latitud", "Longitud",
    ]
    ws.append(columnas)
    for col_idx in range(1, len(columnas) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in reportes:
        ws.append([
            r.get("codigo", ""),
            r.get("fecha", ""),
            r.get("sector", ""),
            r.get("referencia", ""),
            r.get("clasificacion", ""),
            r.get("predominante", ""),
            int(r.get("objetos", 0)),
            float(r.get("peso_kg", 0.0)),
            r.get("estado", "Pendiente"),
            int(r.get("confirmaciones", 1)),
            float(r.get("lat", 0.0)),
            float(r.get("lon", 0.0)),
        ])

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(columnas)):
        for cell in row:
            cell.border = thin_border

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 3, 12), 38)

    ws_res = wb.create_sheet("Resumen por Barrio")
    ws_res.append(["Barrio", "Cantidad de Reportes", "Peso Total (kg)"])
    for c in range(1, 4):
        ws_res.cell(row=1, column=c).fill = header_fill
        ws_res.cell(row=1, column=c).font = header_font

    conteo_b: Counter = Counter()
    peso_b: Counter = Counter()
    for r in reportes:
        sec = r.get("sector") or "Santa Cruz"
        conteo_b[sec] += 1
        peso_b[sec] += float(r.get("peso_kg", 0.0))

    for b in BARRIOS:
        ws_res.append([b, conteo_b[b], round(peso_b[b], 1)])

    chart = BarChart()
    chart.title = "Peso Acumulado de Residuos por Barrio (kg)"
    chart.y_axis.title = "Kilogramos (kg)"
    chart.x_axis.title = "Barrio Comuna 2"
    data_ref = Reference(ws_res, min_col=3, min_row=1, max_row=len(BARRIOS) + 1)
    cats_ref = Reference(ws_res, min_col=1, min_row=2, max_row=len(BARRIOS) + 1)
    chart.add_data(data_ref, titles_from_data=True)
    chart.set_categories(cats_ref)
    chart.width = 18
    chart.height = 10
    ws_res.add_chart(chart, "E2")

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ==============================================================================
# 9. ASISTENTE INTELIGENTE ECOBOT IA 2.0 (CONVERSACIONAL + ACCIONES AUTOMÁTICAS)
# ==============================================================================
def analizar_mensaje_ecobot(mensaje_usuario: str, reportes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Motor inteligente de EcoBot IA 2.0:
    1. Detecta códigos de reporte (ej. ECO-C201) para consultar su estado en vivo o sumar confirmación si el vecino dice "confirmo" / "sigue ahí".
    2. Detecta descripciones en lenguaje natural de residuos en un barrio y prepara el prellenado automático.
    3. Responde sobre horarios de recolección por barrio y rutas de economía circular / voluminosos (Línea Amiga Emvarias).
    4. Se conecta con Gemini API inyectando datos en tiempo real de la Comuna 2, con respaldo local instantáneo.
    """
    msg = mensaje_usuario.strip()
    msg_norm = unicodedata.normalize("NFKD", msg.lower()).encode("ascii", "ignore").decode("utf-8")

    # A. ¿Menciona un código de reporte existente (ej. ECO-C201)?
    match_cod = re.search(r"(eco[-_]?[a-z0-9]{3,10})", msg_norm)
    if match_cod:
        cod_buscado = match_cod.group(1).upper().replace("_", "-")
        quiere_confirmar = any(p in msg_norm for p in ["confirmo", "confirmar", "sigue ahi", "todavia esta"])
        for r in reportes:
            if r.get("codigo", "").upper() == cod_buscado:
                if quiere_confirmar:
                    r["confirmaciones"] = int(r.get("confirmaciones", 1)) + 1
                    guardar_reporte_sqlite(r)
                    respaldar_en_github(reportes)
                    return {
                        "respuesta": (
                            f"👍 **¡Confirmación registrada automáticamente para `{r['codigo']}`!**\n"
                            f"- Ahora cuenta con **{r['confirmaciones']} confirmaciones vecinales** en **{r.get('sector')}**.\n"
                            f"- Esto eleva su prioridad en la ruta de recolección."
                        ),
                        "accion": None,
                    }
                info_h = info_horario_barrio(r.get("sector", "Santa Cruz"))
                return {
                    "respuesta": (
                        f"🔎 **Estado en tiempo real del reporte `{r['codigo']}`:**\n"
                        f"- **Estado actual:** `{r.get('estado', 'Pendiente')}` (👍 {r.get('confirmaciones', 1)} confirmaciones vecinales)\n"
                        f"- **Barrio:** {r.get('sector')} ({r.get('referencia', 'Sin referencia')})\n"
                        f"- **Clasificación IA:** {r.get('clasificacion')} — *{r.get('predominante')}* (~{r.get('peso_kg')} kg)\n"
                        f"- **Recolección en el sector:** {info_h['mensaje_hoy']}\n\n"
                        f"💡 *Si pasaste por ahí y sigue igual, escríbeme: `Confirmo {r['codigo']}`.*"
                    ),
                    "accion": None,
                }
        return {
            "respuesta": f"No encontré ningún reporte registrado con el código `{cod_buscado}`. Puedes ver tus códigos en la pestaña **👤 Mi Historial**.",
            "accion": None,
        }

    # B. ¿Identifica algún barrio de la Comuna 2 en el mensaje?
    barrio_mencionado = None
    for b in BARRIOS:
        b_norm = unicodedata.normalize("NFKD", b.lower()).encode("ascii", "ignore").decode("utf-8")
        if b_norm in msg_norm:
            barrio_mencionado = b
            break

    # C. ¿Tiene intención de reportar basura / escombros / colchón / punto crítico?
    palabras_reporte = [
        "reportar", "reporte", "basura", "escombro", "escombros", "colchon",
        "colchones", "mueble", "llanta", "llantas", "bolsas", "tiraron",
        "acumulacion", "punto critico", "botadero", "sucio", "vidrio", "reciclaje",
    ]
    quiere_reportar = any(p in msg_norm for p in palabras_reporte) and not any(
        q in msg_norm for q in ["como reporto", "como se reporta", "que significa", "horario", "cuando pasa", "donde llamo"]
    )

    if quiere_reportar:
        es_critico = any(p in msg_norm for p in ["escombro", "colchon", "mueble", "llanta", "critico", "botadero"])
        barrio_destino = barrio_mencionado or st.session_state.get("barrio_actual", "Santa Cruz")
        lat_dest, lon_dest = COORDENADAS_BARRIOS.get(barrio_destino, CENTRO_COMUNA2)
        info_h = info_horario_barrio(barrio_destino)

        accion_ui = {
            "tipo": "prellenar_reporte",
            "barrio": barrio_destino,
            "lat": lat_dest,
            "lon": lon_dest,
            "referencia": msg[:120],
            "seccion": "critico" if es_critico else "residuo",
        }
        return {
            "respuesta": (
                f"✅ **¡He configurado tu reporte automáticamente en {barrio_destino}!**\n"
                f"- **Ubicación verificada:** {barrio_destino} (`{lat_dest:.4f}, {lon_dest:.4f}`)\n"
                f"- **Categoría activada:** {'🚨 Punto Crítico (Escombros / Voluminosos)' if es_critico else '📸 Reporte de Residuos'}\n"
                f"- **Referencia prellenada:** *\"{msg[:100]}\"*\n"
                f"- {info_h['mensaje_hoy']}\n\n"
                "👇 **Puedes subir la foto aquí mismo abajo en el Asistente Rápido o en el formulario principal para publicarlo en 1 clic.**"
            ),
            "accion": accion_ui,
        }

    # D. ¿Pregunta por horarios de recolección?
    if any(p in msg_norm for p in ["horario", "horarios", "cuando pasa", "camion", "carro de la basura", "emvarias", "dias"]):
        if barrio_mencionado:
            h = info_horario_barrio(barrio_mencionado)
            return {
                "respuesta": (
                    f"📅 **Horario oficial en {barrio_mencionado}:**\n"
                    f"- **Días:** {h['dias']}\n"
                    f"- **Franja horaria:** {h['franja']}\n"
                    f"- **Estado hoy:** {h['mensaje_hoy']}\n"
                    f"- 💡 *{h['nota']}*"
                ),
                "accion": None,
            }
        return {
            "respuesta": (
                "📅 **Horarios de recolección Emvarias en la Comuna 2 (Santa Cruz):**\n"
                "- **La Rosa y Moscú No. 1:** Lunes y jueves de **7:00 p.m. a 9:00 p.m.**\n"
                "- **Los demás 9 barrios** (*Santa Cruz, Villa del Socorro, Andalucía, La Isla, Playón de los Comuneros, Pablo VI, La Frontera, La Francia y Villa Niza*): Miércoles y sábado de **3:00 p.m. a 11:00 p.m.**\n\n"
                "Escríbeme el nombre de tu barrio si quieres saber si hoy pasa el camión."
            ),
            "accion": None,
        }

    # E. ¿Pregunta qué hacer con colchones, escombros o reciclaje?
    if any(p in msg_norm for p in ["donde llamo", "linea amiga", "telefono", "recogen escombros", "recogen colchon"]):
        return {
            "respuesta": (
                "📞 **Ruta oficial para escombros y voluminosos (colchones, muebles, madera) en Medellín:**\n"
                "- **Línea Amiga del Aseo (Emvarias):** `(604) 444 56 36`\n"
                "- **En EcoCom2:** Repórtalo marcando **🚨 Punto Crítico** para georreferenciarlo en la ruta prioritaria de la Comuna 2."
            ),
            "accion": None,
        }

    if "rojo" in msg_norm or "amarillo" in msg_norm or "verde" in msg_norm or "colores" in msg_norm or "semaforo" in msg_norm:
        return {
            "respuesta": (
                "🚦 **Semáforo ambiental de EcoCom2 Circular IA:**\n"
                "- 🔴 **Punto Crítico (Rojo):** Escombros (RCD), colchones, muebles abandonados, ≥ 50 kg o < 30% reciclable. Prioridad máxima.\n"
                "- 🟡 **Punto Amarillo:** Acumulación moderada o bolsas domiciliarias sacadas fuera de horario (20 a 50 kg).\n"
                "- 🟢 **Punto Verde (Aprovechable):** ≥ 60% de material reciclable limpio (PET, cartón, vidrio, latas) para recuperadores del sector."
            ),
            "accion": None,
        }

    # F. Consulta con Gemini API con contexto en tiempo real de la Comuna 2
    api_key = None
    try:
        api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY")
    except Exception:
        api_key = os.environ.get("GEMINI_API_KEY")

    pendientes = [r for r in reportes if r.get("estado") != "Resuelto"]
    contexto_comuna = (
        f"Eres EcoBot IA 2.0, el asistente comunitario de EcoCom2 Circular IA en la Comuna 2 (Santa Cruz) de Medellín. "
        f"Actualmente hay {len(pendientes)} reportes activos en la comuna. "
        f"Barrio actual del vecino: {st.session_state.get('barrio_actual', 'Santa Cruz')}. "
        f"Horarios Emvarias: La Rosa y Moscú No. 1 (Lunes y jueves 7pm-9pm); resto de barrios (Miércoles y sábado 3pm-11pm). "
        f"Responde de forma cálida, breve (máximo 4 líneas) y práctica a: {msg}"
    )

    if api_key:
        for modelo in MODELOS_GEMINI_RESPALDO:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent?key={api_key}"
            payload = {"contents": [{"parts": [{"text": contexto_comuna}]}]}
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    texto = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if texto:
                        return {"respuesta": texto, "accion": None}
            except Exception:
                continue

    barrio_usr = barrio_mencionado or st.session_state.get("barrio_actual", "Santa Cruz")
    h_usr = info_horario_barrio(barrio_usr)
    return {
        "respuesta": (
            f"👋 ¡Hola! Puedo ayudarte de forma automática: escríbeme por ejemplo *\"Hay escombros en {barrio_usr} cerca al parque\"* "
            f"y llenaré el formulario y la ubicación por ti, o dime un código `ECO-...` para rastrear o confirmar un reporte.\n\n"
            f"📌 Recuerda: {h_usr['mensaje_hoy']}"
        ),
        "accion": None,
    }


# ==============================================================================
# 10. INICIALIZACIÓN DE SESSION STATE Y DATOS DEMO SEMILLA
# ==============================================================================
def inicializar_estado() -> None:
    defaults: Dict[str, Any] = {
        "lat": CENTRO_COMUNA2[0],
        "lon": CENTRO_COMUNA2[1],
        "validado": False,
        "fuera": False,
        "direccion": "",
        "barrio_actual": "Santa Cruz",
        "seccion": "residuo",
        "vista_mapa": "📍 Puntos individuales",
        "mis_codigos": [],
        "residente_codigo": f"VEC-{hashlib.md5(str(time.time()).encode()).hexdigest()[:6].upper()}",
        "admin_ok": False,
        "admin_intentos": 0,
        "admin_bloqueado_hasta": 0.0,
        "tutorial_visto": False,
        "ls_cargado": False,
        "prefill_referencia": "",
        "ultimo_analisis_ia": None,
        "ultimo_hash_archivo": "",
        "ecobot_historial": [
            {
                "role": "assistant",
                "content": (
                    "¡Hola vecino! 👋 Soy **EcoBot IA 2.0**. Escríbeme qué residuo encontraste y en qué barrio "
                    "(ej. *\"Hay colchones y basura en Villa del Socorro\"*) y **prepararé el reporte automáticamente por ti**, "
                    "o sube la foto aquí abajo para publicarlo en 1 clic."
                ),
            }
        ],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "reportes" not in st.session_state:
        cargados = restaurar_desde_github_si_vacio()
        if not cargados:
            semilla = [
                {
                    "codigo": "ECO-C201",
                    "sector": "Villa del Socorro",
                    "referencia": "Cerca a la cancha sintética calle 104",
                    "objetos": 18,
                    "peso_kg": 42.5,
                    "predominante": "Escombros de construcción (RCD)",
                    "clasificacion": "🔴 Punto Crítico",
                    "lat": 6.3014,
                    "lon": -75.5570,
                    "fecha": (datetime.now() - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M"),
                    "estado": "Pendiente",
                    "foto_b64": "",
                    "observaciones": "Acumulación de costales de escombros en esquina peatonal.",
                    "confirmaciones": 3,
                    "reportes_falsos": 0,
                    "residente_codigo": "VEC-DEMO01",
                    "phash": "",
                },
                {
                    "codigo": "ECO-C202",
                    "sector": "Santa Cruz",
                    "referencia": "Carrera 51B con Calle 100",
                    "objetos": 9,
                    "peso_kg": 6.2,
                    "predominante": "Cajas de cartón y botellas PET",
                    "clasificacion": "🟢 Punto Verde (Aprovechable)",
                    "lat": 6.2954,
                    "lon": -75.5550,
                    "fecha": (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
                    "estado": "Pendiente",
                    "foto_b64": "",
                    "observaciones": "Material reciclable limpio listo para recuperadores.",
                    "confirmaciones": 2,
                    "reportes_falsos": 0,
                    "residente_codigo": "VEC-DEMO02",
                    "phash": "",
                },
                {
                    "codigo": "ECO-C203",
                    "sector": "Moscú No. 1",
                    "referencia": "Esquina Calle 98 con Carrera 50A",
                    "objetos": 14,
                    "peso_kg": 24.0,
                    "predominante": "Bolsas de basura domiciliaria",
                    "clasificacion": "🟡 Punto Amarillo (Acumulación Moderada)",
                    "lat": 6.2920,
                    "lon": -75.5530,
                    "fecha": (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
                    "estado": "Pendiente",
                    "foto_b64": "",
                    "observaciones": "Bolsas sacadas fuera del horario de lunes y jueves.",
                    "confirmaciones": 2,
                    "reportes_falsos": 0,
                    "residente_codigo": "VEC-DEMO03",
                    "phash": "",
                },
            ]
            for s in semilla:
                guardar_reporte_sqlite(s)
            cargados = cargar_reportes_db()
        st.session_state.reportes = cargados

    sincronizar_estado_localstorage(guardar=False)


# ==============================================================================
# 11. MODALES EMERGENTES (@st.dialog): TUTORIAL Y HORARIOS
# ==============================================================================
@st.dialog("📅 Horarios Oficiales de Recolección — Comuna 2 (Emvarias)")
def mostrar_modal_horarios() -> None:
    barrio_actual = st.session_state.get("barrio_actual", "Santa Cruz")
    info_actual = info_horario_barrio(barrio_actual)
    st.markdown(f"<div class='schedule-banner'>{info_actual['mensaje_hoy']}<br><small>{info_actual['nota']}</small></div>", unsafe_allow_html=True)

    filas = []
    for b in BARRIOS:
        h = info_horario_barrio(b)
        filas.append({
            "Barrio": f"📍 {b}" if b == barrio_actual else b,
            "Días de Recolección": h["dias"],
            "Franja Horaria": h["franja"],
            "¿Pasa hoy?": "✅ Sí, hoy pasa" if h["pasa_hoy"] else "⏳ Próximo turno",
        })
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)
    st.caption("💡 Recomendación circular: saca las bolsas máximo 1 hora antes del inicio de la franja y entrega el reciclaje limpio a los recuperadores de tu cuadra.")


@st.dialog("👋 ¡Bienvenido a EcoCom2 Circular IA v8.0!")
def mostrar_modal_tutorial() -> None:
    st.markdown(
        """
        Reportar un punto de basura o material reciclable en la **Comuna 2 (Santa Cruz)** ahora toma menos de **20 segundos** y está asistido por IA:

        1. **📍 Autoverificación en 1 toque:** Toca cualquier punto dentro de la Comuna 2 en el mapa (o usa el botón **GPS**) y quedarás verificado automáticamente sin llenar formularios largos.
        2. **🤖 Habla con EcoBot IA 2.0:** Puedes decirle al asistente *"Hay escombros en La Isla cerca al colegio"* y él ubicará el barrio y llenará los datos por ti.
        3. **📸 Sube la foto y deja que la IA clasifique:** El sistema detecta automáticamente qué tipo de residuo es, calcula el peso aproximado, **difumina rostros/personas por privacidad** y te avisa cuándo pasa el camión recolector.
        4. **🤝 Validación comunitaria:** Toca cualquier punto en el mapa o dile a EcoBot `Confirmo ECO-C201` para validar que sigue ahí.
        """
    )
    if st.button("✅ ¡Entendido, empezar ahora!", type="primary", use_container_width=True):
        st.session_state.tutorial_visto = True
        sincronizar_estado_localstorage(guardar=True)
        st.rerun()


# ==============================================================================
# 12. FRAGMENTO DEL ASISTENTE ECOBOT IA 2.0 (CON REPORTE EXPRESS POR FOTO/CHAT)
# ==============================================================================
@st.fragment
def renderizar_ecobot_asistente(en_popover: bool = True) -> None:
    st.markdown("#### 🤖 EcoBot IA 2.0 — Asistente Inteligente para Vecinos")
    st.caption("Describe el problema con tus palabras, consulta un código `ECO-...` o sube una foto para que EcoBot haga el reporte por ti.")

    preguntas_rapidas = [
        "📅 ¿Cuándo pasa el camión en mi barrio?",
        "🚨 Hay escombros en Villa del Socorro",
        "♻️ Hay reciclaje limpio en Santa Cruz",
        "🔎 Estado del reporte ECO-C201",
    ]
    cols_q = st.columns(2)
    prompt_rapido = None
    for idx, q in enumerate(preguntas_rapidas):
        if cols_q[idx % 2].button(q, key=f"ecobot_q_{en_popover}_{idx}", use_container_width=True):
            prompt_rapido = q

    contenedor_chat = st.container(height=260)
    with contenedor_chat:
        for msg in st.session_state.ecobot_historial:
            with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"):
                st.markdown(msg["content"])

    col_in, col_clear = st.columns([5, 1])
    with col_in:
        entrada_txt = st.chat_input(
            "Ej: 'Hay un colchón en Moscú No. 1' o 'Confirmo ECO-C201'...",
            key=f"ecobot_input_{en_popover}",
        )
    with col_clear:
        if st.button("🗑️", key=f"ecobot_clear_{en_popover}", help="Limpiar conversación"):
            st.session_state.ecobot_historial = st.session_state.ecobot_historial[:1]
            st.rerun(scope="fragment")

    # Reporte Express guiado dentro del mismo asistente
    with st.expander("📸 Reporte Express Asistido (Sube la foto aquí y EcoBot publica por ti)"):
        barrio_exp = st.selectbox(
            "Barrio donde tomaste la foto:",
            options=BARRIOS,
            index=BARRIOS.index(st.session_state.get("barrio_actual", "Santa Cruz"))
            if st.session_state.get("barrio_actual") in BARRIOS
            else 9,
            key=f"ecobot_barrio_exp_{en_popover}",
        )
        foto_exp = st.file_uploader(
            "Adjunta la foto del residuo:",
            type=["jpg", "jpeg", "png", "webp"],
            key=f"ecobot_foto_exp_{en_popover}",
        )
        if foto_exp is not None and st.button("⚡ Analizar con IA y Publicar Ahora", key=f"ecobot_pub_exp_{en_popover}", type="primary", use_container_width=True):
            img_mem, _ = preparar_imagen_memoria(foto_exp.getvalue())
            res_ia = procesar_evidencia_ia(img_mem)
            lat_b, lon_b = COORDENADAS_BARRIOS.get(barrio_exp, CENTRO_COMUNA2)
            cod_exp = f"ECO-{int(time.time()) % 100000:05d}"
            nuevo_rep = {
                "codigo": cod_exp,
                "sector": barrio_exp,
                "referencia": f"Reporte Express vía EcoBot IA en {barrio_exp}",
                "objetos": int(res_ia["objetos"]),
                "peso_kg": float(res_ia["peso_kg"]),
                "predominante": res_ia["predominante"],
                "clasificacion": res_ia["clasificacion"],
                "lat": lat_b,
                "lon": lon_b,
                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "estado": "Pendiente",
                "foto_b64": res_ia.get("foto_b64", ""),
                "foto_clasificada_b64": res_ia.get("foto_clasificada_b64", ""),
                "observaciones": "Creado automáticamente por EcoBot IA 2.0",
                "residente_codigo": st.session_state.residente_codigo,
                "phash": res_ia.get("phash", ""),
                "confirmaciones": 1,
                "reportes_falsos": 0,
            }
            guardar_reporte_sqlite(nuevo_rep)
            st.session_state.reportes.insert(0, nuevo_rep)
            st.session_state.mis_codigos.append(cod_exp)
            st.session_state.validado = True
            st.session_state.barrio_actual = barrio_exp
            sincronizar_estado_localstorage(guardar=True)
            respaldar_en_github(st.session_state.reportes)
            st.session_state.ecobot_historial.append({
                "role": "assistant",
                "content": (
                    f"🎉 **¡He publicado tu reporte `{cod_exp}` en {barrio_exp}!**\n"
                    f"- **Diagnóstico IA:** {res_ia['clasificacion']} — *{res_ia['predominante']}* (~{res_ia['peso_kg']} kg)\n"
                    f"- **Privacidad:** {res_ia['personas_difuminadas']} rostros difuminados automáticamente."
                ),
            })
            st.rerun()

    mensaje_final = prompt_rapido or entrada_txt
    if mensaje_final:
        st.session_state.ecobot_historial.append({"role": "user", "content": mensaje_final})
        resultado = analizar_mensaje_ecobot(mensaje_final, st.session_state.reportes)
        st.session_state.ecobot_historial.append({"role": "assistant", "content": resultado["respuesta"]})

        accion = resultado.get("accion")
        if accion and accion.get("tipo") == "prellenar_reporte":
            st.session_state.lat = accion["lat"]
            st.session_state.lon = accion["lon"]
            st.session_state.barrio_actual = accion["barrio"]
            st.session_state.direccion = f"{accion['barrio']} (Autodetectado por EcoBot IA)"
            st.session_state.validado = True
            st.session_state.fuera = False
            st.session_state.prefill_referencia = accion["referencia"]
            st.session_state.seccion = accion["seccion"]
            sincronizar_estado_localstorage(guardar=True)
            st.rerun()
        else:
            st.rerun(scope="fragment")


# ==============================================================================
# 13. FRAGMENTO PRINCIPAL: MAPA INTERACTIVO + REPORTE AUTOMATIZADO CON IA
# ==============================================================================
@st.fragment
def renderizar_mapa_y_reportes() -> None:
    reportes_activos = [r for r in st.session_state.reportes if r.get("estado") != "Resuelto"]
    barrio_actual = st.session_state.get("barrio_actual", "Santa Cruz")
    info_h = info_horario_barrio(barrio_actual)

    with st.container():
        c_ver1, c_ver2, c_ver3 = st.columns([2.2, 1.3, 1.5])
        with c_ver1:
            dir_input = st.text_input(
                "📍 Tu dirección o barrio en Comuna 2 (o toca directamente el mapa abajo):",
                value=st.session_state.get("direccion", ""),
                placeholder="Ej: Calle 102 # 50-14 o Villa del Socorro",
                label_visibility="collapsed",
            )
        with c_ver2:
            if st.button("🔍 Verificar dirección", use_container_width=True):
                lat_g, lon_g, barrio_g, dentro = geocodificar_direccion_comuna2(dir_input)
                if lat_g is not None and dentro:
                    st.session_state.lat = lat_g
                    st.session_state.lon = lon_g
                    st.session_state.barrio_actual = barrio_g
                    st.session_state.direccion = dir_input
                    st.session_state.validado = True
                    st.session_state.fuera = False
                    sincronizar_estado_localstorage(guardar=True)
                    st.toast(f"✅ Ubicación verificada en {barrio_g}", icon="📍")
                else:
                    st.session_state.validado = False
                    st.session_state.fuera = True
                    st.warning("⚠️ No pudimos ubicar esa dirección dentro de la Comuna 2. Toca directamente tu cuadra en el mapa de abajo.")
        with c_ver3:
            selector_barrio = st.selectbox(
                "Ir rápido a un barrio:",
                options=["🔄 Seleccionar tu barrio en 1 clic..."] + BARRIOS,
                index=0,
                label_visibility="collapsed",
            )
            if selector_barrio != "🔄 Seleccionar tu barrio en 1 clic..." and selector_barrio != st.session_state.get("barrio_actual"):
                blat, blon = COORDENADAS_BARRIOS[selector_barrio]
                st.session_state.lat = blat
                st.session_state.lon = blon
                st.session_state.barrio_actual = selector_barrio
                st.session_state.direccion = f"Barrio {selector_barrio}, Comuna 2"
                st.session_state.validado = True
                st.session_state.fuera = False
                sincronizar_estado_localstorage(guardar=True)
                st.rerun(scope="fragment")

    st.markdown(
        f"<div class='schedule-banner'>{info_h['mensaje_hoy']} — <small>{info_h['nota']}</small></div>",
        unsafe_allow_html=True,
    )

    col_mapa, col_form = st.columns([1.35, 1.0], gap="medium")

    with col_mapa:
        c_vista, c_filtro = st.columns([1.2, 1.2])
        with c_vista:
            vista_mapa = st.radio(
                "Vista del mapa:",
                options=["📍 Puntos individuales", "🔥 Mapa de calor"],
                horizontal=True,
                label_visibility="collapsed",
            )
        with c_filtro:
            filtro_color = st.selectbox(
                "Filtrar puntos:",
                options=["Todos los puntos", "🔴 Solo Puntos Críticos", "🟢 Solo Reciclables (Punto Verde)", "🟡 Solo Amarillos"],
                label_visibility="collapsed",
            )

        m = folium.Map(
            location=[st.session_state.lat, st.session_state.lon],
            zoom_start=15,
            tiles="CartoDB positron",
            control_scale=True,
        )

        coords_poly_latlon = [(lat, lon) for lon, lat in POLIGONO_COMUNA2.exterior.coords]
        folium.Polygon(
            locations=coords_poly_latlon,
            color="#059669",
            weight=2.5,
            fill=True,
            fill_color="#10b981",
            fill_opacity=0.07,
            tooltip="Límite Comuna 2 — Santa Cruz ( Toca dentro para ubicar y verificar )",
        ).add_to(m)

        folium.Marker(
            location=[st.session_state.lat, st.session_state.lon],
            tooltip=f"📍 Punto seleccionado ({barrio_actual})",
            icon=folium.Icon(color="blue", icon="user", prefix="fa"),
        ).add_to(m)

        puntos_calor = []
        for rep in reportes_activos:
            clasif = str(rep.get("clasificacion", ""))
            if filtro_color == "🔴 Solo Puntos Críticos" and "Crítico" not in clasif:
                continue
            if filtro_color == "🟢 Solo Reciclables (Punto Verde)" and "Verde" not in clasif:
                continue
            if filtro_color == "🟡 Solo Amarillos" and "Amarillo" not in clasif:
                continue

            rlat = float(rep.get("lat", CENTRO_COMUNA2[0]))
            rlon = float(rep.get("lon", CENTRO_COMUNA2[1]))
            peso = float(rep.get("peso_kg", 5.0))
            puntos_calor.append([rlat, rlon, min(1.0, peso / 40.0)])

            if vista_mapa == "📍 Puntos individuales":
                color_pin = "red" if "Crítico" in clasif else ("green" if "Verde" in clasif else "orange")
                popup_html = (
                    f"<div style='font-family:sans-serif;min-width:190px'>"
                    f"<b>{rep.get('codigo')} — {rep.get('sector')}</b><br>"
                    f"<span style='font-size:12px'>{clasif}</span><br>"
                    f"<b>Material:</b> {rep.get('predominante')}<br>"
                    f"<b>Peso est.:</b> {peso} kg ({rep.get('objetos', 1)} obj.)<br>"
                    f"<b>Ref:</b> {rep.get('referencia', '')}<br>"
                    f"<b>Confirmaciones:</b> 👍 {rep.get('confirmaciones', 1)}"
                    f"</div>"
                )
                folium.CircleMarker(
                    location=[rlat, rlon],
                    radius=9 if "Crítico" in clasif else 7,
                    color=color_pin,
                    fill=True,
                    fill_color=color_pin,
                    fill_opacity=0.85,
                    popup=folium.Popup(popup_html, max_width=240),
                    tooltip=f"{rep.get('codigo')} | {rep.get('sector')} ({rep.get('predominante')})",
                ).add_to(m)

        if vista_mapa == "🔥 Mapa de calor" and puntos_calor:
            HeatMap(puntos_calor, radius=24, blur=16, min_opacity=0.35).add_to(m)

        mapa_out = st_folium(
            m,
            height=430,
            use_container_width=True,
            returned_objects=["last_clicked"],
            key="mapa_principal_comuna2",
        )

        # Autoverificación en 1 clic al tocar cualquier punto del mapa
        if mapa_out and mapa_out.get("last_clicked"):
            clat = round(float(mapa_out["last_clicked"]["lat"]), 6)
            clon = round(float(mapa_out["last_clicked"]["lng"]), 6)
            if (clat, clon) != (round(st.session_state.lat, 6), round(st.session_state.lon, 6)):
                dentro = esta_en_comuna2(clat, clon)
                st.session_state.lat = clat
                st.session_state.lon = clon
                if dentro:
                    barrio_cercano = detectar_barrio_cercano(clat, clon)
                    st.session_state.barrio_actual = barrio_cercano
                    st.session_state.direccion = f"{barrio_cercano} ({clat:.4f}, {clon:.4f})"
                    st.session_state.validado = True
                    st.session_state.fuera = False
                    sincronizar_estado_localstorage(guardar=True)
                    st.toast(f"✅ Punto ubicado y verificado automáticamente en {barrio_cercano}", icon="🗺️")
                    st.rerun(scope="fragment")
                else:
                    st.session_state.validado = False
                    st.session_state.fuera = True
                    st.warning("⚠️ El punto seleccionado está fuera del polígono de la Comuna 2 (Santa Cruz).")

        if reportes_activos:
            with st.expander("🤝 Confirmar si un residuo sigue ahí o reportar falso positivo"):
                cods_activos = [f"{r['codigo']} — {r['sector']} ({r['predominante']})" for r in reportes_activos]
                sel_rep = st.selectbox("Selecciona el reporte cercano:", options=cods_activos)
                cod_sel = sel_rep.split(" — ")[0]
                c_btn1, c_btn2 = st.columns(2)
                if c_btn1.button("👍 Confirmar que sigue ahí", use_container_width=True):
                    for r in st.session_state.reportes:
                        if r["codigo"] == cod_sel:
                            r["confirmaciones"] = int(r.get("confirmaciones", 1)) + 1
                            guardar_reporte_sqlite(r)
                            respaldar_en_github(st.session_state.reportes)
                            st.success(f"¡Gracias! Confirmación sumada al reporte {cod_sel}.")
                            break
                if c_btn2.button("🚩 Reportar como falso / ya recogido", use_container_width=True):
                    for r in st.session_state.reportes:
                        if r["codigo"] == cod_sel:
                            r["reportes_falsos"] = int(r.get("reportes_falsos", 0)) + 1
                            if r["reportes_falsos"] >= 3:
                                r["estado"] = "Resuelto"
                                r["fecha_resuelto"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                            guardar_reporte_sqlite(r)
                            respaldar_en_github(st.session_state.reportes)
                            st.info(f"Se registró tu aviso sobre {cod_sel}.")
                            break

    with col_form:
        tab_rep, tab_hist = st.tabs(["📸 Reportar con IA Automática", f"👤 Mi Historial ({len(st.session_state.mis_codigos)})"])

        with tab_rep:
            modo_critico = st.toggle(
                "🚨 Es un Punto Crítico urgente (escombros, colchones o bloqueo de vía)",
                value=(st.session_state.get("seccion") == "critico"),
            )
            st.caption(
                f"📍 **Sector detectado:** `{barrio_actual}` ({st.session_state.lat:.4f}, {st.session_state.lon:.4f}) — "
                + ("<span class='badge-ok'>✅ Residente Verificado</span>" if st.session_state.validado else "<span class='badge-warn'>👆 Toca el mapa o elige tu barrio para activar</span>"),
                unsafe_allow_html=True,
            )

            metodo_foto = st.radio(
                "Evidencia fotográfica:",
                options=["📁 Subir foto de galería", "📷 Usar cámara en vivo"],
                horizontal=True,
                label_visibility="collapsed",
            )
            if metodo_foto == "📷 Usar cámara en vivo":
                archivo_img = st.camera_input("Toma la foto del residuo o punto crítico")
            else:
                archivo_img = st.file_uploader(
                    "Sube una foto del residuo (JPG, PNG, WEBP) — La IA llenará el reporte sola",
                    type=["jpg", "jpeg", "png", "webp"],
                )

            analisis_ia = st.session_state.get("ultimo_analisis_ia")
            if archivo_img is not None:
                raw_bytes = archivo_img.getvalue()
                hash_archivo = hashlib.md5(raw_bytes).hexdigest()
                if hash_archivo != st.session_state.get("ultimo_hash_archivo"):
                    with st.spinner("🤖 Analizando residuo con IA, calculando peso y difuminando rostros por privacidad..."):
                        img_mem, exif_info = preparar_imagen_memoria(raw_bytes)
                        res_ia = procesar_evidencia_ia(img_mem)
                        res_ia["exif"] = exif_info
                        st.session_state.ultimo_analisis_ia = res_ia
                        st.session_state.ultimo_hash_archivo = hash_archivo
                        analisis_ia = res_ia

            if analisis_ia:
                st.markdown("<div class='eco-card'>", unsafe_allow_html=True)
                st.markdown(f"**🤖 Diagnóstico Automático IA:** `{analisis_ia['clasificacion']}`")
                ca1, ca2, ca3 = st.columns(3)
                ca1.metric("Objetos", analisis_ia["objetos"])
                ca2.metric("Peso est.", f"{analisis_ia['peso_kg']} kg")
                ca3.metric("Privacidad", f"{analisis_ia['personas_difuminadas']} rostros difuminados")
                st.caption(f"💡 **Material detectado:** {analisis_ia['predominante']} — *{analisis_ia['recomendacion']}*")
                if analisis_ia.get("exif", {}).get("tiene_exif") and not analisis_ia["exif"]["reciente"]:
                    st.warning(f"⚠️ La fecha EXIF de la foto tiene {analisis_ia['exif']['dias_antiguedad']} días (máximo permitido: 20 días).")
                st.markdown("</div>", unsafe_allow_html=True)

            referencia_val = st.text_input(
                "Referencia del lugar (opcional, ayuda al camión recolector):",
                value=st.session_state.get("prefill_referencia", ""),
                placeholder="Ej: Frente a la tienda Don José, escaleras del pasaje 103...",
            )
            material_pred = st.text_input(
                "Material predominante (autocompletado por IA, editable):",
                value=(
                    "Escombros / Voluminosos (Punto Crítico)"
                    if modo_critico and not analisis_ia
                    else (analisis_ia["predominante"] if analisis_ia else "Bolsas de basura domiciliaria")
                ),
            )
            observaciones_val = st.text_area(
                "Observaciones adicionales:",
                placeholder="Ej: Obstruye el paso peatonal o lleva más de 2 días acumulado.",
                height=68,
            )

            if st.button("🚀 Publicar Reporte Inteligente en Comuna 2", type="primary", use_container_width=True):
                if not st.session_state.validado and esta_en_comuna2(st.session_state.lat, st.session_state.lon):
                    st.session_state.validado = True
                    st.session_state.fuera = False

                if not st.session_state.validado or st.session_state.fuera:
                    st.error("📍 Toca primero un punto dentro de la Comuna 2 en el mapa o selecciona tu barrio arriba.")
                else:
                    hoy_str = datetime.now().strftime("%Y-%m-%d")
                    mis_rep_hoy = [
                        r for r in st.session_state.reportes
                        if r.get("residente_codigo") == st.session_state.residente_codigo
                        and str(r.get("fecha", "")).startswith(hoy_str)
                    ]
                    if len(mis_rep_hoy) >= LIMITE_REPORTES_DIA:
                        st.error(f"⛔ Has alcanzado el límite de {LIMITE_REPORTES_DIA} reportes diarios para evitar spam.")
                    else:
                        phash_actual = analisis_ia.get("phash", "") if analisis_ia else ""
                        rep_dup, tipo_dup = buscar_posible_duplicado(
                            phash_actual, st.session_state.lat, st.session_state.lon, st.session_state.reportes
                        )
                        if tipo_dup == "foto_reciclada":
                            st.error(f"🚫 Esta fotografía ya fue utilizada en otro sector ({rep_dup.get('sector')}, código `{rep_dup.get('codigo')}`). Toma una foto real del punto.")
                        elif tipo_dup == "duplicado_cercano" and rep_dup:
                            rep_dup["confirmaciones"] = int(rep_dup.get("confirmaciones", 1)) + 1
                            guardar_reporte_sqlite(rep_dup)
                            respaldar_en_github(st.session_state.reportes)
                            st.info(f"🤝 Ya existía el reporte `{rep_dup['codigo']}` en este mismo punto. ¡Sumamos tu confirmación vecinal automáticamente!")
                        else:
                            nuevo_codigo = f"ECO-{int(time.time()) % 100000:05d}"
                            clasif_final = (
                                "🔴 Punto Crítico"
                                if modo_critico
                                else (analisis_ia["clasificacion"] if analisis_ia else "🟡 Punto Amarillo (Acumulación Moderada)")
                            )
                            nuevo_rep = {
                                "codigo": nuevo_codigo,
                                "sector": barrio_actual,
                                "referencia": referencia_val or f"Punto en {barrio_actual}",
                                "objetos": int(analisis_ia["objetos"]) if analisis_ia else (15 if modo_critico else 5),
                                "peso_kg": float(analisis_ia["peso_kg"]) if analisis_ia else (45.0 if modo_critico else 10.0),
                                "predominante": material_pred,
                                "clasificacion": clasif_final,
                                "lat": round(st.session_state.lat, 6),
                                "lon": round(st.session_state.lon, 6),
                                "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "estado": "Pendiente",
                                "foto_b64": analisis_ia.get("foto_b64", "") if analisis_ia else "",
                                "foto_clasificada_b64": analisis_ia.get("foto_clasificada_b64", "") if analisis_ia else "",
                                "observaciones": observaciones_val,
                                "residente_codigo": st.session_state.residente_codigo,
                                "phash": phash_actual,
                                "confirmaciones": 1,
                                "reportes_falsos": 0,
                            }
                            guardar_reporte_sqlite(nuevo_rep)
                            st.session_state.reportes.insert(0, nuevo_rep)
                            if nuevo_codigo not in st.session_state.mis_codigos:
                                st.session_state.mis_codigos.append(nuevo_codigo)
                            st.session_state.prefill_referencia = ""
                            st.session_state.ultimo_analisis_ia = None
                            sincronizar_estado_localstorage(guardar=True)
                            respaldar_en_github(st.session_state.reportes)
                            st.success(f"🎉 ¡Reporte `{nuevo_codigo}` publicado en **{barrio_actual}**! Guardado en tu historial.")

        with tab_hist:
            mis_reps = [
                r for r in st.session_state.reportes
                if r.get("codigo") in st.session_state.mis_codigos
                or r.get("residente_codigo") == st.session_state.residente_codigo
            ]
            if not mis_reps:
                st.info("Aún no tienes reportes en este dispositivo. También puedes buscar cualquier código abajo:")
            else:
                for mr in mis_reps:
                    st.markdown(
                        f"<div class='eco-card'>"
                        f"<b>{mr['codigo']}</b> — {mr['sector']} <span style='float:right'><b>Estado:</b> {mr.get('estado', 'Pendiente')}</span><br>"
                        f"<small>{mr.get('clasificacion')} | {mr.get('predominante')} (~{mr.get('peso_kg')} kg) | 👍 {mr.get('confirmaciones', 1)} confirmaciones</small>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            cod_manual = st.text_input("➕ Vincular un código de reporte anterior (ej. ECO-C201):")
            if st.button("Vincular a Mi Historial", use_container_width=True) and cod_manual.strip():
                c_up = cod_manual.strip().upper()
                if c_up not in st.session_state.mis_codigos:
                    st.session_state.mis_codigos.append(c_up)
                    sincronizar_estado_localstorage(guardar=True)
                    st.success(f"Código `{c_up}` guardado en tu navegador.")
                    st.rerun(scope="fragment")


# ==============================================================================
# 14. SECCIÓN: COMUNA EN CIFRAS (ESTADÍSTICAS PÚBLICAS Y RUTA LOGÍSTICA)
# ==============================================================================
def renderizar_comuna_en_cifras() -> None:
    st.markdown("### 📊 Comuna 2 (Santa Cruz) en Cifras — Tablero Abierto")
    reps = st.session_state.reportes
    pendientes = [r for r in reps if r.get("estado") != "Resuelto"]
    resueltos = [r for r in reps if r.get("estado") == "Resuelto"]
    criticos = [r for r in pendientes if "Crítico" in str(r.get("clasificacion", ""))]
    verdes = [r for r in pendientes if "Verde" in str(r.get("clasificacion", ""))]
    peso_total = sum(float(r.get("peso_kg", 0.0)) for r in pendientes)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Reportes Activos", len(pendientes), f"{len(resueltos)} resueltos")
    k2.metric("🔴 Puntos Críticos", len(criticos))
    k3.metric("🟢 Puntos Aprovechables", len(verdes))
    k4.metric("⚖️ Peso Acumulado Activo", f"{peso_total:.1f} kg")

    if reps:
        df = pd.DataFrame(reps)
        c_g1, c_g2 = st.columns(2)
        with c_g1:
            st.markdown("##### 📍 Reportes por Barrio de la Comuna 2")
            conteo_barrio = df["sector"].value_counts().reset_index()
            conteo_barrio.columns = ["Barrio", "Reportes"]
            st.bar_chart(conteo_barrio.set_index("Barrio"))
        with c_g2:
            st.markdown("##### ⚖️ Kilogramos Estimados por Barrio")
            peso_barrio = df.groupby("sector")["peso_kg"].sum().reset_index()
            peso_barrio.columns = ["Barrio", "Kilogramos (kg)"]
            st.bar_chart(peso_barrio.set_index("Barrio"))

    if pendientes:
        st.markdown("#### 🚛 Ruta Óptima Sugerida de Recolección (Algoritmo TSP)")
        ruta_opt = optimizar_ruta_recoleccion(pendientes)
        link_maps = generar_link_google_maps_ruta(ruta_opt)
        st.markdown(f"👉 **[Abrir Ruta Multipunto Optimizada en Google Maps ({len(ruta_opt)} paradas)]({link_maps})**")
        df_ruta = pd.DataFrame([
            {
                "Orden": idx + 1,
                "Código": r.get("codigo"),
                "Barrio": r.get("sector"),
                "Clasificación": r.get("clasificacion"),
                "Material": r.get("predominante"),
                "Peso (kg)": r.get("peso_kg"),
                "Referencia": r.get("referencia"),
            }
            for idx, r in enumerate(ruta_opt)
        ])
        st.dataframe(df_ruta, use_container_width=True, hide_index=True)


# ==============================================================================
# 15. SECCIÓN: PANEL ADMINISTRATIVO SEGURO (SIN CONTRASEÑAS EN TEXTO PLANO)
# ==============================================================================
def renderizar_panel_admin() -> None:
    st.markdown("### 🛡️ Panel de Administración y Gestión Ambiental — EcoCom2")
    if not st.session_state.get("admin_ok", False):
        st.info("🔐 Ingresa tus credenciales administrativas (validadas mediante hash SHA-256 en `st.secrets`).")
        pwd = st.text_input("Contraseña de Administrador:", type="password")
        if st.button("Ingresar al Panel Admin", type="primary"):
            ok, msg = verificar_credenciales_admin(pwd)
            if ok:
                st.session_state.admin_ok = True
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)
        return

    c_top1, c_top2, c_top3 = st.columns([2, 2, 1])
    with c_top1:
        excel_bytes = generar_excel_ejecutivo(st.session_state.reportes)
        st.download_button(
            "📥 Descargar Informe Ejecutivo Excel (.xlsx)",
            data=excel_bytes,
            file_name=f"EcoCom2_Reporte_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with c_top2:
        if st.button("☁️ Sincronizar Respaldo en GitHub Ahora", use_container_width=True):
            ok_gh = respaldar_en_github(st.session_state.reportes)
            if ok_gh:
                st.success("✅ Respaldo sincronizado en GitHub correctamente.")
            else:
                st.warning("Respaldo guardado localmente en `data_backup/reportes_backup.json` (configura `GITHUB_TOKEN` para nube).")
    with c_top3:
        if st.button("🔒 Cerrar sesión", use_container_width=True):
            st.session_state.admin_ok = False
            st.rerun()

    for r in list(st.session_state.reportes):
        with st.expander(f"{r.get('codigo')} | {r.get('sector')} — {r.get('clasificacion')} ({r.get('estado')})"):
            ca, cb, cc = st.columns([2, 1, 1])
            ca.write(f"**Referencia:** {r.get('referencia')}  \n**Material:** {r.get('predominante')} ({r.get('peso_kg')} kg)  \n**Fecha:** {r.get('fecha')}")
            nuevo_est = cb.selectbox(
                "Cambiar estado:",
                options=["Pendiente", "En ruta", "Resuelto"],
                index=["Pendiente", "En ruta", "Resuelto"].index(r.get("estado", "Pendiente"))
                if r.get("estado") in ("Pendiente", "En ruta", "Resuelto")
                else 0,
                key=f"adm_est_{r['codigo']}",
            )
            if cb.button("💾 Guardar estado", key=f"adm_save_{r['codigo']}", use_container_width=True):
                r["estado"] = nuevo_est
                if nuevo_est == "Resuelto":
                    r["fecha_resuelto"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                guardar_reporte_sqlite(r)
                respaldar_en_github(st.session_state.reportes)
                st.success(f"Estado de `{r['codigo']}` actualizado a {nuevo_est}.")
                st.rerun()
            if cc.button("🗑️ Eliminar reporte", key=f"adm_del_{r['codigo']}", use_container_width=True):
                eliminar_reporte_sqlite(r["codigo"])
                st.session_state.reportes = [x for x in st.session_state.reportes if x["codigo"] != r["codigo"]]
                respaldar_en_github(st.session_state.reportes)
                st.warning(f"Reporte `{r['codigo']}` eliminado.")
                st.rerun()


# ==============================================================================
# 16. PUNTO DE ENTRADA PRINCIPAL Y BARRA SUPERIOR / LATERAL UNIFICADA
# ==============================================================================
def main() -> None:
    inyectar_estilos_css()
    inicializar_estado()

    col_h1, col_h2, col_h3, col_h4 = st.columns([3.2, 1.1, 1.1, 1.3], vertical_alignment="center")
    with col_h1:
        st.markdown(
            f"""
            <div class="eco-hero">
                <h1>♻️ EcoCom2 Circular IA <span style="font-size:0.85rem;font-weight:500;opacity:0.85">{APP_VERSION}</span></h1>
                <p>Gestión inteligente y automatizada de residuos — Comuna 2 (Santa Cruz), Medellín</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_h2:
        if st.button("📅 Horarios", use_container_width=True):
            mostrar_modal_horarios()
    with col_h3:
        if st.button("🎬 Tutorial 20s", use_container_width=True):
            mostrar_modal_tutorial()
    with col_h4:
        with st.popover("🤖 EcoBot IA", use_container_width=True):
            renderizar_ecobot_asistente(en_popover=True)

    with st.sidebar:
        st.markdown("### 🧭 Navegación EcoCom2")
        if st.session_state.validado and not st.session_state.fuera:
            st.markdown(
                f"<div class='badge-ok'>✅ Verificado en {st.session_state.barrio_actual}</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div class='badge-warn'>📍 Toca el mapa o usa GPS para verificar</div>",
                unsafe_allow_html=True,
            )

        if HAS_JS_EVAL:
            if st.button("📡 Autodetectar mi ubicación (GPS)", use_container_width=True):
                loc = get_geolocation()
                if loc and isinstance(loc, dict) and "coords" in loc:
                    glat = float(loc["coords"]["latitude"])
                    glon = float(loc["coords"]["longitude"])
                    if esta_en_comuna2(glat, glon):
                        barrio_gps = detectar_barrio_cercano(glat, glon)
                        st.session_state.lat = glat
                        st.session_state.lon = glon
                        st.session_state.barrio_actual = barrio_gps
                        st.session_state.direccion = f"GPS: {barrio_gps}"
                        st.session_state.validado = True
                        st.session_state.fuera = False
                        sincronizar_estado_localstorage(guardar=True)
                        st.success(f"📍 Ubicado por GPS en {barrio_gps}")
                    else:
                        st.warning("Tu GPS actual indica que estás fuera de la Comuna 2.")

        vista_principal = st.radio(
            "Módulo activo:",
            options=[
                "🏠 Reportar y Ver Mapa",
                "📊 Comuna en Cifras y Rutas",
                "🤖 Asistente EcoBot IA (Vista completa)",
                "ℹ️ Información y Economía Circular",
                "🛡️ Panel Admin",
            ],
            index=0,
        )

        st.caption(f"⚙️ EcoCom2 {APP_VERSION} | Territorio INN 2026 — ITM Medellín | Dev: Brandon Duque")

    if vista_principal == "🏠 Reportar y Ver Mapa":
        renderizar_mapa_y_reportes()
    elif vista_principal == "📊 Comuna en Cifras y Rutas":
        renderizar_comuna_en_cifras()
    elif vista_principal == "🤖 Asistente EcoBot IA (Vista completa)":
        renderizar_ecobot_asistente(en_popover=False)
    elif vista_principal == "ℹ️ Información y Economía Circular":
        st.markdown("### ℹ️ Cómo funciona EcoCom2 Circular IA en Santa Cruz")
        st.markdown(
            """
            * **Visión Artificial con Privacidad por Diseño:** Utilizamos segmentación abierta (`YOLOE`) y modelos multimodales de respaldo (`Gemini`) para estimar peso, volumen y fracción aprovechable, aplicando desenfoque gaussiano automático (`difuminar_personas`) sobre cualquier transeúnte.
            * **Rutas de Recolección Inteligentes:** Los puntos reportados alimentan un algoritmo de optimización logística (TSP) que prioriza los **🔴 Puntos Críticos** y conecta a los recuperadores ambientales con los **🟢 Puntos Verdes**.
            * **Validación Comunitaria:** Cada reporte puede ser confirmado por otros vecinos de la cuadra o marcado si ya fue recogido por Emvarias.
            """
        )
    elif vista_principal == "🛡️ Panel Admin":
        renderizar_panel_admin()


if __name__ == "__main__":
    main()
