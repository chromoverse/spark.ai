import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from typing import Callable, Any, TypeVar, Coroutine, ParamSpec

logger = logging.getLogger(__name__)

# Create a shared thread pool for blocking operations
_executor = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="async_wrapper"
)

T = TypeVar('T')
P = ParamSpec('P')

async def run_in_executor(func: Callable[..., T], *args, **kwargs) -> T:
    """
    Run a blocking/synchronous function in a thread pool executor.
    
    Usage:
        result = await run_in_executor(blocking_function, arg1, arg2, key=value)
    
    Args:
        func: The blocking function to execute
        *args: Positional arguments for the function
        **kwargs: Keyword arguments for the function
    
    Returns:
        The result of the function execution
    """
    loop = asyncio.get_event_loop()
    
    try:
        # Wrap the function with kwargs if provided
        if kwargs:
            wrapped_func = lambda: func(*args, **kwargs)
            result = await loop.run_in_executor(_executor, wrapped_func)
        else:
            result = await loop.run_in_executor(_executor, func, *args)
        
        return result
    
    except Exception as e:
        logger.error(f"Error executing {func.__name__} in executor: {e}", exc_info=True)
        raise


def make_async(func: Callable[P, T]) -> Callable[P, Coroutine[Any, Any, T]]:
    """
    Decorator to convert a synchronous function into an async function.
    
    Usage:
        @make_async
        def blocking_function(arg1, arg2):
            # blocking code
            return result
        
        # Now you can await it:
        result = await blocking_function(arg1, arg2)
    
    Args:
        func: The synchronous function to wrap
    
    Returns:
        An async version of the function
    """
    @wraps(func)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        return await run_in_executor(func, *args, **kwargs)
    
    return wrapper


def cleanup_executor():
    """
    Cleanup the thread pool executor.
    Call this when shutting down your application.
    """
    global _executor
    if _executor:
        logger.info("Shutting down async executor...")
        _executor.shutdown(wait=True)
        logger.info("Executor shutdown complete")


# ── Retry helpers ─────────────────────────────────────────────────────────────

async def with_retry(
    coro_factory: Callable[[], Coroutine[Any, Any, T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: float = 2.0,
    name: str = "op",
    retry_on: tuple[type, ...] = (Exception,),
    do_not_retry_on: tuple[type, ...] = (),
) -> T:
    """
    Run an async operation up to ``attempts`` times with exponential backoff.

    The factory is invoked fresh on every attempt — this matters because
    a coroutine object can only be awaited once.

    Args:
        coro_factory: Zero-argument callable that returns a fresh coroutine
                      each time it's invoked. Use a lambda:
                          ``lambda: client.do_something(args)``
        attempts:     Total number of attempts (including the first). Default 3.
        base_delay:   Seconds to sleep before the second attempt. Each
                      subsequent retry doubles up to ``max_delay``.
        max_delay:    Cap for the per-retry sleep.
        name:         Label used in log messages (e.g. ``"groq-stt"``).
        retry_on:     Exception types that trigger a retry.
        do_not_retry_on: Exception types that should propagate immediately
                      regardless of ``retry_on``. Useful for auth / 4xx errors.

    Raises:
        The last exception encountered if every attempt failed.
    """
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except do_not_retry_on as e:
            logger.warning("%s: non-retryable error on attempt %d: %s", name, attempt, e)
            raise
        except retry_on as e:
            last_exc = e
            if attempt >= attempts:
                logger.error("%s: failed after %d attempts: %s", name, attempts, e)
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            logger.warning(
                "%s: attempt %d/%d failed (%s); retrying in %.0fms",
                name, attempt, attempts, e, delay * 1000,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc