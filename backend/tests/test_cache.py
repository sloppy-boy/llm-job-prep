from app import cache

def test_cache_roundtrip():
    cache.cache_set("退货政策是什么", "answer-x")
    assert cache.cache_get("退货政策是什么") == "answer-x"

def test_redis_runtime_failure_falls_back(monkeypatch):
    class BoomRedis:
        def get(self, k):
            raise ConnectionError("redis down")
        def set(self, k, v, ex):
            raise ConnectionError("redis down")
    monkeypatch.setattr(cache, "_available", True)
    monkeypatch.setattr(cache, "_r", BoomRedis())
    # 先清空内存，验证 get 走内存分支
    with cache._lock:
        cache._mem.clear()
    cache.cache_set("q1", "a1")
    assert cache.cache_get("q1") == "a1"
