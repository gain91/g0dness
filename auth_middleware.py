"""LAN 鉴权中间件 — Token 认证保护所有 API"""
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

AUTH_DIR = os.path.expanduser("~/.ai-suite")
AUTH_FILE = os.path.join(AUTH_DIR, "auth_token")
os.makedirs(AUTH_DIR, exist_ok=True)


def get_or_create_token() -> str:
    """获取或生成认证 token"""
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r") as f:
            token = f.read().strip()
            if token:
                return token
    token = secrets.token_hex(16)
    with open(AUTH_FILE, "w") as f:
        f.write(token)
    return token


AUTH_TOKEN = get_or_create_token()

# 无需鉴权的路径前缀
PUBLIC_PATHS = ("/mobile", "/api/status", "/api/health", "/output/", "/favicon.ico")


class AuthMiddleware(BaseHTTPMiddleware):
    """Token 鉴权中间件 — 检查 X-Auth-Token header 或 ?token= query"""

    async def dispatch(self, request, call_next):
        path = request.url.path

        # 公开路径跳过
        if any(path.startswith(p) for p in PUBLIC_PATHS):
            return await call_next(request)

        # 本地请求跳过 (127.0.0.1 / localhost / [::1])
        client = request.client
        if client and client.host in ("127.0.0.1", "localhost", "::1"):
            return await call_next(request)

        # 从 header 或 query param 取 token
        token = request.headers.get("X-Auth-Token") or request.query_params.get("token")
        if token and secrets.compare_digest(token, AUTH_TOKEN):
            return await call_next(request)

        return JSONResponse({"error": "Unauthorized — need valid token"}, 401)
