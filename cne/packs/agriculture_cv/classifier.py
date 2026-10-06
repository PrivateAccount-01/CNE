"""Vision classification is deliberately unavailable until a validated model ships."""
from __future__ import annotations
from dataclasses import dataclass

IMPLEMENTATION_STATUS = "STUB"


@dataclass(frozen=True)
class DiagnosisResult:
    disease_key: str
    confidence: float
    disease_name: str
    treatment: str
    severity: str


class CropDiseaseClassifier:
    IMPLEMENTATION_STATUS = IMPLEMENTATION_STATUS

    def __init__(self, model_path=None):
        self.model_path = model_path

    def classify_image(self, image_bytes):
        raise NotImplementedError(
            "NOT_IMPLEMENTED: no validated crop disease model is installed"
        )


def lookup_treatment(disease_key):
    return {
        "status": "NOT_IMPLEMENTED",
        "validation": "UNVERIFIED",
        "source": None,
        "version": None,
        "last_updated": None,
        "applicable_crop": None,
        "region_limitations": None,
        "error": "No sourced and validated treatment knowledge installed",
    }
