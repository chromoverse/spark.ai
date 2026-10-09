"""Cuts a token stream into speakable chunks (ported from v1 `stream_service`). The first chunk
is cut early, at a clause if needed, so the device starts speaking as soon as possible."""

from __future__ import annotations

import re

_SENTENCE = re.compile(r"(?<!\.)(?<!…)[.!?][\"')\]]?\s+")
_CLAUSE = re.compile(r"[,;:—]\s+")


def _words(text: str) -> int:
    return len(text.split())


def _last_boundary(pattern: re.Pattern[str], buf: str, min_words: int) -> int:
    cut = -1
    for m in pattern.finditer(buf):
        if _words(buf[: m.end()]) >= min_words:
            cut = m.end()
    return cut


class Splitter:
    """feed() returns the chunks ready to speak; flush() returns the rest at end of stream."""

    def __init__(self) -> None:
        self.buf = ""
        self.first = True

    def _cut(self) -> int:
        min_w, soft_w, max_w = (2, 8, 30) if self.first else (4, 12, 30)
        n = _words(self.buf)
        if n < min_w:
            return -1
        if (cut := _last_boundary(_SENTENCE, self.buf, min_w)) > 0:
            return cut
        if n >= soft_w and (cut := _last_boundary(_CLAUSE, self.buf, min_w)) > 0:
            return cut
        if n >= max_w:
            return len(" ".join(self.buf.split()[:max_w]))
        return -1

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while (cut := self._cut()) > 0:
            chunk, self.buf = self.buf[:cut].strip(), self.buf[cut:].lstrip()
            if chunk:
                out.append(chunk)
                self.first = False
        return out

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []

    def reset(self) -> None:
        self.buf = ""
