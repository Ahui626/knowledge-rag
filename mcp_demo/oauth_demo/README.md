# MCP + OAuth 教学 Demo

这个目录是一个独立的 OAuth 示例，用来回答三个问题：

1. OAuth 到底是什么、一次授权发生了什么；
2. MCP server 怎么保护自己，怎么校验 access token；
3. 有没有必要在 MCP 前面再加一个网关。

它不是生产实现，而是一个**可以完整跑通、每一层都能看懂**的最小版本。

## 1. 先看整体结构

```
用户浏览器                OAuth 客户端                 授权服务器 AS             MCP 资源服务器
   |                     (client_oauth.py)            (auth_server.py)        (mcp_server_oauth.py)
   |  1. 打开 /authorize  |                              |                       |
   |-------------------->|                              |                       |
   |  2. 登录 + 同意       |                              |                       |
   |----------------------|----------------------------->|                       |
   |                      |  3. 302 回调 ?code=...       |                       |
   |<---------------------|                              |                       |
   |                      |  4. POST /token              |                       |
   |                      |  code + code_verifier        |                       |
   |                      |----------------------------->|                       |
   |                      |  5. access_token (JWT)       |                       |
   |                      |<-----------------------------|                       |
   |                      |  6. POST /mcp                 |                       |
   |                      |  Authorization: Bearer ...   |                       |
   |                      |----------------------------------------------------->|
   |                      |                              |  7. 校验签名/iss/aud/exp/scope
   |                      |<-----------------------------------------------------|
```

四个角色：

| 角色 | 在本 demo 里 | 作用 |
|---|---|---|
| Resource Owner | demo-user | 同意授权的用户 |
| Client | `client_oauth.py` | 发起授权、拿 token、调 MCP |
| Authorization Server | `auth_server.py` | 登录/同意、发 code、换 token |
| Resource Server | `mcp_server_oauth.py` | 校验 token，提供 MCP 工具 |

## 2. 目录

```
oauth_demo/
  config.py              URL、client_id、scope
  auth_server.py         最小 OAuth 2.1 AS（授权码 + PKCE）
  mcp_server_oauth.py    受保护的 MCP server（JWT 校验）
  client_oauth.py        完整客户端流程（浏览器 / headless）
  keys/                  自动生成的 RSA 密钥（不要提交到仓库）
```

## 3. 运行

需要三个终端，顺序很重要：

**终端 1：授权服务器**

```powershell
cd d:\Code\database_demo
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\auth_server.py
```

首次启动会在 `keys/` 生成 RSA 私钥和公钥。

**终端 2：MCP server**

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\mcp_server_oauth.py
```

它需要读 `keys/public.pem`，所以必须在 AS 启动之后运行。

**终端 3：客户端**

真实浏览器授权：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\client_oauth.py
```

会自动打开浏览器，点“同意授权”后回到终端。

自动测试（跳过浏览器，直接模拟用户同意）：

```powershell
mcp_demo\.venv\Scripts\python.exe mcp_demo\oauth_demo\client_oauth.py --headless
```

成功时能看到：

```
[3] 拿到 code：...
[4] 拿到 access_token：...
    claims: {"iss": "...", "aud": "http://127.0.0.1:8765/mcp", "scope": "mcp:tools", ...}
[5] 用 access_token 连接 MCP server
工具： ['add', 'current_user']
[6] 调用 current_user
{"authenticated": true, "subject": "demo-user", "client_id": "mcp-demo-client", "scopes": ["mcp:tools"]}
[7] 调用 add(10, 20)
30
```

## 4. OAuth 的关键概念

### 4.1 为什么需要 OAuth

MCP server 可能访问用户私有数据。不能只靠一个静态 API Key，因为：

- 用户要能授权、撤销；
- 客户端不应该拿到用户密码；
- token 要能限制权限（scope）和有效期；
- token 只能用于某个资源（audience），不能被别的服务复用。

OAuth 2.1 的授权码模式就是解决这些问题的标准流程。

### 4.2 授权码 + PKCE

本 demo 用的是 **Authorization Code + PKCE**：

1. 客户端生成随机 `code_verifier`，并算出 `code_challenge = SHA256(verifier)`；
2. 浏览器跳到 `/authorize`，带上 `client_id`、`redirect_uri`、`state`、`code_challenge`；
3. 用户在授权页点“同意”；
4. AS 把一次性 `code` 通过 302 回调给客户端；
5. 客户端用 `code + code_verifier` 去 `/token` 换 `access_token`；
6. AS 校验 `SHA256(verifier)` 是否等于之前存的 challenge。

为什么需要 PKCE：

- CLI、桌面客户端是“公开客户端”，没有 client_secret；
- 如果 code 被拦截，攻击者没有 verifier 也换不到 token；
- MCP 的远程客户端通常就是这种公开客户端。

`state` 用来防 CSRF：回调里的 state 必须和发起时一致。

### 4.3 access token 里有什么

本 demo 签发的是 RS256 JWT：

```json
{
  "iss": "http://127.0.0.1:9000",
  "aud": "http://127.0.0.1:8765/mcp",
  "sub": "demo-user",
  "client_id": "mcp-demo-client",
  "scope": "mcp:tools",
  "iat": 1793790983,
  "exp": 1793794583
}
```

MCP server 校验：

- 签名：用 AS 的公钥验证，伪造的 token 直接拒绝；
- `iss`：必须来自预期的授权服务器；
- `aud`：必须是这个 MCP server，防止 token 被拿去调别的服务；
- `exp`：过期拒绝；
- `scope`：必须有 `mcp:tools`。

### 4.4 JWKS 和 401 发现

- AS 通过 `/.well-known/jwks.json` 暴露公钥；
- MCP server 通过 `/.well-known/oauth-protected-resource/mcp` 告诉客户端“我受哪个 AS 保护、需要什么 scope”；
- 未带 token 时返回：

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer error="invalid_token",
  resource_metadata="http://127.0.0.1:8765/.well-known/oauth-protected-resource/mcp"
```

客户端看到 401 和 metadata 后，才知道该去哪个 AS 授权。这是 MCP 客户端自动登录的基础。

## 5. 代码怎么读

### 5.1 授权服务器

`auth_server.py` 提供：

| 端点 | 作用 |
|---|---|
| `/.well-known/oauth-authorization-server` | AS 元数据 |
| `/.well-known/jwks.json` | 公钥 |
| `/authorize` | 授权页（演示用 HTML） |
| `/authorize/approve` | 用户同意后发 code |
| `/token` | code + PKCE 换 JWT |

关键实现：

- `AUTH_CODES[code]` 保存 code、redirect_uri、challenge、scope、5 分钟过期；
- `/token` 里 `AUTH_CODES.pop(code)` 保证 code 一次性；
- `secrets.compare_digest` 比较 PKCE；
- `jwt.encode(..., algorithm="RS256")` 签发 token。

### 5.2 MCP 资源服务器

`mcp_server_oauth.py`：

```python
class JWTVerifier(TokenVerifier):
    async def verify_token(self, token):
        payload = jwt.decode(token, PUBLIC_KEY,
                             algorithms=["RS256"],
                             audience=MCP_URL,
                             issuer=AS_URL)
        ...
        return AccessToken(token=token, client_id=..., scopes=scopes,
                           expires_at=..., resource=payload["aud"],
                           subject=payload["sub"])
```

然后把它交给 MCPServer：

```python
mcp = MCPServer(
    "oauth-demo-server",
    token_verifier=JWTVerifier(),
    auth=AuthSettings(
        issuer_url=AS_URL,
        resource_server_url=MCP_URL,
        required_scopes=["mcp:tools"],
        validate_token_resource=True,
    ),
)
```

`current_user` 工具里用 `get_access_token()` 读取当前 token，演示“工具如何拿到用户身份”。

### 5.3 客户端

`client_oauth.py` 做了这些事：

1. 生成 verifier / challenge / state；
2. 起本地回调服务器 `127.0.0.1:8766`；
3. 打开 `/authorize`；
4. 收到 code，校验 state；
5. POST `/token` 换 token；
6. 用 `Authorization: Bearer` 连接 MCP；
7. 调用工具。

`--headless` 模式只是把“浏览器 + 点击同意”替换成直接 POST `/authorize/approve`，方便自动化测试，**不是真实登录**。

## 6. 有没有必要加网关？

**这个 demo 不需要。** MCP server 自己就是 OAuth 资源服务器，已经完成了 token 校验。

但生产环境可以考虑网关，判断标准如下：

| 场景 | 是否加网关 | 原因 |
|---|---|---|
| 单个 MCP server，内部使用 | 不需要 | 直接校验 JWT 足够，少一层运维 |
| 多个 MCP server 共用一套认证/限流 | 建议 | 统一 TLS、限流、日志、WAF |
| 同时有 MCP 和普通 REST API | 建议 | 网关统一入口和策略 |
| 需要隐藏内网拓扑、灰度、审计 | 建议 | 网关更适合做流量治理 |
| 只想“加个 OAuth” | 不需要 | 网关不是授权服务器，本身不发 token |

网关能做什么：

- TLS 终止、统一域名；
- 校验 JWT（或调用 introspection）；
- 限流、配额、WAF、访问日志；
- 多 MCP server 路由。

网关不能替代什么：

- **不能替代授权服务器**：登录、同意、发 code、发 token 仍然要 IdP/AS；
- **不能破坏 MCP 的发现链路**：必须放行 `/.well-known/oauth-protected-resource/mcp` 和 `WWW-Authenticate`，否则客户端不知道去哪里授权；
- **不建议改写 `aud`**：MCP server 仍然要用原始 resource 做校验，否则会 401。

如果以后要加，推荐组合是：

```
Client → 网关（TLS/限流/日志/JWT 预校验） → MCP server（再做一次 aud/scope 校验）
```

也就是“网关做流量治理，MCP server 做最终授权判断”，不要只依赖网关。

## 7. 生产化清单

这个 demo 刻意省略了：

1. **真实用户登录**：现在是固定 `demo-user`，生产要接 SSO/密码/MFA；
2. **HTTPS**：demo 全走 HTTP，生产必须 TLS；
3. **动态客户端注册（DCR）**：MCP 客户端通常需要自动注册，demo 是固定 client_id；
4. **refresh token**：demo token 1 小时过期，没有刷新；
5. **撤销与 introspection**：demo 没有 revocation endpoint；
6. **按工具授权**：demo 是全 server 的 `mcp:tools`，生产可以按工具检查 scope；
7. **密钥管理**：`keys/private.pem` 是本地文件，生产要放 KMS/HSM，并轮换；
8. **审计与限流**：谁在什么时候调了什么工具；
9. **CORS/CSRF**：浏览器客户端需要额外配置；
10. **resource 参数（RFC 8707）**：demo 把 `aud` 固定为 MCP_URL，真实 AS 应支持客户端传 `resource` 并绑定 token。

## 8. 练习

1. 把 `SCOPE` 改成 `mcp:admin`，观察 MCP server 是否拒绝旧 token。
2. 手动把 token 的 `aud` 改成别的地址，验证 MCP 返回 401。
3. 在 `current_user` 工具里检查 `mcp:admin` scope，实现“按工具授权”。
4. 给 AS 加 `/revoke`，让 token 立即失效。
5. 用 Keycloak/Auth0 替换 `auth_server.py`，MCP server 只改 `issuer_url` 和公钥来源。
6. 在 MCP 前面加 APISIX/Kong，观察哪些请求应该放行、哪些应该拦截。

## 9. 与其他 demo 的关系

- `../README.md` 是最基础的 MCP 教学：stdio、tools/resources/prompts、LLM 自动调用；
- 本目录专注 OAuth，不依赖原 RAG 项目；
- 真实 Host（Claude Desktop / Cursor）通常会自动完成这套 OAuth 流程，MCP server 只需要正确暴露 metadata 和 401。
