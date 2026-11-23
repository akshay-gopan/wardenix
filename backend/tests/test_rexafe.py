"""ReDoS-safe regex guard tests."""

from __future__ import annotations

import time

import pytest

from app.security.rexafe import MAX_PATTERN_LEN, UnsafeRegex, search, validate_pattern


def test_catastrophic_pattern_runs_in_linear_time():
    # A pattern that would cause catastrophic backtracking in `re`.
    pattern = "(a+)+$"
    text = "a" * 40 + "!"
    start = time.monotonic()
    result = search(pattern, text)
    elapsed = time.monotonic() - start
    assert result is False
    assert elapsed < 1.0  # re2 is linear; `re` would take exponential time here


def test_validate_rejects_overlong_pattern():
    with pytest.raises(UnsafeRegex):
        validate_pattern("a" * (MAX_PATTERN_LEN + 1))


def test_validate_rejects_invalid_pattern():
    with pytest.raises(UnsafeRegex):
        validate_pattern("(unclosed")


def test_search_matches():
    assert search(r"^del", "delete") is True
    assert search(r"^del", "create") is False


def test_search_caps_input_length():
    # Should not raise or hang on huge input.
    assert search(r"needle", "x" * 200_000 + "needle"[:0]) is False
