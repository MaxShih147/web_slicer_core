"""Process-wide FIFO for Prusa / engine jobs.

At most one engine job runs at a time. Later jobs stay ``pending`` until they
acquire the lock and the wrapped function writes ``processing``.
"""
from __future__ import annotations

import asyncio
import functools
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")
Work = Callable[[], Awaitable[T]]


class EngineJobQueue:
    """FIFO serializer. ``asyncio.Lock`` waiters are FIFO on CPython."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._running_job_id: str | None = None
        self._pending_job_ids: list[str] = []

    @property
    def running_count(self) -> int:
        return 1 if self._running_job_id is not None else 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "running_job_id": self._running_job_id,
            "pending_job_ids": list(self._pending_job_ids),
        }

    async def run(self, job_id: str, work: Work[T]) -> T:
        self._pending_job_ids.append(job_id)
        try:
            async with self._lock:
                if job_id in self._pending_job_ids:
                    self._pending_job_ids.remove(job_id)
                self._running_job_id = job_id
                try:
                    return await work()
                finally:
                    if self._running_job_id == job_id:
                        self._running_job_id = None
        finally:
            if job_id in self._pending_job_ids:
                self._pending_job_ids.remove(job_id)


_queue = EngineJobQueue()


def get_engine_job_queue() -> EngineJobQueue:
    return _queue


def reset_engine_job_queue_for_tests() -> None:
    global _queue
    _queue = EngineJobQueue()


def serialized_engine_job(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
    """Run an engine job entrypoint through the process-wide FIFO."""

    @functools.wraps(fn)
    async def wrapper(job_id: str, *args: Any, **kwargs: Any) -> T:
        async def work() -> T:
            return await fn(job_id, *args, **kwargs)

        return await get_engine_job_queue().run(job_id, work)

    return wrapper
