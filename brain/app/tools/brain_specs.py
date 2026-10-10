"""Brain tools the agent loop runs itself (REDESIGN §5.2): planning, asking, sub-agents, plan
approval, and finding more tools. They touch only the job, so they're all read risk."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.spec import Risk, ToolSpec


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TodoItem(_In):
    text: str = Field(max_length=200)
    status: Literal["pending", "in_progress", "done"] = "pending"


class TodoWrite(_In):
    items: list[TodoItem] = Field(min_length=1, max_length=20)
    eta_s: int | None = Field(
        default=None, ge=1, le=3600, description="Your estimate of the seconds left"
    )


class AskUser(_In):
    question: str = Field(max_length=200, description="One short spoken question")
    options: list[str] = Field(default_factory=list, max_length=6)


class Task(_In):
    description: str = Field(
        max_length=2000, description="A self-contained task; the sub-agent sees nothing else"
    )


class PlanStep(_In):
    tool: str = Field(max_length=60)
    target: str = Field(
        default="", max_length=500, description="The exact path, command, or name it acts on"
    )
    why: str = Field(default="", max_length=200)


class PlanSubmit(_In):
    summary: str = Field(max_length=300, description="One sentence: what you'll do")
    steps: list[PlanStep] = Field(min_length=1, max_length=20)


class ToolSearch(_In):
    query: str = Field(max_length=200, description="What you need to do, in a few words")


BRAIN_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "todo_write",
        "Writes the job's checklist (the whole list each time). Use it for 3+ step jobs and "
        "keep statuses current; the user watches it.",
        TodoWrite,
        "brain",
        Risk.READ,
    ),
    ToolSpec(
        "ask_user",
        "Asks the user one question and waits for the answer. Only when you're blocked.",
        AskUser,
        "brain",
        Risk.READ,
        timeout_s=300,
    ),
    ToolSpec(
        "task",
        "Runs a sub-agent with read-only tools on a self-contained task (heavy reading, "
        "searching many files) and returns only its answer.",
        Task,
        "brain",
        Risk.READ,
        timeout_s=180,
    ),
    ToolSpec(
        "plan_submit",
        "Shows the user your plan before destructive or sending steps and waits for OK. "
        "Approved steps run without asking again.",
        PlanSubmit,
        "brain",
        Risk.READ,
        timeout_s=300,
    ),
    ToolSpec(
        "tool_search",
        "Finds more tools when none of yours fit; the matches become available next turn.",
        ToolSearch,
        "brain",
        Risk.READ,
    ),
)
