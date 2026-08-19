import time, uuid, logging, hmac
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from app import metrics
from app.config import settings
from app.ratelimit import get_store

logger = logging.getLogger("app")

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        # 健康检查免鉴权；浏览器跨域预检（OPTIONS，不带自定义头）也放行给 CORS 中间件处理；
        # 其余路径校验 X-API-Key
        if not request.url.path.endswith("/health") and request.method != "OPTIONS":
            key = request.headers.get("X-API-Key") or ""
            if not hmac.compare_digest(key, settings.api_key):
                metrics.record_rejected("auth")
                return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "bad api key"}}, status_code=401, headers={"X-Request-ID": rid})
        response = await call_next(request)
        latency = (time.perf_counter() - start) * 1000
        metrics.record_request(latency)
        response.headers["X-Request-ID"] = rid
        logger.info("req=%s path=%s status=%s latency_ms=%.1f", rid, request.url.path, response.status_code, latency)
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """全局按 X-API-Key 限流（令牌桶）。/health 豁免；空 Key 跳过（交给鉴权层 401）。"""

    async def dispatch(self, request: Request, call_next):
        if settings.ratelimit_enabled and not request.url.path.endswith("/health"):
            key = request.headers.get("X-API-Key") or ""
            if key:
                try:
                    allowed, wait, remaining = get_store().check(
                        f"key:{key}", settings.ratelimit_global_per_min)
                except Exception:
                    allowed, wait, remaining = True, 0.0, 0  # 限流器故障失败开放，可用性优先
                if not allowed:
                    metrics.record_rejected("ratelimit")
                    reset = int(time.time()) + int(wait) + 1
                    return JSONResponse(
                        {"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后重试"}},
                        status_code=429,
                        headers={"Retry-After": str(max(1, int(wait))),
                                 "X-RateLimit-Limit": str(settings.ratelimit_global_per_min),
                                 "X-RateLimit-Remaining": str(int(max(0, remaining))),
                                 "X-RateLimit-Reset": str(reset)})
        return await call_next(request)
