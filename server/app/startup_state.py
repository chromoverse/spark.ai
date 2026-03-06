from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StartupState:
    """
    Shared startup state populated by startup initializers and consumed by main lifespan.
    """

    model_loader: Any = None
    embedding_worker: Any = None
    ml_device: str | None = None
    embedding_ready: bool = False
    pinecone_service: Any = None
    pinecone_ready: bool = False


startup_state = StartupState()
