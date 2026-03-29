"""
health/server_watch.py

Blocks daemon startup until the server is healthy.
Also called after a socket disconnect to verify server is still alive
before attempting a reconnect.
"""

import asyncio
import logging
import httpx
from config import settings

logger = logging.getLogger(__name__)


async def wait_for_server(
    url: str | None = None,
    poll_interval: float | None = None,
    timeout: float | None = None,
) -> bool:
    """
    Poll GET /health until the server responds 200.

    Returns True when healthy, False if timeout exceeded.
    Logs progress every 5 polls so the user knows it's not frozen.
    """
    base = url or settings.SERVER_URL
    health_url = f"{base.rstrip('/')}/health"
    interval = poll_interval or settings.HEALTH_POLL_INTERVAL_S
    deadline = timeout or settings.HEALTH_POLL_TIMEOUT_S

    logger.info(f"⏳ Waiting for server at {health_url} (timeout: {deadline}s)")

    elapsed = 0.0
    attempt = 0

    async with httpx.AsyncClient(timeout=3.0) as client:
        while elapsed < deadline:
            attempt += 1
            try:
                resp = await client.get(health_url)
                if resp.status_code == 200:
                    logger.info(f"✅ Server healthy after {elapsed:.1f}s ({attempt} attempts)")
                    return True
            except (httpx.ConnectError, httpx.TimeoutException):
                pass  # server not up yet — expected on boot
            except Exception as exc:
                logger.debug(f"Health check error: {exc}")

            if attempt % 5 == 0:
                logger.info(f"  still waiting… ({elapsed:.0f}s elapsed)")

            await asyncio.sleep(interval)
            elapsed += interval

    logger.error(
        f"❌ Server did not become healthy within {deadline}s. "
        f"Check that the server process started correctly."
    )
    return False


async def is_server_alive(url: str | None = None) -> bool:
    """
    Single non-blocking health check — used by socket_client before reconnect.
    Returns True/False immediately.
    """
    base = url or settings.SERVER_URL
    health_url = f"{base.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(health_url)
            return resp.status_code == 200
    except Exception:
        return False