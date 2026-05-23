"""
Triage tool: maps free-text symptom to specialty, attention type and urgency.
Uses keyword matching against symptom_router data, then falls back to LLM context.
"""
import unicodedata
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from data_loader import load_data

RED_FLAG_KEYWORDS = [
    "dolor de pecho", "presion en el pecho", "falta de aire", "dificultad para respirar",
    "dificultad respiratoria", "debilidad en un lado", "dificultad para hablar",
    "perdida de conciencia", "convulsion", "sangrado abundante", "sangrado", "deficit neurologico",
    "hormigueo en el brazo", "sudor frio", "dolor irradiado"
]

URGENCY_LABEL = {
    "alta": "Alta",
    "media_alta": "Media-Alta",
    "media": "Media",
    "baja_media": "Baja-Media",
    "baja": "Baja",
}

def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text

def classify_symptom(symptom_text: str) -> dict:
    """
    Classifies a free-text symptom into specialty, attention_type and urgency.

    Args:
        symptom_text: Patient description in natural language (Spanish).

    Returns:
        dict with keys: specialty, attention_type, urgency, follow_up_question, red_flags
    """
    data = load_data()
    norm = _normalize(symptom_text)

    # Check for red flags first
    detected_red_flags = [kw for kw in RED_FLAG_KEYWORDS if _normalize(kw) in norm]

    # Score each symptom_router entry
    best_match = None
    best_score = 0
    for entry in data["symptom_router"]:
        score = sum(1 for kw in entry["symptom_keywords"] if _normalize(kw) in norm)
        if score > best_score:
            best_score = score
            best_match = entry

    # Override to emergencia if red flags present
    if detected_red_flags:
        specialty = best_match["specialty"] if best_match else "medicina_general"
        if any(k in norm for k in ["dolor de pecho", "presion en el pecho", "falta de aire",
                                    "dificultad para respirar", "dificultad respiratoria"]):
            specialty = "cardiologia"
        elif any(k in norm for k in ["debilidad en un lado", "dificultad para hablar",
                                      "hormigueo en el brazo"]):
            specialty = "neurologia"
        return {
            "specialty": specialty,
            "attention_type": "emergencia",
            "urgency": "alta",
            "follow_up_question": None,
            "red_flags": detected_red_flags,
        }

    if best_match and best_score > 0:
        urgency_raw = best_match["urgency"]
        follow_up = best_match["recommended_followups"][0] if best_match.get("recommended_followups") else None
        return {
            "specialty": best_match["specialty"],
            "attention_type": best_match["attention_type"],
            "urgency": urgency_raw,
            "follow_up_question": follow_up,
            "red_flags": [],
        }

    # Fallback
    return {
        "specialty": "medicina_general",
        "attention_type": "consulta",
        "urgency": "baja",
        "follow_up_question": "¿Puedes describir más detalladamente tu síntoma principal?",
        "red_flags": [],
    }
