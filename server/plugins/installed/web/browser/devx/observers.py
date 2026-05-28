"""Network and console observers for debugging."""
import asyncio
from typing import Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NetworkEvent:
    timestamp: datetime
    url: str
    method: str
    status: Optional[int] = None
    failed: bool = False


@dataclass
class ConsoleEvent:
    timestamp: datetime
    type: str  # log, warn, error
    text: str


class PageObservers:
    """Attach network and console observers to page."""
    
    def __init__(self):
        self.network_events: list[NetworkEvent] = []
        self.console_events: list[ConsoleEvent] = []
        self._attached = False
    
    async def attach(self, page: Any):
        """Attach observers to page."""
        if self._attached:
            return
        
        page.on("console", self._on_console)
        page.on("requestfailed", self._on_request_failed)
        page.on("response", self._on_response)
        
        self._attached = True
    
    def _on_console(self, msg):
        """Handle console message."""
        try:
            self.console_events.append(ConsoleEvent(
                timestamp=datetime.now(),
                type=msg.type,
                text=msg.text
            ))
        except:
            pass
    
    def _on_request_failed(self, request):
        """Handle failed request."""
        try:
            self.network_events.append(NetworkEvent(
                timestamp=datetime.now(),
                url=request.url,
                method=request.method,
                failed=True
            ))
        except:
            pass
    
    def _on_response(self, response):
        """Handle response."""
        try:
            self.network_events.append(NetworkEvent(
                timestamp=datetime.now(),
                url=response.url,
                method=response.request.method,
                status=response.status,
                failed=response.status >= 400
            ))
        except:
            pass
    
    async def network_idle_for(self, seconds: float) -> bool:
        """Check if network has been idle for N seconds."""
        if not self.network_events:
            return True
        
        last_event = self.network_events[-1]
        elapsed = (datetime.now() - last_event.timestamp).total_seconds()
        return elapsed >= seconds
    
    async def recent_failures(self, *, since_s: float = 5.0) -> list[NetworkEvent]:
        """Get recent failed requests."""
        cutoff = datetime.now().timestamp() - since_s
        return [
            e for e in self.network_events
            if e.failed and e.timestamp.timestamp() >= cutoff
        ]
    
    def get_errors(self) -> list[ConsoleEvent]:
        """Get console errors."""
        return [e for e in self.console_events if e.type == "error"]
    
    def clear(self):
        """Clear all events."""
        self.network_events.clear()
        self.console_events.clear()
