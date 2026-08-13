# 限流（Rate Limiting）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为电商售后客服后端加双层限流——全局按 API Key（中间件）+ 用户层按 user_id（/chat），令牌桶算法，Redis 优先内存降级，429 带标准限流响应头。

**Architecture:** 纯逻辑令牌桶 `TokenBucket` + `RateLimitStore` 统一入口（`MemoryRateLimitStore` 内存锁实现 / `RedisRateLimitStore` Lua 脚本原子实现，二者同一语义）；`RateLimitMiddleware` 挂在 Observability 内层做全局检查；`/chat` 处理器内按 `user_id` 二次检查。Redis 可用性探测沿用 `cache.py` 的 `_available` 模式。

**Tech Stack:** Python 3.13 / FastAPI / starlette middleware / redis-py / pytest

**分支:** 从 `main` 开 `feature/task-15-ratelimit`

## Global Constraints

- TDD 红→绿循环，每任务最后提交
- 后端测试命令：`cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`
- 现有 80 个 pytest 必须保持全绿 → 新增 `tests/conftest.py` autouse fixture **默认关闭限流**，限流用例自行 `monkeypatch` 开启（避免共享 `dev-local-key` 被全局配额打到 429）
- 429 响应固定带 4 个头：`Retry-After` / `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`
- 错误体沿用现有形状：`{"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后重试"}}`
- 中间件顺序：`RateLimitMiddleware` 加在 `ObservabilityMiddleware` 之前（即更内层）→ 被限请求仍被日志/metrics 记录
- 限流器运行时故障**失败开放**（放行请求），可用性优先

---

### Task 1: TokenBucket + MemoryRateLimitStore

**Files:**
- Create: `backend/app/ratelimit.py`
- Test: `backend/tests/test_ratelimit.py`

**Interfaces:**
- Produces: `TokenBucket(rate, capacity).consume(n=1) -> (ok: bool, wait: float, remaining: float)`
- Produces: `MemoryRateLimitStore().check(key, per_min) -> (ok: bool, wait: float, remaining: float)`
- Produces: `RateLimitStore` 基类（`check` 抛 `NotImplementedError`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_ratelimit.py`:
```python
from app.ratelimit import TokenBucket, MemoryRateLimitStore


def test_bucket_starts_full():
    b = TokenBucket(rate=1.0, capacity=10)
    ok, wait, remaining = b.consume()
    assert ok is True and wait == 0.0 and remaining == 9.0


def test_bucket_exhaustion_returns_wait():
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_ratelimit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ratelimit'`

- [ ] **Step 3: 实现**

`backend/app/ratelimit.py`:
```python
import threading
import time


class TokenBucket:
    """令牌桶：惰性注水，consume O(1)。rate=每秒补充 token，capacity=突发上限。"""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()

    def consume(self, n: int = 1) -> tuple[bool, float, float]:
        """返回 (是否放行, 需等待秒数, 剩余 token)。"""
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens >= n:
            self._tokens -= n
            return True, 0.0, self._tokens
        wait = (n - self._tokens) / self.rate
        return False, wait, self._tokens


class RateLimitStore:
    """限流仓库契约：按 key 限流，per_min 为每分钟配额。"""

    def check(self, key: str, per_min: int) -> tuple[bool, float, float]:
        raise NotImplementedError


class MemoryRateLimitStore(RateLimitStore):
    """内存实现：dict[TokenBucket] + 全局锁。单实例 demo；多实例生产换 Redis。"""

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str, per_min: int) -> tuple[bool, float, float]:
        rate = per_min / 60.0
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(rate, per_min)
                self._buckets[key] = bucket
            return bucket.consume()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_ratelimit.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/ratelimit.py backend/tests/test_ratelimit.py
git commit -m "feat: 令牌桶 + 内存限流仓库（惰性注水 O(1)）"
```

---

### Task 2: config 扩展 + metrics 拒绝计数

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/metrics.py`
- Test: `backend/tests/test_ratelimit.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `settings.ratelimit_enabled: bool`, `settings.ratelimit_global_per_min: int`, `settings.ratelimit_user_per_min: int`
- Produces: `metrics.record_rejected(reason: str) -> None`；`metrics.snapshot()` 增加 `"rejected": {"ratelimit": int, "auth": int}`

- [ ] **Step 1: 写失败测试**

`backend/tests/test_ratelimit.py` 追加:
```python
def test_metrics_tracks_rejected():
    import app.metrics as m
    m._state["rejected"] = {"ratelimit": 0, "auth": 0}
    m.record_rejected("ratelimit")
    snap = m.snapshot()
    assert snap["rejected"]["ratelimit"] == 1
    assert snap["rejected"]["auth"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_ratelimit.py::test_metrics_tracks_rejected -q`
Expected: FAIL — `KeyError: 'rejected'`

- [ ] **Step 3: 实现**

`backend/app/config.py` 的 `Settings` 末尾追加:
```python
    ratelimit_enabled: bool = True
    ratelimit_global_per_min: int = 120
    ratelimit_user_per_min: int = 30
```

`backend/app/metrics.py` 全文替换:
```python
import threading

_lock = threading.Lock()
_state = {"requests": 0, "latency_sum_ms": 0.0, "total_tokens": 0,
          "rejected": {"ratelimit": 0, "auth": 0}}

def record_request(latency_ms: float):
    with _lock:
        _state["requests"] += 1
        _state["latency_sum_ms"] += latency_ms

def record_tokens(n: int):
    with _lock:
        _state["total_tokens"] += n

def record_rejected(reason: str):
    with _lock:
        _state["rejected"][reason] = _state["rejected"].get(reason, 0) + 1

def snapshot() -> dict:
    with _lock:
        reqs = _state["requests"]
        return {
            "requests": reqs,
            "avg_latency_ms": round(_state["latency_sum_ms"] / reqs, 2) if reqs else 0,
            "total_tokens": _state["total_tokens"],
            "total_cost_yuan": round(_state["total_tokens"] / 1_000_000, 4),
            "rejected": dict(_state["rejected"]),
        }
```

- [ ] **Step 4: 跑测试确认通过（含既有 metrics 用例）**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_ratelimit.py tests/test_health.py -q`
Expected: PASS（6 + 4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/config.py backend/app/metrics.py backend/tests/test_ratelimit.py
git commit -m "feat: 限流配置 + metrics 拒绝计数"
```

---

### Task 3: RedisRateLimitStore（Lua 原子令牌桶）

**Files:**
- Modify: `backend/app/ratelimit.py`
- Test: `backend/tests/test_ratelimit.py`（追加）

**Interfaces:**
- Consumes: `RateLimitStore` 基类
- Produces: `RedisRateLimitStore(redis_client).check(key, per_min)`（同一 `(ok, wait, remaining)` 语义）
- Produces: `get_store() -> RateLimitStore`（Redis 可用则 Redis，否则内存降级）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_ratelimit.py` 追加:
```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_ratelimit.py::test_redis_store_uses_lua_allow -q`
Expected: FAIL — `ImportError: cannot import name 'RedisRateLimitStore'`

- [ ] **Step 3: 实现**

`backend/app/ratelimit.py` 追加:
```python
# Redis 令牌桶 Lua：读改写原子，避免并发下重复放行（内存实现用锁达成同一语义）
_TOKEN_BUCKET_LUA = """
local tokens = tonumber(redis.call('get', KEYS[1]))
local last = tonumber(redis.call('get', KEYS[1] .. ':ts'))
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local n = tonumber(ARGV[4])
if not tokens then tokens = capacity end
if not last then last = now end
tokens = math.min(capacity, tokens + (now - last) * rate)
redis.call('set', KEYS[1] .. ':ts', now)
if tokens >= n then
    tokens = tokens - n
    redis.call('set', KEYS[1], tokens)
    redis.call('expire', KEYS[1], 300)
    return {1, 0, tokens}
else
    local wait = (n - tokens) / rate
    redis.call('set', KEYS[1], tokens)
    redis.call('expire', KEYS[1], 300)
    return {0, wait, tokens}
end
"""


class RedisRateLimitStore(RateLimitStore):
    """Redis 实现：同语义令牌桶，Lua 脚本保证 read-modify-write 原子性。"""

    def __init__(self, redis_client):
        self._r = redis_client

    def check(self, key: str, per_min: int) -> tuple[bool, float, float]:
        res = self._r.eval(_TOKEN_BUCKET_LUA, 1, key,
                           time.time(), per_min / 60.0, per_min, 1)
        return bool(res[0]), float(res[1]), float(res[2])


_available = False
_store = None


def get_store() -> RateLimitStore:
    """Redis 可用则 Redis，否则内存降级（与 cache.py 的 _available 模式一致）。"""
    global _available, _store
    if _store is None:
        try:
            import redis as _redis
            _r = _redis.Redis.from_url(settings.redis_url)
            _available = bool(_r.ping())
        except Exception:
            _available = False
        _store = RedisRateLimitStore(_r) if _available else MemoryRateLimitStore()
    return _store
```

`backend/app/ratelimit.py` 顶部 import 增加 `from app.config import settings`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_ratelimit.py -q`
Expected: PASS（8 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/ratelimit.py backend/tests/test_ratelimit.py
git commit -m "feat: Redis 令牌桶（Lua 原子）+ get_store 降级工厂"
```

---

### Task 4: RateLimitMiddleware + conftest + 注册 + 集成测试

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_rate_limit_middleware.py`
- Modify: `backend/app/middleware.py`
- Modify: `backend/app/main.py`

**Interfaces:**
- Consumes: `get_store()`, `settings.ratelimit_enabled`, `settings.ratelimit_global_per_min`, `metrics.record_rejected`
- Produces: `RateLimitMiddleware`（Starlette `BaseHTTPMiddleware`，`/health` 豁免，空 Key 跳过）

- [ ] **Step 1: 写失败测试**

`backend/tests/conftest.py`:
```python
import pytest
from app.config import settings


@pytest.fixture(autouse=True)
def _ratelimit_off():
    """默认关闭限流，避免共享 dev-local-key 的既有用例被全局配额打到 429；限流用例自行开启。"""
    prev = settings.ratelimit_enabled
    settings.ratelimit_enabled = False
    yield
    settings.ratelimit_enabled = prev
```

`backend/tests/test_rate_limit_middleware.py`:
```python
from fastapi.testclient import TestClient
from app.main import app
import app.config as cfg


def _enable(monkeypatch, per_min=3, api_key="rl-test-key"):
    monkeypatch.setattr(cfg.settings, "ratelimit_enabled", True)
    monkeypatch.setattr(cfg.settings, "ratelimit_global_per_min", per_min)
    monkeypatch.setattr(cfg.settings, "api_key", api_key)


def test_global_rate_limit_429_after_quota(monkeypatch):
    _enable(monkeypatch, per_min=3)
    c = TestClient(app)
    for _ in range(3):
        assert c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"}).status_code == 200
    r = c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"})
    assert r.status_code == 429
    assert r.headers.get("Retry-After")
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert "RATE_LIMITED" in r.text


def test_health_exempt_from_ratelimit(monkeypatch):
    _enable(monkeypatch, per_min=2)
    c = TestClient(app)
    for _ in range(5):
        assert c.get("/api/v1/health").status_code == 200


def test_rate_limited_requests_recorded_in_metrics(monkeypatch):
    import app.metrics as m
    m._state["rejected"] = {"ratelimit": 0, "auth": 0}
    _enable(monkeypatch, per_min=1)
    c = TestClient(app)
    c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"})
    r = c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"})
    assert r.status_code == 429
    assert m.snapshot()["rejected"]["ratelimit"] >= 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_rate_limit_middleware.py -q`
Expected: FAIL（没有 RateLimitMiddleware 时不返回 429，assert 失败）

- [ ] **Step 3: 实现**

`backend/app/middleware.py` 追加 import（`time` 已导入）并新增类:
```python
class RateLimitMiddleware(BaseHTTPMiddleware):
    """全局按 X-API-Key 限流（令牌桶）。/health 豁免；空 Key 跳过（交给鉴权层 401）。"""

    async def dispatch(self, request: Request, call_next):
        if settings.ratelimit_enabled and not request.url.path.endswith("/health"):
            key = request.headers.get("X-API-Key") or ""
            if key:
                try:
                    allowed, wait, remaining = get_store().check(
                        f"key:{key}", settings.ratelimit_global_per_min)
                except Exception:
                    allowed, wait, remaining = True, 0.0, 0  # 限流器故障失败开放，可用性优先
                if not allowed:
                    metrics.record_rejected("ratelimit")
                    reset = int(time.time()) + int(wait) + 1
                    return JSONResponse(
                        {"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后重试"}},
                        status_code=429,
                        headers={"Retry-After": str(max(1, int(wait))),
                                 "X-RateLimit-Limit": str(settings.ratelimit_global_per_min),
                                 "X-RateLimit-Remaining": str(int(max(0, remaining))),
                                 "X-RateLimit-Reset": str(reset)})
        return await call_next(request)
```

`backend/app/middleware.py` 顶部 import 追加:
```python
from app.ratelimit import get_store
```

`backend/app/middleware.py` 鉴权 401 分支追加拒绝计数（`metrics.record_rejected("auth")`，放在返回 401 之前）:
```python
        if not request.url.path.endswith("/health"):
            key = request.headers.get("X-API-Key") or ""
            if not hmac.compare_digest(key, settings.api_key):
                metrics.record_rejected("auth")
                return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "bad api key"}},
                                    status_code=401, headers={"X-Request-ID": rid})
```

`backend/app/main.py` 导入与注册（**RateLimit 加在 Observability 之前**，使其更内层）:
```python
from app.middleware import ObservabilityMiddleware, RateLimitMiddleware
...
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_rate_limit_middleware.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: 全量回归确认既有用例不破**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`
Expected: 全绿（80 既有 + 新增，conftest 已默认关限流）

- [ ] **Step 6: 提交**

```bash
git add backend/tests/conftest.py backend/tests/test_rate_limit_middleware.py \
        backend/app/middleware.py backend/app/main.py
git commit -m "feat: RateLimitMiddleware 全局限流 + conftest 默认关闭 + auth 拒绝计数"
```

---

### Task 5: /chat 按 user_id 二次限流

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_rate_limit_middleware.py`（追加）

**Interfaces:**
- Consumes: `get_store()`, `settings.ratelimit_enabled`, `settings.ratelimit_user_per_min`
- Produces: `chat()` 在解析 `ChatRequest` 后先做用户层检查，超限返回 429 JSON

- [ ] **Step 1: 写失败测试**

`backend/tests/test_rate_limit_middleware.py` 追加:
```python
def test_chat_per_user_rate_limit(monkeypatch):
    monkeypatch.setattr(cfg.settings, "ratelimit_enabled", True)
    monkeypatch.setattr(cfg.settings, "ratelimit_user_per_min", 2)
    monkeypatch.setattr(cfg.settings, "api_key", "rl-user-key")
    import app.api.chat as chat_mod
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h, uid: {
        "question": q, "session_id": sid, "history": h or [],
        "domain": "chitchat", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: True)
    monkeypatch.setattr(chat_mod, "llm_chat_stream", lambda m: iter([]))
    c = TestClient(app)
    body = {"session_id": "s1", "message": "hi", "user_id": "rl-u-1"}
    for _ in range(2):
        assert c.post("/api/v1/chat", json=body,
                      headers={"X-API-Key": "rl-user-key"}).status_code == 200
    r = c.post("/api/v1/chat", json=body, headers={"X-API-Key": "rl-user-key"})
    assert r.status_code == 429
    assert "RATE_LIMITED" in r.text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_rate_limit_middleware.py::test_chat_per_user_rate_limit -q`
Expected: FAIL（第三个请求返回 200 而非 429）

- [ ] **Step 3: 实现**

`backend/app/api/chat.py` 顶部 import 追加:
```python
import time
from fastapi.responses import JSONResponse
from app import metrics
from app.config import settings
from app.ratelimit import get_store
```

`backend/app/api/chat.py` 的 `chat()` 开头（解析 `req` 后、`async def gen()` 之前）插入:
```python
    if settings.ratelimit_enabled:
        allowed, wait, remaining = get_store().check(f"user:{req.user_id}", settings.ratelimit_user_per_min)
        if not allowed:
            metrics.record_rejected("ratelimit")
            reset = int(time.time()) + int(wait) + 1
            return JSONResponse(
                {"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后重试"}},
                status_code=429,
                headers={"Retry-After": str(max(1, int(wait))),
                         "X-RateLimit-Limit": str(settings.ratelimit_user_per_min),
                         "X-RateLimit-Remaining": str(int(max(0, remaining))),
                         "X-RateLimit-Reset": str(reset)})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_rate_limit_middleware.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/chat.py backend/tests/test_rate_limit_middleware.py
git commit -m "feat: /chat 按 user_id 二次限流"
```

---

### Task 6: 全量回归 + 文档更新 + 收尾

**Files:**
- Modify: `docs/optimization-todo.md`
- Modify: `CONTEXT.md`

- [ ] **Step 1: 全量回归**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`
Expected: 全绿（85 用例：80 既有 + 5 新增）

- [ ] **Step 2: 更新待优化清单**

`docs/optimization-todo.md` 的「四、推荐优先级」表格第 2 行勾选并补注：
```markdown
| 2 | ✅ 限流（令牌桶，Redis/内存双层降级） | API Key 全局 + user_id 双层，429 带标准头 | 已做 |
```
「二、与成熟项目差距」表中「限流」行「本项目」列改为：`令牌桶限流（API Key + user_id 双层，Redis Lua/内存降级）`。

- [ ] **Step 3: 更新 CONTEXT**

`CONTEXT.md` 的优化轮段落追加一行：
```markdown
- **限流（2026-08-14）**：令牌桶 + `RateLimitStore`（Redis Lua 原子/内存锁降级）；`RateLimitMiddleware` 全局按 Key + `/chat` 按 user_id 双层；429 带 `Retry-After`/`X-RateLimit-*` 头；metrics 拒绝计数；conftest 默认关闭避免污染既有用例。85 pytest 全绿。
```

- [ ] **Step 4: 提交**

```bash
git add docs/optimization-todo.md CONTEXT.md
git commit -m "docs: 限流完成（令牌桶双层限流，85 用例全绿）"
```

---

## 完成定义

- [ ] `feature/task-15-ratelimit` 上 85 pytest 全绿
- [ ] curl 验证：连续打 `/api/v1/metrics` 超配额返回 429 + 4 个限流头
- [ ] `/health` 永不被限
- [ ] 合并回 `main` 前跑一遍完整回归
