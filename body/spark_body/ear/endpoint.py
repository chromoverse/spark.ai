"""Endpointing from VAD speech probabilities (REDESIGN §4.2): the end of an utterance fires after
200 ms of silence (a speculative start: the brain begins right away), and speech that resumes
shortly after cancels it. While Spark is talking, a much stronger, longer voice is needed to
count as the user (barge-in), so Spark's own voice from the speakers isn't heard as a signal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Event = Literal["start", "end", "resume", "closed", "barge_in"]


@dataclass
class Endpointer:
    frame_ms: float = 32.0  # Silero VAD window at 16 kHz
    start_ms: float = 96.0  # speech this long starts an utterance
    end_ms: float = 200.0  # silence this long ends it (speculative)
    resume_ms: float = 800.0  # speech within this after an end resumes the same utterance
    pos: float = 0.5
    neg: float = 0.35
    barge_pos: float = 0.85  # while Spark speaks (echo suppression)
    barge_ms: float = 200.0
    speaking: bool = False  # set by the mouth: Spark's audio is playing

    state: Literal["idle", "speech", "ended"] = "idle"
    _pos_ms: float = 0.0
    _neg_ms: float = 0.0

    def feed(self, prob: float) -> list[Event]:
        events: list[Event] = []
        threshold, needed = (
            (self.barge_pos, self.barge_ms) if self.speaking else (self.pos, self.start_ms)
        )
        if prob >= threshold:
            self._pos_ms += self.frame_ms
            self._neg_ms = 0.0
        elif prob < self.neg:
            self._neg_ms += self.frame_ms
            self._pos_ms = 0.0
        if self.state == "idle" and self._pos_ms >= needed:
            self.state = "speech"
            events.append("barge_in" if self.speaking else "start")
        elif self.state == "speech" and self._neg_ms >= self.end_ms:
            self.state = "ended"
            events.append("end")
        elif self.state == "ended":
            if self._pos_ms >= self.start_ms:
                self.state = "speech"
                events.append("resume")
            elif self._neg_ms >= self.end_ms + self.resume_ms:
                self.state = "idle"
                self._neg_ms = 0.0
                events.append("closed")
        return events
