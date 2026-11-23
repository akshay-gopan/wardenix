"""WSHub fan-out unit tests."""

from __future__ import annotations

import asyncio

from app.api.ws import WSHub


async def test_publish_fans_out_to_subscribers():
    hub = WSHub()
    q1 = hub.subscribe()
    q2 = hub.subscribe()
    hub.publish({"type": "approval.pending", "x": 1})
    assert (await q1.get())["x"] == 1
    assert (await q2.get())["x"] == 1


async def test_unsubscribe_stops_delivery():
    hub = WSHub()
    q = hub.subscribe()
    hub.unsubscribe(q)
    hub.publish({"type": "x"})
    assert q.empty()


async def test_full_queue_drops_without_blocking():
    hub = WSHub(max_queue=1)
    q = hub.subscribe()
    hub.publish({"n": 1})
    hub.publish({"n": 2})  # dropped, must not raise/block
    assert (await asyncio.wait_for(q.get(), 1))["n"] == 1
    assert q.empty()
