"""Replay log - JSONL event logging with screenshots."""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
from .events import BrowserEvent, BrowserEventType, get_event_bus

logger = logging.getLogger(__name__)


class ReplayLog:
    """JSONL replay log writer."""
    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_log: Optional[Path] = None
        self.run_id: Optional[str] = None
        
        # Subscribe to all browser events
        bus = get_event_bus()
        for event_type in BrowserEventType:
            bus.subscribe(event_type, self._on_event)

    def start_run(self, run_id: str):
        """Start a new run log."""
        self.run_id = run_id
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.current_log = self.log_dir / f"run_{run_id}_{timestamp}.jsonl"
        logger.info("ReplayLog started: %s", self.current_log)

    def _on_event(self, event: BrowserEvent):
        """Handle browser event."""
        if not self.current_log:
            return
        
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "run_id": self.run_id,
                "event_type": event.type.value,
                "data": event.data
            }
            with open(self.current_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.exception("Failed to write replay log: %s", e)

    def write_screenshot(self, screenshot_data: bytes, label: str) -> str:
        """Write screenshot to disk, return path."""
        if not self.run_id:
            return ""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"screenshot_{self.run_id}_{label}_{timestamp}.png"
        path = self.log_dir / filename
        
        try:
            with open(path, "wb") as f:
                f.write(screenshot_data)
            return str(path)
        except Exception as e:
            logger.exception("Failed to write screenshot: %s", e)
            return ""

    def end_run(self):
        """End current run."""
        if self.current_log:
            logger.info("ReplayLog ended: %s", self.current_log)
        self.current_log = None
        self.run_id = None
