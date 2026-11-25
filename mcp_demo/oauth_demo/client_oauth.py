r"""
OAuth 客户端：完整走一遍 Authorization Code + PKCE。

两种模式：
  1. 默认：打开浏览器，在授权页点“同意”，回调服务器接收 code
  2. --headless：脚本直接模拟“用户同意”，用于自动测试

运行：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\client_oauth.py
  mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\client_oauth.py --headless
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from config import AS_URL, CLIENT_ID, MCP_URL, REDIRECT_URI, SCOPE

CALLBACK_PORT = 8766

_result: dict[str, str] = {}
_event = threading.Event()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        _result.update({k: v[0] for k, v in query.items()})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("<h2>授权完成，可以关闭此页面</h2>".encode("utf-8"))
        _event.set()

    def log_message(self, *args):
        pass


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def authorize_params(challenge: str, state: str) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": SCOPE,
    }


def get_code_via_browser(params: dict[str, str]) -> str:
    _result.clear()
    _event.clear()
    server = ThreadingHTTPServer(("127.0.0.1", CALLBACK_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"{AS_URL}/authorize?{urlencode(params)}"
    print(f"\n[1] 打开浏览器授权：{url}")
    webbrowser.open(url)
    print(f"[2] 等待回调 http://127.0.0.1:{CALLBACK_PORT}/callback ...")

    try:
        if not _event.wait(timeout=180):
            raise SystemExit("等待授权超时")
    finally:
        server.shutdown()
        server.server_close()

    if "error" in _result:
        raise SystemExit(f"授权失败：{_result.get('error')} {_result.get('error_description', '')}")
    if _result.get("state") != params["state"]:
        raise SystemExit("state 校验失败，可能是 CSRF")
    if "code" not in _result:
        raise SystemExit("回调里没有 code")
    return _result["code"]


def get_code_headless(params: dict[str, str]) -> str:
    """自动测试：跳过浏览器，直接 POST 授权确认。真实场景不要这样绕过用户同意。"""
    resp = httpx.post(
        f"{AS_URL}/authorize/approve",
        data={**params, "decision": "approve"},
        follow_redirects=False,
        timeout=30,
    )
    location = resp.headers.get("location")
    if not location:
        raise SystemExit(f"授权失败：HTTP {resp.status_code} {resp.text[:200]}")
    query = parse_qs(urlparse(location).query)
    if "error" in query:
        raise SystemExit(f"授权失败：{query['error'][0]}")
    if query.get("state", [""])[0] != params["state"]:
        raise SystemExit("state 校验失败")
    return query["code"][0]


def exchange_code(code: str, verifier: str) -> str:
    resp = httpx.post(
        f"{AS_URL}/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": CLIENT_ID,
            "code_verifier": verifier,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise SystemExit(f"换 token 失败：HTTP {resp.status_code} {resp.text[:300]}")
    return resp.json()["access_token"]


def result_text(result) -> str:
    parts = [getattr(c, "text", None) for c in result.content]
    parts = [p for p in parts if p]
    if parts:
        return "\n".join(parts)
    if result.structured_content:
        return json.dumps(result.structured_content, ensure_ascii=False)
    return "（无返回）"


async def call_mcp(token: str) -> None:
    print("\n[5] 用 access_token 连接 MCP server")
    async with create_mcp_http_client(headers={"Authorization": f"Bearer {token}"}) as http_client:
        async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                print("工具：", [t.name for t in tools])

                print("\n[6] 调用 current_user")
                result = await session.call_tool("current_user", {})
                print(result_text(result))

                print("\n[7] 调用 add(10, 20)")
                result = await session.call_tool("add", {"a": 10, "b": 20})
                print(result_text(result))


def check_services() -> None:
    try:
        httpx.get(f"{AS_URL}/health", timeout=3)
    except Exception:
        raise SystemExit(f"授权服务器未启动：{AS_URL}（先运行 auth_server.py）")
    try:
        httpx.get(f"{MCP_URL.rsplit('/mcp', 1)[0]}/.well-known/oauth-protected-resource/mcp", timeout=3)
    except Exception:
        raise SystemExit(f"MCP server 未启动：{MCP_URL}（先运行 mcp_server_oauth.py）")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true", help="自动模拟用户同意，仅用于测试")
    args = ap.parse_args()

    check_services()

    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    params = authorize_params(challenge, state)

    code = get_code_headless(params) if args.headless else get_code_via_browser(params)
    print(f"[3] 拿到 code：{code[:18]}...")

    token = exchange_code(code, verifier)
    print(f"[4] 拿到 access_token：{token[:28]}...")
    claims = jwt.decode(token, options={"verify_signature": False})
    print("    claims:", json.dumps(
        {k: claims[k] for k in ["iss", "aud", "sub", "client_id", "scope", "exp"]},
        ensure_ascii=False,
    ))

    asyncio.run(call_mcp(token))


if __name__ == "__main__":
    main()
