"""
CNE Semantic IR Type System.
Hardware-agnostic types for Semantic IR nodes and values.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class TypeKind(Enum):
    SCALAR = auto()
    RECORD = auto()
    COLLECTION = auto()
    BOOLEAN = auto()
    NUMERIC = auto()
    STRING = auto()
    TUPLE = auto()
    ANY = auto()
    NOTHING = auto()


@dataclass(frozen=True)
class SemanticType:
    kind: TypeKind
    name: str = ""
    element_type: Optional[SemanticType] = None
    fields: Optional[Dict[str, SemanticType]] = None

    @classmethod
    def scalar(cls, name: str = "Scalar") -> SemanticType:
        return cls(kind=TypeKind.SCALAR, name=name)

    @classmethod
    def boolean(cls) -> SemanticType:
        return cls(kind=TypeKind.BOOLEAN, name="Boolean")

    @classmethod
    def numeric(cls, name: str = "Numeric") -> SemanticType:
        return cls(kind=TypeKind.NUMERIC, name=name)

    @classmethod
    def string(cls) -> SemanticType:
        return cls(kind=TypeKind.STRING, name="String")

    @classmethod
    def collection(cls, element_type: SemanticType, name: str = "Collection") -> SemanticType:
        return cls(kind=TypeKind.COLLECTION, name=name, element_type=element_type)

    @classmethod
    def record(cls, fields: Dict[str, SemanticType], name: str = "Record") -> SemanticType:
        return cls(kind=TypeKind.RECORD, name=name, fields=fields)

    @classmethod
    def any(cls) -> SemanticType:
        return cls(kind=TypeKind.ANY, name="Any")

    def is_compatible_with(self, other: SemanticType) -> bool:
        if self.kind == TypeKind.ANY or other.kind == TypeKind.ANY:
            return True
        if self.kind != other.kind:
            return False
        if self.kind == TypeKind.COLLECTION:
            if self.element_type and other.element_type:
                return self.element_type.is_compatible_with(other.element_type)
            return True
        if self.kind == TypeKind.RECORD:
            if self.fields and other.fields:
                for k, v in other.fields.items():
                    if k not in self.fields or not self.fields[k].is_compatible_with(v):
                        return False
            return True
        return True


@dataclass(frozen=True)
class DependencyKey:
    """
    Mandatory dependency identity for sound invalidation.
    Supports both coarse (source/table) and fine (key/field/range/predicate) granularity.
    """
    source: str
    granularity: str  # "source", "table", "key", "field", "range", "predicate", "join"
    key: Optional[str] = None
    field_name: Optional[str] = None
    range_bounds: Optional[Tuple[Any, Any]] = None
    predicate_desc: Optional[str] = None

    def matches(self, change_key: DependencyKey) -> bool:
        """
        Determine if this dependency is affected by a change described by change_key.
        """
        if self.source != change_key.source:
            return False
        if self.granularity == "source" or change_key.granularity == "source":
            return True
        if self.granularity == "table" or change_key.granularity == "table":
            return True
        if self.granularity == "key" and change_key.granularity == "key":
            return self.key == change_key.key
        if self.granularity == "field" and change_key.granularity == "field":
            return (self.key == change_key.key) and (self.field_name == change_key.field_name)
        if self.granularity == "predicate" and change_key.granularity == "key":
            # Predicate dependency must be tested against changed row
            return True
        return True
