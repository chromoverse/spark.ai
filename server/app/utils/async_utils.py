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