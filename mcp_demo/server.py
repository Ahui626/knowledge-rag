r"""
MCP 演示服务器（stdio）。

启动方式：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\server.py

这个服务器提供：
  - 4 个 tools：add / current_time / word_count / search_notes
  - 2 个 resources：notes://all、notes://{note_id}
  - 1 个 prompt：summarize
"""
from __future__ import annotations

from datetime import datetime

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    "demo-server",
    instructions="这是一个教学用的 MCP 服务器，提供计算、时间、文本统计和笔记检索工具。",
)

NOTES = [
    {
        "id": "mcp",
        "title": "MCP 是什么",
        "content": "MCP（Model Context Protocol）是一个让大模型应用连接外部工具和数据的开放协议。"
                   "它把工具提供方（server）和调用方（host/client）解耦，工具可以用任意语言实现。",
    },
    {
        "id": "transport",
        "title": "MCP 的传输方式",
        "content": "stdio 适合本地进程，Streamable HTTP 适合远程服务；SSE 是较早的远程方案。",
    },
    {
        "id": "concept",
        "title": "MCP 的三个核心概念",
        "content": "Tools 是可调用的函数，Resources 是可读取的数据，Prompts 是可复用的提示词模板。",
    },
]


@mcp.tool()
def add(a: int, b: int) -> int:
    """计算两个整数之和。"""
    return a + b


@mcp.tool()
def current_time() -> str:
    """返回当前的本地时间，ISO 8601 格式。"""
    return datetime.now().isoformat(timespec="seconds")


@mcp.tool()
def word_count(text: str) -> dict:
    """统计一段文本的字符数、非空白字符数和英文单词数。"""
    words = [w for w in text.replace("\n", " ").split(" ") if w.strip()]
    return {
        "characters": len(text),
        "non_space_characters": len("".join(text.split())),
        "words": len(words),
    }


@mcp.tool()
def search_notes(keyword: str) -> list[dict]:
    """在演示笔记中按关键词检索，返回匹配的标题和内容。关键词为空时返回全部。"""
    keyword = keyword.strip().lower()
    if not keyword:
        return NOTES
    return [
        n for n in NOTES
        if keyword in n["id"].lower()
        or keyword in n["title"].lower()
        or keyword in n["content"].lower()
    ]


@mcp.resource("notes://all")
def all_notes() -> str:
    """返回全部笔记的纯文本。"""
    return "\n\n".join(f"# {n['title']}\n{n['content']}" for n in NOTES)


@mcp.resource("notes://{note_id}")
def note_by_id(note_id: str) -> str:
    """按 id 返回单条笔记。"""
    for n in NOTES:
        if n["id"] == note_id:
            return f"# {n['title']}\n{n['content']}"
    return f"没有找到 id 为 {note_id} 的笔记"


@mcp.prompt()
def summarize(text: str) -> str:
    """生成一个“三点总结”的提示词。"""
    return f"请用三点总结下面的内容，每点不超过 30 字：\n\n{text}"


if __name__ == "__main__":
    mcp.run()  # 默认 stdio
