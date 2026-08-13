from app.ratelimit import TokenBucket, MemoryRateLimitStore


def test_bucket_starts_full():
    b = TokenBucket(rate=1.0, capacity=10)
    ok, wait, remaining = b.consume()
    assert ok is True and wait == 0.0 and remaining == 9.0


def test_bucket_exhaustion_returns_wait(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.ratelimit.time.monotonic", lambda: now[0])
    b = TokenBucket(rate=1.0, capacity=1)
    b.consume()
    ok, wait, remaining = b.consume()
    assert ok is False
    assert wait > 0
    assert remaining == 0.0


def test_bucket_refills_over_time(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("app.ratelimit.time.monotonic", lambda: now[0])
    b = TokenBucket(rate=2.0, capacity=10)
    b.consume()  # → 9
    b.consume()  # → 8
    now[0] += 1.0  # +2 token → 封顶 capacity 10
    ok, wait, remaining = b.consume()
    assert ok is True and remaining == 9.0


def test_bucket_capacity_is_burst_limit():
    b = TokenBucket(rate=0.1, capacity=5)
    for _ in range(5):
        assert b.consume()[0] is True
    assert b.consume()[0] is False


def test_memory_store_separates_keys():
    s = MemoryRateLimitStore()
    for _ in range(3):
        assert s.check("a", per_min=3)[0] is True
    assert s.check("a", per_min=3)[0] is False
    assert s.check("b", per_min=3)[0] is True  # 独立配额


def test_metrics_tracks_rejected():
    import app.metrics as m
    m._state["rejected"] = {"ratelimit": 0, "auth": 0}
    m.record_rejected("ratelimit")
    snap = m.snapshot()
    assert snap["rejected"]["ratelimit"] == 1
    assert snap["rejected"]["auth"] == 0


def test_redis_store_uses_lua_allow():
    from app.ratelimit import RedisRateLimitStore, _TOKEN_BUCKET_LUA
    calls = {}
    class FakeRedis:
        def eval(self, script, numkeys, key, *args):
            calls["script"] = script
            return [1, 0, 10]
    store = RedisRateLimitStore(FakeRedis())
    allowed, wait, remaining = store.check("k", 60)
    assert allowed is True and wait == 0.0 and remaining == 10.0
    assert calls["script"] == _TOKEN_BUCKET_LUA


def test_redis_store_uses_lua_deny():
    from app.ratelimit import RedisRateLimitStore
    class FakeRedis:
        def eval(self, script, numkeys, key, *args):
            return [0, 2.5, 0]
    store = RedisRateLimitStore(FakeRedis())
    allowed, wait, remaining = store.check("k", 60)
    assert allowed is False and wait == 2.5 and remaining == 0.0


def test_redis_store_degrades_to_memory_on_failure(monkeypatch):
    from app.ratelimit import RedisRateLimitStore, MemoryRateLimitStore
    calls = {"n": 0}
    class DeadRedis:
        def eval(self, script, numkeys, key, *args):
            calls["n"] += 1
            raise ConnectionError("redis down")
    store = RedisRateLimitStore(DeadRedis())
    # 第一次：eval 抛异常 → 降级内存，仍能返回结果
    ok, wait, remaining = store.check("k", 60)
    assert ok is True or ok is False  # 内存桶正常返回，不抛
    assert calls["n"] == 1
    # 第二次：已标记 dead，不再碰 redis
    store.check("k", 60)
    assert calls["n"] == 1
    assert isinstance(store._mem, MemoryRateLimitStore)
