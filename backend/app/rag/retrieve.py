import threading
from pathlib import Path
import httpx
import jieba
from rank_bm25 import BM25Okapi
from app.rag.embed import embed_texts
from app.rag.vector_store import VectorStore
from app.config import settings
from app.rag.chunker import chunk_markdown, is_draft

_KB_ROOT = Path(__file__).resolve().parents[2] / "knowledge_base"

_store = None
_bm25 = None
_bm25_lock = threading.Lock()

def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store

def _tokenize(text: str) -> list[str]:
    """jieba 分词，过滤空白/纯标点 token。query 与语料统一用此函数保证一致性。"""
    return [t.strip() for t in jieba.lcut(text) if t.strip()]

def _load_corpus() -> list[str]:
    """与 build_kb 同源同序读取 knowledge_base，返回全部分块文本（BM25 语料）。草稿跳过。"""
    texts = []
    for md in sorted(_KB_ROOT.rglob("*.md")):
        if is_draft(md):
            continue
        for c in chunk_markdown(md):
            texts.append(c["text"])
    return texts

def _get_bm25() -> tuple[BM25Okapi, dict] | None:
    """懒构建整库 BM25 索引（threading.Lock 防并发首次构建竞态）。失败返回 None 由调用方回退纯向量。"""
    global _bm25
    if _bm25 is None:
        with _bm25_lock:
            if _bm25 is None:
                try:
                    corpus = _load_corpus()
                    tokenized = [_tokenize(t) for t in corpus]
                    idx = {}
                    for i, t in enumerate(corpus):
                        idx.setdefault(t, i)  # 重复文本取首个位置
                    _bm25 = (BM25Okapi(tokenized), idx)
                except Exception:
                    _bm25 = None  # 语料不可用则不启用 BM25
    return _bm25

def invalidate_bm25() -> None:
    """语料变化后调用：置空缓存，下次 _get_bm25 懒重建（回填发布/重索引后刷新）。"""
    global _bm25
    _bm25 = None

def _norm(vals: list[float]) -> list[float]:
    """min-max 归一化到 [0,1]；全等（单候选）时给 0.5 避免除零。"""
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return [0.5] * len(vals)
    return [(v - lo) / (hi - lo) for v in vals]

def _keyword_boost(query: str, docs: list[dict]) -> list[dict]:
    """向量分与真 BM25 分融合重排：min-max 归一化后 0.6*vec + 0.4*bm25。

    BM25 不可用 / 查询词全不命中 / 任何异常 → 回退纯向量顺序。永不抛出。
    """
    try:
        bm25 = _get_bm25()
        if bm25 is None:
            return sorted(docs, key=lambda x: x.get("score", 0), reverse=True)
        bm25_obj, idx = bm25
        q_tokens = _tokenize(query)
        scores = bm25_obj.get_scores(q_tokens)
        if not scores or max(scores) <= 0:
            return sorted(docs, key=lambda x: x.get("score", 0), reverse=True)
        score_by_text = {text: scores[i] for text, i in idx.items()}
        vecs = [d.get("score", 0) for d in docs]
        bms = [score_by_text.get(d["text"], 0.0) for d in docs]  # 不在语料（旧向量库）→ 0
        nv, nb = _norm(vecs), _norm(bms)
        for i, d in enumerate(docs):
            d["score"] = 0.6 * nv[i] + 0.4 * nb[i]
        return sorted(docs, key=lambda x: x["score"], reverse=True)
    except Exception:
        return sorted(docs, key=lambda x: x.get("score", 0), reverse=True)

def hybrid_search(query: str, top_k=20) -> list[dict]:
    vec = embed_texts([query])[0]
    return _keyword_boost(query, get_store().search(vec, top_k=top_k))

def rerank(query: str, docs: list[dict]) -> list[dict]:
    if not docs:
        return []
    resp = httpx.post("https://api.siliconflow.cn/v1/rerank",
                      headers={"Authorization": f"Bearer {settings.siliconflow_api_key}"},
                      json={"model": settings.rerank_model, "query": query,
                            "documents": [d["text"] for d in docs]},
                      timeout=30)
    resp.raise_for_status()
    results = sorted(resp.json()["results"], key=lambda r: r["relevance_score"], reverse=True)
    return [docs[r["index"]] for r in results[:settings.rerank_top_k]]
