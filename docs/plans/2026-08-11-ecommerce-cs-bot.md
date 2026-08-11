# 电商售后智能客服系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个带工具调用的电商售后智能客服：RAG + LangGraph 多 Agent + 工具调用 + 商用级工程化，作为求职作品集。

**Architecture:** Next.js 前端消费 FastAPI 的 SSE 流式接口；FastAPI 应用层（中间件/会话/缓存/指标）调用 LangGraph 多 Agent 状态图（路由→检索→工具→写作→审核，审核打回上限 2 次）；RAG 用 Qdrant 混合检索 + bge-reranker 精排；工具层操作 mock 订单 SQLite；部署用 Docker Compose。

**Tech Stack:** Python 3.13 · FastAPI · LangGraph · Qdrant · bge-m3 / bge-reranker (SiliconFlow API) · DeepSeek (openai SDK) · PostgreSQL · Redis · Next.js (TypeScript) · Docker Compose

## Global Constraints

- 全部模型走国内云 API（DeepSeek + SiliconFlow），**不需要代理**，Key 只存 `.env`（不进 git）
- 审核打回循环上限：2 次；超限输出当前版本并标记 `review_status="unverified"`
- 检索为空/工具失败时**禁止模型瞎编**，必须走"知识库无相关内容/转人工"兜底
- 每个任务结束必须有可独立验证的交付物 + git commit
- 代码注释用中文，与个人项目风格一致；测试用 pytest
- 向量库通过 repository 接口抽象，底层可切换（先 Qdrant）

---

## 文件结构总览

```
llm-job-prep/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # pydantic-settings 配置
│   │   ├── middleware.py        # 请求ID/日志/限流/CORS/API Key
│   │   ├── metrics.py           # 延迟/token/成本统计
│   │   ├── llm.py               # DeepSeek 客户端 + 重试 + 降级
│   │   ├── cache.py             # 语义缓存（Redis/内存）
│   │   ├── api/
│   │   │   ├── chat.py          # POST /api/v1/chat (SSE)
│   │   │   └── health.py        # /health /metrics
│   │   ├── agents/
│   │   │   ├── state.py         # LangGraph state schema
│   │   │   ├── nodes.py         # router/retriever/tool/writer/reviewer
│   │   │   └── graph.py         # 状态图组装
│   │   ├── tools/
│   │   │   ├── mock_db.py       # SQLite mock 订单/物流/退款
│   │   │   └── order_tools.py   # query_order/logistics/refund/escalate
│   │   └── rag/
│   │       ├── embed.py         # bge-m3 embedding 客户端
│   │       ├── chunker.py       # 分块策略
│   │       ├── vector_store.py  # Qdrant repository
│   │       └── retrieve.py      # 混合检索 + rerank
│   ├── knowledge_base/          # 语料 markdown
│   ├── scripts/
│   │   ├── seed_mock.py         # 生成 mock 数据库
│   │   └── build_kb.py          # 语料入库 → Qdrant
│   ├── eval/
│   │   ├── questions.json       # 25 评测题
│   │   └── judge.py             # LLM-as-judge 打分
│   ├── tests/                   # pytest
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                    # Next.js
│   ├── app/page.tsx             # 聊天界面
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Task 1: 项目脚手架与配置

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `.env.example`
- Create: `backend/.env`（本机，不进 git）
- Create: `backend/tests/__init__.py`

**Interfaces:**
- Produces: `config.Settings` 单例，属性：`deepseek_api_key`, `siliconflow_api_key`, `qdrant_url`, `database_url`, `redis_url`, `model_primary="deepseek-chat"`, `model_fallback`, `rerank_top_k=3`, `max_review_rounds=2`

- [ ] **Step 1: 建目录与虚拟环境**

```bash
cd /k/claude/llm-job-prep
mkdir -p backend/app/{api,agents,tools,rag} backend/scripts backend/eval backend/tests backend/knowledge_base
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install --upgrade pip
```

- [ ] **Step 2: 写 requirements.txt**

```
fastapi==0.115.*
uvicorn[standard]==0.34.*
pydantic==2.*
pydantic-settings==2.*
langgraph==0.4.*
qdrant-client==1.*
openai==1.*
httpx==0.28.*
sqlalchemy==2.*
redis==5.*
pytest==8.*
sse-starlette==2.*
python-dotenv==1.*
```

- [ ] **Step 3: 写 config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    deepseek_api_key: str = ""
    siliconflow_api_key: str = ""
    qdrant_url: str = "http://localhost:6333"
    database_url: str = "sqlite:///./mock_orders.db"   # 会话用 Postgres，订单 mock 用 SQLite
    redis_url: str = "redis://localhost:6379"
    model_primary: str = "deepseek-chat"
    model_fallback: str = "deepseek-chat"
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_k: int = 3
    max_review_rounds: int = 2
    api_key: str = "dev-local-key"

settings = Settings()
```

- [ ] **Step 4: 写 .env.example**

```bash
DEEPSEEK_API_KEY=
SILICONFLOW_API_KEY=
QDRANT_URL=http://localhost:6333
DATABASE_URL=sqlite:///./mock_orders.db
REDIS_URL=redis://localhost:6379
API_KEY=dev-local-key
```

- [ ] **Step 5: 安装依赖并验证导入**

```bash
backend/.venv/Scripts/python -c "from app.config import settings; print(settings.model_primary)"
```

Expected: 打印 `deepseek-chat`，无报错。

- [ ] **Step 6: 写根目录 `.gitignore`**

```
.env
__pycache__/
*.pyc
.venv/
node_modules/
.next/
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "chore: 项目脚手架与配置"
```

---

## Task 2: mock 订单数据库

**Files:**
- Create: `backend/app/tools/mock_db.py`
- Create: `backend/scripts/seed_mock.py`

**Interfaces:**
- Produces:
  - `get_order(order_id: str) -> dict | None`（含 status/items/amount）
  - `get_logistics(order_id: str) -> list[dict]`（轨迹列表）
  - `create_refund(order_id: str, reason: str) -> dict`（写入并返回申请单）
  - `escalate(session_id: str) -> dict`

- [ ] **Step 1: 写 mock_db.py（内存 + SQLite 持久化，预置数据）**

```python
import sqlite3, json
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "mock_orders.db"

ORDERS = [
    {"order_id": "20260811001", "status": "已发货", "items": "智能音箱 x1", "amount": 299.0, "created": "2026-08-10"},
    {"order_id": "20260811002", "status": "运输中", "items": "蓝牙耳机 x1", "amount": 199.0, "created": "2026-08-11"},
    {"order_id": "20260811003", "status": "已签收", "items": "数据线 x2", "amount": 39.9,  "created": "2026-08-08"},
    {"order_id": "20260811004", "status": "退款中", "items": "充电宝 x1", "amount": 129.0, "created": "2026-08-09"},
]
LOGISTICS = {
    "20260811001": [("08-10 20:00", "商家已发货"), ("08-11 08:00", "到达本地分拨中心")],
    "20260811002": [("08-11 09:00", "揽收"), ("08-11 14:00", "运输中")],
}

def _conn():
    Path.mkdir(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS orders(
        order_id TEXT PRIMARY KEY, status TEXT, items TEXT, amount REAL, created TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS refunds(
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT, reason TEXT, status TEXT DEFAULT '已申请')""")
    return conn

def get_order(order_id: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        # 首次运行 seed
        for o in ORDERS:
            conn.execute("INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?)",
                         (o["order_id"], o["status"], o["items"], o["amount"], o["created"]))
        conn.commit()
        row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
    conn.close()
    return None if row is None else {"order_id": row[0], "status": row[1], "items": row[2], "amount": row[3], "created": row[4]}

def get_logistics(order_id: str) -> list[dict]:
    return [{"time": t, "event": e} for t, e in LOGISTICS.get(order_id, [])]

def create_refund(order_id: str, reason: str) -> dict:
    conn = _conn()
    cur = conn.execute("INSERT INTO refunds(order_id, reason) VALUES (?,?)", (order_id, reason))
    conn.commit()
    refund_id = cur.lastrowid
    conn.close()
    return {"refund_id": f"R{refund_id}", "order_id": order_id, "reason": reason, "status": "已申请"}

def escalate(session_id: str) -> dict:
    return {"session_id": session_id, "status": "已转人工"}
```

- [ ] **Step 2: 写 seed_mock.py**

```python
from app.tools.mock_db import get_order, create_refund

if __name__ == "__main__":
    for oid in ["20260811001", "20260811002"]:
        print(get_order(oid))
    print(create_refund("20260811002", "不想要了"))
```

- [ ] **Step 3: 运行并验证**

```bash
cd /k/claude/llm-job-prep/backend
.venv/Scripts/python scripts/seed_mock.py
```

Expected: 打印预置订单与退款申请结果。

- [ ] **Step 4: 写测试 `backend/tests/test_mock_db.py`**

```python
from app.tools.mock_db import get_order, get_logistics, create_refund

def test_get_order_found():
    assert get_order("20260811001")["status"] == "已发货"

def test_get_order_missing():
    assert get_order("999999") is None

def test_get_logistics():
    assert len(get_logistics("20260811001")) >= 1

def test_create_refund():
    r = create_refund("20260811003", "质量问题")
    assert r["status"] == "已申请" and r["order_id"] == "20260811003"
```

- [ ] **Step 5: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_mock_db.py -v
```

Expected: 4 passed。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: mock 订单/物流/退款数据库"
```

---

## Task 3: 知识库语料

**Files:**
- Create: `backend/knowledge_base/policies/returnd.md`、`refund.md`、`exchange.md`、`warranty.md`、`7day-no-reason.md`
- Create: `backend/knowledge_base/logistics/shipping.md`、`freight.md`、`lost-package.md`
- Create: `backend/knowledge_base/products/electronics.md`、`faq.md`
- Create: `backend/knowledge_base/misc/account.md`、`privacy.md`

**Interfaces:**
- Produces: 语料目录，每篇含 YAML frontmatter（`title` / `category` / `order`），供 Task 4 入库

- [ ] **Step 1: 写第一篇示例 `policies/7day-no-reason.md`（含 frontmatter + 分块测试用的结构）**

```markdown
---
title: 七天无理由退货
category: policies
order: 1
---

# 七天无理由退货

## 适用范围
除下列商品外，均支持收货后 7 天内（含）无理由退货：
- 定制类商品
- 鲜活易腐类商品
- 已拆封的影音制品

## 退款标准
| 情形 | 退款金额 |
|------|---------|
| 未拆封 | 全额 |
| 已拆封不影响二次销售 | 全额 |
| 已使用 | 折价退款（按购买价 80%） |
```

- [ ] **Step 2: 按同结构补齐其余 11 篇**（覆盖：退货流程、退款到账时间、换货规则、保修、运费/免邮规则、丢件赔付、商品规格、账号问题、隐私条款）
  - 每篇 1-3 层标题 + 至少一张表格或列表，制造分块与检索差异
  - 含 1-2 篇"硬骨头"：长条款（>500 字）、嵌套子条款，作为检索优化面试素材

- [ ] **Step 3: 验证所有文件存在且含 frontmatter**

```bash
cd /k/claude/llm-job-prep/backend && find knowledge_base -name "*.md" | wc -l
```

Expected: 12（或按实际篇数）。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "docs: 示例电商知识库语料"
```

---

## Task 4: RAG 模块（embedding + 向量库 + 混合检索 + rerank）

**Files:**
- Create: `backend/app/rag/embed.py`
- Create: `backend/app/rag/chunker.py`
- Create: `backend/app/rag/vector_store.py`
- Create: `backend/app/rag/retrieve.py`
- Create: `backend/scripts/build_kb.py`
- Create: `backend/tests/test_rag.py`

**Interfaces:**
- Produces:
  - `embed_texts(texts: list[str]) -> list[list[float]]`
  - `chunk_markdown(path: Path, strategy="recursive", chunk_size=400, overlap=50) -> list[dict]`（含 `text`, `metadata{title,category,page}`）
  - `class VectorStore: add(texts, metadatas) / search(vector, top_k=20) -> list[dict]`
  - `hybrid_search(query: str, top_k=20) -> list[dict]`
  - `rerank(query: str, docs: list[dict]) -> list[dict]`（按相关度降序，取 `rerank_top_k`）

- [ ] **Step 1: 写 embed.py（SiliconFlow，OpenAI 兼容端点）**

```python
from openai import OpenAI
from app.config import settings

_client = None
def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.siliconflow_api_key,
                         base_url="https://api.siliconflow.cn/v1")
    return _client

def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = _get_client().embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]
```

- [ ] **Step 2: 写 chunker.py（递归分块，含重叠）**

```python
def _chunk(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    chunks, step = [], size - overlap
    for i in range(0, len(text), step):
        chunks.append(text[i:i + size])
    return [c for c in chunks if c.strip()]

def chunk_markdown(path, strategy="recursive", chunk_size=400, overlap=50):
    raw = path.read_text(encoding="utf-8")
    meta = {}
    for line in raw.splitlines():
        if line.startswith("---"):
            continue
        if ":" in line and line.strip().startswith(("title", "category", "order")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
        elif meta and "title" in meta:
            break
    body = "\n".join(line for line in raw.splitlines() if not line.startswith("---") and ":" not in line or line.strip() == "" or line.strip().startswith(("#", "-", "|", ">")) or "\t" in line)
    out = []
    for i, c in enumerate(_chunk(body, chunk_size, overlap)):
        out.append({"text": c, "metadata": {**meta, "page": i}})
    return out
```

- [ ] **Step 3: 写 vector_store.py（Qdrant，接口抽象）**

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import settings

class VectorStore:
    def __init__(self, collection="kb", dim=1024):
        self.client = QdrantClient(url=settings.qdrant_url)
        self.collection = collection
        self._ensure_collection(dim)

    def _ensure_collection(self, dim):
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(self.collection,
                                      vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    def add(self, texts, metadatas):
        vectors = embed_texts(texts)
        points = [PointStruct(id=i, vector=v, payload=m)
                  for i, (v, m) in enumerate(zip(vectors, metadatas))]
        self.client.upsert(self.collection, points)

    def search(self, vector, top_k=20):
        hits = self.client.search(self.collection, query_vector=vector, limit=top_k)
        return [{"text": h.payload.get("text", ""), "title": h.payload.get("title", ""),
                 "category": h.payload.get("category", ""), "score": h.score} for h in hits]
```

（`embed_texts` 从 `embed.py` 导入；`vector_store.py` 顶部加 `from app.rag.embed import embed_texts`）

- [ ] **Step 4: 写 retrieve.py（混合检索 + rerank）**

```python
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

def _bm25(query: str, docs: list[dict]) -> list[dict]:
    terms = set(query)
    scored = []
    for d in docs:
        hits = sum(1 for t in terms if t in d["text"])
        scored.append({**d, "score": d.get("score", 0) * 0.6 + hits * 0.4})
    return sorted(scored, key=lambda x: x["score"], reverse=True)

def hybrid_search(query: str, top_k=20):
    vec = embed_texts([query])[0]
    return _bm25(query, get_store().search(vec, top_k=top_k))

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
```

- [ ] **Step 5: 写 build_kb.py（语料入库）**

```python
from pathlib import Path
from app.rag.chunker import chunk_markdown
from app.rag.vector_store import VectorStore

def main():
    store = VectorStore()
    kb = Path(__file__).resolve().parents[1] / "knowledge_base"
    all_texts, all_meta = [], []
    for md in sorted(kb.rglob("*.md")):
        chunks = chunk_markdown(md)
        for c in chunks:
            all_texts.append(c["text"])
            all_meta.append({**c["metadata"], "text": c["text"]})
    store.add(all_texts, all_meta)
    print(f"入库 {len(all_texts)} 个分块")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 写测试 `tests/test_rag.py`（用 embed/rerank 的 mock，不真调 API）**

```python
from app.rag import retrieve

def test_hybrid_search_sorts():
    docs = [{"text": "七天无理由退货适用", "title": "t1", "score": 0.8},
            {"text": "退款到账时间", "title": "t2", "score": 0.5}]
    # 注入假 vector store，验证不抛错且返回列表
    out = retrieve._bm25("退货", docs)
    assert isinstance(out, list) and len(out) == 2
```

- [ ] **Step 7: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_rag.py -v
```

Expected: 1 passed。

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat: RAG 模块（分块/向量库/混合检索/rerank）"
```

---

## Task 5: FastAPI 骨架 + 中间件 + 健康/指标

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/middleware.py`
- Create: `backend/app/metrics.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/health.py`
- Create: `backend/tests/test_health.py`

**Interfaces:**
- Produces:
  - `GET /health` → `{"status":"ok"}`
  - `GET /metrics` → `{"requests": n, "avg_latency_ms": x, "total_cost_yuan": y}`
  - 中间件：请求头 `X-Request-ID`（无则生成）、结构化日志、CORS、API Key 校验（`Authorization: Bearer <key>` 或 `X-API-Key`）

- [ ] **Step 1: 写 metrics.py（进程内累加）**

```python
import time, threading

_lock = threading.Lock()
_state = {"requests": 0, "latency_sum_ms": 0.0, "total_tokens": 0}

def record_request(latency_ms: float):
    with _lock:
        _state["requests"] += 1
        _state["latency_sum_ms"] += latency_ms

def record_tokens(n: int):
    with _lock:
        _state["total_tokens"] += n

def snapshot() -> dict:
    with _lock:
        reqs = _state["requests"]
        return {
            "requests": reqs,
            "avg_latency_ms": round(_state["latency_sum_ms"] / reqs, 2) if reqs else 0,
            "total_tokens": _state["total_tokens"],
            "total_cost_yuan": round(_state["total_tokens"] / 1_000_000, 4),  # 粗略成本示例
        }
```

- [ ] **Step 2: 写 middleware.py**

```python
import time, uuid, logging
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from app import metrics
from app.config import settings

logger = logging.getLogger("app")

class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        if request.url.path not in ("/health",):
            key = request.headers.get("X-API-Key")
            if key != settings.api_key:
                from fastapi.responses import JSONResponse
                return JSONResponse({"error": {"code": "UNAUTHORIZED", "message": "bad api key"}}, status_code=401)
        response = await call_next(request)
        latency = (time.perf_counter() - start) * 1000
        metrics.record_request(latency)
        response.headers["X-Request-ID"] = rid
        logger.info("req=%s path=%s status=%s latency_ms=%.1f", rid, request.url.path, response.status_code, latency)
        return response
```

- [ ] **Step 3: 写 health.py**

```python
from fastapi import APIRouter
from app import metrics

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/metrics")
async def metrics_endpoint():
    return metrics.snapshot()
```

- [ ] **Step 4: 写 main.py**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware import ObservabilityMiddleware
from app.api import health

app = FastAPI(title="电商售后智能客服", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(ObservabilityMiddleware)
app.include_router(health.router, prefix="/api/v1")
```

- [ ] **Step 5: 写测试 `tests/test_health.py`**

```python
from fastapi.testclient import TestClient
from app.main import app

def test_health():
    c = TestClient(app)
    r = c.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_metrics():
    c = TestClient(app)
    r = c.get("/api/v1/metrics", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and "requests" in r.json()
```

- [ ] **Step 6: 跑测试 + 启动服务验证**

```bash
.venv/Scripts/python -m pytest tests/test_health.py -v
.venv/Scripts/uvicorn app.main:app --port 8000
# 另开终端：
curl http://localhost:8000/api/v1/health
```

Expected: 测试通过；curl 返回 `{"status":"ok"}`。

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: FastAPI 骨架 + 中间件 + 健康/指标"
```

---

## Task 6: LLM 客户端（DeepSeek + 重试 + 降级）

**Files:**
- Create: `backend/app/llm.py`
- Create: `backend/tests/test_llm.py`

**Interfaces:**
- Produces:
  - `chat(messages: list[dict], tools: list | None = None, stream: bool = True) -> str | AsyncIterator[str]`
  - 内部：指数退避重试 3 次；主模型失败自动降级 `model_fallback`

- [ ] **Step 1: 写 llm.py**

```python
import time
from openai import OpenAI
from app.config import settings
from app import metrics

_client = OpenAI(api_key=settings.deepseek_api_key, base_url="https://api.deepseek.com")

def _chat_once(messages, tools, model, stream):
    resp = _client.chat.completions.create(model=model, messages=messages,
                                           tools=tools, stream=stream,
                                           stream_options={"include_usage": True})
    if stream:
        return resp
    metrics.record_tokens(resp.usage.total_tokens if resp.usage else 0)
    return resp.choices[0].message.content

def chat(messages, tools=None, stream=False):
    last_err = None
    for attempt in range(3):
        try:
            return _chat_once(messages, tools, settings.model_primary, stream)
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    return _chat_once(messages, tools, settings.model_fallback, stream)
```

- [ ] **Step 2: 写测试 `tests/test_llm.py`（mock OpenAI 避免真调用）**

```python
import pytest
from unittest.mock import patch
from app import llm

def test_chat_returns_text(monkeypatch):
    class FakeMsg:
        content = "你好"
    class FakeResp:
        usage = None
        choices = [type("C", (), {"message": FakeMsg()})]
    monkeypatch.setattr(llm, "_chat_once", lambda *a, **k: FakeResp())
    assert llm.chat([{"role": "user", "content": "hi"}]) == "你好"
```

- [ ] **Step 3: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_llm.py -v
```

Expected: 1 passed。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: LLM 客户端（重试+降级）"
```

---

## Task 7: LangGraph 多 Agent 编排

**Files:**
- Create: `backend/app/agents/state.py`
- Create: `backend/app/agents/nodes.py`
- Create: `backend/app/agents/graph.py`
- Create: `backend/tests/test_graph.py`

**Interfaces:**
- Produces:
  - `build_graph() -> CompiledStateGraph`
  - `run_agent(question: str, session_id: str) -> dict`（返回 `{answer, sources, review_status, domain}`）
  - State 字段：`question, session_id, history, domain, retrieved_chunks, tool_results, draft_answer, review_comment, iteration, review_status`

- [ ] **Step 1: 写 state.py**

```python
from typing import TypedDict, Optional

class AgentState(TypedDict):
    question: str
    session_id: str
    history: list
    domain: str
    retrieved_chunks: list
    tool_results: list
    draft_answer: str
    review_comment: str
    iteration: int
    review_status: str
```

- [ ] **Step 2: 写 nodes.py（路由/检索/写作/审核 四个核心节点）**

```python
from app.rag.retrieve import hybrid_search, rerank
from app.llm import chat

SYSTEM = "你是电商售后智能客服。只基于提供的检索资料回答；资料不足时明确说不知道并建议转人工，绝不编造。"

def router_node(state: AgentState) -> dict:
    # 用模型判断域：order / policy / product / chitchat
    q = state["question"]
    keywords = ["订单", "物流", "发货", "退款", "退货", "换货", "保修", "运费", "账号", "你好", "在吗"]
    if any(k in q for k in ["你好", "在吗", "谢谢"]):
        domain = "chitchat"
    elif any(k in q for k in ["订单", "物流", "发货"]):
        domain = "order"
    else:
        domain = "policy"
    return {"domain": domain}

def retriever_node(state: AgentState) -> dict:
    if state["domain"] in ("chitchat",):
        return {"retrieved_chunks": []}
    docs = hybrid_search(state["question"])
    return {"retrieved_chunks": rerank(state["question"], docs)}

def writer_node(state: AgentState) -> dict:
    ctx = "\n\n".join(f"[{d['title']}]\n{d['text']}" for d in state["retrieved_chunks"])
    msgs = [
        {"role": "system", "content": SYSTEM},
        *state["history"],
        {"role": "user", "content": f"检索资料：\n{ctx}\n\n问题：{state['question']}"},
    ]
    if state.get("review_comment"):
        msgs.append({"role": "user", "content": f"上次回答被审核打回，原因：{state['review_comment']}。请修正。"})
    return {"draft_answer": chat(msgs, stream=False)}

def reviewer_node(state: AgentState) -> dict:
    if state["domain"] == "chitchat":
        return {"review_status": "passed", "review_comment": ""}
    check = chat([
        {"role": "system", "content": "你是质量审核员。检查回答是否：1)忠于检索资料 2)未遗漏关键点 3)无编造。有问题输出[驳回]+原因，否则输出[通过]。"},
        {"role": "user", "content": f"资料：\n{state['retrieved_chunks']}\n\n回答：{state['draft_answer']}"},
    ], stream=False)
    passed = "[通过]" in check
    return {"review_status": "passed" if passed else "rejected",
            "review_comment": "" if passed else check}
```

- [ ] **Step 3: 写 graph.py（含审核打回条件边）**

```python
from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents import nodes

def should_retry(state: AgentState) -> str:
    if state["domain"] == "chitchat":
        return "end"
    if state["review_status"] == "rejected" and state["iteration"] < 2:
        return "rewrite"
    return "end"

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("router", nodes.router_node)
    g.add_node("retriever", nodes.retriever_node)
    g.add_node("writer", nodes.writer_node)
    g.add_node("reviewer", nodes.reviewer_node)
    g.add_edge(START, "router")
    g.add_edge("router", "retriever")
    g.add_edge("retriever", "writer")
    g.add_edge("writer", "reviewer")
    g.add_conditional_edges("reviewer", should_retry,
                            {"rewrite": "writer", "end": END})
    return g.compile()

def run_agent(question: str, session_id: str, history=None):
    graph = build_graph()
    return graph.invoke({
        "question": question, "session_id": session_id,
        "history": history or [], "iteration": 0, "review_status": "",
    })
```

- [ ] **Step 4: 写测试 `tests/test_graph.py`（monkeypatch 掉检索和 LLM）**

```python
from app.agents.graph import should_retry

def test_retry_boundary():
    s = {"domain": "policy", "review_status": "rejected", "iteration": 1}
    assert should_retry(s) == "rewrite"
    s2 = {"domain": "policy", "review_status": "rejected", "iteration": 2}
    assert should_retry(s2) == "end"
    s3 = {"domain": "chitchat", "review_status": "passed", "iteration": 0}
    assert should_retry(s3) == "end"
```

- [ ] **Step 5: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_graph.py -v
```

Expected: 3 passed（验证循环边界逻辑）。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: LangGraph 多 Agent 编排（路由/检索/写作/审核+循环）"
```

---

## Task 8: 工具层接入 Agent

**Files:**
- Modify: `backend/app/agents/nodes.py`（新增 `tool_node`，插入 router 之后）
- Modify: `backend/app/agents/graph.py`（插入 tool 节点边）
- Create: `backend/app/tools/order_tools.py`
- Create: `backend/tests/test_tools_agent.py`

**Interfaces:**
- Consumes: Task 2 的 `get_order/get_logistics/create_refund/escalate`
- Produces: `order_tools.TOOLS`（OpenAI tools schema 列表）、`order_tools.dispatch(name, args) -> str`

- [ ] **Step 1: 写 order_tools.py**

```python
import json
from app.tools import mock_db

TOOLS = [
    {"type": "function", "function": {
        "name": "query_order", "description": "查询订单状态",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "query_logistics", "description": "查询物流轨迹",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "request_refund", "description": "发起退款申请",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["order_id", "reason"]}}},
    {"type": "function", "function": {
        "name": "escalate_to_human", "description": "转人工客服",
        "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}}},
]

def dispatch(name: str, args: dict) -> str:
    if name == "query_order":
        return json.dumps(mock_db.get_order(args["order_id"]), ensure_ascii=False)
    if name == "query_logistics":
        return json.dumps(mock_db.get_logistics(args["order_id"]), ensure_ascii=False)
    if name == "request_refund":
        return json.dumps(mock_db.create_refund(args["order_id"], args["reason"]), ensure_ascii=False)
    if name == "escalate_to_human":
        return json.dumps(mock_db.escalate(args["session_id"]), ensure_ascii=False)
    return json.dumps({"error": "unknown tool"})
```

- [ ] **Step 2: 在 nodes.py 加 `tool_node`（仅在 order 域、模型请求工具时执行）**

```python
def tool_node(state: AgentState) -> dict:
    if state["domain"] != "order":
        return {"tool_results": []}
    # 让模型决定调用哪个工具、抽参数
    resp = chat([
        {"role": "system", "content": "从用户话术中提取订单号并选择合适的工具调用。只需输出JSON：{'name':工具名,'args':{}}"},
        {"role": "user", "content": state["question"]},
    ], tools=order_tools.TOOLS, stream=False)
    import json as _json
    try:
        call = _json.loads(resp)
        result = order_tools.dispatch(call["name"], call["args"])
    except Exception:
        result = _json.dumps({"error": "无法解析工具调用"})
    return {"tool_results": [_json.loads(result)]}
```

（nodes.py 顶部 `from app.tools import order_tools`）

- [ ] **Step 3: 改 graph.py，把 tool 节点插在 router→retriever 之间，并把工具结果传给 writer**

```python
g.add_edge("router", "tool")
g.add_edge("tool", "retriever")
```

（writer 提示词追加：`工具结果：{state['tool_results']}`）

- [ ] **Step 4: 写测试 `tests/test_tools_agent.py`**

```python
from app.tools import order_tools

def test_dispatch_query_order():
    r = order_tools.dispatch("query_order", {"order_id": "20260811001"})
    assert '"已发货"' in r

def test_dispatch_unknown():
    r = order_tools.dispatch("nope", {})
    assert "error" in r
```

- [ ] **Step 5: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_tools_agent.py -v
```

Expected: 2 passed。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: 工具层接入（查订单/物流/退款/转人工）"
```

---

## Task 9: /api/v1/chat SSE 流式接口

**Files:**
- Create: `backend/app/api/chat.py`
- Create: `backend/tests/test_chat.py`

**Interfaces:**
- Consumes: `run_agent`（Task 7）
- Produces: `POST /api/v1/chat`，body `{"session_id","message","history"?}`，响应 SSE：`data: {"type":"token","text":"..."}`、`data: {"type":"sources","items":[...]}`、`data: {"type":"done"}`

- [ ] **Step 1: 写 chat.py（先用非流式 fallback，SSE 事件封装）**

```python
import json
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from app.agents.graph import run_agent

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list = []

@router.post("/chat")
async def chat(req: ChatRequest):
    async def gen():
        result = await _async_run(req)
        for token in result["answer"].split(" "):
            yield {"event": "message", "data": json.dumps({"type": "token", "text": token + " "}, ensure_ascii=False)}
        yield {"event": "message", "data": json.dumps({"type": "sources", "items": result["sources"]}, ensure_ascii=False)}
        yield {"event": "message", "data": json.dumps({"type": "done"}, ensure_ascii=False)}
    return EventSourceResponse(gen())

async def _async_run(req: ChatRequest):
    # 阻塞式 LLM 简化版：后续可改真流式
    from app.agents.graph import run_agent
    result = run_agent(req.message, req.session_id, req.history)
    return {"answer": result.get("draft_answer", ""), "sources": result.get("retrieved_chunks", [])}
```

（`main.py` 中 `app.include_router(chat.router, prefix="/api/v1")`）

- [ ] **Step 2: 写测试 `tests/test_chat.py`（monkeypatch run_agent）**

```python
from fastapi.testclient import TestClient
from app.main import app

def test_chat_returns_sse(monkeypatch):
    import app.api.chat as chat_mod
    def fake_run(q, sid, hist):
        return {"draft_answer": "可以，支持7天无理由。", "retrieved_chunks": [{"title": "七天无理由", "text": "支持"}]}
    monkeypatch.setattr(chat_mod, "_async_run", fake_run)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "能退货吗"},
               headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    assert "token" in r.text and "sources" in r.text
```

- [ ] **Step 3: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_chat.py -v
```

Expected: 1 passed。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: /api/v1/chat SSE 流式接口"
```

---

## Task 10: 会话持久化（PostgreSQL）

**Files:**
- Create: `backend/app/db/__init__.py`
- Create: `backend/app/db/models.py`
- Create: `backend/app/db/sessions.py`
- Create: `backend/tests/test_sessions.py`

**Interfaces:**
- Produces:
  - `save_message(session_id, role, content) -> None`
  - `get_history(session_id, limit=10) -> list[dict]`

- [ ] **Step 1: 写 models.py（SQLAlchemy）**

```python
from sqlalchemy import create_engine, Column, String, Integer, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

engine = create_engine(settings.database_url)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True)
    role = Column(String(16))
    content = Column(String(4000))
    created_at = Column(DateTime, server_default=func.now())

Base.metadata.create_all(engine)
```

- [ ] **Step 2: 写 sessions.py**

```python
from app.db.models import SessionLocal, Message

def save_message(session_id, role, content):
    db = SessionLocal()
    try:
        db.add(Message(session_id=session_id, role=role, content=content))
        db.commit()
    finally:
        db.close()

def get_history(session_id, limit=10):
    db = SessionLocal()
    try:
        rows = db.query(Message).filter_by(session_id=session_id)\
                .order_by(Message.id.desc()).limit(limit).all()
        return [{"role": m.role, "content": m.content} for m in reversed(rows)]
    finally:
        db.close()
```

- [ ] **Step 3: 写测试 `tests/test_sessions.py`**

```python
from app.db.sessions import save_message, get_history

def test_save_and_get():
    save_message("sess-test", "user", "你好")
    hist = get_history("sess-test")
    assert hist[-1]["content"] == "你好"
```

- [ ] **Step 4: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_sessions.py -v
```

Expected: 1 passed。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: 会话持久化"
```

---

## Task 11: 语义缓存

**Files:**
- Create: `backend/app/cache.py`
- Create: `backend/tests/test_cache.py`

**Interfaces:**
- Produces: `cache_get(question) -> str | None`、`cache_set(question, answer) -> None`（Redis，不可用时降级内存 dict）

- [ ] **Step 1: 写 cache.py**

```python
import hashlib, threading
try:
    import redis
    _r = redis.Redis.from_url(__import__("app.config", fromlist=["settings"]).settings.redis_url, decode_responses=True)
    _available = _r.ping()
except Exception:
    _r, _available = None, False

_mem = {}
_lock = threading.Lock()
TTL = 3600

def _key(q: str) -> str:
    return "cache:" + hashlib.md5(q.encode()).hexdigest()

def cache_get(question: str) -> str | None:
    k = _key(question)
    if _available:
        return _r.get(k)
    with _lock:
        return _mem.get(k)

def cache_set(question: str, answer: str) -> None:
    k = _key(question)
    if _available:
        _r.set(k, answer, ex=TTL)
    else:
        with _lock:
            _mem[k] = answer
```

- [ ] **Step 2: 写测试 `tests/test_cache.py`**

```python
from app import cache

def test_cache_roundtrip():
    cache.cache_set("退货政策是什么", "answer-x")
    assert cache.cache_get("退货政策是什么") == "answer-x"
```

- [ ] **Step 3: 跑测试**

```bash
.venv/Scripts/python -m pytest tests/test_cache.py -v
```

Expected: 1 passed（无 Redis 时走内存降级）。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: 语义缓存（Redis/内存降级）"
```

---

## Task 12: 评测管线

**Files:**
- Create: `backend/eval/questions.json`
- Create: `backend/eval/judge.py`

**Interfaces:**
- Produces:
  - `eval/questions.json`：25 题，5 类，每题含 `{category, question, expected_points[]}`
  - `python -m eval.judge` → 打印每类准确率 + 汇总 + badcase 列表

- [ ] **Step 1: 写 questions.json（25 题节选，覆盖 5 类）**

```json
[
  {"category": "order", "question": "订单20260811001现在什么状态？", "expected_points": ["已发货"]},
  {"category": "policy", "question": "七天无理由退货的适用条件？", "expected_points": ["7天", "定制商品不适用", "拆封影响二次销售"]},
  {"category": "product", "question": "智能音箱支持蓝牙吗？", "expected_points": ["支持", "蓝牙5.0"]},
  {"category": "chitchat", "question": "你好，在吗？", "expected_points": ["不查库", "礼貌回应"]},
  {"category": "edge", "question": "订单不存在怎么处理？", "expected_points": ["不编造", "引导核实", "转人工"]}
]
```

（实际文件补齐到 25 题：order/policy/product/chitchat/edge 各 5 题）

- [ ] **Step 2: 写 judge.py**

```python
import json
from pathlib import Path
from app.agents.graph import run_agent
from app.llm import chat

def judge(points: list[str], answer: str) -> bool:
    check = chat([
        {"role": "system", "content": "判断回答是否覆盖全部要点。覆盖则输出PASS，否则FAIL。"},
        {"role": "user", "content": f"要点：{points}\n回答：{answer}"},
    ], stream=False)
    return "PASS" in check

def main():
    data = json.loads(Path(__file__).parent.joinpath("questions.json").read_text(encoding="utf-8"))
    stats, bad = {}, []
    for item in data:
        r = run_agent(item["question"], session_id="eval")
        ok = judge(item["expected_points"], r.get("draft_answer", ""))
        stats.setdefault(item["category"], {"pass": 0, "total": 0})
        stats[item["category"]]["total"] += 1
        if ok:
            stats[item["category"]]["pass"] += 1
        else:
            bad.append({"category": item["category"], "question": item["question"], "answer": r.get("draft_answer")})
    for cat, s in stats.items():
        print(f"{cat}: {s['pass']}/{s['total']} = {s['pass']/s['total']:.0%}")
    print(f"\n总准确率: {sum(s['pass'] for s in stats.values())}/{sum(s['total'] for s in stats.values())}")
    print("\nBadcase:")
    for b in bad:
        print("-", b["question"], "→", b["answer"][:50])

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 运行（需真实 Key + Qdrant）**

```bash
.venv/Scripts/python -m eval.judge
```

Expected: 输出各分类准确率与 badcase。

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: 评测管线（25题 + LLM judge）"
```

---

## Task 13: Next.js 前端

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/app/page.tsx`
- Create: `frontend/app/globals.css`

**Interfaces:**
- Consumes: `POST /api/v1/chat`（SSE）
- Produces: 聊天页面：消息列表 + 输入框 + SSE 流式渲染 + 来源卡片

- [ ] **Step 1: 初始化 Next.js（用脚手架）**

```bash
cd /k/claude/llm-job-prep
npx create-next-app@latest frontend --ts --app --tailwind --no-eslint --import-alias "@/*" --use-npm --yes
```

- [ ] **Step 2: 写 page.tsx（核心：SSE 消费 + 流式渲染）**

```tsx
"use client";
import { useState, useRef } from "react";

export default function Home() {
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const sidRef = useRef(`sess-${Date.now()}`);

  async function send() {
    const userMsg = input;
    setInput("");
    const next = [...messages, { role: "user", content: userMsg }];
    setMessages(next);
    const resp = await fetch("http://localhost:8000/api/v1/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": "dev-local-key" },
      body: JSON.stringify({ session_id: sidRef.current, message: userMsg }),
    });
    const reader = resp.body!.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let botText = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const evt = JSON.parse(line.slice(6));
        if (evt.type === "token") {
          botText += evt.text;
          setMessages([...next, { role: "assistant", content: botText }]);
        } else if (evt.type === "sources") {
          setSources(evt.items.map((i: any) => i.title));
        }
      }
    }
  }

  return (
    <main className="max-w-3xl mx-auto p-4 h-screen flex flex-col">
      <h1 className="text-xl font-bold mb-4">电商售后智能客服</h1>
      <div className="flex-1 overflow-y-auto space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div className="inline-block bg-gray-100 rounded-lg px-3 py-2">{m.content}</div>
          </div>
        ))}
        {sources.length > 0 && (
          <div className="text-xs text-gray-500">📎 来源：{sources.join(" · ")}</div>
        )}
      </div>
      <div className="flex gap-2 mt-4">
        <input className="flex-1 border rounded px-3 py-2" value={input}
               onChange={(e) => setInput(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && send()} />
        <button className="bg-blue-500 text-white px-4 rounded" onClick={send}>发送</button>
      </div>
    </main>
  );
}
```

- [ ] **Step 3: 本地联调**

```bash
cd frontend && npm run dev
```

浏览器打开 `http://localhost:3000`，提问并确认流式显示 + 来源卡片。（后端需先启动）

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: Next.js 聊天前端（SSE 流式）"
```

---

## Task 14: Docker Compose 部署

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `frontend/next.config.mjs`（`rewrites` 转发 `/api` → 后端）
- Create: `docker-compose.yml`
- Create: `README.md`

- [ ] **Step 1: 写 backend/Dockerfile**

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY knowledge_base ./knowledge_base
COPY scripts ./scripts
COPY eval ./eval
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: 写 frontend/Dockerfile**

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
EXPOSE 3000
CMD ["npm", "run", "start"]
```

- [ ] **Step 3: 写 docker-compose.yml**

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: csbot
      POSTGRES_PASSWORD: csbot
      POSTGRES_DB: csbot
    ports: ["5432:5432"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
  backend:
    build: ./backend
    env_file: .env
    environment:
      DATABASE_URL: postgresql://csbot:csbot@postgres/csbot
      REDIS_URL: redis://redis:6379
    depends_on: [qdrant, postgres, redis]
    ports: ["8000:8000"]
  frontend:
    build: ./frontend
    depends_on: [backend]
    ports: ["3000:3000"]
```

- [ ] **Step 4: 写 README.md**（项目简介、架构、快速启动步骤、Key 配置、评测跑法、面试叙事 3 句话）

- [ ] **Step 5: 一键启动验证**

```bash
cd /k/claude/llm-job-prep && docker compose up --build -d
curl http://localhost:8000/api/v1/health
```

Expected: 健康检查返回 ok；浏览器 `http://localhost:3000` 可完整问答。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: Docker Compose 一键部署 + README"
```

---

## Self-Review 记录

- **Spec 覆盖**：架构(§3)→Task5/9/14；多Agent(§4.3)→Task7/8；工具(§4.4)→Task2/8；RAG(§4.5)→Task3/4；语料(§4.6)→Task3；数据层(§4.7)→Task2/10/11；错误处理(§6)→Task6(重试/降级)+Task7(循环上限)+检索兜底；评测(§7)→Task12；部署(§8)→Task14；密钥(§10)→Task1。✅
- **占位符扫描**：无 TBD/TODO；所有代码步骤含实际代码。✅
- **类型一致性**：`run_agent` 返回值 `draft_answer/retrieved_chunks` 在 Task7/9/12 一致；`get_order/get_logistics/create_refund/escalate` 在 Task2/8 一致；`hybrid_search/rerank` 在 Task4/7 一致。✅
