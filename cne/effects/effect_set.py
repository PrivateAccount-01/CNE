"""
CNE Effect System.
Effect sets are sets of atomic effect markers, NEVER a severity hierarchy.
"""
from __future__ import annotations
from enum import Enum, auto
from typing import FrozenSet, Iterable, Set


class Effect(Enum):
    ReadExternal = auto()
    WriteExternal = auto()
    Nondeterministic = auto()
    Interactive = auto()


class EffectSet:
    """
    Immutable set of effects.
    Supports set union and query operations.
    """
    def __init__(self, effects: Iterable[Effect] = ()):
        self._effects: FrozenSet[Effect] = frozenset(effects)

    @classmethod
    def pure(cls) -> EffectSet:
        return cls(())

    @classmethod
    def read_external(cls) -> EffectSet:
        return cls((Effect.ReadExternal,))

    @classmethod
    def write_external(cls) -> EffectSet:
        return cls((Effect.WriteExternal,))

    @classmethod
    def nondeterministic(cls) -> EffectSet:
        return cls((Effect.Nondeterministic,))

    @classmethod
    def interactive(cls) -> EffectSet:
        return cls((Effect.Interactive,))

    @classmethod
    def from_set(cls, effects: Set[Effect]) -> EffectSet:
        return cls(effects)

    def union(self, other: EffectSet) -> EffectSet:
        return EffectSet(self._effects | other._effects)

    def contains(self, effect: Effect) -> bool:
        return effect in self._effects

    @property
    def is_pure(self) -> bool:
        return len(self._effects) == 0

    def is_empty(self) -> bool:
        return len(self._effects) == 0

    def __bool__(self) -> bool:
        return len(self._effects) > 0

    @property
    def effects(self) -> FrozenSet[Effect]:
        return self._effects

    def __contains__(self, effect: Effect) -> bool:
        return effect in self._effects

    def __iter__(self):
        return iter(self._effects)

    def __len__(self) -> int:
        return len(self._effects)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, EffectSet):
            return self._effects == other._effects
        return False

    def __hash__(self) -> int:
        return hash(self._effects)

    def __repr__(self) -> str:
        if not self._effects:
            return "EffectSet(Pure)"
        names = sorted([e.name for e in self._effects])
        return f"EffectSet({', '.join(names)})"
