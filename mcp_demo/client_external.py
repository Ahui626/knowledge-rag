r"""
通用 MCP 客户端：连接任意外部 MCP server（stdio 或 Streamable HTTP）。

示例：
  # 连接本地 Python server
  mcp_demo\.venv\Scripts\python.exe mcp_demo\client_external.py --server-file mcp_demo\server.py

  # 连接 GitHub 官方远程 server（需要 PAT）
  mcp_demo\.venv\Scripts\python.exe mcp_demo\client_external.py ^
      --url https://api.githubcopilot.com/mcp/ --token %GITHUB_TOKEN%

  # 连接 Docker 形式的 server
  mcp_demo\.venv\Scripts\python.exe mcp_demo\client_external.py ^
      --command docker --arg run --arg -i --arg --rm ^
      --arg -e --arg GITHUB_PERSONAL_ACCESS_TOKEN ^
      --arg ghcr.io/github/github-mcp-server ^
      --env GITHUB_PERSONAL_ACCESS_TOKEN=%GITHUB_TOKEN%

  # 连接并调用某个工具
  ... --call get_repo --arg-kv owner=octocat --arg-kv repo=Hello-World
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client


def result_text(result) -> str:
    parts = [getattr(c, "text", None) for c in result.content]
    parts = [p for p in parts if p]
    if parts:
        return "\n".join(parts)
    if result.structured_content:
        return json.dumps(result.structured_content, ensure_ascii=False)
    return "（无返回）"


async def run(args) -> None:
    if args.url:
        headers = {}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"
        connect_ctx = create_mcp_http_client(headers=headers)
    else:
        env = dict(os.environ)
        for pair in args.env:
            key, _, value = pair.partition("=")
            env[key] = value
        command = args.command or sys.executable
        cli_args = list(args.arg) if args.command else [str(Path(args.server_file).resolve())]
        params = StdioServerParameters(command=command, args=cli_args, env=env)
        connect_ctx = None

    if args.url:
        async with connect_ctx as http_client:
            async with streamable_http_client(args.url, http_client=http_client) as (read, write):
                await handle(read, write, args)
    else:
        async with stdio_client(params) as (read, write):
            await handle(read, write, args)


async def handle(read, write, args) -> None:
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = (await session.list_tools()).tools
        print(f"已连接，工具 {len(tools)} 个：")
        for t in tools:
            print(f"- {t.name}: {t.description}")
        if not args.call:
            return
        arguments = {}
        for pair in args.arg_kv:
            key, _, value = pair.partition("=")
            arguments[key] = value
        arguments.update(json.loads(args.args_json or "{}"))
        print(f"\n调用 {args.call}({json.dumps(arguments, ensure_ascii=False)})")
        result = await session.call_tool(args.call, arguments)
        print("is_error:", result.is_error)
        print(result_text(result))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-file", default="mcp_demo/server.py", help="本地 Python server 文件")
    ap.add_argument("--command", help="自定义启动命令，比如 docker")
    ap.add_argument("--arg", action="append", default=[], help="传给 --command 的参数，可重复")
    ap.add_argument("--env", action="append", default=[], help="环境变量 KEY=VALUE，可重复")
    ap.add_argument("--url", help="Streamable HTTP server URL")
    ap.add_argument("--token", help="HTTP Bearer token")
    ap.add_argument("--call", help="连接后调用的工具名")
    ap.add_argument("--arg-kv", action="append", default=[], help="工具参数 key=value，可重复")
    ap.add_argument("--args-json", default="{}", help="工具参数 JSON（复杂参数用这个）")
    args = ap.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
