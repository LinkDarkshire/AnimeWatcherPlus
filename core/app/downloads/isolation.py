"""Plugin code never runs on the server's own event loop.

Download plugins are anyone's Python. One that makes a blocking call --
`requests`, `time.sleep`, a synchronous HTTP library -- would otherwise stop
the whole server (every other request, the live updates) for as long as it
takes. So each plugin call runs on a worker thread with an event loop of its
own: the plugin is created there, called, and closed there. The server only
waits for the result, with a time limit; a plugin that hangs costs its own
result and a worker thread, nothing else.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Enough for every source of a search at once plus status polling; a hung
# plugin keeps its thread, so not too few either.
_EXECUTOR = ThreadPoolExecutor(max_workers=16, thread_name_prefix="awp-plugin")


async def run_plugin[T](
    make: Callable[[], Any],
    call: Callable[[Any], Awaitable[T]],
    *,
    limit_s: float | None,
) -> T:
    """`make()` creates the plugin, `call(plugin)` uses it -- both on a
    worker thread; the plugin is closed there afterwards. Raises whatever the
    plugin raised, or TimeoutError."""

    def worker() -> T:
        async def run() -> T:
            plugin = make()
            try:
                return await call(plugin)
            finally:
                try:
                    await plugin.close()
                except Exception:
                    logger.exception("download_plugin_close_failed")

        return asyncio.run(run())

    future = asyncio.get_running_loop().run_in_executor(_EXECUTOR, worker)
    return await asyncio.wait_for(future, timeout=limit_s)
