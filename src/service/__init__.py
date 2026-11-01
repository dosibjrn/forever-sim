"""Persistent optimizer service/control-plane primitives.

Phase 1 owns durable job identity and queue state. Heavy optimizer execution is
wired in later slices; browser/CLI clients should converge on this contract.
"""

from .models import JobRequest, JobState
from .store import QueueStore

__all__ = ["JobRequest", "JobState", "QueueStore"]
