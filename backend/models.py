"""Request models for the API. Responses are plain dicts produced by the
dataclasses in the other modules, which FastAPI serializes directly.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """Sent over the /ws/run WebSocket to start a benchmark."""
    letter: str = Field(..., description="Drive letter, e.g. 'E'")
    depth: str = Field("quick", description="quick | full | sustained")
    blurb: Optional[str] = Field(None, description="Marketing text to grade against")
    sustained_size_mb: Optional[int] = Field(
        None, description="Override sustained-test size in MB")
    seq_size_mb: Optional[int] = Field(None, description="Override sequential file size in MB")
    allow_system: bool = Field(False, description="Permit benchmarking the system drive")


class AnalyzeRequest(BaseModel):
    """Re-grade an existing result set against (possibly edited) marketing text,
    without re-running the benchmark."""
    blurb: str
    benchmark: dict
    diagnostics: dict
