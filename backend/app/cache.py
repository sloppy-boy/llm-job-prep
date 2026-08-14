import hashlib, threading, time
from app.config import settings
from app.rag.embed import embed_texts

_mem = {}  # key -> (expires_at, answer)
_lock = threading.Lock()
TTL = 3600  # 秒；内存层与 Redis 精确层同 TTL，语义层亦按此过期

# 语义缓存层：内存余弦索引（单实例 demo；多实例生产换 Qdrant/Redis 向量，接口不变）
_sem = []  # list of {"embed": list[float], "answer": str, "ts": float}
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

def _expired(ts: float) -> bool:
    return time.time() - ts > TTL

def cache_get(question: str) -> str | None:
    # 1) 精确命中短路（不触发 embed）；内存条目带 TTL，过期即视为未命中
    k = _key(question)
    global _available
    if _available:
        try:
            v = _r.get(k)
            if v is not None:
                return v
        except Exception:
            _available = False  # 运行时 Redis 故障 → 降级内存
    now = time.time()
    with _lock:
        entry = _mem.get(k)
        if entry is not None:
            expires_at, v = entry
            if now <= expires_at:
                return v
            del _mem[k]
    # 2) 语义层：embed query 后余弦扫描（过期条目跳过并顺带清理）；embed 失败绝不崩，返回 None
    try:
        vec = embed_texts([question])[0]
    except Exception:
        return None
    best, best_sim = None, 0.0
    with _lock:
        expired = [e for e in _sem if _expired(e["ts"])]
        if expired:
            for e in expired:
                _sem.remove(e)
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
        _mem[k] = (time.time() + TTL, answer)
    # 语义层写（失败不影响精确缓存）；写前惰性清理过期条目控制内存
    try:
        vec = embed_texts([question])[0]
    except Exception:
        return
    with _lock:
        if len(_sem) >= SEM_MAX:
            # 先清过期，仍满则淘汰最旧
            _sem[:] = [e for e in _sem if not _expired(e["ts"])]
            if len(_sem) >= SEM_MAX:
                del _sem[:len(_sem) - SEM_MAX + 1]
        _sem.append({"embed": vec, "answer": answer, "ts": time.time()})
