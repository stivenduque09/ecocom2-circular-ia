# ====================================================================
# GEOCODING UTILITIES — EcoCom2 Circular IA
# ====================================================================

import streamlit as st
from geopy.geocoders import Nominatim
from config import GEOPY_TIMEOUT, GEOPY_USER_AGENT, GEOPY_REVERSE_AGENT


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar(direccion: str) -> tuple:
    """
    Convierte una dirección de texto a coordenadas GPS.
    
    Args:
        direccion: Dirección como string (ej: "Cra 50 #107-62, Andalucía")
        
    Returns:
        tuple: (latitud, longitud, dirección_completa) o (None, None, None) si falla
    """
    try:
        geo = Nominatim(user_agent=GEOPY_USER_AGENT, timeout=GEOPY_TIMEOUT)
        r = geo.geocode(f"{direccion}, Medellín, Antioquia, Colombia")
        if r:
            return r.latitude, r.longitude, r.address
    except Exception as e:
        print(f"Error geocodificando: {e}")
    return None, None, None


@st.cache_data(show_spinner=False, ttl=3600)
def geocodificar_inversa(lat: float, lon: float) -> str:
    """
    Convierte coordenadas GPS a dirección de texto (reverse geocoding).
    
    Args:
        lat: Latitud
        lon: Longitud
        
    Returns:
        str: Dirección legible o coordenadas si falla
    """
    try:
        geo = Nominatim(user_agent=GEOPY_REVERSE_AGENT, timeout=GEOPY_TIMEOUT)
        r = geo.reverse(f"{lat}, {lon}", language="es")
        if r and r.raw.get("address"):
            a = r.raw["address"]
            partes = []
            calle = a.get("road") or a.get("pedestrian") or a.get("path") or ""
            num = a.get("house_number", "")
            barrio = a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or ""
            if calle:
                partes.append(calle + (f" #{num}" if num else ""))
            if barrio:
                partes.append(barrio)
            partes.append("Medellín")
            return ", ".join(partes) if partes else r.address
        return f"{lat:.5f}, {lon:.5f}"
    except Exception as e:
        print(f"Error reverse geocoding: {e}")
        return f"{lat:.5f}, {lon:.5f}"
