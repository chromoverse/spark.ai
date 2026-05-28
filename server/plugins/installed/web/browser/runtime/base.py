"""BrowserRuntime interface."""
from abc import ABC, abstractmethod
from typing import Callable, Any


class BrowserRuntime(ABC):
    """Abstract interface for browser automation backends."""
    
    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run
        self._connected = False

    @abstractmethod
    async def connect(self) -> None:
        """Connect to browser via CDP or other protocol."""
        pass

    @abstractmethod
    async def new_page(self) -> Any:
        """Create and return a new page/tab."""
        pass

    @abstractmethod
    async def pages(self) -> list[Any]:
        """Return list of all open pages."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from browser."""
        pass

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    @abstractmethod
    async def is_alive(self) -> bool:
        """Check if browser is still responsive."""
        pass

    @abstractmethod
    async def is_authenticated(self, *, hint_url: str) -> bool:
        """Check if user is authenticated on the given site."""
        pass

    @abstractmethod
    async def on_tab_crashed(self, cb: Callable) -> None:
        """Register callback for tab crash events."""
        pass
