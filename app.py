import streamlit as st
from ultralytics import YOLO
from PIL import Image
import tempfile
from collections import Counter

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="EcoCom2 - IA", layout="wide")

# Diccionario de pesos (IA reconoce el nombre, diccionario da el peso)
PESOS_MATERIALES = {
    "bottle": 0.05, "cup": 0.03, "can": 0.02, "box": 0.30, 
    "book": 0.30, "paper": 0.05, "chair": 2.00, "laptop": 2.50
}

if "registro_reportes" not in st.session_state: st.session_state.registro_reportes = []
modelo = YOLO("yolov8m.pt")

# --- MENÚ ---
menu = st.sidebar.radio("Menú", ["Inicio", "Reportar Residuo"])

if menu == "Inicio":
    st.title("♻️ EcoCom2 - IA")
    # Lógica de GPS (Simple: Si detecta ubicación, verifica)
    # Aquí puedes poner el componente de JS para obtener lat/lon
    st.info("Sistema de monitoreo de Comuna 2 activo.")
    st.dataframe(pd.DataFrame(st.session_state.registro_reportes))

elif menu == "Reportar Residuo":
    st.header("Reportar con IA")
    
    # 1. VALIDACIÓN GPS (La lógica que pediste)
    es_comuna2 = True # <- Aquí iría tu lógica de validación GPS real
    
    if not es_comuna2:
        st.error("❌ Solo habitantes de Comuna 2 pueden reportar.")
    else:
        st.success("✅ Ubicación verificada: Comuna 2.")
        img_file = st.file_uploader("Sube la foto:", type=["jpg", "png"])
        
        if img_file:
            if st.button("Analizar y Calcular Peso"):
                # Procesar con IA
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    img_file.save(tmp.name)
                    res = modelo(tmp.name)
                
                # Clasificar y Sumar Kilos
                objetos = [modelo.names[int(box.cls[0])] for r in res for box in r.boxes]
                conteo = Counter(objetos)
                kilos_totales = sum([PESOS_MATERIALES.get(obj, 0.1) for obj in objetos])
                
                st.write(f"### Análisis: {sum(conteo.values())} objetos detectados")
                for obj, cant in conteo.items():
                    st.write(f"- {obj}: {cant}")
                
                st.metric("Peso Estimado", f"{kilos_totales:.2f} kg")
                
                # Botón de Guardar
                if st.button("Confirmar y Enviar Reporte"):
                    st.session_state.registro_reportes.append({
                        "Materiales": str(dict(conteo)), 
                        "Kilos": kilos_totales
                    })
                    st.success("Reporte enviado al sistema central.")
