r"""
自定义 GitHub MCP server：把 GitHub REST API 包装成 MCP 工具。

这是一种“外部工具接入”方式：MCP 只负责暴露工具，真正调用的是 GitHub API。

启动（stdio）：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\github_server.py

可选环境变量：
  GITHUB_TOKEN 或 GITHUB_PERSONAL_ACCESS_TOKEN，用于提高限额和访问私有仓库。
"""
from __future__ import annotations

import logging
import os

import httpx
from mcp.server.mcpserver import MCPServer

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
BASE = "https://api.github.com"

mcp = MCPServer(
    "github-demo-server",
    instructions="只读的 GitHub 示例工具：查仓库、列 issue、搜仓库。",
)


def _client() -> httpx.Client:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "mcp-demo/1.0",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return httpx.Client(base_url=BASE, headers=headers, timeout=30, follow_redirects=True)


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        # 不要把 token 带进错误信息
        raise RuntimeError(f"GitHub API {resp.status_code}: {resp.text[:200]}")


@mcp.tool()
def get_repo(owner: str, repo: str) -> dict:
    """查询一个 GitHub 仓库的基本信息和 star 数。"""
    with _client() as client:
        resp = client.get(f"/repos/{owner}/{repo}")
        _raise_for(resp)
        data = resp.json()
    return {
        "full_name": data["full_name"],
        "description": data.get("description"),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "open_issues": data.get("open_issues_count"),
        "language": data.get("language"),
        "default_branch": data.get("default_branch"),
        "url": data.get("html_url"),
    }


@mcp.tool()
def list_issues(owner: str, repo: str, state: str = "open", limit: int = 5) -> list[dict]:
    """列出仓库的 issue（会过滤掉 pull request），state 可选 open/closed/all。"""
    limit = max(1, min(limit, 20))
    with _client() as client:
        resp = client.get(
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": limit},
        )
        _raise_for(resp)
        items = resp.json()
    return [
        {
            "number": x["number"],
            "title": x["title"],
            "state": x["state"],
            "url": x["html_url"],
            "comments": x.get("comments"),
        }
        for x in items
        if "pull_request" not in x
    ][:limit]


@mcp.tool()
def search_repositories(query: str, limit: int = 5) -> list[dict]:
    """按关键词搜索 GitHub 仓库，返回仓库名、描述和 star 数。"""
    limit = max(1, min(limit, 10))
    with _client() as client:
        resp = client.get(
            "/search/repositories",
            params={"q": query, "per_page": limit, "sort": "stars", "order": "desc"},
        )
        _raise_for(resp)
        items = resp.json().get("items", [])
    return [
        {
            "full_name": x["full_name"],
            "description": x.get("description"),
            "stars": x.get("stargazers_count"),
            "url": x.get("html_url"),
        }
        for x in items
    ]


if __name__ == "__main__":
    mcp.run()
