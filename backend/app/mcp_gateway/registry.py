"""Tool-name namespacing.

Agents see upstream tools as ``<server>.<tool>`` so names never collide across
servers. The server name (operator-controlled) must not contain the separator;
the tool name may. Split on the *first* separator so dotted tool names survive.
"""

from __future__ import annotations

NAMESPACE_SEP = "."


class InvalidNamespacedName(ValueError):
    pass


def make_namespaced(server_name: str, tool_name: str) -> str:
    if NAMESPACE_SEP in server_name:
        raise InvalidNamespacedName(
            f"server name {server_name!r} must not contain {NAMESPACE_SEP!r}"
        )
    return f"{server_name}{NAMESPACE_SEP}{tool_name}"


def split_namespaced(name: str) -> tuple[str, str]:
    server_name, sep, tool_name = name.partition(NAMESPACE_SEP)
    if not sep or not server_name or not tool_name:
        raise InvalidNamespacedName(
            f"expected '<server>{NAMESPACE_SEP}<tool>', got {name!r}"
        )
    return server_name, tool_name
