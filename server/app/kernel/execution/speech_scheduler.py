import asyncio
import logging
from enum import IntEnum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

class SpeechPriority(IntEnum):
    BACKGROUND = 1  # Long summaries / informational reports
    NORMAL = 2      # Standard responses (e.g. weather, query replies)
    URGENT = 3      # Crucial warnings / cancellation logs / emergency feedback

class SpeechStream:
    """Wrapper around client speech stream, permitting interruption."""
    def __init__(self, stream_task: asyncio.Task, stream_id: str):
        self.stream_task = stream_task
        self.stream_id = stream_id

    async def terminate(self):
        """Cancel the stream task to halt audio output immediately."""
        if not self.stream_task.done():
            logger.info("Interrupting speech stream: %s", self.stream_id)
            self.stream_task.cancel()
            try:
                await self.stream_task
            except asyncio.CancelledError:
                pass

class TTSScheduler:
    """
    Priority-based speech scheduler.
    Higher-priority speech preempts and cancels lower-priority speech.
    """
    def __init__(self):
        self.current_stream: Optional[SpeechStream] = None
        self.current_priority: SpeechPriority = SpeechPriority.BACKGROUND
        self._lock = asyncio.Lock()

    async def speak(self, text: str, priority: SpeechPriority, user_id: str) -> None:
        """
        Speak text to the user.
        If a higher priority request arrives, interrupts current lower priority stream.
        """
        async with self._lock:
            # Check for preemption
            if self.current_stream:
                if priority > self.current_priority:
                    logger.info(
                        "Preempting speech stream (priority %s > %s)",
                        priority.name,
                        self.current_priority.name
                    )
                    await self.current_stream.terminate()
                    self.current_stream = None
                else:
                    logger.info(
                        "Speech request discarded/postponed due to active higher/equal priority stream (%s >= %s)",
                        self.current_priority.name,
                        priority.name
                    )
                    # For simplicity, if priority is lower or equal, serialize it after the current one finishes
                    # Wait for current stream to finish
                    while self.current_stream and not self.current_stream.stream_task.done():
                        await asyncio.sleep(0.1)

            # Define the actual streaming coroutine
            from app.socket.utils import stream_tts_to_client

            async def _stream():
                try:
                    await stream_tts_to_client(text, user_id=user_id)
                except asyncio.CancelledError:
                    logger.info("Speech stream cancelled: %s", text[:30])
                    raise
                except Exception as exc:
                    logger.error("TTS stream error: %s", exc)

            stream_id = f"stream_{hash(text)}_{asyncio.get_event_loop().time()}"
            task = asyncio.create_task(_stream())
            self.current_stream = SpeechStream(task, stream_id)
            self.current_priority = priority

            # Clean up reference when task completes
            def _cleanup(t):
                if self.current_stream and self.current_stream.stream_task == t:
                    self.current_stream = None
                    self.current_priority = SpeechPriority.BACKGROUND

            task.add_done_callback(_cleanup)


_scheduler = TTSScheduler()

def get_tts_scheduler() -> TTSScheduler:
    global _scheduler
    return _scheduler
