"""Desktop mode: the core runs as the desktop app's child process. If the app
goes away without stopping it (crash, killed from the task manager, a
restart), the core ends too instead of running on in the background -- with
the scanner, on the same folders and database.

Two processes are watched: the app (its PID comes from the app) and the
core's own parent at start. In the bundled app those differ: PyInstaller's
one-file executable is a small launcher that starts the actual Python process,
so the app stopping the core ends the launcher -- the Python process must
notice that, too.
"""

from __future__ import annotations

import asyncio
import os
import select
import signal
import sys
from collections.abc import Callable

import structlog

logger = structlog.get_logger(__name__)

CHECK_INTERVAL_S = 2.0


def _process_alive_check(pid: int) -> Callable[[], bool]:
    """A check bound to the process as it is now -- a later process that
    happens to get the same PID doesn't count as alive."""
    if sys.platform == "win32":
        import ctypes

        synchronize, wait_timeout = 0x00100000, 0x102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(synchronize, False, pid)
        if not handle:
            logger.warning("parent_watch_unavailable", pid=pid)
            return lambda: True
        return lambda: bool(kernel32.WaitForSingleObject(handle, 0) == wait_timeout)

    if hasattr(os, "pidfd_open"):  # Linux: becomes readable when the process ends
        try:
            fd = os.pidfd_open(pid)
        except ProcessLookupError:
            return lambda: False
        except OSError:
            fd = None
        if fd is not None:
            return lambda: not select.select([fd], [], [], 0)[0]

    def alive() -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    return alive


def parents_alive_check(app_pid: int) -> Callable[[], bool]:
    checks = [_process_alive_check(pid) for pid in {app_pid, os.getppid()}]
    return lambda: all(check() for check in checks)


def _shut_down() -> None:
    if sys.platform == "win32":
        os._exit(0)
    # uvicorn shuts down cleanly on SIGTERM.
    os.kill(os.getpid(), signal.SIGTERM)


async def watch_parent(app_pid: int, alive: Callable[[], bool] | None = None) -> None:
    alive = alive or parents_alive_check(app_pid)
    while True:
        await asyncio.sleep(CHECK_INTERVAL_S)
        if not alive():
            logger.warning("desktop_app_gone_shutting_down", parent_pid=app_pid)
            _shut_down()
            return
