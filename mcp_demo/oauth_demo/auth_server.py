r"""
最小 OAuth 2.1 授权服务器（教学用）。

它实现：
  GET  /.well-known/oauth-authorization-server  元数据
  GET  /.well-known/jwks.json                  公钥
  GET  /authorize                              登录/授权页
  POST /authorize/approve                      用户同意后发 code
  POST /token                                  用 code + PKCE 换 access_token

启动：
  mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\auth_server.py

注意：这是教学实现，没有真实用户登录、刷新令牌、撤销、动态客户端注册。
"""
from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import AS_URL, CLIENT_ID, MCP_URL, REDIRECT_URI, SCOPE

KEY_DIR = Path(__file__).parent / "keys"
KID = "demo-key-1"
AUTH_CODES: dict[str, dict] = {}


def _load_or_create_keys():
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    private_path = KEY_DIR / "private.pem"
    public_path = KEY_DIR / "public.pem"
    if private_path.exists() and public_path.exists():
        private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
        public_key = serialization.load_pem_public_key(public_path.read_bytes())
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        private_path.write_bytes(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        public_path.write_bytes(public_key.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ))
    return private_key, public_key


PRIVATE_KEY, PUBLIC_KEY = _load_or_create_keys()

app = FastAPI(title="MCP OAuth Demo AS")


def _validate_authorize(data: dict[str, str]) -> str | None:
    if data.get("response_type") != "code":
        return "response_type 必须是 code"
    if data.get("client_id") != CLIENT_ID:
        return "未知的 client_id"
    if data.get("redirect_uri") != REDIRECT_URI:
        return "redirect_uri 不匹配"
    if data.get("code_challenge_method") != "S256":
        return "只支持 PKCE S256"
    challenge = data.get("code_challenge", "")
    if not 43 <= len(challenge) <= 128:
        return "code_challenge 长度不合法"
    return None


def _error_page(message: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(
        f"<h2>授权失败</h2><p>{html.escape(message)}</p>",
        status_code=status,
    )


def _oauth_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": "invalid_request", "error_description": message},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@app.get("/.well-known/oauth-authorization-server")
def metadata():
    return {
        "issuer": AS_URL,
        "authorization_endpoint": f"{AS_URL}/authorize",
        "token_endpoint": f"{AS_URL}/token",
        "jwks_uri": f"{AS_URL}/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [SCOPE],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@app.get("/.well-known/jwks.json")
def jwks():
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(PUBLIC_KEY, as_dict=True)
    jwk.update({"kid": KID, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


@app.get("/authorize", response_class=HTMLResponse)
def authorize(
    response_type: str = "code",
    client_id: str = "",
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    scope: str = SCOPE,
):
    data = {
        "response_type": response_type,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "scope": scope,
    }
    error = _validate_authorize(data)
    if error:
        return _error_page(error)

    hidden = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in data.items()
    )
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>授权确认</title>
<style>
body{{font-family:"Microsoft YaHei",sans-serif;background:#f5f6f9;display:flex;
justify-content:center;align-items:center;min-height:100vh;margin:0}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:28px 32px;
width:460px;box-shadow:0 10px 30px rgba(16,26,51,.08)}}
h2{{margin:0 0 8px;color:#1b2333}}
p{{color:#4b5563;font-size:14px;line-height:1.7}}
.code{{background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:10px;
font-family:Consolas,monospace;font-size:12px;word-break:break-all}}
button{{border:0;border-radius:9px;padding:10px 18px;font-size:14px;cursor:pointer;
font-family:inherit;margin-right:10px}}
.ok{{background:#2f6bff;color:#fff}}.no{{background:#eef0f4;color:#4b5563}}
</style></head><body>
<div class="card">
  <h2>授权 MCP 客户端</h2>
  <p><b>客户端</b>：{html.escape(client_id)}<br>
     <b>用户</b>：demo-user<br>
     <b>请求权限</b>：{html.escape(scope)}</p>
  <p class="code">redirect_uri: {html.escape(redirect_uri)}</p>
  <p>同意后，授权服务器会把一次性 code 发回客户端，客户端再用 code + PKCE 换 access_token。</p>
  <form method="post" action="/authorize/approve">
    {hidden}
    <button class="ok" name="decision" value="approve">同意授权</button>
    <button class="no" name="decision" value="deny">拒绝</button>
  </form>
</div></body></html>""")


@app.post("/authorize/approve")
async def approve(request: Request):
    form = await request.form()
    data = {k: str(v) for k, v in form.items() if k != "decision"}
    error = _validate_authorize(data)
    if error:
        return _error_page(error)

    redirect_uri = data["redirect_uri"]
    state = data.get("state", "")
    if form.get("decision") != "approve":
        params = {"error": "access_denied", "error_description": "用户拒绝授权"}
        if state:
            params["state"] = state
        return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

    code = secrets.token_urlsafe(32)
    AUTH_CODES[code] = {
        "client_id": data["client_id"],
        "redirect_uri": redirect_uri,
        "code_challenge": data["code_challenge"],
        "scope": data.get("scope", SCOPE),
        "expires_at": time.time() + 300,
    }
    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)


@app.post("/token")
async def token(request: Request):
    form = await request.form()
    if form.get("grant_type") != "authorization_code":
        return _oauth_error("只支持 authorization_code")
    if form.get("client_id") != CLIENT_ID:
        return _oauth_error("client_id 不匹配", 401)

    code = form.get("code", "")
    entry = AUTH_CODES.pop(code, None)  # code 一次性使用
    if not entry:
        return _oauth_error("code 无效或已使用")
    if entry["expires_at"] < time.time():
        return _oauth_error("code 已过期")
    if form.get("redirect_uri") != entry["redirect_uri"]:
        return _oauth_error("redirect_uri 不匹配")

    verifier = form.get("code_verifier", "")
    if not 43 <= len(verifier) <= 128:
        return _oauth_error("code_verifier 长度不合法")
    computed = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    if not secrets.compare_digest(computed, entry["code_challenge"]):
        return _oauth_error("PKCE 校验失败")

    now = int(time.time())
    payload = {
        "iss": AS_URL,
        "aud": MCP_URL,
        "sub": "demo-user",
        "client_id": CLIENT_ID,
        "scope": entry["scope"],
        "iat": now,
        "exp": now + 3600,
        "jti": secrets.token_urlsafe(16),
    }
    access_token = jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": KID})
    return JSONResponse(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": entry["scope"],
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@app.get("/health")
def health():
    return {"ok": True, "issuer": AS_URL}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="info")
