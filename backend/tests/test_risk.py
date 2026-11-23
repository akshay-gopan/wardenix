"""Deterministic risk scorer tests."""

from __future__ import annotations

from app.enums import RiskBand
from app.risk.assessor import assess


def test_benign_call_is_low():
    r = assess(server_name="fs", tool_name="read_file", arguments={"path": "notes.txt"})
    assert r.band is RiskBand.LOW
    assert r.score == 0


def test_destructive_verb_in_tool_name_raises_band():
    r = assess(server_name="fs", tool_name="delete_file", arguments={"name": "x"})
    assert "destructive" in r.signals
    assert r.band in (RiskBand.HIGH, RiskBand.CRITICAL)


def test_secret_key_flagged():
    r = assess(server_name="api", tool_name="login", arguments={"password": "hunter2"})
    assert "secret_key" in r.signals


def test_path_signal():
    r = assess(server_name="fs", tool_name="read", arguments={"p": "/etc/passwd"})
    assert "path" in r.signals


def test_network_signal():
    r = assess(server_name="net", tool_name="fetch", arguments={"url": "https://evil.example"})
    assert "network" in r.signals


def test_scoring_is_deterministic_and_additive():
    args = {"url": "https://x", "password": "p", "target": "/root/secrets"}
    r1 = assess(server_name="s", tool_name="delete", arguments=args)
    r2 = assess(server_name="s", tool_name="delete", arguments=args)
    assert r1 == r2
    # destructive(3) + network(1) + secret(2) + path(2) = 8 -> critical
    assert r1.band is RiskBand.CRITICAL
