# ====================================================================
# REPORTS MANAGEMENT — EcoCom2 Circular IA
# ====================================================================

import json
import os
from datetime import datetime
from config import REPORTES_FILE


def cargar_reportes_disco() -> list:
    """
    Carga todos los reportes guardados en disco.
    
    Returns:
        list: Lista de reportes o lista vacía si no existen
    """
    if os.path.exists(REPORTES_FILE):
        try:
            with open(REPORTES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error cargando reportes: {e}")
            return []
    return []


def guardar_reportes_disco(reportes: list) -> bool:
    """
    Guarda reportes en disco en formato JSON.
    
    Args:
        reportes: Lista de reportes a guardar
        
    Returns:
        bool: True si se guardó exitosamente, False en caso contrario
    """
    try:
        with open(REPORTES_FILE, "w", encoding="utf-8") as f:
            json.dump(reportes, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Error guardando reportes: {e}")
        return False


def crear_reporte(
    codigo: str,
    sector: str,
    referencia: str,
    objetos: int,
    peso: float,
    predominante: str,
    clasificacion: str,
    lat: float,
    lon: float,
    estado: str = "🔴 Pendiente",
) -> dict:
    """
    Crea un diccionario de reporte estructurado.
    
    Args:
        codigo: Código único del reporte
        sector: Barrio donde se reportó
        referencia: Descripción de la ubicación
        objetos: Cantidad de objetos detectados
        peso: Peso total estimado en kg
        predominante: Material predominante
        clasificacion: Nivel de clasificación (🟢/🟡/🔴)
        lat: Latitud
        lon: Longitud
        estado: Estado del reporte (por defecto pendiente)
        
    Returns:
        dict: Reporte estructurado
    """
    return {
        "Código": codigo,
        "Sector": sector,
        "Referencia": referencia,
        "Objetos": objetos,
        "Peso (Kg)": peso,
        "Predominante": predominante,
        "Clasificación": clasificacion,
        "Lat": lat,
        "Lon": lon,
        "Fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "Estado": estado,
    }


def actualizar_estado_reporte(reportes: list, codigo: str, nuevo_estado: str) -> bool:
    """
    Actualiza el estado de un reporte.
    
    Args:
        reportes: Lista de reportes
        codigo: Código del reporte a actualizar
        nuevo_estado: Nuevo estado
        
    Returns:
        bool: True si se actualizó, False si no encontró el reporte
    """
    for r in reportes:
        if r.get("Código") == codigo:
            r["Estado"] = nuevo_estado
            return True
    return False


def eliminar_reporte(reportes: list, codigo: str) -> list:
    """
    Elimina un reporte de la lista.
    
    Args:
        reportes: Lista de reportes
        codigo: Código del reporte a eliminar
        
    Returns:
        list: Lista actualizada sin el reporte
    """
    return [r for r in reportes if r.get("Código") != codigo]


def limpiar_resueltos(reportes: list) -> int:
    """
    Elimina todos los reportes con estado "✅ Resuelto".
    
    Args:
        reportes: Lista de reportes
        
    Returns:
        int: Cantidad de reportes eliminados
    """
    antes = len(reportes)
    nuevos = [r for r in reportes if r.get("Estado") != "✅ Resuelto"]
    eliminados = antes - len(nuevos)
    return eliminados, nuevos
