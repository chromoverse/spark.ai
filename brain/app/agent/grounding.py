"""Grounding check (REDESIGN §19.1, RULES §6): a wrap-up may only name things that came from the
user or a tool output. Catches v1's invented calendar events and emails before they're spoken.

ponytail: claims are found by shape (quoted text, file names, times, ids, capitalized names mid-
sentence), not understood. Counts and paraphrases pass. An LLM judge can replace it if real
summaries slip through or get blocked wrongly."""

from __future__ import annotations

import re
from collections.abc import Iterable

# Quotes, but not apostrophes: "didn't … couldn't" isn't a quotation.
_QUOTED = re.compile(r"[\"“]([^\"”]{3,60})[\"”]|(?<!\w)'([^']{3,60})'(?!\w)")
_FILE = re.compile(r"\b[\w\-]+\.[A-Za-z0-9]{2,5}\b")
_TIME = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)", re.IGNORECASE)
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
_IDLIKE = re.compile(r"\b(?=[A-Za-z\-]*\d)(?=\w*[A-Za-z])[\w\-]{4,}\b")  # INV-2041, r2d2
_NAME = re.compile(r"(?<=[a-z,;] )([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)")  # capitalized mid-sentence

# Words that are capitalized without being claims about the user's data.
_COMMON = frozenset(
    "i spark ok okay monday tuesday wednesday thursday friday saturday sunday january february "
    "march april may june july august september october november december desktop documents "
    "downloads pictures music videos home recycle bin windows powershell today tomorrow "
    "english your my the this that a an".split()
)
# Models write non-breaking hyphens and spaces, soft hyphens, and curly quotes; tools don't.
_UNICODE = str.maketrans(
    {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
     "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u00ad": None, "\u200b": None,
     "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
)  # fmt: skip


def plain(text: str) -> str:
    return text.translate(_UNICODE)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w:.\-@ ]", " ", plain(text).lower())).strip()


def claims(summary: str) -> set[str]:
    found: set[str] = set()
    summary = plain(summary)
    for pattern in (_QUOTED, _FILE, _TIME, _CLOCK, _IDLIKE, _NAME):
        for m in pattern.finditer(summary):
            text = next((g for g in m.groups() if g), m.group(0)).strip().rstrip(".,!?;:")
            if pattern is _NAME:  # "Your Pictures" → "Pictures" → common: not a claim
                text = " ".join(w for w in text.split() if w.lower() not in _COMMON)
            if text and text.lower() not in _COMMON:
                found.add(text)
    return found


def unsupported(summary: str, evidence: Iterable[str]) -> list[str]:
    """Claims in the summary that no evidence text contains (case and spacing ignored)."""
    pool = _norm(" ".join(evidence))
    squashed = pool.replace(" ", "")
    missing = []
    for claim in sorted(claims(summary)):
        c = _norm(claim)
        if c and c not in pool and c.replace(" ", "") not in squashed:
            missing.append(claim)
    return missing
