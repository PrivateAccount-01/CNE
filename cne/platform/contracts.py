"""Typed, intent-owned outcome contract declarations for platform compilation."""
from dataclasses import dataclass
from cne.contracts.outcome_contract import ContractType, OutcomeContract


@dataclass(frozen=True)
class OutcomeContractSpec:
    version: int
    contract_type: ContractType
    output_schema: dict | None = None
    required_facts: tuple = ()
    tolerances: dict | None = None
    decision_boundary: float | None = None
    provenance_requirements: dict | None = None

    @classmethod
    def from_intent(cls, manifest, intent):
        mapping = next(
            (item for item in manifest.schemas.get("intents", []) if item.get("intent") == intent),
            None,
        )
        if mapping is None:
            raise ValueError("Outcome contract requires a declared intent owner")
        raw = mapping.get("outcome_contract")
        if not isinstance(raw, dict) or set(raw) - {
            "version", "type", "output_schema", "required_facts", "tolerances",
            "decision_boundary", "provenance_requirements",
        }:
            raise ValueError("Intent must declare a typed outcome_contract")
        if raw.get("version") != 1:
            raise ValueError("Unsupported outcome contract spec version")
        contract_type = ContractType[raw["type"]]
        allowed = manifest.schemas.get("contracts", [])
        if allowed and contract_type.name not in allowed:
            raise ValueError("Intent outcome contract is not in the manifest allowlist")
        tolerances = dict(raw.get("tolerances", {}))
        if any(not isinstance(v, (int, float)) or v < 0 for v in tolerances.values()):
            raise ValueError("Invalid outcome contract tolerance")
        boundary = raw.get("decision_boundary")
        if boundary is not None and not isinstance(boundary, (int, float)):
            raise ValueError("Invalid decision boundary")
        return cls(
            1, contract_type, raw.get("output_schema"),
            tuple(raw.get("required_facts", ())), tolerances, boundary,
            raw.get("provenance_requirements"),
        )

    def build(self):
        return OutcomeContract(
            self.contract_type,
            output_schema=self.output_schema,
            required_facts=set(self.required_facts),
            tolerances=dict(self.tolerances or {}),
            decision_boundary=self.decision_boundary,
            provenance_requirements=self.provenance_requirements,
        )

    def to_dict(self):
        return {
            "version": self.version,
            "type": self.contract_type.name,
            "output_schema": self.output_schema,
            "required_facts": list(self.required_facts),
            "tolerances": dict(self.tolerances or {}),
            "decision_boundary": self.decision_boundary,
            "provenance_requirements": self.provenance_requirements,
        }
