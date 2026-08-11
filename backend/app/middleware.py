import time, uuid, logging, hmac
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
from app import metrics
from app.config import settings

logger = logging.getLogger("app")

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        # 健康检查免鉴权；其余路径校验 X-API-Key
        if not request.url.path.endswith("/health"):
            key = request.headers.get("X-API-Key") or ""
            if not hmac.compare_digest(key, settings.api_key):
                return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "bad api key"}}, status_code=401, headers={"X-Request-ID": rid})
        response = await call_next(request)
        latency = (time.perf_counter() - start) * 1000
        metrics.record_request(latency)
        response.headers["X-Request-ID"] = rid
        logger.info("req=%s path=%s status=%s latency_ms=%.1f", rid, request.url.path, response.status_code, latency)
        return response
