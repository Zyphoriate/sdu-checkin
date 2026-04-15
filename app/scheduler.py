from __future__ import annotations

import asyncio
import logging

from .service import CheckInService


LOGGER = logging.getLogger(__name__)


class SchedulerLoop:
    def __init__(self, service: CheckInService, interval_seconds: int) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="checkin-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self._service.run_due_users)
            except Exception:
                LOGGER.exception("scheduler loop failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
            except asyncio.TimeoutError:
                continue
