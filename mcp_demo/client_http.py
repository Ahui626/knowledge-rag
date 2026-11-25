"""通过 HTTP 连接 MCP server，验证远程传输。

先启动 server_http.py，再运行本文件。
"""
from __future__ import annotations

import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = "http://127.0.0.1:8765/mcp"


async def main() -> None:
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("HTTP 连接成功，工具：")
            for t in tools.tools:
                print("-", t.name, t.description)

            result = await session.call_tool("add", {"a": 10, "b": 20})
            print("add(10,20) ->", "\n".join(
                getattr(c, "text", str(c)) for c in result.content
            ))


if __name__ == "__main__":
    asyncio.run(main())
