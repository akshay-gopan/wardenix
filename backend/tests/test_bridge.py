"""Bridge approval-retry logic (resolve_call) — unit-tested with fakes, no gateway."""

from __future__ import annotations

from types import SimpleNamespace

from bridge.stdio_bridge import resolve_call


def _result(status=None, text="ok"):
    sc = {"status": "approval_required", "approval_id": "abc"} if status == "pending" else None
    return SimpleNamespace(structured_content=sc, is_error=status == "pending", content=[text])


async def _noop_sleep(_):
    return None


async def test_allow_result_returns_immediately():
    calls = 0

    async def do_call():
        nonlocal calls
        calls += 1
        return _result(status=None)

    async def get_status(_):
        raise AssertionError("should not poll for a non-approval result")

    out = await resolve_call(do_call, get_status, interval=0, deadline=5, sleep=_noop_sleep)
    assert out.structured_content is None
    assert calls == 1


async def test_polls_until_approved_then_reissues():
    call_results = [_result(status="pending"), _result(status=None, text="done")]
    statuses = ["pending", "pending", "approved"]

    async def do_call():
        return call_results.pop(0)

    async def get_status(_):
        return statuses.pop(0)

    out = await resolve_call(do_call, get_status, interval=0, deadline=5, sleep=_noop_sleep)
    assert out.content == ["done"]
    assert call_results == []  # both calls were made


async def test_denied_surfaces_pending_result_without_reissue():
    pending = _result(status="pending")

    async def do_call():
        return pending

    async def get_status(_):
        return "denied"

    out = await resolve_call(do_call, get_status, interval=0, deadline=5, sleep=_noop_sleep)
    assert out is pending  # no re-issue after denial


async def test_timeout_surfaces_pending():
    pending = _result(status="pending")
    clock_values = iter([0, 0, 1, 2, 3, 99])

    async def do_call():
        return pending

    async def get_status(_):
        return "pending"

    out = await resolve_call(
        do_call,
        get_status,
        interval=0,
        deadline=5,
        sleep=_noop_sleep,
        clock=lambda: next(clock_values),
    )
    assert out is pending
