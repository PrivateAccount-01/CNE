"""Typed, provenance-carrying slot binding; no implicit global attribute scan."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re


@dataclass(frozen=True)
class SlotResult:
    name: str
    value: object
    type: str
    source_span: tuple | None
    confidence: float | None
    normalizer: str


class SlotBindingError(ValueError):
    pass


class TypedSlotBinder:
    def bind(self, schema, extracted, spans=None):
        result = {}
        if set(extracted) - set(schema):
            raise SlotBindingError("Undeclared slots")
        for name, spec in schema.items():
            raw = extracted.get(name)
            if raw is None:
                if spec.get("required", False):
                    raise SlotBindingError(f"MISSING: {name}")
                continue
            if isinstance(raw, list):
                raise SlotBindingError(f"AMBIGUOUS: {name}")
            kind = spec["type"]
            try:
                if kind in ("number", "integer", "percentage", "currency", "unit"):
                    text = str(raw).strip()
                    if kind == "currency":
                        currency = spec.get("currency")
                        if not currency or not re.fullmatch("[A-Z]{3}", currency):
                            raise ValueError("Currency required")
                        text = text.removeprefix(currency).strip()
                    if kind == "unit":
                        unit = spec["unit"]
                        text = text.removesuffix(unit).strip()
                    if kind == "percentage":
                        text = text.removesuffix("%")
                    value = Decimal(text)
                    if not value.is_finite():
                        raise ValueError("Non-finite")
                    if kind == "percentage":
                        value /= 100
                    if kind == "integer" and value != value.to_integral_value():
                        raise ValueError("Non-integer")
                    value = int(value) if kind == "integer" else float(value)
                elif kind == "date":
                    value = date.fromisoformat(str(raw)).isoformat()
                elif kind in ("string", "enum"):
                    value = str(raw).strip()
                else:
                    raise ValueError(f"Unsupported slot type {kind}")
                if "enum" in spec and value not in spec["enum"]:
                    raise ValueError("Invalid enum")
                if "minimum" in spec and value < spec["minimum"]:
                    raise ValueError("Below range")
                if "maximum" in spec and value > spec["maximum"]:
                    raise ValueError("Above range")
            except (ValueError, InvalidOperation, KeyError) as exc:
                raise SlotBindingError(f"INVALID: {name}: {exc}") from exc
            result[name] = SlotResult(
                name, value, kind, (spans or {}).get(name), None, f"{kind}-v1"
            )
        return result
