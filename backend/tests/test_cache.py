import pytest
from app import cache


@pytest.fixture(autouse=True)
def _clean_cache(monkeypatch):
    """每个测试前清空精确缓存与语义索引，防止模块级状态跨测试污染；
    默认 mock embed，防真调 SiliconFlow API。"""
    with cache._lock:
        cache._mem.clear()
        cache._sem.clear()
    monkeypatch.setattr(cache, "embed_texts", lambda texts: [[1.0, 0, 0, 0] for _ in texts])
    yield
    with cache._lock:
        cache._mem.clear()
        cache._sem.clear()


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
    cache.cache_set("q1", "a1")
    assert cache.cache_get("q1") == "a1"  # Redis 故障 → mem 精确命中


def test_semantic_hit_returns_answer(monkeypatch):
    cache.cache_set("我的订单到哪了", "A")
    monkeypatch.setattr(cache, "embed_texts", lambda texts: [[1.0, 0, 0, 0] for _ in texts])
    assert cache.cache_get("我订单到哪了") == "A"  # 精确 miss，语义同向量命中


def test_semantic_miss_returns_none(monkeypatch):
    cache.cache_set("我的订单到哪了", "A")
    monkeypatch.setattr(cache, "embed_texts", lambda texts: [[0.0, 1.0, 0, 0] for _ in texts])
    assert cache.cache_get("完全不相关的问题") is None  # 正交向量，余弦 0 < 阈值


def test_exact_hit_short_circuits_before_embed(monkeypatch):
    cache.cache_set("q", "A")
    calls = []

    def fake_embed(texts):
        calls.append(texts)
        return [[1.0, 0, 0, 0] for _ in texts]

    monkeypatch.setattr(cache, "embed_texts", fake_embed)
    assert cache.cache_get("q") == "A"
    assert calls == []  # 精确命中不触发 embed


def test_embed_failure_does_not_crash(monkeypatch):
    monkeypatch.setattr(cache, "embed_texts", lambda texts: (_ for _ in ()).throw(RuntimeError("embed down")))
    assert cache.cache_get("新问题") is None  # get 不抛
    cache.cache_set("新问题", "B")  # set 里 embed 失败也不崩，仍写精确缓存
    assert cache.cache_get("新问题") == "B"


def test_semantic_index_capped(monkeypatch):
    monkeypatch.setattr(cache, "SEM_MAX", 2)
    cache.cache_set("q1", "a1")
    cache.cache_set("q2", "a2")
    cache.cache_set("q3", "a3")
    with cache._lock:
        assert len(cache._sem) <= 2


def test_cosine_unit():
    assert cache._cosine([1, 0, 0], [1, 0, 0]) == 1.0
    assert cache._cosine([1, 0, 0], [0, 1, 0]) == 0.0
    assert cache._cosine([0, 0], [0, 0]) == 0.0  # 零范数不除零
