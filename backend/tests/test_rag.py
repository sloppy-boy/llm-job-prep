from app.rag import retrieve

def test_keyword_boost_sorts_and_filters():
    docs = [{"text": "七天无理由退货适用", "title": "t1", "score": 0.8},
            {"text": "退款到账时间", "title": "t2", "score": 0.5}]
    out = retrieve._keyword_boost("退货", docs)
    assert isinstance(out, list) and len(out) == 2
    assert out[0]["score"] > out[1]["score"]

def test_hybrid_search_returns_list():
    # 不真调 embed/向量库，只验证函数存在且返回 list（用 monkeypatch 替换）
    from app.rag import retrieve
    def fake_embed(texts):
        return [[0.0] * 1024 for _ in texts]
    class FakeStore:
        def search(self, vector, top_k=20):
            return [{"text": "abc", "title": "t", "category": "p", "score": 0.9}]
    retrieve.embed_texts = fake_embed
    retrieve.get_store = lambda: FakeStore()
    out = retrieve.hybrid_search("你好")
    assert isinstance(out, list)
