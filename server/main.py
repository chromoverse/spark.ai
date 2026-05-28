# main.py
import asyncio
import sys

# CRITICAL — must run before anything imports Playwright. On Windows,
# Playwright spawns its node-based driver via asyncio.create_subprocess_exec,
# which raises NotImplementedError under SelectorEventLoop. Uvicorn's
# --reload mode can land us on Selector even on Python 3.11 (where
# Proactor is the documented default). Pinning the policy here is the
# only reliable way to guarantee Playwright works in dev + prod.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    # Uvicorn passes an explicit loop_factory to asyncio.Runner, which
    # bypasses the policy above. When reload=True (or workers>1) its
    # factory returns SelectorEventLoop on Windows — and Selector can't
    # spawn subprocesses, so Playwright dies with NotImplementedError.
    # Force the factory to hand back ProactorEventLoop regardless.
    import uvicorn.loops.asyncio as _uv_asyncio
    _uv_asyncio.asyncio_loop_factory = lambda use_subprocess=False: asyncio.ProactorEventLoop

import uvicorn
from app.config import settings

from dotenv import load_dotenv
load_dotenv()

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=settings.port, reload=True)