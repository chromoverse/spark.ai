"""Quick device tools the reflex may call (REDESIGN §5.1). Implemented in `body/spark_body/hands/`;
the brain only declares them. Deterministic order keeps the prompt cacheable."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.tools.spec import Risk, ToolSpec


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VolumeSet(_In):
    level: int = Field(ge=0, le=100, description="Volume percent, 0-100")


class VolumeChange(_In):
    direction: Literal["up", "down"]
    step: int = Field(default=10, ge=1, le=50, description="Percent to move, default 10")


class VolumeMute(_In):
    mute: bool = Field(description="true mutes, false unmutes")


class MediaControl(_In):
    action: Literal["play", "pause", "toggle", "next", "previous"]


class MediaPlay(_In):
    query: str = Field(max_length=200, description="What to play, in the user's words")
    app: str | None = Field(
        default=None, max_length=60, description="App to play it in, e.g. 'spotify'; omit if unsaid"
    )


class AppOpen(_In):
    app: str = Field(max_length=60, description="App name as the user said it, e.g. 'spotify'")


class BrightnessSet(_In):
    level: int = Field(ge=0, le=100, description="Screen brightness percent, 0-100")


QUICK_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "volume_set",
        "Sets the device volume to a percent.",
        VolumeSet,
        "device",
        Risk.WRITE,
        requires=frozenset({"volume"}),
    ),
    ToolSpec(
        "volume_change",
        "Turns the volume up or down by a step. Use for 'louder', 'turn it down'.",
        VolumeChange,
        "device",
        Risk.WRITE,
        requires=frozenset({"volume"}),
    ),
    ToolSpec(
        "volume_mute",
        "Mutes or unmutes the device.",
        VolumeMute,
        "device",
        Risk.WRITE,
        requires=frozenset({"volume"}),
    ),
    ToolSpec(
        "media_control",
        "Controls whatever media is playing: play (also 'resume'), pause, next, previous. "
        "toggle only when the user doesn't say which.",
        MediaControl,
        "device",
        Risk.WRITE,
        requires=frozenset({"media"}),
    ),
    ToolSpec(
        "media_play",
        "Starts playing something (a song, artist, mood, video) in a media app. 'Open Spotify "
        "and play X' is one media_play call with app set.",
        MediaPlay,
        "device",
        Risk.WRITE,
        requires=frozenset({"media"}),
        timeout_s=8,
    ),
    ToolSpec(
        "app_open",
        "Opens an installed app by the name the user said ('google chrome', or a generic "
        "'browser'); the device resolves it against its installed apps.",
        AppOpen,
        "device",
        Risk.WRITE,
        requires=frozenset({"apps"}),
    ),
    ToolSpec(
        "brightness_set",
        "Sets the screen brightness to a percent.",
        BrightnessSet,
        "device",
        Risk.WRITE,
        requires=frozenset({"brightness"}),
    ),
)
