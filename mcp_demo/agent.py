r"""
LLM + MCP：让 DeepSeek 通过 tool calling 自动选择 MCP 工具。

运行：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py
  mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py "帮我算 12*34，再查一下 MCP 笔记"

  # 连接自定义 GitHub 包装 server
  mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py ^
      --server-file mcp_demo\github_server.py "查一下 octocat/Hello-World 的 star 数"

  # 连接 GitHub 官方远程 MCP server（需要 PAT）
  mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py ^
      --url https://api.githubcopilot.com/mcp/ --token %GITHUB_TOKEN% "列出我最近的 issue"

流程：
  1. 启动 MCP server（stdio 子进程）
  2. 从 MCP 拿到工具列表，转成 OpenAI tools schema
  3. 把问题交给 LLM；LLM 返回 tool_calls
  4. 通过 MCP 执行工具，把结果作为 role=tool 消息送回 LLM
  5. 循环直到 LLM 给出最终回答
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("LLM_API_KEY", "").strip()
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1").strip()
MODEL = os.getenv("LLM_MODEL", "deepseek-chat").strip()

SERVER = Path(__file__).parent / "server.py"
SYSTEM = """你是 MCP 工具使用演示助手。
需要实时数据、外部系统信息或执行操作时，必须先调用可用工具，再根据工具返回结果回答。
不要自己编造工具结果。回答用中文，简洁。"""


def to_openai_tool(tool) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema or {"type": "object", "properties": {}},
        },
    }


def result_text(result) -> str:
    parts = []
    for item in result.content:
        if getattr(item, "text", None):
            parts.append(item.text)
    if parts:
        return "\n".join(parts)
    if result.structured_content:
        return json.dumps(result.structured_content, ensure_ascii=False)
    return "（工具没有返回文本）"


@asynccontextmanager
async def connect(server_file: Path, url: str | None, token: str | None):
    """统一连接本地 stdio server 或远程 Streamable HTTP server。"""
    if url:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with create_mcp_http_client(headers=headers) as http_client:
            async with streamable_http_client(url, http_client=http_client) as streams:
                yield streams
    else:
        params = StdioServerParameters(command=sys.executable, args=[str(server_file)])
        async with stdio_client(params) as streams:
            yield streams


async def run(question: str, server_file: Path, url: str | None, token: str | None) -> None:
    if not API_KEY:
        raise SystemExit("没有找到 LLM_API_KEY，请检查项目根目录 .env")

    async with connect(server_file, url, token) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"MCP server: {init.server_info.name} {init.server_info.version}")

            tools = (await session.list_tools()).tools
            openai_tools = [to_openai_tool(t) for t in tools]
            print(f"暴露给 LLM 的工具: {[t['function']['name'] for t in openai_tools]}\n")

            client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=90)
            messages: list[dict] = [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": question},
            ]

            for step in range(6):
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                    temperature=0.1,
                )
                msg = resp.choices[0].message
                if not msg.tool_calls:
                    print("最终回答：")
                    print(msg.content or "（空）")
                    return

                print(f"--- 第 {step + 1} 轮：LLM 决定调用工具 ---")
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                })
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    print(f"→ {name}({json.dumps(args, ensure_ascii=False)})")
                    result = await session.call_tool(name, args)
                    text = result_text(result)
                    print(f"← {text[:300]}")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": text,
                    })

            print("达到最大轮次，停止。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--server-file", default=str(SERVER), help="本地 stdio server 文件")
    ap.add_argument("--url", default=None, help="远程 Streamable HTTP server URL")
    ap.add_argument("--token", default=None, help="HTTP Bearer token")
    args = ap.parse_args()

    q = " ".join(args.question).strip() or (
        "请计算 12345 + 67890，告诉我现在几点，"
        "并查一下笔记里关于 MCP 的内容。"
    )
    asyncio.run(run(q, Path(args.server_file), args.url, args.token))
