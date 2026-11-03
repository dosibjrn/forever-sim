"""Compatibility re-export; solo-leveling travel policy is scenario-owned."""
from src.scenarios.timing import (
    BASE_BETWEEN_PULL_TRAVEL_S,
    TIMING_CONTRACT_VERSION,
    between_pull_travel_s,
)

__all__ = [
    "BASE_BETWEEN_PULL_TRAVEL_S",
    "TIMING_CONTRACT_VERSION",
    "between_pull_travel_s",
]
