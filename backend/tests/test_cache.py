from app import cache

def test_cache_roundtrip():
    cache.cache_set("退货政策是什么", "answer-x")
    assert cache.cache_get("退货政策是什么") == "answer-x"
