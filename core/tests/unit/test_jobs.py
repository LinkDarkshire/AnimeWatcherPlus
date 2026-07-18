from __future__ import annotations

import asyncio

import pytest

from app.services.jobs import EventBus, JobQueue


@pytest.mark.asyncio
async def test_event_bus_publishes_to_subscribers() -> None:
    bus = EventBus()
    received = []

    async def handler(payload):
        received.append(payload)

    bus.subscribe(handler)
    await bus.publish("anime.discovered", {"anime_id": 1})
    assert received == [{"event": "anime.discovered", "data": {"anime_id": 1}}]


@pytest.mark.asyncio
async def test_event_bus_isolates_failing_subscriber() -> None:
    """NFA-12-adjacent: one broken subscriber must not break the others."""
    bus = EventBus()
    received = []

    async def bad_handler(_payload):
        raise RuntimeError("boom")

    async def good_handler(payload):
        received.append(payload)

    bus.subscribe(bad_handler)
    bus.subscribe(good_handler)
    await bus.publish("x", {})
    assert len(received) == 1


@pytest.mark.asyncio
async def test_job_queue_runs_jobs_and_isolates_failures() -> None:
    bus = EventBus()
    queue = JobQueue(bus)
    queue.start()
    results = []

    async def ok_job():
        results.append("ok")

    async def failing_job():
        raise ValueError("nope")

    job1 = queue.enqueue("test", ok_job)
    job2 = queue.enqueue("test", failing_job)

    for _ in range(50):
        if job1.status != "queued" and job2.status != "queued" and job1.status != "running" and job2.status != "running":
            break
        await asyncio.sleep(0.02)

    assert job1.status == "done"
    assert job2.status == "failed"
    assert job2.error == "nope"
    assert results == ["ok"]

    await queue.stop()
