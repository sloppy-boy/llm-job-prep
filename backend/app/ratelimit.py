import threading
import time


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
