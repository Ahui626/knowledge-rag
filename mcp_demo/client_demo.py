r"""
MCP 客户端演示：不接大模型，先手动列出工具、调用工具、读资源。

运行：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\client_demo.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).parent / "server.py"


def text_of(result) -> str:
    parts = []
    for item in result.content:
        if getattr(item, "text", None):
            parts.append(item.text)
        else:
            parts.append(str(item))
    if not parts and result.structured_content:
        return json.dumps(result.structured_content, ensure_ascii=False)
    return "\n".join(parts)


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("已连接 MCP 服务器\n")

            tools = await session.list_tools()
            print(f"工具数量：{len(tools.tools)}")
            for tool in tools.tools:
                print(f"- {tool.name}: {tool.description}")
                print("  参数:", json.dumps(tool.input_schema, ensure_ascii=False))

            print("\n调用 add(2, 3)")
            result = await session.call_tool("add", {"a": 2, "b": 3})
            print("结果:", text_of(result), "| is_error:", result.is_error)

            print("\n调用 word_count")
            result = await session.call_tool(
                "word_count",
                {"text": "MCP 让模型可以调用外部工具。MCP is useful."},
            )
            print("结果:", text_of(result))

            print("\n调用 search_notes('transport')")
            result = await session.call_tool("search_notes", {"keyword": "transport"})
            print("结果:", text_of(result))

            print("\n读取资源 notes://all")
            resource = await session.read_resource("notes://all")
            for content in resource.contents:
                print(getattr(content, "text", content)[:200])

            print("\n获取 prompt summarize")
            prompt = await session.get_prompt(
                "summarize",
                {"text": "MCP 把工具提供方和调用方解耦，支持 stdio 与 HTTP 两种传输。"},
            )
            for msg in prompt.messages:
                print(f"[{msg.role}] {getattr(msg.content, 'text', msg.content)}")


if __name__ == "__main__":
    asyncio.run(main())
