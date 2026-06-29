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
