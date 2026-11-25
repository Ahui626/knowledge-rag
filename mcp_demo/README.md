# MCP 教学 Demo

一个不依赖原 RAG 项目的独立示例，用来理解 MCP 怎么工作、怎么自己写 server、怎么让大模型自动调用工具。

## 1. MCP 是什么

MCP（Model Context Protocol）是一个**协议**，不是一个库。它解决的是：

> 大模型应用怎么用统一的方式发现和调用外部工具、读取外部数据。

三个角色：

```
Host（Claude Desktop / Cursor / 我们的 agent.py）
  └─ MCP Client ──stdio 或 HTTP── MCP Server
                                   ├─ Tools     可调用的函数
                                   ├─ Resources 可读取的数据
                                   └─ Prompts   可复用的提示词模板
```

- **Host**：最终用户用的应用，负责把工具交给 LLM。
- **Client**：协议客户端，负责连接 server、列出工具、发起调用。
- **Server**：工具提供方，可以用 Python、Node、Go 任意语言写。

三种能力：

| 能力 | 作用 | 例子 |
|---|---|---|
| Tools | 模型可以主动调用 | 查数据库、发请求、算数 |
| Resources | 模型可以读取的数据 | 文件、配置、笔记 |
| Prompts | 可复用的提示词模板 | 总结、翻译、代码审查 |

两种常用传输：

- **stdio**：Host 启动一个子进程，通过标准输入输出通信，适合本地工具。
- **Streamable HTTP**：server 跑在远端，多个客户端可连接，适合服务化。

## 2. 目录

```
mcp_demo/
  server.py        MCP server：4 个工具、2 个资源、1 个 prompt
  client_demo.py   不用 LLM，手动列出/调用工具
  agent.py         LLM + MCP：DeepSeek 自动选择工具
  server_http.py   HTTP 传输的 server
  client_http.py   HTTP 传输的 client
  requirements.txt
```

## 3. 环境

已经创建好 `mcp_demo/.venv`。如果要重建：

```powershell
uv venv --python 3.12 mcp_demo\.venv
uv pip install --python mcp_demo\.venv\Scripts\python.exe -r mcp_demo\requirements.txt
```

安装的是官方 Python SDK `mcp`（当前 2.3.0）。注意：网上很多教程基于 1.x 的 `FastMCP`，2.x 已改名为 `MCPServer`：

```python
# 2.x（本 demo）
from mcp.server.mcpserver import MCPServer

# 1.x（旧教程）
from mcp.server.fastmcp import FastMCP
```

## 4. 快速开始

### 4.1 先不用 LLM：手动调用工具

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_demo.py
```

它会：

1. 用 stdio 启动 `server.py`；
2. `initialize()` 握手；
3. `list_tools()` 拿到 4 个工具及参数 schema；
4. `call_tool("add", {"a": 2, "b": 3})`；
5. `read_resource("notes://all")`；
6. `get_prompt("summarize", ...)`。

这一步是理解 MCP 的关键：**工具发现和调用都是协议消息，不需要 LLM 参与**。

### 4.2 让 LLM 自动选工具

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py
```

或者自定义问题：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py "帮我算 12*34，再查一下 MCP 笔记"
```

流程：

```
启动 MCP server
  → list_tools()
  → 把 MCP 工具 schema 转成 OpenAI tools
  → 问题交给 DeepSeek
  → DeepSeek 返回 tool_calls
  → 通过 MCP call_tool 执行
  → 结果作为 role=tool 消息送回
  → DeepSeek 生成最终回答
```

`agent.py` 用的是项目根目录 `.env` 里的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`，代码里没有硬编码 key。

### 4.3 HTTP 传输

终端 1：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\server_http.py
```

终端 2：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_http.py
```

server 默认监听 `http://127.0.0.1:8765/mcp`。

### 4.4 用官方 Inspector 调试

需要 Node.js（本机已有 Node 24）：

```powershell
mcp_demo\.venv\Scripts\mcp.exe dev mcp_demo\server.py
```

它会启动 MCP Inspector，在浏览器里可视化查看 tools/resources/prompts，并手动调用。

## 5. 代码怎么读

### 5.1 定义工具

`server.py`：

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("demo-server")

@mcp.tool()
def add(a: int, b: int) -> int:
    """计算两个整数之和。"""
    return a + b
```

- `@mcp.tool()` 把函数注册成工具；
- 参数类型注解生成 JSON Schema；
- docstring 变成工具描述，LLM 靠它判断什么时候调用；
- 返回 `dict` / `list` 会同时生成 `structured_content`。

### 5.2 定义资源和提示词

```python
@mcp.resource("notes://all")
def all_notes() -> str:
    ...

@mcp.prompt()
def summarize(text: str) -> str:
    return f"请用三点总结：\n{text}"
```

资源用 URI 标识，支持模板，比如 `notes://{note_id}`。

### 5.3 客户端连接

`client_demo.py`：

```python
params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("add", {"a": 2, "b": 3})
```

### 5.4 LLM 自动调用

`agent.py` 的核心是三步：

1. **MCP 工具转 OpenAI tools**

```python
{
  "type": "function",
  "function": {
    "name": tool.name,
    "description": tool.description,
    "parameters": tool.input_schema,
  },
}
```

2. **把模型返回的 tool_calls 逐个执行**

```python
result = await session.call_tool(name, args)
```

3. **把结果作为 tool 消息送回模型**

```python
messages.append({
    "role": "tool",
    "tool_call_id": tc.id,
    "content": text,
})
```

循环到模型不再调用工具为止。

## 6. 接到 Claude Desktop / Cursor

MCP server 写好后，Host 只需要一段配置。Windows 路径里的反斜杠要转义：

```json
{
  "mcpServers": {
    "demo": {
      "command": "D:\\Code\\database_demo\\mcp_demo\\.venv\\Scripts\\python.exe",
      "args": ["D:\\Code\\database_demo\\mcp_demo\\server.py"]
    }
  }
}
```

- Claude Desktop：`%APPDATA%\Claude\claude_desktop_config.json`
- Cursor：项目下 `.cursor/mcp.json`（或全局配置，取决于版本）

改完重启 Host，它会自动启动 server 并发现工具。

## 7. 常见坑

1. **server 里不能用 `print()`**
   stdio 传输下，stdout 是协议通道。日志必须写 `sys.stderr` 或用 `logging` 到 stderr，否则协议会被污染。

2. **工具描述决定 LLM 是否调用**
   docstring 要写清楚“什么时候用、参数是什么”。只写函数名，模型很难判断。

3. **参数 schema 来自类型注解**
   用 `str`、`int`、`dict`、`list[dict]`，不要用复杂自定义类，否则 schema 可能生成失败。

4. **大结果要截断**
   工具返回几千行文本会挤爆上下文，最好在工具里截断或分页。

5. **HTTP 模式没有内置鉴权**
   本 demo 只监听 `127.0.0.1`。如果要对外提供服务，必须加认证、限流和 TLS，不要直接绑 `0.0.0.0`。

6. **工具有权限**
   `read_file`、`execute_command` 这类工具等于把系统权限交给模型。要做路径白名单、命令白名单、超时和审计。

7. **stdio 是“一客户端一进程”**
   每次 Host 连接都会启动一个新的 server 进程，不要在 server 里做重量级全局初始化。

8. **版本差异**
   2.x 的 `MCPServer` 和 1.x 的 `FastMCP` API 不同；跟旧教程混用会报 `ModuleNotFoundError`。

## 8. 练习

1. 给 `server.py` 增加 `multiply(a, b)`，然后用 `agent.py` 问“12 乘 34 等于多少”，确认模型会调用新工具。
2. 增加 `read_text_file(path)`，但只允许读 `mcp_demo/data/` 下的文件，练习路径白名单。
3. 用 `mcp dev` 打开 Inspector，手动调用 `search_notes`，观察请求和响应。
4. 把 `server_http.py` 加一个简单的 Bearer token 校验，理解远程 MCP 的鉴权。
5. 接一个官方 server（filesystem / sqlite），对比“自己写”和“复用现成”的差别。

## 9. 接入外部工具（以 GitHub 为例）

先分清两层，很多困惑来自把这两层混在一起：

| 你在做什么 | 要不要写 `@mcp.tool()` | 做法 |
|---|---|---|
| 用别人写好的 MCP server（GitHub 官方） | **不需要** | 客户端配置 command/URL，自动发现工具 |
| 自己写 server 包装外部 API | 需要 | `@mcp.tool()` + `httpx` 调外部接口 |

### 11.1 用 GitHub 官方 MCP server（推荐）

GitHub 官方 server：`github/github-mcp-server`。  
注意：npm 包 `@modelcontextprotocol/server-github` 在 2025 年 4 月后已不再维护，不要再用。

**远程模式（最简单）**

```powershell
$env:GITHUB_PERSONAL_ACCESS_TOKEN="github_pat_xxx"
mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py ^
  --url https://api.githubcopilot.com/mcp/ ^
  --token $env:GITHUB_PERSONAL_ACCESS_TOKEN ^
  "列出我最近的 issue"
```

`agent.py` 会通过 Streamable HTTP 连接，自动拿到 GitHub 的工具列表，再让 DeepSeek 选择工具。

**本地 Docker 模式**

```powershell
docker pull ghcr.io/github/github-mcp-server
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_external.py ^
  --command docker ^
  --arg run --arg -i --arg --rm ^
  --arg -e --arg GITHUB_PERSONAL_ACCESS_TOKEN ^
  --arg ghcr.io/github/github-mcp-server ^
  --env GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_xxx
```

Claude Desktop / Cursor 的配置形状：

```json
{
  "mcpServers": {
    "github": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
        "ghcr.io/github/github-mcp-server"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "github_pat_xxx"
      }
    }
  }
}
```

远程配置则是 `serverUrl` + `headers.Authorization`。

**PAT 权限**：只勾选需要的最小权限，比如只读仓库、issue、PR；不要给 admin。

### 11.2 自己包装 GitHub API

看 [github_server.py](github_server.py)。它用 `@mcp.tool()` 把三个 GitHub REST 接口暴露成工具：

- `get_repo(owner, repo)`
- `list_issues(owner, repo, state, limit)`
- `search_repositories(query, limit)`

不用 PAT 也能查公开仓库（GitHub 未认证限额约 60 次/小时）；设置 `GITHUB_TOKEN` 或 `GITHUB_PERSONAL_ACCESS_TOKEN` 可提高限额并访问私有仓库。

不接 LLM，直接看工具和调用：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_external.py ^
  --server-file mcp_demo\github_server.py ^
  --call get_repo --arg-kv owner=octocat --arg-kv repo=Hello-World
```

让 LLM 自动调用：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py ^
  --server-file mcp_demo\github_server.py ^
  "查一下 octocat/Hello-World 的 star 数和开放 issue 数量"
```

### 11.3 两种方式的取舍

| | 官方 GitHub server | 自己包装 |
|---|---|---|
| 工具数量 | 多，覆盖 repo/issue/PR/Actions/安全 | 只暴露你需要的几个 |
| 维护 | GitHub 维护 | 自己维护 |
| 权限控制 | 用 PAT + toolset 过滤 | 代码里控制 |
| 响应形状 | 官方定义 | 你可以裁剪、截断 |
| 适合 | 通用 GitHub 操作 | 固定业务、只读、需要定制 |

### 11.4 通用外部客户端

`client_external.py` 可以连接任意 MCP server：

```powershell
# stdio：本地 Python server
--server-file mcp_demo\server.py

# stdio：任意命令，比如 docker
--command docker --arg run --arg -i --arg --rm --arg image --env KEY=VALUE

# Streamable HTTP
--url https://example.com/mcp --token xxx
```

列出工具，或加 `--call` / `--arg-kv` 调用某个工具。

### 11.5 接入时的注意事项

1. **密钥不要写进代码**，用环境变量或 `.env`；
2. **只给最小 scope**，GitHub PAT 尤其不要给 admin；
3. **限制输出大小**，issue/代码搜索结果可能非常长，工具里要截断；
4. **处理分页和限流**，GitHub API 有 rate limit，失败要能区分 403/429；
5. **外部内容不可信**，防止 prompt injection；
6. **OpenAPI 自动生成慎用**：MCP SDK 2.x 没有内置 `from_openapi`，GitHub OpenAPI 又很大，生成几百个工具会挤爆上下文；优先用官方 server 或只包装需要的接口。

## 10. OAuth 进阶

基础 demo 的 HTTP server 没有鉴权。要学习 OAuth（授权码 + PKCE、JWT 校验、401 发现、网关取舍），看：

- [oauth_demo/README.md](oauth_demo/README.md)

```powershell
# 终端 1
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\auth_server.py
# 终端 2
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\mcp_server_oauth.py
# 终端 3
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\client_oauth.py --headless
```

## 11. 命令速查

```powershell
# 手动客户端
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_demo.py

# LLM 自动调用
mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py

# 连接外部 server
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_external.py --server-file mcp_demo\github_server.py
mcp_demo\.venv\Scripts\python.exe mcp_demo\agent.py --server-file mcp_demo\github_server.py "查 octocat/Hello-World"

# HTTP
mcp_demo\.venv\Scripts\python.exe mcp_demo\server_http.py
mcp_demo\.venv\Scripts\python.exe mcp_demo\client_http.py

# Inspector
mcp_demo\.venv\Scripts\mcp.exe dev mcp_demo\server.py
```

## 12. 官方 MCPServer 与 FastMCP 的区别

先确认版本，网上最容易混的是两个 `FastMCP`：

| 写法 | 是什么 | 状态 |
|---|---|---|
| `from fastmcp import FastMCP` | 独立的 FastMCP 框架（当前 4.x） | 可用，功能更多 |
| `from mcp.server.fastmcp import FastMCP` | 官方 SDK 1.x 的旧入口 | 2.x 已改名为 `MCPServer` |
| `from mcp.server.mcpserver import MCPServer` | 官方 SDK 2.x | 本项目使用 |

两者说的都是同一种 MCP 协议，客户端（Claude、Cursor、`client_external.py`）看不出区别，区别在**开发体验和运行方式**。

### 12.1 运行方式对比

| | 官方 `MCPServer` | 独立 `FastMCP` |
|---|---|---|
| 默认 `run()` | stdio | stdio |
| HTTP 传输参数 | `transport="streamable-http"` | `transport="http"` |
| HTTP 端点 | 默认 `/mcp` | 默认 `/mcp` |
| CLI 启动 | `mcp run server.py` | `fastmcp run server.py` |
| CLI 指定传输 | `--transport streamable-http` | `--transport http` |
| Inspector | `mcp dev server.py` | `fastmcp dev server.py` |
| 自动重载 | 无 | `fastmcp run server.py --reload` |
| ASGI 应用 | `mcp.streamable_http_app()` | `mcp.http_app()` |
| 自定义路由 | 自己挂 Starlette/FastAPI | `@mcp.custom_route` |

### 12.2 代码对比

官方 SDK 2.x：

```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("ecommerce_tools")

@mcp.tool()
def get_order(order_id: str) -> dict:
    """查询订单。"""
    ...

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
```

独立 FastMCP：

```python
from fastmcp import FastMCP

mcp = FastMCP("ecommerce_tools")

@mcp.tool
def get_order(order_id: str) -> dict:
    """查询订单。"""
    ...

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)
```

主要差别：

- 装饰器：官方支持 `@mcp.tool()`，FastMCP 也支持 `@mcp.tool` 和 `@mcp.tool()`；
- HTTP 关键字：官方是 `streamable-http`，FastMCP 是 `http`；
- FastMCP 多出 OpenAPI/FastAPI 转换、认证 Provider、中间件、代理/挂载、CLI 依赖管理等功能；
- 官方 SDK 更轻，适合想贴近协议、自己控制 OAuth/资源服务器的场景。

### 12.3 什么时候用哪个

- 学习 MCP 协议、只需要 tools/resources/prompts：官方 `MCPServer` 够了；
- 要把现有 FastAPI/OpenAPI 快速变成 MCP server：FastMCP 更省事；
- 要接 Google/GitHub/Azure 登录、中间件、代理多个 server：FastMCP 的现成能力更多；
- 要自己实现 OAuth 资源服务器（像 `oauth_demo`）：官方 `MCPServer` + `TokenVerifier` 更直接。

> 注意：`fastmcp` 4.x 依赖 `mcp>=2.3`，和本项目 SDK 兼容；但两者不要混用同一个 server 对象。
