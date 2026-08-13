import hashlib, threading
from app.config import settings
from app.rag.embed import embed_texts

_mem = {}
_lock = threading.Lock()
TTL = 3600  # 秒

# 语义缓存层：内存余弦索引（单实例 demo；多实例生产换 Qdrant/Redis 向量，接口不变）
_sem = []  # list of {"embed": list[float], "answer": str}
SEM_MAX = settings.semantic_cache_max

# Redis 可用则用 Redis，否则内存降级
_available = False
_r = None
try:
    import redis as _redis
    _r = _redis.Redis.from_url(settings.redis_url, decode_responses=True)
    _available = _r.ping()
except Exception:
    _available = False

def _key(question: str) -> str:
    return "cache:" + hashlib.md5(question.encode()).hexdigest()

def _cosine(a, b) -> float:
    """余弦相似度；任一向量零范数返回 0。"""
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)

def cache_get(question: str) -> str | None:
    # 1) 精确命中短路（不触发 embed）
    k = _key(question)
    global _available
    if _available:
        try:
            v = _r.get(k)
            if v is not None:
                return v
        except Exception:
            _available = False  # 运行时 Redis 故障 → 降级内存
    with _lock:
        v = _mem.get(k)
        if v is not None:
            return v
    # 2) 语义层：embed query 后余弦扫描；embed 失败绝不崩，返回 None
    try:
        vec = embed_texts([question])[0]
    except Exception:
        return None
    best, best_sim = None, 0.0
    with _lock:
        for entry in _sem:
            sim = _cosine(vec, entry["embed"])
            if sim > best_sim:
                best, best_sim = entry["answer"], sim
    if best is not None and best_sim >= settings.semantic_cache_threshold:
        return best
    return None

def cache_set(question: str, answer: str) -> None:
    k = _key(question)
    global _available
    if _available:
        try:
            _r.set(k, answer, ex=TTL)
        except Exception:
            _available = False
    with _lock:
        _mem[k] = answer
    # 语义层写（失败不影响精确缓存）
    try:
        vec = embed_texts([question])[0]
    except Exception:
        return
    with _lock:
        _sem.append({"embed": vec, "answer": answer})
        if len(_sem) > SEM_MAX:
            del _sem[:len(_sem) - SEM_MAX]  # 淘汰最旧
