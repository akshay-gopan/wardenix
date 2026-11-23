"""Gateway error taxonomy (see plan §8). Each maps to a safe, structured
message surfaced to the agent and an audited outcome — no internal detail leaks.
"""

from __future__ import annotations


class GatewayError(Exception):
    """Base class. ``public_message`` is what the agent is allowed to see."""

    code: str = "internal_error"

    def __init__(self, public_message: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message


class UnauthenticatedAgent(GatewayError):
    code = "unauthenticated"


class UnknownTool(GatewayError):
    code = "unknown_tool"


class PolicyDenied(GatewayError):
    code = "policy_denied"


class ArgsTooLarge(GatewayError):
    code = "args_too_large"


class UpstreamTimeout(GatewayError):
    code = "upstream_timeout"


class UpstreamError(GatewayError):
    code = "upstream_error"


class UpstreamUnavailable(GatewayError):
    code = "upstream_unavailable"
