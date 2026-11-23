"""In-process WebSocket hub for live Control Plane events.

Best-effort fan-out: each connection gets a bounded queue; a slow/overflowing
consumer drops events rather than blocking the Data Plane. The DB is always the
source of truth, so the dashboard reconciles via REST on (re)connect.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("wardenix.ws")


class WSHub:
    def __init__(self, max_queue: int = 200) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._max_queue = max_queue

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        """Non-blocking fan-out. Called from Data Plane / Control Plane code."""
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("ws subscriber queue full; dropping event")

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
