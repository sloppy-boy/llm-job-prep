from rank_bm25 import BM25Okapi
from app.rag import retrieve


def test_bm25_fusion_prefers_keyword_doc(monkeypatch):
    # 向量平分时，BM25 关键词命中者应胜出（对比旧字符启发式）
    corpus = ["七天无理由退货适用", "退款到账时间"]
    bm25 = BM25Okapi([retrieve._tokenize(t) for t in corpus])
    idx = {t: i for i, t in enumerate(corpus)}
    monkeypatch.setattr(retrieve, "_get_bm25", lambda: (bm25, idx))
    docs = [{"text": "七天无理由退货适用", "title": "t1", "score": 0.5},
            {"text": "退款到账时间", "title": "t2", "score": 0.5}]
    out = retrieve._keyword_boost("退货", docs)
    assert isinstance(out, list) and len(out) == 2
    assert out[0]["text"] == "七天无理由退货适用"


def test_bm25_all_zero_falls_back_to_vector(monkeypatch):
    corpus = ["七天无理由退货适用", "退款到账时间"]
    bm25 = BM25Okapi([retrieve._tokenize(t) for t in corpus])
    idx = {t: i for i, t in enumerate(corpus)}
    monkeypatch.setattr(retrieve, "_get_bm25", lambda: (bm25, idx))
    docs = [{"text": "退款到账时间", "title": "t2", "score": 0.9},
            {"text": "七天无理由退货适用", "title": "t1", "score": 0.2}]
    out = retrieve._keyword_boost("完全不存在关键词xyz", docs)  # query 分词后不命中语料
    assert out[0]["text"] == "退款到账时间"  # 纯向量顺序


def test_tokenize_returns_list():
    tokens = retrieve._tokenize("退货政策")
    assert isinstance(tokens, list) and tokens
    assert all(isinstance(t, str) and t.strip() for t in tokens)


def test_hybrid_search_returns_list(monkeypatch):
    def fake_embed(texts):
        return [[0.0] * 1024 for _ in texts]

    class FakeStore:
        def search(self, vector, top_k=20):
            return [{"text": "abc", "title": "t", "category": "p", "score": 0.9}]

    monkeypatch.setattr(retrieve, "embed_texts", fake_embed)
    monkeypatch.setattr(retrieve, "get_store", lambda: FakeStore())
    monkeypatch.setattr(retrieve, "_get_bm25", lambda: None)  # 不真读 KB / 建索引
    out = retrieve.hybrid_search("你好")
    assert isinstance(out, list)


def test_hybrid_search_survives_bm25_failure(monkeypatch):
    def fake_embed(texts):
        return [[0.0] * 1024 for _ in texts]

    class FakeStore:
        def search(self, vector, top_k=20):
            return [{"text": "abc", "title": "t", "category": "p", "score": 0.9}]

    def boom(*a, **k):
        raise RuntimeError("bm25 down")

    monkeypatch.setattr(retrieve, "embed_texts", fake_embed)
    monkeypatch.setattr(retrieve, "get_store", lambda: FakeStore())
    monkeypatch.setattr(retrieve, "_get_bm25", boom)
    out = retrieve.hybrid_search("你好")
    assert isinstance(out, list)  # BM25 挂了回退纯向量，不崩


def test_fusion_handles_single_candidate(monkeypatch):
    corpus = ["唯一文档内容"]
    bm25 = BM25Okapi([retrieve._tokenize(t) for t in corpus])
    idx = {t: 0 for t in corpus}
    monkeypatch.setattr(retrieve, "_get_bm25", lambda: (bm25, idx))
    out = retrieve._keyword_boost("退货", [{"text": "唯一文档内容", "score": 0.7}])
    assert isinstance(out, list) and len(out) == 1  # 单候选 max==min 不除零
