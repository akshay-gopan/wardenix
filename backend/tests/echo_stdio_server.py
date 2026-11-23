"""A minimal real stdio MCP server used by tests to exercise the gateway's
stdio upstream path (subprocess spawn + stdio transport), which the in-process
fake upstream does not cover. Run as: ``python tests/echo_stdio_server.py``.
"""

from __future__ import annotations

import anyio
import mcp.types as mt
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server


async def on_list_tools(ctx, params):
    return mt.ListToolsResult(
        tools=[
            mt.Tool(
                name="echo",
                description="echo text back over stdio",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                },
            )
        ]
    )


async def on_call_tool(ctx, params):
    args = params.arguments or {}
    return mt.CallToolResult(
        content=[mt.TextContent(type="text", text=f"stdio-echo: {args.get('text')}")]
    )


def main() -> None:
    server = Server(
        "echo-stdio",
        version="0.0.1",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )

    async def run() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
