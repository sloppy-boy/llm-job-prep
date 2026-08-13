import threading
import time

from app.config import settings


class TokenBucket:
    """令牌桶：惰性注水，consume O(1)。rate=每秒补充 token，capacity=突发上限。"""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()

    def consume(self, n: int = 1) -> tuple[bool, float, float]:
        """返回 (是否放行, 需等待秒数, 剩余 token)。"""
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens >= n:
            self._tokens -= n
            return True, 0.0, self._tokens
        wait = (n - self._tokens) / self.rate
        return False, wait, self._tokens


class RateLimitStore:
    """限流仓库契约：按 key 限流，per_min 为每分钟配额。"""

    def check(self, key: str, per_min: int) -> tuple[bool, float, float]:
        raise NotImplementedError


class MemoryRateLimitStore(RateLimitStore):
    """内存实现：dict[TokenBucket] + 全局锁。单实例 demo；多实例生产换 Redis。"""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, per_min: int) -> tuple[bool, float, float]:
        rate = per_min / 60.0
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(rate, per_min)
                self._buckets[key] = bucket
            return bucket.consume()


# Redis 令牌桶 Lua：读改写原子，避免并发下重复放行（内存实现用锁达成同一语义）
_TOKEN_BUCKET_LUA = """
local tokens = tonumber(redis.call('get', KEYS[1]))
local last = tonumber(redis.call('get', KEYS[1] .. ':ts'))
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local n = tonumber(ARGV[4])
if not tokens then tokens = capacity end
if not last then last = now end
tokens = math.min(capacity, tokens + (now - last) * rate)
redis.call('set', KEYS[1] .. ':ts', now)
if tokens >= n then
    tokens = tokens - n
    redis.call('set', KEYS[1], tokens)
    redis.call('expire', KEYS[1], 300)
    return {1, 0, tokens}
else
    local wait = (n - tokens) / rate
    redis.call('set', KEYS[1], tokens)
    redis.call('expire', KEYS[1], 300)
    return {0, wait, tokens}
end
"""


class RedisRateLimitStore(RateLimitStore):
    """Redis 实现：同语义令牌桶，Lua 脚本保证 read-modify-write 原子性。"""

    def __init__(self, redis_client):
        self._r = redis_client

    def check(self, key: str, per_min: int) -> tuple[bool, float, float]:
        res = self._r.eval(_TOKEN_BUCKET_LUA, 1, key,
                           time.time(), per_min / 60.0, per_min, 1)
        return bool(res[0]), float(res[1]), float(res[2])


_available = False
_store = None


def get_store() -> RateLimitStore:
    """Redis 可用则 Redis，否则内存降级（与 cache.py 的 _available 模式一致）。"""
    global _available, _store
    if _store is None:
        try:
            import redis as _redis
            _r = _redis.Redis.from_url(settings.redis_url)
            _available = bool(_r.ping())
        except Exception:
            _available = False
        _store = RedisRateLimitStore(_r) if _available else MemoryRateLimitStore()
    return _store
