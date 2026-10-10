"""PERSONA.md in code: the prompt block, the phrase bank, the banned-phrase lint, and tone tags."""

from __future__ import annotations

import random
import re
import uuid
from typing import Literal

from redis.asyncio import Redis

PERSONA_BLOCK = """\
You are Spark, a voice assistant that talks like a sharp, relaxed friend: warm, confident, a \
little playful, never robotic.
How you speak (your words are read aloud):
- Lead with the answer. Short sentences, about 20 words max, everyday words, contractions.
- No lists, markdown, emoji, links, or ids out loud. Say numbers the way people say them.
- Match the user's energy. One question at a time, only when needed.
- Never say "Certainly!", "Absolutely!", "I'd be happy to help", "As an AI", or "Task completed \
successfully". Don't narrate tools ("I executed volume_set"); say what happened in plain words.
- Optionally start a sentence with one tone tag: [chill] [cheerful] [calm] [serious] [excited] \
[whisper]. Default is no tag. Use [serious] for failures that matter, money, or other people.
Hard rules: never invent facts or results. If something failed, say so and offer a next step. \
Never pretend to have human experiences."""

Moment = Literal["ack", "working", "done", "failure", "unreachable", "stuck"]

BANK: dict[Moment, tuple[str, ...]] = {
    "ack": ("On it.", "Got it.", "Sure thing.", "Yep.", "You got it."),
    "working": ("Give me a sec.", "Almost there.", "One moment."),
    "done": ("Done.", "All set.", "There you go.", "Easy."),
    "failure": (
        "Hmm, that didn't work.",
        "That one didn't go through.",
        "Something went sideways there.",
    ),
    "stuck": (
        "That one got stuck on my side. Mind saying it again?",
        "I lost track of that one, sorry. Try me again?",
    ),
    "unreachable": (
        "I can't reach my brain's models right now. Give me a minute and try again.",
        "My models aren't answering right now. Try me again in a minute.",
    ),
}


async def phrase(redis: Redis, user_id: uuid.UUID, moment: Moment) -> str:
    """A phrase for the moment, never the same as this user's last one (PERSONA §2.6)."""
    key = f"phrase:{user_id}:{moment}"
    last = await redis.get(key)
    options = [p for p in BANK[moment] if p != last] or list(BANK[moment])
    choice = random.choice(options)  # noqa: S311 (variety, not security)
    await redis.set(key, choice, ex=3600)
    return choice


# Banned phrase → replacement (PERSONA §9). Matched case-insensitively, whole phrase.
_BANNED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), r)
    for p, r in (
        (r"\btask (has been )?completed successfully\.?", "Done."),
        (r"\bthe operation has been executed\.?", "Done."),
        (r"\bcertainly!?\s*", ""),
        (r"\babsolutely!?\s*", ""),
        (r"\bI'?d be (happy|glad) to help( you)?( with that)?[.!]?\s*", ""),
        (r"\bas an AI( language model)?,?\s*", ""),
        (r"\bprocessing your request\.?", "Give me a sec."),
        (r"\bplease wait\.?", "One sec."),
        (r"\ban error (has )?occurred\.?", "Something went wrong."),
    )
)
_URL = re.compile(r"https?://\S+")
_MARKDOWN = re.compile(r"[*_#`>]+|^\s*[-•]\s+|^\s*\d+\.\s+", re.MULTILINE)
_EMOJI = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f\u200d]")  # TTS reads them out
_TAG = re.compile(r"^\s*\[(\w+)\]\s*")
TONES = frozenset({"chill", "cheerful", "calm", "serious", "excited", "whisper"})


def has_banned(text: str) -> bool:
    """For the persona eval: did the model say something PERSONA.md bans?"""
    return any(p.search(text) for p, _ in _BANNED)


def lint(sentence: str) -> str:
    """Rewrites banned phrases and strips what can't be spoken. May return ''."""
    out = sentence
    for pattern, replacement in _BANNED:
        out = pattern.sub(replacement, out)
    out = _URL.sub("the link on screen", out)
    out = _MARKDOWN.sub("", out)
    out = _EMOJI.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    if out and out[0].islower() and sentence[:1].isupper():
        out = out[0].upper() + out[1:]
    return out


def split_tone(sentence: str) -> tuple[str | None, str]:
    """'[serious] Heads up…' → ('serious', 'Heads up…'). Unknown tags are dropped, not spoken."""
    m = _TAG.match(sentence)
    if not m:
        return None, sentence
    tag = m.group(1).lower()
    return (tag if tag in TONES else None), sentence[m.end() :]
