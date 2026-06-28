# ====================================================================
# YOLO DETECTION MODULE — EcoCom2 Circular IA
# ====================================================================

import tempfile
from collections import Counter
import pandas as pd
from PIL import Image
from ultralytics import YOLO
from config import YOLO_MODEL, YOLO_CONFIDENCE, MATERIALES


class YOLODetector:
    """
    Wrapper para YOLO que maneja detección y clasificación de materiales.
    """

    def __init__(self):
        """Carga el modelo YOLO una sola vez."""
        self.modelo = YOLO(YOLO_MODEL)

    def analizar(self, img: Image.Image):
        """
        Analiza una imagen PIL con YOLO.
        
        Args:
            img: Imagen PIL Image
            
        Returns:
            Resultados de YOLO
        """
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            img.save(tmp.name)
            return self.modelo(tmp.name, conf=YOLO_CONFIDENCE, verbose=False)

    def procesar(self, resultados):
        """
        Clasifica la escena según ratio de reciclables:
        🟢 Verde      ≥60% reciclables  → alta valorización
        🟡 Amarillo   30-60% mixto      → mezcla
        🔴 Rojo       <30% reciclables  → acumulación sin valor
        
        Args:
            resultados: Resultados de YOLO
            
        Returns:
            tuple: (tabla, residuos, peso_total, tipo_material, nivel_clasificacion)
        """
        objetos = []
        for r in resultados:
            for box in r.boxes:
                objetos.append((self.modelo.names[int(box.cls[0])], float(box.conf[0])))

        if not objetos:
            return [], 0, 0.0, "N/D", "🟢 Sin residuos detectados"

        conteo = Counter(o[0] for o in objetos)
        mejor = {n: max(c for nn, c in objetos if nn == n) for n in conteo}

        tabla, peso_total, residuos, no_rec = [], 0.0, 0, 0
        cnt_mat = Counter()

        for obj, cant in conteo.items():
            nom, mat, peso_u, recicl = MATERIALES.get(
                obj, (obj.replace("_", " ").title(), "Desconocido", 0.1, False)
            )
            conf = f"{mejor[obj] * 100:.0f}%"
            if recicl:
                residuos += cant
                p = round(peso_u * cant, 2)
                peso_total += p
                cnt_mat[mat] += cant
                tabla.append(
                    {
                        "Objeto": nom,
                        "Material": mat,
                        "Cant.": cant,
                        "Peso (kg)": p,
                        "Confianza": conf,
                        "♻️": "✅ Sí",
                    }
                )
            else:
                no_rec += cant
                tabla.append(
                    {
                        "Objeto": nom,
                        "Material": "—",
                        "Cant.": cant,
                        "Peso (kg)": 0,
                        "Confianza": conf,
                        "♻️": "❌ No",
                    }
                )

        tipo = cnt_mat.most_common(1)[0][0] if cnt_mat else "Mixto"
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
