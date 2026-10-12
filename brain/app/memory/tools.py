"""remember / recall / forget (REDESIGN §7, Self tools). The reflex runs remember and forget on
the spot; the agent reaches all three through its loop (hooks, permissions, steps)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.memory import store
from app.tools.spec import Risk, ToolSpec


class Remember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(
        max_length=300,
        description="One short sentence about the user, e.g. 'The user's sister is Asha.'",
    )
    kind: Literal["preference", "person", "routine", "fact", "correction"] = "fact"


class Recall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(max_length=200, description="What you want to know, in a few words")


class Forget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    what: str = Field(max_length=200, description="The thing to forget, in a few words")


async def remember(call: Any, inp: dict[str, Any]) -> str:
    """From a job the agent may have read it in a file or a page: it waits for the user's OK on
    the Memory page and stays out of prompts until then."""
    confirmed = call.job_id is None
    await store.save(
        call.rt, call.user_id, inp["text"], inp.get("kind", "fact"), 0.8, confirmed=confirmed
    )
    if confirmed:
        return "Saved."
    return "Saved for the user to confirm on the Memory page. Don't count on it until then."


async def recall(call: Any, inp: dict[str, Any]) -> str:
    hits = await store.search(call.rt, call.user_id, inp["query"])
    return "\n".join(f"- {h.text}" for h in hits) or "Nothing saved about that."


async def forget(call: Any, inp: dict[str, Any]) -> str:
    gone = await store.forget(call.rt, call.user_id, inp["what"])
    return f"Forgot: {gone}" if gone else "Nothing like that was saved."


REMEMBER = ToolSpec(
    "remember",
    "Keeps a fact about the user in your memory (a person, a preference, a routine) when they "
    "ask you to remember it. Not for files or notes.",
    Remember,
    "brain",
    Risk.WRITE,
    keywords="remember note save fact know",
    handler=remember,
)
RECALL = ToolSpec(
    "recall",
    "Searches what you remember about the user.",
    Recall,
    "brain",
    Risk.READ,
    keywords="remember memory know about who",
    handler=recall,
)
FORGET = ToolSpec(
    "forget",
    "Drops a fact about the user from your memory when they ask you to forget it. Not for files.",
    Forget,
    "brain",
    Risk.WRITE,
    keywords="forget memory delete remove",
    handler=forget,
)
MEMORY_TOOLS: tuple[ToolSpec, ...] = (REMEMBER, RECALL, FORGET)
