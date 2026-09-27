"""
CNE State Lifecycle.
Lifecycle transitions:
CREATED -> VERIFIED -> ACTIVE -> STALE -> SUPERSEDED -> ARCHIVED -> DELETED.
"""
from __future__ import annotations
from enum import Enum, auto


class StateLifecycle(Enum):
    CREATED = auto()
    VERIFIED = auto()
    ACTIVE = auto()
    STALE = auto()
    SUPERSEDED = auto()
    ARCHIVED = auto()
    DELETED = auto()

    def can_transition_to(self, target: StateLifecycle) -> bool:
        """
        Validates state transitions.
        """
        valid_transitions = {
            StateLifecycle.CREATED: {StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.DELETED},
            StateLifecycle.VERIFIED: {StateLifecycle.ACTIVE, StateLifecycle.STALE, StateLifecycle.DELETED},
            StateLifecycle.ACTIVE: {StateLifecycle.STALE, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED, StateLifecycle.DELETED},
            StateLifecycle.STALE: {StateLifecycle.VERIFIED, StateLifecycle.ACTIVE, StateLifecycle.SUPERSEDED, StateLifecycle.ARCHIVED, StateLifecycle.DELETED},
            StateLifecycle.SUPERSEDED: {StateLifecycle.ARCHIVED, StateLifecycle.DELETED},
            StateLifecycle.ARCHIVED: {StateLifecycle.DELETED},
            StateLifecycle.DELETED: set()
        }
        return target in valid_transitions.get(self, set())
