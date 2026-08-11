import httpx
from app.rag.embed import embed_texts
from app.rag.vector_store import VectorStore
from app.config import settings

_store = None

def get_store() -> VectorStore:
    global _store
    if _store is None:
        _store = VectorStore()
    return _store

def _keyword_boost(query: str, docs: list[dict]) -> list[dict]:
    """关键词加分（简化启发式，非标准 BM25）：向量分 + 查询字符在文档中的命中加分。"""
    scored = []
    for d in docs:
        hits = sum(1 for t in query if t in d["text"])
        scored.append({**d, "score": d.get("score", 0) * 0.6 + hits * 0.4})
    return sorted(scored, key=lambda x: x["score"], reverse=True)

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
