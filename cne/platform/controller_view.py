"""Immutable whitelisted controller data; package prose is deliberately omitted."""
from dataclasses import dataclass
import json, re

TOKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,95}$")


def identifier(value):
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError("Invalid controller identifier")
    return value


def slot_schema(schema):
    if len(schema) > 32:
        raise ValueError("Too many slots")
    allowed = {"type", "required", "enum", "minimum", "maximum", "currency", "unit"}
    result = {}
    for key, spec in schema.items():
        safe = {k: v for k, v in spec.items() if k in allowed}
        if safe.get("type") not in {
            "string",
            "number",
            "integer",
            "boolean",
            "date",
            "percentage",
            "currency",
            "unit",
        }:
            raise ValueError("Unsupported slot type")
        if len(json.dumps(safe)) > 512:
            raise ValueError("Slot schema too large")
        result[identifier(key)] = safe
    return result


def tool_schema(schema, depth=0):
    if not isinstance(schema, dict) or depth > 3:
        raise ValueError("Invalid tool schema")
    allowed = {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "minimum",
        "maximum",
        "additionalProperties",
    }
    if set(schema) - allowed:
        raise ValueError("Unsupported tool schema field")
    result = {}
    for key, value in schema.items():
        if key == "properties":
            if not isinstance(value, dict) or len(value) > 32:
                raise ValueError("Too many tool arguments")
            result[key] = {
                identifier(name): tool_schema(spec, depth + 1)
                for name, spec in value.items()
            }
        elif key == "items":
            result[key] = tool_schema(value, depth + 1)
        elif key == "required":
            if not isinstance(value, list) or len(value) > 32:
                raise ValueError("Invalid required tool arguments")
            result[key] = [identifier(name) for name in value]
        elif key == "enum":
            if (
                not isinstance(value, list)
                or len(value) > 32
                or any(
                    not isinstance(x, (str, int, float, bool, type(None)))
                    for x in value
                )
            ):
                raise ValueError("Invalid tool enum")
            result[key] = value
        elif key == "type":
            if value not in {
                "object",
                "array",
                "string",
                "number",
                "integer",
                "boolean",
                "null",
            }:
                raise ValueError("Unsupported tool argument type")
            result[key] = value
        elif key == "additionalProperties":
            if value is not False:
                raise ValueError("Tool schemas must close object properties")
            result[key] = False
        elif key in ("minimum", "maximum"):
            if not isinstance(value, (int, float)):
                raise ValueError("Invalid numeric tool bound")
            result[key] = value
    if len(json.dumps(result)) > 2048:
        raise ValueError("Tool schema too large")
    return result


@dataclass(frozen=True)
class ControllerCapabilityView:
    capability_id: str
    version: str
    canonical_data: str

    def to_dict(self):
        return json.loads(self.canonical_data)


class ControllerCapabilityViewBuilder:
    def build(self, manifest):
        intents = []
        for m in manifest.schemas.get("intents", []):
            safe = {k: v for k, v in m.items() if k in ("template", "pattern")}
            if len(json.dumps(safe)) > 1024:
                raise ValueError("Utterance template too large")
            intents.append(
                {
                    "intent": identifier(m["intent"]),
                    "utterance_data": safe,
                    "slots": slot_schema(
                        m.get("slots", manifest.schemas.get("slots", {}))
                    ),
                    "required_permissions": list(m.get("required_permissions", [])),
                }
            )
        tools = [
            {
                "tool_id": identifier(t.tool_id),
                "description": "Declared tool " + identifier(t.tool_id),
                "required_permissions": list(t.required_permissions),
                "parameters": tool_schema(t.parameters_schema),
                "returns": tool_schema(t.returns_schema),
            }
            for t in manifest.deterministic_tools
        ]
        from cne.platform.dsl import _OP_MAP

        data = {
            "capability_id": identifier(manifest.id),
            "version": manifest.version,
            "intents": intents,
            "slots": slot_schema(manifest.schemas.get("slots", {})),
            "sources": [identifier(s) for s in manifest.schemas.get("sources", [])],
            "operations": sorted(_OP_MAP),
            "tools": tools,
            "source_permissions": manifest.schemas.get("source_permissions", {}),
        }
        # Operations and permission enums are checked independently at installation.
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if len(raw) > 8192:
            raise ValueError("Controller view too large")
        return ControllerCapabilityView(manifest.id, manifest.version, raw)
