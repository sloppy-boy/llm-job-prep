import hashlib, threading
from app.config import settings

_mem = {}
_lock = threading.Lock()
TTL = 3600  # 秒

# Redis 可用则用 Redis，否则内存降级
_available = False
_r = None
try:
    import redis as _redis
    _r = _redis.Redis.from_url(settings.redis_url, decode_responses=True)
    _available = _r.ping()
except Exception:
    _available = False

def _key(question: str) -> str:
    return "cache:" + hashlib.md5(question.encode()).hexdigest()

def cache_get(question: str) -> str | None:
    k = _key(question)
    global _available
    if _available:
        try:
            return _r.get(k)
        except Exception:
            _available = False  # 运行时 Redis 故障 → 降级内存
    with _lock:
        return _mem.get(k)

def cache_set(question: str, answer: str) -> None:
    k = _key(question)
    global _available
    if _available:
        try:
            _r.set(k, answer, ex=TTL)
            return
        except Exception:
            _available = False
    with _lock:
        _mem[k] = answer
