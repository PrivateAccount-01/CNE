"""
CNE Effect-Driven Execution Policy.
Translates semantic effect sets into operational policies (Cacheable, Retryable).
Most restrictive policy wins when multiple effects are present.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto
from cne.effects.effect_set import Effect, EffectSet


class Cacheability(Enum):
    ALWAYS = auto()
    CONDITIONAL_ON_DEPENDENCY = auto()
    NEVER = auto()


class Retryability(Enum):
    ALWAYS = auto()
    POLICY_DEPENDENT = auto()
    IDEMPOTENT_ONLY = auto()
    NEVER = auto()


@dataclass(frozen=True)
class ExecutionPolicy:
    cacheability: Cacheability
    retryability: Retryability

    @classmethod
    def from_effect_set(cls, effects: EffectSet) -> ExecutionPolicy:
        """
        Derive execution policy from effect set.
        For multiple effects, use the most restrictive policy.
        Example: {ReadExternal, WriteExternal} -> Cacheability.NEVER.
        """
        # If write external or interactive, NEVER cacheable
        if Effect.WriteExternal in effects or Effect.Interactive in effects:
            c = Cacheability.NEVER
        elif Effect.Nondeterministic in effects:
            c = Cacheability.NEVER
        elif Effect.ReadExternal in effects:
            c = Cacheability.CONDITIONAL_ON_DEPENDENCY
        else:
            c = Cacheability.ALWAYS

        # Retryability
        if Effect.Interactive in effects:
            r = Retryability.NEVER
        elif Effect.WriteExternal in effects:
            r = Retryability.IDEMPOTENT_ONLY
        elif Effect.Nondeterministic in effects:
            r = Retryability.POLICY_DEPENDENT
        elif Effect.ReadExternal in effects:
            r = Retryability.ALWAYS
        else:
            r = Retryability.ALWAYS

        return cls(cacheability=c, retryability=r)
