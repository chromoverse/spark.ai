"""Voice proxy (API.md §2.5): devices reach Groq Orpheus (TTS) and Groq Whisper (STT) through the
brain so platform keys never leave it (ENVIRONMENT §3.3). Keys rotate on rate limits with the
same health circuits as the LLM chains."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from app.api.deps import Me, Rt
from app.core import ratelimit
from app.core.errors import ApiError, ok
from app.llm.chains import providers
from app.llm.health import Health, health_id
from app.llm.types import ProviderError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v2/proxy")

GROQ = "https://api.groq.com/openai/v1"
TTS_MODEL = "canopylabs/orpheus-v1-english"
STT_MODEL = "whisper-large-v3-turbo"
DIRECTIONS = {"cheerful", "calm", "serious", "excited", "whisper"}  # PERSONA §5; chill = none
MAX_AUDIO_BYTES = 4 * 1024 * 1024  # ~2 min of 16 kHz mono WAV
AUDIO_TYPES = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/flac": "flac",
}
NO_VOICE = "My cloud voice is taking a break. I'll use this device's own voice for now."
NO_EARS = "My cloud hearing is taking a break. Try again in a minute."


class TtsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=200)  # Orpheus takes ≤ 200 chars: one sentence
    voice: Literal["autumn", "diana", "hannah", "austin", "daniel", "troy"] = "daniel"
    tone: str | None = Field(default=None, max_length=20)


def _error(r: httpx.Response) -> ProviderError:
    if r.status_code == 429:
        retry = r.headers.get("retry-after")
        return ProviderError(
            "rate_limited", "429", float(retry) if retry and retry.isdigit() else None
        )
    return ProviderError("unavailable" if r.status_code >= 500 else "rejected", str(r.status_code))


async def _keys(rt: Rt, model: str) -> list[tuple[str, str]]:
    """(api_key, health id) for every Groq key whose circuit for `model` is closed."""
    keys = providers(rt.settings)["groq"][1]
    hids = [health_id("groq", k, model) for k in keys]
    closed = await Health(rt.redis, rt.clock).closed(hids)
    return [(k, h) for k, h, ok_ in zip(keys, hids, closed, strict=True) if ok_]


@router.post("/tts")
async def tts(body: TtsBody, me: Me, rt: Rt) -> StreamingResponse:
    await ratelimit.hit(rt.redis, "proxy_tts", str(me.user_id), limit=120, window_s=3600)
    text = f"[{body.tone}] {body.text}" if body.tone in DIRECTIONS else body.text
    health = Health(rt.redis, rt.clock)
    for key, hid in await _keys(rt, TTS_MODEL):
        t0 = rt.clock.monotonic()
        req = rt.http.build_request(
            "POST",
            f"{GROQ}/audio/speech",
            json={"model": TTS_MODEL, "input": text, "voice": body.voice, "response_format": "wav"},
            headers={"Authorization": f"Bearer {key}"},
        )
        try:
            r = await rt.http.send(req, stream=True)
        except httpx.HTTPError:
            await health.fail(hid, ProviderError("unavailable", "transport"))
            continue
        if r.status_code != 200:
            await r.aclose()
            await health.fail(hid, _error(r))
            continue
        await health.ok(hid, (rt.clock.monotonic() - t0) * 1000)

        async def relay(resp: httpx.Response = r) -> AsyncIterator[bytes]:
            async for chunk in resp.aiter_bytes():
                yield chunk

        return StreamingResponse(
            relay(), media_type="audio/wav", background=BackgroundTask(r.aclose)
        )
    raise ApiError("provider_unavailable", NO_VOICE, retry_after_s=60)


@router.post(
    "/stt",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {t: {"schema": {"type": "string", "format": "binary"}} for t in AUDIO_TYPES},
        }
    },
)
async def stt(
    request: Request,
    me: Me,
    rt: Rt,
    lang: str = Query("en", min_length=2, max_length=10),
) -> dict[str, Any]:
    """Raw audio body (`Content-Type: audio/wav` or `audio/webm`) → `{ text, lang }`. Used only
    when the device's engine plan picks cloud STT (RULES §9)."""
    await ratelimit.hit(rt.redis, "proxy_stt", str(me.user_id), limit=300, window_s=3600)
    audio = await request.body()
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        raise ApiError("invalid_input", "That clip was empty or too long. Try a shorter one.")
    mime = request.headers.get("content-type", "audio/wav").split(";")[0]
    ext = AUDIO_TYPES.get(mime)
    if ext is None:
        raise ApiError("invalid_input", "I can only hear WAV, WebM, Ogg, MP3, or FLAC clips.")
    health = Health(rt.redis, rt.clock)
    for key, hid in await _keys(rt, STT_MODEL):
        t0 = rt.clock.monotonic()
        try:
            r = await rt.http.post(
                f"{GROQ}/audio/transcriptions",
                files={"file": (f"clip.{ext}", audio, mime)},
                data={"model": STT_MODEL, "language": lang, "response_format": "json"},
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        except httpx.HTTPError:
            await health.fail(hid, ProviderError("unavailable", "transport"))
            continue
        if r.status_code != 200:
            await health.fail(hid, _error(r))
            continue
        await health.ok(hid, (rt.clock.monotonic() - t0) * 1000)
        return ok({"text": str(r.json().get("text", "")).strip(), "lang": lang})
    raise ApiError("provider_unavailable", NO_EARS, retry_after_s=60)
