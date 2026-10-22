from __future__ import annotations

import os
import subprocess
import sys

import pytest

from app.services import parent_watch


@pytest.mark.asyncio
async def test_core_shuts_down_once_the_app_is_gone(monkeypatch) -> None:
    monkeypatch.setattr(parent_watch, "CHECK_INTERVAL_S", 0)
    stopped: list[bool] = []
    monkeypatch.setattr(parent_watch, "_shut_down", lambda: stopped.append(True))
    answers = iter([True, True, False])

    await parent_watch.watch_parent(123, alive=lambda: next(answers))

    assert stopped == [True]


def test_watches_a_process_not_just_its_pid() -> None:
    """Alive while running, not alive once ended -- also when it isn't the
    direct parent (the bundled core runs behind PyInstaller's launcher)."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        alive = parent_watch._process_alive_check(child.pid)
        assert alive() is True
    finally:
        child.kill()
        child.wait()
    assert alive() is False


def test_own_parent_counts_as_alive() -> None:
    assert parent_watch.parents_alive_check(os.getppid())() is True
