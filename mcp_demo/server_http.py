r"""同一个 MCP server，改用 Streamable HTTP 传输。

启动：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\server_http.py
"""
from server import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
