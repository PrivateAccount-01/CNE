"""
Travel Reference Pack — Itinerary Planner & Freshness Handling.
Demonstrates LOCAL_COMPUTE_NETWORK_DATA with explicit freshness limitations.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from cne.platform.external_data import DataFreshnessStatus


@dataclass
class ItineraryItem:
    time_slot: str
    activity: str
    duration_hours: float
    is_live_status: bool = False
    freshness_notice: Optional[str] = None
    freshness_status: DataFreshnessStatus = DataFreshnessStatus.NO_DATA
    source_id: Optional[str] = None
    retrieved_at: Optional[float] = None
    expires_at: Optional[float] = None


@dataclass
class DayItinerary:
    day_number: int
    items: List[ItineraryItem] = field(default_factory=list)
    total_hours: float = 0.0


def build_day_schedule(
    destination: str,
    attractions: List[str],
    network_available: bool = False,
    pace: str = "moderate",
) -> DayItinerary:
    """
    Deterministically builds a day schedule.
    If network is offline, explicitly marks activities with a freshness limitation notice
    rather than hallucinating live opening hours or flight status.
    """
    hours_per_item = 2.0 if pace == "relaxed" else (1.5 if pace == "moderate" else 1.0)
    itinerary = DayItinerary(day_number=1)

    current_hour = 9.0
    for attr in attractions:
        start_str = f"{int(current_hour):02d}:{int((current_hour % 1) * 60):02d}"
        freshness = "NO_DATA: no opening-hours connector or cache was queried."
        item = ItineraryItem(
            time_slot=start_str,
            activity=f"Visit {attr} in {destination}",
            duration_hours=hours_per_item,
            is_live_status=False,
            freshness_notice=freshness,
        )
        itinerary.items.append(item)
        current_hour += hours_per_item + 0.5  # add transit time

    itinerary.total_hours = sum(i.duration_hours for i in itinerary.items)
    return itinerary
