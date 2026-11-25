r"""
受 OAuth 保护的 MCP server（资源服务器）。

它只负责：
  1. 暴露 MCP 工具
  2. 校验 Authorization: Bearer <JWT>
  3. 校验 iss / aud / exp / scope

启动：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\mcp_server_oauth.py
"""
from __future__ import annotations

from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from config import AS_URL, MCP_URL, SCOPE

PUBLIC_KEY_PATH = Path(__file__).parent / "keys" / "public.pem"
if not PUBLIC_KEY_PATH.exists():
    raise SystemExit("找不到公钥，请先启动一次 auth_server.py 生成 keys/")
PUBLIC_KEY = serialization.load_pem_public_key(PUBLIC_KEY_PATH.read_bytes())


class JWTVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = jwt.decode(
                token,
                PUBLIC_KEY,
                algorithms=["RS256"],
                audience=MCP_URL,
                issuer=AS_URL,
            )
        except jwt.PyJWTError:
            return None

        scopes = str(payload.get("scope", "")).split()
        if SCOPE not in scopes:
            return None
        return AccessToken(
            token=token,
            client_id=str(payload.get("client_id", "")),
            scopes=scopes,
            expires_at=payload.get("exp"),
            resource=payload.get("aud"),
            subject=payload.get("sub"),
            claims=payload,
        )


mcp = MCPServer(
    "oauth-demo-server",
    instructions="这是一个受 OAuth 保护的 MCP 服务器，只返回当前用户可见的数据。",
    token_verifier=JWTVerifier(),
    auth=AuthSettings(
        issuer_url=AS_URL,
        resource_server_url=MCP_URL,
        required_scopes=[SCOPE],
        validate_token_resource=True,
    ),
)


@mcp.tool()
def add(a: int, b: int) -> int:
    """计算两个整数之和。"""
    return a + b


@mcp.tool()
def current_user() -> dict:
    """返回当前 access token 的主体、客户端和 scope。"""
    token = get_access_token()
    if token is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "subject": token.subject,
        "client_id": token.client_id,
        "scopes": token.scopes,
        "expires_at": token.expires_at,
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
