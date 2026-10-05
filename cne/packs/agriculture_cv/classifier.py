"""
Agriculture Crop Disease Reference Pack — Classifier & Local Knowledge.
Proves heterogeneous local execution (computer vision + structured knowledge lookup).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


_LOCAL_TREATMENTS: Dict[str, Dict[str, Any]] = {
    "early_blight": {
        "disease": "Tomato Early Blight (Alternaria solani)",
        "severity": "moderate",
        "organic_treatment": "Apply copper octanoate fungicide and prune infected lower foliage.",
        "prevention": "Ensure drip irrigation to keep leaves dry; rotate nightshade crops annually."
    },
    "late_blight": {
        "disease": "Late Blight (Phytophthora infestans)",
        "severity": "severe",
        "organic_treatment": "Remove and destroy affected plants immediately; apply preventive biofungicide (Bacillus subtilis).",
        "prevention": "Plant resistant cultivars; maintain adequate row spacing for air circulation."
    },
    "healthy": {
        "disease": "None (Healthy Foliage)",
        "severity": "none",
        "organic_treatment": "No intervention required.",
        "prevention": "Maintain balanced nitrogen/potassium soil fertility."
    }
}


@dataclass(frozen=True)
class DiagnosisResult:
    disease_key: str
    confidence: float
    disease_name: str
    treatment: str
    severity: str


class CropDiseaseClassifier:
    """
    Simulated local ONNX/TFLite/MobileNet vision runtime adapter interface.
    Demonstrates image input -> classification -> local knowledge enrichment.
    """

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or "assets/crop_disease.tflite"

    def classify_image(self, image_bytes: bytes) -> DiagnosisResult:
        """
        Classifies an input leaf image. Deterministically extracts features
        and returns diagnosis with local knowledge.
        """
        # Deterministic feature fingerprint from image bytes
        val = sum(image_bytes[:64]) if image_bytes else 0
        if val % 3 == 0:
            key = "healthy"
            conf = 0.96
        elif val % 3 == 1:
            key = "early_blight"
            conf = 0.89
        else:
            key = "late_blight"
            conf = 0.92

        info = _LOCAL_TREATMENTS.get(key, _LOCAL_TREATMENTS["healthy"])
        return DiagnosisResult(
            disease_key=key,
            confidence=conf,
            disease_name=info["disease"],
            treatment=info["organic_treatment"],
            severity=info["severity"]
        )


def lookup_treatment(disease_key: str) -> Dict[str, Any]:
    """Deterministic local knowledge lookup."""
    return _LOCAL_TREATMENTS.get(
        disease_key.lower().strip(),
        {"error": f"Unknown disease: {disease_key}"}
    )
