# 知识库治理与回填闭环实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ① `knowledge_base/` 成为 Obsidian 可管理的知识库（热重索引 + 文档列表）；② 打通「无法解决 → 转人工 → 人工回答 → 沉淀草稿 → 审核发布 → RAG 摄入 → 下次命中」闭环；③ 评分 5 星自动生成草稿候选（自增长知识库）。

**Architecture:** 审核 gate 控制 RAG 摄入（草稿不进检索，approve 后摄入）。稳定 ID 修复（内容寻址 `md5(path:page)`）使增量摄入幂等；`invalidate_bm25()` 刷新整库 BM25。SSE 新增 `human_handoff` 事件驱动前端转人工弹窗。消息表加 `meta` 列记录每轮 domain/had_tools/cached，供自动沉淀判定。

**Tech Stack:** Python 3.13 / FastAPI / Qdrant / rank_bm25 / jieba / deepseek-chat / Next.js 16 / Vitest

**分支:** 从 `main` 开 `feature/task-16-kb-backfill`

## Global Constraints

- TDD 红→绿循环，每任务最后提交
- 后端测试命令：`cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`
- 前端测试：`cd frontend && npm test`；build：`cd frontend && npm run build`
- **草稿（`status: draft`）不进**检索/BM25 语料/索引；approve 后才摄入
- `doc_id` = 文件名（不带目录），approve 必须做路径穿越防护
- 向量 ID = `md5(f"{path}:{page}") % 2**64`（稳定内容寻址，压回 Qdrant u64 点 id 范围）
- SSE 事件类型保持前端兼容：新增 `human_handoff`，其余 `thinking / token / card / sources / error / done` 不变
- **改前端前**先读 `frontend/node_modules/next/dist/docs/` 相关指南（Next.js 16 有破坏性变更；本计划的前端改动全部沿用现有文件风格）
- 自动沉淀失败**静默**（不影响评分闭环）；LLM 提炼失败**回退模板**（沉淀流程绝不中断）

---

### Task 1: chunker 带 path 元数据 + 草稿过滤

**Files:**
- Modify: `backend/app/rag/chunker.py`
- Modify: `backend/app/rag/retrieve.py`
- Modify: `backend/scripts/build_kb.py`
- Test: `backend/tests/test_chunker.py`（追加）、`backend/tests/test_rag.py`（追加）

**Interfaces:**
- Produces: `read_frontmatter(path: Path) -> dict`、`is_draft(path: Path) -> bool`（chunker 导出）
- Produces: `chunk_markdown()` 每个 chunk 的 `metadata` 含 `path`（绝对路径字符串）
- Produces: `retrieve._load_corpus()` 跳过草稿；`retrieve._KB_ROOT` 可被测试 monkeypatch

- [ ] **Step 1: 写失败测试**

`backend/tests/test_chunker.py` 追加:
```python
def test_chunk_metadata_includes_path(tmp_path):
    md = _write(tmp_path, "a.md", "# 标题\n\n正文。")
    chunks = chunk_markdown(md)
    assert chunks[0]["metadata"]["path"] == str(md)


def test_read_frontmatter_and_is_draft(tmp_path):
    d = _write(tmp_path, "d.md", "---\ntitle: x\nstatus: draft\n---\n\n正文")
    p = _write(tmp_path, "p.md", "---\ntitle: x\nstatus: published\n---\n\n正文")
    assert read_frontmatter(d)["status"] == "draft"
    assert is_draft(d) is True
    assert is_draft(p) is False
```
（`_write` 辅助函数已存在于 test_chunker.py。）

`backend/tests/test_rag.py` 追加:
```python
def test_load_corpus_skips_drafts(monkeypatch, tmp_path):
    import app.rag.retrieve as r
    (tmp_path / "a.md").write_text("---\nstatus: draft\n---\n\n草稿内容。", encoding="utf-8")
    (tmp_path / "b.md").write_text("---\nstatus: published\n---\n\n正式内容。", encoding="utf-8")
    monkeypatch.setattr(r, "_KB_ROOT", tmp_path)
    texts = r._load_corpus()
    assert any("正式内容" in t for t in texts)
    assert not any("草稿内容" in t for t in texts)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_chunker.py tests/test_rag.py -q`
Expected: FAIL — `ImportError`（`read_frontmatter`/`is_draft` 未定义；metadata 无 path；`_KB_ROOT` 不存在）

- [ ] **Step 3: 实现**

`backend/app/rag/chunker.py` 追加（放 `_extract_frontmatter` 之后）:
```python
def read_frontmatter(path: Path) -> dict:
    """读取 md 的 YAML frontmatter 元数据（轻量，供列表/过滤用）。"""
    meta, _ = _extract_frontmatter(path.read_text(encoding="utf-8"))
    return meta


def is_draft(path: Path) -> bool:
    """frontmatter status == draft 视为草稿（不进检索/语料/索引）。"""
    return read_frontmatter(path).get("status") == "draft"
```

`backend/app/rag/chunker.py` 的 `chunk_markdown` 返回值改为携带 path:
```python
    return [{"text": c, "metadata": {**meta, "path": str(path), "page": i}} for i, c in enumerate(chunks)]
```

`backend/app/rag/retrieve.py` 顶部加模块级 KB 根并让 `_load_corpus` 用它 + 跳草稿:
```python
_KB_ROOT = Path(__file__).resolve().parents[2] / "knowledge_base"

def _load_corpus() -> list[str]:
    """与 build_kb 同源同序读取 knowledge_base，返回全部分块文本（BM25 语料）。草稿跳过。"""
    texts = []
    for md in sorted(_KB_ROOT.rglob("*.md")):
        if is_draft(md):
            continue
        for c in chunk_markdown(md):
            texts.append(c["text"])
    return texts
```
（`retrieve.py` 的 import 增加 `is_draft`；删除原来 `_load_corpus` 里的 `kb = ...` 行。）

`backend/scripts/build_kb.py` 的 `main()` 循环加草稿跳过:
```python
    for md in sorted(kb.rglob("*.md")):
        if is_draft(md):
            continue
        for c in chunk_markdown(md):
            all_texts.append(c["text"])
            all_meta.append({**c["metadata"], "text": c["text"]})
```
（`build_kb.py` 的 import 加 `from app.rag.chunker import chunk_markdown, is_draft`。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_chunker.py tests/test_rag.py -q`
Expected: PASS（既有 + 3 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/chunker.py backend/app/rag/retrieve.py \
        backend/scripts/build_kb.py backend/tests/test_chunker.py backend/tests/test_rag.py
git commit -m "feat: chunker 带 path 元数据 + 草稿过滤（read_frontmatter/is_draft）"
```

---

### Task 2: VectorStore 稳定内容寻址 ID

**Files:**
- Modify: `backend/app/rag/vector_store.py`
- Test: `backend/tests/test_vector_store.py`（追加）

**Interfaces:**
- Produces: `VectorStore.add(texts, metadatas)` 以 `md5(f"{metadata['path']}:{metadata['page']}")` 为 Point id（同 path+page 重入幂等）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_vector_store.py` 追加:
```python
class _FakeUpsertClient:
    def __init__(self):
        self.points = []

    def upsert(self, collection, points):
        self.points = points


def test_add_uses_stable_content_addressed_ids(monkeypatch):
    from app.rag.vector_store import VectorStore
    store = VectorStore.__new__(VectorStore)
    store.collection = "kb"
    store.client = _FakeUpsertClient()
    monkeypatch.setattr("app.rag.vector_store.embed_texts", lambda texts: [[0.1] * 4 for _ in texts])
    meta1 = [{"path": "backfill/20260814-a.md", "page": 0, "text": "x"},
             {"path": "backfill/20260814-a.md", "page": 1, "text": "y"}]
    meta2 = [{"path": "backfill/20260814-a.md", "page": 0, "text": "x"},
             {"path": "backfill/20260814-b.md", "page": 0, "text": "z"}]
    store.add(["x", "y"], meta1)
    ids1 = [p.id for p in store.client.points]
    store.add(["x", "z"], meta2)
    ids2 = [p.id for p in store.client.points]
    assert ids1[0] == ids2[0], "同 path+page 重入必须同 id（幂等覆盖）"
    assert ids1[1] != ids2[1], "不同 path 的 id 必须不同"
    assert ids1[0] != ids1[1], "同文件不同 page 的 id 必须不同"
    for p in ids1 + ids2:
        assert 0 <= p < 2**64, "Qdrant 点 id 必须落在 u64 范围"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_vector_store.py::test_add_uses_stable_content_addressed_ids -q`
Expected: FAIL — 旧实现 `add()` 用 `enumerate` 给 id，第二次 `add(["x","z"], meta2)` 的 ids 是 `[0,1]`；断言 `ids1[1] != ids2[1]`（不同 path 必须不同 id）在 `1 != 1` 处失败（旧实现不同 path 也得到 id 1）。

- [ ] **Step 3: 实现**

`backend/app/rag/vector_store.py` 顶部加 `import hashlib`，`add()` 改为稳定 ID（**md5 128-bit 取模压回 Qdrant u64 点 id 范围**）:
```python
    def add(self, texts: list[str], metadatas: list[dict]):
        vectors = embed_texts(texts)
        points = []
        for i, (v, m) in enumerate(zip(vectors, metadatas)):
            digest = hashlib.md5(f"{m.get('path', '')}:{m.get('page', i)}".encode()).hexdigest()
            stable = int(digest, 16) % (2**64)  # 128-bit md5 取模压回 u64
            points.append(PointStruct(id=stable, vector=v, payload=m))
        self.client.upsert(self.collection, points)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_vector_store.py -q`
Expected: PASS（3 既有 + 1 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/vector_store.py backend/tests/test_vector_store.py
git commit -m "feat: 向量库稳定内容寻址 ID（md5 path:page，增量幂等）"
```

---

### Task 3: invalidate_bm25

**Files:**
- Modify: `backend/app/rag/retrieve.py`
- Test: `backend/tests/test_rag.py`（追加）

**Interfaces:**
- Produces: `retrieve.invalidate_bm25() -> None`（置空缓存，下次 `_get_bm25` 懒重建）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_rag.py` 追加:
```python
def test_invalidate_bm25_resets_cache(monkeypatch, tmp_path):
    import app.rag.retrieve as r
    (tmp_path / "a.md").write_text("正式内容若干。", encoding="utf-8")
    monkeypatch.setattr(r, "_KB_ROOT", tmp_path)
    monkeypatch.setattr(r, "_tokenize", lambda t: [t])
    r._bm25 = ("built", {})  # 模拟已构建
    r.invalidate_bm25()
    assert r._bm25 is None
    bm25 = r._get_bm25()
    assert bm25 is not None  # 懒重建成功
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_rag.py::test_invalidate_bm25_resets_cache -q`
Expected: FAIL — `AttributeError: module has no attribute 'invalidate_bm25'`

- [ ] **Step 3: 实现**

`backend/app/rag/retrieve.py` 追加:
```python
def invalidate_bm25() -> None:
    """语料变化后调用：置空缓存，下次 _get_bm25 懒重建（回填发布/重索引后刷新）。"""
    global _bm25
    _bm25 = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_rag.py -q`
Expected: PASS（既有 + 1 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app/rag/retrieve.py backend/tests/test_rag.py
git commit -m "feat: invalidate_bm25 缓存失效（语料变化后懒重建）"
```

---

### Task 4: Message.meta 列 + save_message meta + get_last_round

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/sessions.py`
- Test: `backend/tests/test_sessions.py`（追加）

**Interfaces:**
- Produces: `save_message(session_id, role, content, meta: dict | None = None) -> None`（meta 存 JSON 字符串）
- Produces: `get_last_round(session_id) -> dict | None`，返回 `{"question", "answer", "meta"}`（最近一轮 user→assistant）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_sessions.py` 追加:
```python
def test_save_message_with_meta_and_get_last_round():
    from app.db.sessions import save_message, get_last_round
    sid = "s-meta-test"
    save_message(sid, "user", "怎么开电子发票")
    save_message(sid, "assistant", "请提供抬头", {"domain": "policy", "had_tools": False, "cached": False})
    round_ = get_last_round(sid)
    assert round_ == {"question": "怎么开电子发票", "answer": "请提供抬头",
                      "meta": {"domain": "policy", "had_tools": False, "cached": False}}


def test_get_last_round_returns_none_without_pair():
    from app.db.sessions import save_message, get_last_round
    sid = "s-meta-none"
    save_message(sid, "user", "只有问题")
    assert get_last_round(sid) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_sessions.py::test_save_message_with_meta_and_get_last_round -q`
Expected: FAIL — `TypeError`（save_message 不接受 meta）或 meta 为空

- [ ] **Step 3: 实现**

`backend/app/db/models.py` 的 `Message` 加列:
```python
class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True)
    role = Column(String(16))
    content = Column(String(4000))
    meta = Column(String, nullable=True)  # 每轮 domain/had_tools/cached 标记（自动沉淀判定依据）
    created_at = Column(DateTime, server_default=func.now())
```

`backend/app/db/models.py` 末尾（`create_all` 之后）加轻量迁移:
```python
# 轻量迁移：既有 SQLite 库补 meta 列（create_all 不会 ALTER 已有表）
def _ensure_meta_column() -> None:
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN meta VARCHAR"))
            conn.commit()
    except Exception:
        pass  # 已存在则忽略

_ensure_meta_column()
```

`backend/app/db/sessions.py` 顶部加 `import json`，改 `save_message` 并新增 `get_last_round`:
```python
def save_message(session_id: str, role: str, content: str, meta: dict | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(Message(session_id=session_id, role=role, content=content,
                       meta=json.dumps(meta, ensure_ascii=False) if meta else None))
        db.commit()
    finally:
        db.close()


def get_last_round(session_id: str) -> dict | None:
    """最近一轮 user→assistant 对 + assistant 的 meta（自动沉淀判定依据）。无完整轮次返回 None。"""
    with SessionLocal() as db:
        rows = db.query(Message).filter_by(session_id=session_id)\
                .order_by(Message.id.asc()).all()
    last = None
    pending_q = None
    for m in rows:
        if m.role == "user":
            pending_q = m.content
        elif m.role == "assistant" and pending_q is not None:
            meta = {}
            if m.meta:
                try:
                    meta = json.loads(m.meta)
                except Exception:
                    meta = {}
            last = {"question": pending_q, "answer": m.content, "meta": meta}
            pending_q = None  # 只保留最近一对
    return last
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_sessions.py -q`
Expected: PASS（既有 + 2 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app/db/models.py backend/app/db/sessions.py backend/tests/test_sessions.py
git commit -m "feat: Message.meta 列 + get_last_round（自动沉淀判定依据）"
```

---

### Task 5: kb 模块（列表 / 重索引 / 沉淀 / 审核 / 自动沉淀）

**Files:**
- Create: `backend/app/kb.py`
- Test: `backend/tests/test_kb.py`

**Interfaces:**
- Produces（`app.kb`）:
  - `draft_doc(question, answer) -> {"status": "draft"|"exists", "doc_id", "path", "title"}`
  - `approve_doc(doc_id) -> {"status": "published"|"noop", "chunk_count"}`（路径穿越防护，ValueError）
  - `pending_docs() -> list[{"doc_id","path","title","category"}]`
  - `list_docs() -> list[{"path","title","category","status","chunks"}]`
  - `reindex() -> {"indexed", "skipped_drafts"}`
  - `auto_suggest(session_id) -> dict | None`
  - 模块级 `KB_ROOT` / `BACKFILL_DIR`（测试可 monkeypatch）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_kb.py`:
```python
import pytest
from app import kb as kb_mod


@pytest.fixture
def kb_env(tmp_path, monkeypatch):
    monkeypatch.setattr(kb_mod, "KB_ROOT", tmp_path)
    monkeypatch.setattr(kb_mod, "BACKFILL_DIR", tmp_path / "backfill")
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "refund.md").write_text(
        "---\ntitle: 退货政策\ncategory: policies\nstatus: published\n---\n\n七天无理由退货。",
        encoding="utf-8")
    (tmp_path / "policies" / "draft.md").write_text(
        "---\ntitle: 草稿\nstatus: draft\n---\n\n草稿内容。", encoding="utf-8")
    return tmp_path


def test_reindex_skips_drafts(kb_env, monkeypatch):
    calls = {}
    class FakeStore:
        def reset(self): calls["reset"] = True
        def add(self, texts, metadatas): calls["texts"] = list(texts)
    monkeypatch.setattr(kb_mod, "VectorStore", lambda: FakeStore())
    monkeypatch.setattr(kb_mod, "invalidate_bm25", lambda: None)
    res = kb_mod.reindex()
    assert res["skipped_drafts"] == 1
    assert all("草稿" not in t for t in calls["texts"])
    assert any("七天无理由" in t for t in calls["texts"])


def test_draft_doc_writes_file(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [])
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: 测试\ncategory: backfill\nstatus: draft\n---\n\n正文。")
    res = kb_mod.draft_doc("怎么开发票", "请提供发票抬头。")
    assert res["status"] == "draft"
    assert res["doc_id"].endswith(".md")
    assert (kb_mod.BACKFILL_DIR / res["doc_id"]).exists()


def test_draft_doc_dedup_on_high_score(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [{"score": 0.99}])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [{"score": 0.99}])
    res = kb_mod.draft_doc("怎么退货", "答案")
    assert res["status"] == "exists"


def test_draft_doc_falls_back_on_llm_failure(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [])
    def boom(q, a): raise RuntimeError("llm down")
    monkeypatch.setattr(kb_mod, "_format_doc", boom)
    res = kb_mod.draft_doc("怎么开发票", "答案")
    assert res["status"] == "draft"


def test_approve_publishes_and_ingests(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [])
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: T\ncategory: backfill\nstatus: draft\n---\n\n正文内容若干。")
    res = kb_mod.draft_doc("q", "a")
    added = {}
    class FakeStore:
        def add(self, texts, metadatas): added["n"] = len(texts)
    monkeypatch.setattr(kb_mod, "get_store", lambda: FakeStore())
    monkeypatch.setattr(kb_mod, "invalidate_bm25", lambda: None)
    out = kb_mod.approve_doc(res["doc_id"])
    assert out["status"] == "published"
    assert added["n"] >= 1
    raw = (kb_mod.BACKFILL_DIR / res["doc_id"]).read_text(encoding="utf-8")
    assert "status: published" in raw


def test_approve_rejects_path_traversal(kb_env, monkeypatch):
    with pytest.raises(ValueError):
        kb_mod.approve_doc("../../etc/passwd")


def test_pending_docs_lists_drafts(kb_env):
    (kb_mod.BACKFILL_DIR).mkdir(exist_ok=True)
    (kb_mod.BACKFILL_DIR / "20260814-a.md").write_text(
        "---\ntitle: A\nstatus: draft\n---\n\nx", encoding="utf-8")
    pending = kb_mod.pending_docs()
    assert len(pending) == 1 and pending[0]["doc_id"] == "20260814-a.md"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_kb.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.kb'`

- [ ] **Step 3: 实现**

`backend/app/kb.py`:
```python
import re
import time
from pathlib import Path

from app.config import settings
from app.llm import chat as llm_chat
from app.rag.chunker import chunk_markdown, read_frontmatter, is_draft, _extract_frontmatter
from app.rag.retrieve import hybrid_search, rerank, get_store, invalidate_bm25
from app.rag.vector_store import VectorStore

KB_ROOT = Path(__file__).resolve().parents[1] / "knowledge_base"
BACKFILL_DIR = KB_ROOT / "backfill"

KB_EDITOR_SYSTEM = (
    "你是电商售后知识库编辑。把用户问题与人工客服回答提炼成一条规范的售后知识条目（markdown）。"
    "要求：\n1. 以 YAML frontmatter 开头，含 title（简明标题）、category（值固定为 backfill）、status（值固定为 draft）\n"
    "2. 正文用清晰客观的售后话术，覆盖同类问题的常见变体问法，不要出现'用户说/客服说'这类对话体\n"
    "3. 只输出 markdown 文档本身，不要任何解释"
)


def _slug(question: str) -> str:
    s = re.sub(r"[^\w一-龥]", "", question)[:12]
    return s or "question"


def _format_doc(question: str, answer: str) -> str:
    text = (llm_chat([
        {"role": "system", "content": KB_EDITOR_SYSTEM},
        {"role": "user", "content": f"问题：{question}\n人工客服回答：{answer}"},
    ], stream=False) or "").strip()
    if not text:
        raise ValueError("LLM 提炼为空")
    return text


def _fallback_doc(question: str, answer: str) -> str:
    """LLM 失败时的模板兜底，保证沉淀流程绝不中断。"""
    title = question[:20]
    return (f"---\ntitle: {title}\ncategory: backfill\nstatus: draft\n---\n\n"
            f"## {title}\n\n{answer}\n")


def _extract_title(body: str) -> str:
    meta, _ = _extract_frontmatter(body)
    return meta.get("title", "")


def draft_doc(question: str, answer: str) -> dict:
    """把问答沉淀为 draft 草稿。防重 → LLM 提炼（失败回退模板）→ 写文件。"""
    # 1) 防重：最高重排分 ≥ 语义缓存阈值视为已存在
    try:
        docs = hybrid_search(question, top_k=5)
        reranked = rerank(question, docs)
        if reranked and reranked[0].get("score", 0) >= settings.semantic_cache_threshold:
            return {"status": "exists", "doc_id": "", "path": "",
                    "title": "知识库已存在类似条目，跳过沉淀"}
    except Exception:
        pass
    # 2) 生成文档
    try:
        body = _format_doc(question, answer)
    except Exception:
        body = _fallback_doc(question, answer)
    # 3) 写文件（文件名即 doc_id，日期前缀保证可排序）
    BACKFILL_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{time.strftime('%Y%m%d')}-{_slug(question)}.md"
    path = BACKFILL_DIR / fname
    path.write_text(body, encoding="utf-8")
    return {"status": "draft", "doc_id": fname, "path": f"backfill/{fname}",
            "title": _extract_title(body) or f"售后问题：{question[:20]}"}


def approve_doc(doc_id: str) -> dict:
    """审核通过：draft → published，摄入向量库（稳定 ID）+ 刷新 BM25。路径穿越防护。"""
    path = (BACKFILL_DIR / doc_id).resolve()
    if path.name != doc_id or path.parent != BACKFILL_DIR.resolve() or not path.exists():
        raise ValueError("无效的 doc_id")
    raw = path.read_text(encoding="utf-8")
    if "status: draft" not in raw:
        return {"status": "noop", "chunk_count": 0}
    path.write_text(raw.replace("status: draft", "status: published"), encoding="utf-8")
    chunks = chunk_markdown(path)
    get_store().add([c["text"] for c in chunks],
                    [{**c["metadata"], "text": c["text"]} for c in chunks])
    invalidate_bm25()
    return {"status": "published", "chunk_count": len(chunks)}


def pending_docs() -> list[dict]:
    """待审核草稿列表（status: draft）。"""
    if not BACKFILL_DIR.exists():
        return []
    out = []
    for md in sorted(BACKFILL_DIR.rglob("*.md")):
        meta = read_frontmatter(md)
        if meta.get("status") == "draft":
            out.append({"doc_id": md.name, "path": f"backfill/{md.name}",
                        "title": meta.get("title", ""), "category": meta.get("category", "")})
    return out


def list_docs() -> list[dict]:
    """列出全部 KB 文档（path/title/category/status/chunk 数）。"""
    out = []
    for md in sorted(KB_ROOT.rglob("*.md")):
        meta = read_frontmatter(md)
        chunks = chunk_markdown(md)
        out.append({"path": str(md.relative_to(KB_ROOT)),
                    "title": meta.get("title", ""),
                    "category": meta.get("category", ""),
                    "status": meta.get("status", "published"),
                    "chunks": len(chunks)})
    return out


def reindex() -> dict:
    """全量重建索引（Obsidian 编辑后调用）。跳 draft。"""
    store = VectorStore()
    store.reset()
    texts, metas, skipped = [], [], 0
    for md in sorted(KB_ROOT.rglob("*.md")):
        if is_draft(md):
            skipped += 1
            continue
        for c in chunk_markdown(md):
            texts.append(c["text"])
            metas.append({**c["metadata"], "text": c["text"]})
    store.add(texts, metas)
    invalidate_bm25()
    return {"indexed": len(texts), "skipped_drafts": skipped}


def auto_suggest(session_id: str) -> dict | None:
    """5 星评分触发：读最近一轮，policy/非工具/非缓存 → 自动生成 draft 草稿。"""
    from app.db.sessions import get_last_round
    round_ = get_last_round(session_id)
    if not round_:
        return None
    meta = round_["meta"] or {}
    if meta.get("domain") != "policy" or meta.get("had_tools") or meta.get("cached"):
        return None
    if not round_["question"].strip() or not round_["answer"].strip():
        return None
    return draft_doc(round_["question"], round_["answer"])
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_kb.py -q`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/kb.py backend/tests/test_kb.py
git commit -m "feat: 知识库模块（沉淀草稿/审核发布/重索引/自动沉淀）"
```

---

### Task 6: kb API 路由 + 人工回复端点

**Files:**
- Create: `backend/app/api/kb.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_kb_api.py`

**Interfaces:**
- Consumes: `app.kb` 全部函数、`save_message`
- Produces 路由（`/api/v1` 前缀）:
  - `GET /kb/docs`、`POST /kb/reindex`
  - `POST /kb/backfill` `{question, answer}`
  - `POST /kb/backfill/{doc_id}/approve`（ValueError → 404）
  - `GET /kb/backfill/pending`
  - `POST /sessions/{session_id}/human-reply` `{question, answer}`（存为带「（人工客服）」前缀的 assistant 消息）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_kb_api.py`:
```python
from fastapi.testclient import TestClient
from app.main import app
from app import kb


def _c():
    return TestClient(app)


def test_kb_docs_lists(monkeypatch):
    monkeypatch.setattr(kb, "list_docs",
                        lambda: [{"path": "policies/a.md", "status": "published"}])
    r = _c().get("/api/v1/kb/docs", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["docs"][0]["path"] == "policies/a.md"


def test_kb_backfill_calls_draft(monkeypatch):
    monkeypatch.setattr(kb, "draft_doc",
                        lambda q, a: {"status": "draft", "doc_id": "x.md", "title": "t"})
    r = _c().post("/api/v1/kb/backfill", json={"question": "q", "answer": "a"},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["status"] == "draft"


def test_kb_approve_ok(monkeypatch):
    monkeypatch.setattr(kb, "approve_doc",
                        lambda doc_id: {"status": "published", "chunk_count": 2})
    r = _c().post("/api/v1/kb/backfill/x.md/approve",
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["status"] == "published"


def test_kb_approve_404_on_bad_doc(monkeypatch):
    def boom(doc_id): raise ValueError("无效的 doc_id")
    monkeypatch.setattr(kb, "approve_doc", boom)
    r = _c().post("/api/v1/kb/backfill/x.md/approve",
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 404


def test_kb_pending_lists(monkeypatch):
    monkeypatch.setattr(kb, "pending_docs",
                        lambda: [{"doc_id": "20260814-a.md", "title": "A"}])
    r = _c().get("/api/v1/kb/backfill/pending", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["pending"][0]["doc_id"] == "20260814-a.md"


def test_human_reply_saves_message(monkeypatch):
    import app.api.kb as kb_api
    saved = {}
    monkeypatch.setattr(kb_api, "save_message",
                        lambda sid, role, content: saved.update(
                            {"sid": sid, "role": role, "content": content}))
    r = _c().post("/api/v1/sessions/s9/human-reply",
                  json={"question": "q", "answer": "人工答复"},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    assert saved["content"] == "（人工客服）人工答复"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_kb_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.kb'`

- [ ] **Step 3: 实现**

`backend/app/api/kb.py`:
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import kb
from app.db.sessions import save_message

router = APIRouter()


class BackfillRequest(BaseModel):
    question: str
    answer: str


class HumanReplyRequest(BaseModel):
    question: str
    answer: str


@router.get("/kb/docs")
def kb_docs():
    return {"docs": kb.list_docs()}


@router.post("/kb/reindex")
def kb_reindex():
    res = kb.reindex()
    return {"ok": True, **res}


@router.post("/kb/backfill")
def kb_backfill(req: BackfillRequest):
    return kb.draft_doc(req.question, req.answer)


@router.get("/kb/backfill/pending")
def kb_pending():
    return {"pending": kb.pending_docs()}


@router.post("/kb/backfill/{doc_id}/approve")
def kb_approve(doc_id: str):
    try:
        return kb.approve_doc(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/human-reply")
def human_reply(session_id: str, req: HumanReplyRequest):
    save_message(session_id, "assistant", f"（人工客服）{req.answer}")
    return {"ok": True}
```

`backend/app/main.py` 导入与注册:
```python
from app.api import kb as kb_api
...
app.include_router(kb_api.router, prefix="/api/v1")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_kb_api.py -q`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/kb.py backend/app/main.py backend/tests/test_kb_api.py
git commit -m "feat: kb API（reindex/docs/backfill/approve/pending）+ 人工回复端点"
```

---

### Task 7: chat 流式 human_handoff 事件 + meta 透传

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat.py`（追加）

**Interfaces:**
- Produces: `gate_decision` 为 False 时 SSE 流先发 `{"type": "human_handoff"}`
- Produces: `save_message` 的 assistant 消息携带 `meta`（缓存命中 `cached: True`；正常 `{domain, had_tools, cached: False}`）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_chat.py` 追加:
```python
def test_chat_emits_human_handoff_on_gate_fail(monkeypatch):
    import app.api.chat as chat_mod
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h, uid: {
        "question": q, "session_id": sid, "history": h or [],
        "domain": "policy", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: False)
    monkeypatch.setattr(chat_mod, "llm_chat", lambda msgs, stream=False: "暂时没找到相关说明，可转人工处理。")
    r = _post("怎么开电子发票")
    assert "human_handoff" in r.text


def test_chat_saves_meta_with_assistant_message(monkeypatch):
    import app.api.chat as chat_mod
    saved = []
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h, uid: {
        "question": q, "session_id": sid, "history": h or [],
        "domain": "policy", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: False)
    monkeypatch.setattr(chat_mod, "llm_chat", lambda msgs, stream=False: "答案A")
    monkeypatch.setattr(chat_mod, "save_message",
                        lambda sid, role, content, meta=None: saved.append((role, meta)))
    r = _post("怎么退货")
    assert ("assistant", {"domain": "policy", "had_tools": False, "cached": False}) in saved
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_chat.py::test_chat_emits_human_handoff_on_gate_fail tests/test_chat.py::test_chat_saves_meta_with_assistant_message -q`
Expected: FAIL — `"human_handoff" not in r.text`；meta 未透传

- [ ] **Step 3: 实现**

`backend/app/api/chat.py` 缓存命中分支的 assistant 保存加 meta:
```python
                    await _blocking(save_message, req.session_id, "user", req.message)
                    await _blocking(save_message, req.session_id, "assistant", cached,
                                    {"domain": None, "had_tools": False, "cached": True})
```

`backend/app/api/chat.py` 兜底分支（`else`，`gate_decision` False）在输出 token 前先发 handoff 事件:
```python
            else:
                # 资料不足兜底：整句一次返回（诚实话术，无需流式）
                yield _sse({"type": "human_handoff"})
                msgs = build_writer_messages(st)
                answer = await _blocking(llm_chat, msgs, False) or ""
                yield _sse({"type": "token", "text": answer})
```

`backend/app/api/chat.py` 结尾持久化 try 块的 assistant 保存加 meta:
```python
            try:
                await _blocking(save_message, req.session_id, "user", req.message)
                await _blocking(save_message, req.session_id, "assistant", answer,
                                {"domain": st.get("domain"),
                                 "had_tools": bool(st.get("tool_results")),
                                 "cached": False})
            except Exception:
                pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_chat.py -q`
Expected: PASS（既有 + 2 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/chat.py backend/tests/test_chat.py
git commit -m "feat: SSE human_handoff 事件 + 会话 meta 透传"
```

---

### Task 8: feedback 评分驱动自动沉淀

**Files:**
- Modify: `backend/app/api/feedback.py`
- Test: `backend/tests/test_feedback.py`（追加）

**Interfaces:**
- Produces: `POST /feedback` 返回增加 `"suggested": dict | None`（5 星且符合条件时返回草稿信息）

- [ ] **Step 1: 写失败测试**

`backend/tests/test_feedback.py` 顶部（import 区）补一个辅助函数:
```python
def _c():
    return TestClient(app)
```
然后追加:
```python
def test_feedback_5_star_triggers_auto_suggest(monkeypatch):
    from app.api import feedback as fb
    from app import kb as kb_mod
    monkeypatch.setattr(fb, "save_feedback", lambda sid, rating: None)
    monkeypatch.setattr(kb_mod, "auto_suggest",
                        lambda sid: {"status": "draft", "doc_id": "x.md", "title": "t"})
    r = _c().post("/api/v1/feedback", json={"session_id": "s1", "rating": 5},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["suggested"]["status"] == "draft"


def test_feedback_low_rating_skips_suggest(monkeypatch):
    from app.api import feedback as fb
    monkeypatch.setattr(fb, "save_feedback", lambda sid, rating: None)
    r = _c().post("/api/v1/feedback", json={"session_id": "s1", "rating": 3},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["suggested"] is None


def test_feedback_suggest_failure_is_silent(monkeypatch):
    from app.api import feedback as fb
    from app import kb as kb_mod
    monkeypatch.setattr(fb, "save_feedback", lambda sid, rating: None)
    def boom(sid): raise RuntimeError("boom")
    monkeypatch.setattr(kb_mod, "auto_suggest", boom)
    r = _c().post("/api/v1/feedback", json={"session_id": "s1", "rating": 5},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["suggested"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_feedback.py -q`
Expected: FAIL — 响应无 `suggested` 字段

- [ ] **Step 3: 实现**

`backend/app/api/feedback.py`:
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.models import SessionLocal, Feedback
from app import kb as kb_mod

router = APIRouter()

class FeedbackRequest(BaseModel):
    session_id: str
    rating: int

def save_feedback(session_id: str, rating: int) -> None:
    """把一条评分写入 feedback 表。独立成函数便于测试 monkeypatch。"""
    db = SessionLocal()
    try:
        db.add(Feedback(session_id=session_id, rating=rating))
        db.commit()
    finally:
        db.close()

@router.post("/feedback")
def feedback(req: FeedbackRequest):
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="rating 必须在 1-5 之间")
    save_feedback(req.session_id, req.rating)
    suggested = None
    if req.rating == 5:
        try:
            suggested = kb_mod.auto_suggest(req.session_id)
        except Exception:
            suggested = None  # 自动沉淀失败不影响评分闭环
    return {"ok": True, "suggested": suggested}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/test_feedback.py -q`
Expected: PASS（既有 + 3 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/feedback.py backend/tests/test_feedback.py
git commit -m "feat: 评分 5 星自动沉淀草稿候选（自增长知识库）"
```

---

### Task 9: 前端 SSE 事件 + 弹窗流程

> ⚠️ 改前端前先读 `frontend/node_modules/next/dist/docs/` 相关指南（Next.js 16 破坏性变更）。本任务全部沿用现有文件风格。

**Files:**
- Modify: `frontend/lib/sse.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/ChatWindow.tsx`
- Modify: `frontend/tests/ChatWindow.test.tsx`

**Interfaces:**
- Produces: `streamChat` handlers 增加 `onHandoff: () => void`
- Produces: `lib/api.ts` 新增 `humanReply(sessionId, question, answer)`, `backfill(question, answer)`, `approveBackfill(docId)`
- Produces: `ChatMessage` 增加可选 `handoff?: boolean`、`human?: boolean`

- [ ] **Step 1: 写失败测试**

`frontend/tests/ChatWindow.test.tsx`：
- mock 声明增加三个函数:
```ts
vi.mock("@/lib/api", () => ({
  fetchHistory: vi.fn(),
  submitFeedback: vi.fn(),
  humanReply: vi.fn(),
  backfill: vi.fn(),
  approveBackfill: vi.fn(),
}));
```
- 顶部引用追加:
```ts
import { humanReply, backfill, approveBackfill } from "@/lib/api";
const mockedHumanReply = vi.mocked(humanReply);
const mockedBackfill = vi.mocked(backfill);
const mockedApproveBackfill = vi.mocked(approveBackfill);
```
- 追加两条用例:
```ts
it("收到 human_handoff 后显示转人工按钮", async () => {
  const user = userEvent.setup();
  const getHandlers = captureHandlers();
  render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
  await user.type(screen.getByPlaceholderText("输入问题…"), "怎么开电子发票");
  await user.click(screen.getByRole("button", { name: "发送" }));
  act(() => { getHandlers().onHandoff(); getHandlers().onDone(); });
  expect(await screen.findByRole("button", { name: /转人工/ })).toBeInTheDocument();
});

it("转人工 → 回复 → 沉淀 → 发布 完整流程", async () => {
  const user = userEvent.setup();
  const getHandlers = captureHandlers();
  mockedHumanReply.mockResolvedValue(true);
  mockedBackfill.mockResolvedValue({
    status: "draft", doc_id: "x.md", path: "backfill/x.md", title: "开票指南",
  });
  mockedApproveBackfill.mockResolvedValue(true);
  render(<ChatWindow sessionId="s1" onSources={vi.fn()} onThinking={vi.fn()} />);
  await user.type(screen.getByPlaceholderText("输入问题…"), "怎么开电子发票");
  await user.click(screen.getByRole("button", { name: "发送" }));
  act(() => { getHandlers().onHandoff(); getHandlers().onDone(); });
  await user.click(await screen.findByRole("button", { name: /转人工/ }));
  await user.type(screen.getByPlaceholderText("输入人工客服的回答…"), "请联系财务开具");
  await user.click(screen.getByRole("button", { name: "回复" }));
  expect(mockedHumanReply).toHaveBeenCalledWith("s1", "怎么开电子发票", "请联系财务开具");
  expect(await screen.findByText(/（人工客服）请联系财务开具/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "沉淀" }));
  expect(mockedBackfill).toHaveBeenCalledWith("怎么开电子发票", "请联系财务开具");
  await user.click(screen.getByRole("button", { name: "确认发布" }));
  expect(mockedApproveBackfill).toHaveBeenCalledWith("x.md");
  expect(screen.getByText(/已发布/)).toBeInTheDocument();
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL — `humanReply`/`backfill`/`approveBackfill` 未定义（模块未实现）或 `onHandoff` 未触发

- [ ] **Step 3: 实现 sse.ts**

`frontend/lib/sse.ts` 的 handlers 类型加 `onHandoff: () => void;`，事件分发加一行:
```ts
          else if (evt.type === "human_handoff") handlers.onHandoff();
```

- [ ] **Step 4: 实现 api.ts**

`frontend/lib/api.ts` 追加:
```ts
export type BackfillResult = { status: string; doc_id: string; path: string; title: string };

export async function humanReply(sessionId: string, question: string, answer: string): Promise<boolean> {
  try {
    const r = await fetch(`/api/v1/sessions/${sessionId}/human-reply`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ question, answer }),
    });
    return r.ok;
  } catch {
    return false;
  }
}

export async function backfill(question: string, answer: string): Promise<BackfillResult | null> {
  try {
    const r = await fetch("/api/v1/kb/backfill", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": API_KEY },
      body: JSON.stringify({ question, answer }),
    });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export async function approveBackfill(docId: string): Promise<boolean> {
  try {
    const r = await fetch(`/api/v1/kb/backfill/${encodeURIComponent(docId)}/approve`, {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
    });
    return r.ok;
  } catch {
    return false;
  }
}
```

- [ ] **Step 5: 实现 ChatWindow.tsx**

`frontend/components/ChatWindow.tsx`：
1) 类型与 import:
```tsx
import { humanReply, backfill, approveBackfill } from "@/lib/api";
```
2) `ChatMessage` 类型（`frontend/lib/sse.ts`）加字段:
```ts
  handoff?: boolean;
  human?: boolean;
```
3) 组件内 state 与 ref（放在现有 state 声明区）:
```tsx
  const lastQuestionRef = useRef("");
  const [handoff, setHandoff] = useState<{
    open: boolean; question: string; answer: string;
    step: "reply" | "drafted" | "approved";
    draft?: { doc_id: string; path: string; title: string };
    error?: string;
  }>({ open: false, question: "", answer: "", step: "reply" });
```
4) `send()` 开头记录问题、末尾 handlers 加 `onHandoff`:
```tsx
  function send(text?: string) {
    const userText = (text ?? input).trim();
    if (!userText || busy) return;
    lastQuestionRef.current = userText;
    ...
    const p = streamChat(sessionId, userText, {
      ...
      onHandoff: () => {
        if (sessionRef.current !== sessionId) return;
        setMessages((ms) => {
          const next = [...ms];
          const i = next.length - 1;
          if (i >= 0 && next[i].role === "assistant") next[i] = { ...next[i], handoff: true };
          return next;
        });
        setHandoff((h) => ({ ...h, question: lastQuestionRef.current }));
      },
      ...
    });
```
5) 三个处理函数（放在 `rate()` 之后）:
```tsx
  async function doHumanReply() {
    const a = handoff.answer.trim();
    if (!a || busy) return;
    setBusy(true);
    const ok = await humanReply(sessionId, handoff.question, a);
    setBusy(false);
    if (!ok) { setHandoff((h) => ({ ...h, error: "提交失败" })); return; }
    setMessages((ms) => [...ms, { role: "assistant", content: `（人工客服）${a}`, human: true }]);
    setHandoff((h) => ({ ...h, answer: a, step: "drafted", error: undefined }));
  }

  async function doBackfill() {
    setBusy(true);
    const d = await backfill(handoff.question, handoff.answer);
    setBusy(false);
    if (!d || d.status === "exists") {
      setHandoff((h) => ({ ...h, error: d?.status === "exists" ? "知识库已存在类似条目" : "沉淀失败" }));
      return;
    }
    setHandoff((h) => ({ ...h, draft: d, error: undefined }));
  }

  async function doApprove() {
    if (!handoff.draft) return;
    setBusy(true);
    const ok = await approveBackfill(handoff.draft.doc_id);
    setBusy(false);
    if (!ok) { setHandoff((h) => ({ ...h, error: "发布失败" })); return; }
    setHandoff((h) => ({ ...h, step: "approved", error: undefined }));
    setTimeout(() => setHandoff((h) => ({ ...h, open: false })), 2000);
  }
```
6) 消息渲染区，assistant 消息后加转人工按钮（放在重试按钮旁边）:
```tsx
            {m.role === "assistant" && m.handoff && !handoff.open && (
              <button onClick={() => setHandoff((h) => ({ ...h, open: true }))}
                      className="block ml-2 mt-1 text-xs border rounded px-2 py-1 text-amber-700 hover:bg-amber-50">
                🤝 转人工
              </button>
            )}
```
7) 组件 JSX 末尾（输入栏之后）加弹窗:
```tsx
      {handoff.open && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50"
             onClick={() => setHandoff((h) => ({ ...h, open: false }))}>
          <div className="bg-white rounded-lg shadow-lg p-4 w-96 max-w-[90vw]"
               onClick={(e) => e.stopPropagation()}>
            {handoff.step === "reply" && (
              <>
                <h3 className="font-bold mb-2">🤝 人工客服（模拟）</h3>
                <p className="text-sm text-gray-600 mb-2">用户问题：{handoff.question}</p>
                <textarea className="border rounded w-full p-2 text-sm" rows={4}
                          placeholder="输入人工客服的回答…" value={handoff.answer}
                          onChange={(e) => setHandoff((h) => ({ ...h, answer: e.target.value }))} />
                {handoff.error && <p className="text-red-500 text-xs">{handoff.error}</p>}
                <div className="flex gap-2 mt-2 justify-end">
                  <button className="border rounded px-3 py-1 text-sm"
                          onClick={() => setHandoff((h) => ({ ...h, open: false }))}>取消</button>
                  <button className="bg-blue-500 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                          disabled={busy || !handoff.answer.trim()} onClick={doHumanReply}>回复</button>
                </div>
              </>
            )}
            {handoff.step === "drafted" && (
              <>
                <h3 className="font-bold mb-2">📥 沉淀到知识库</h3>
                {!handoff.draft ? (
                  <button className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                          onClick={doBackfill}>沉淀</button>
                ) : (
                  <>
                    <p className="text-sm text-gray-600 mb-2">已生成草稿：{handoff.draft.title}</p>
                    <p className="text-xs text-gray-400 mb-2">路径：{handoff.draft.path}</p>
                    <div className="flex gap-2 justify-end">
                      <button className="border rounded px-3 py-1 text-sm"
                              onClick={() => setHandoff((h) => ({ ...h, open: false }))}>关闭</button>
                      <button className="bg-green-600 text-white px-3 py-1 rounded text-sm"
                              onClick={doApprove}>确认发布</button>
                    </div>
                  </>
                )}
              </>
            )}
            {handoff.step === "approved" && (
              <p className="text-green-600 font-bold">✅ 已发布，下次命中知识库</p>
            )}
          </div>
        </div>
      )}
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd frontend && npm test`
Expected: PASS（既有 16 + 新增 2）

- [ ] **Step 7: build 验证**

Run: `cd frontend && npm run build`
Expected: 成功，无类型错误

- [ ] **Step 8: 提交**

```bash
git add frontend/lib/sse.ts frontend/lib/api.ts frontend/components/ChatWindow.tsx frontend/tests/ChatWindow.test.tsx
git commit -m "feat: 前端转人工弹窗 + 沉淀发布闭环 + human_handoff 事件"
```

---

### Task 10: 全量回归 + 文档 + 收尾

**Files:**
- Modify: `CONTEXT.md`
- Modify: `docs/optimization-todo.md`
- Modify: `knowledge_base/README.md`（新增）

- [ ] **Step 1: 后端全量回归**

Run: `cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`
Expected: 全绿（80 既有 + 新增 ~20）

- [ ] **Step 2: 前端全量回归**

Run: `cd frontend && npm test && npm run build`
Expected: 全绿 + build 成功

- [ ] **Step 3: Obsidian 使用说明**

新增 `knowledge_base/README.md`:
```markdown
# 知识库（Obsidian Vault）

用 Obsidian「打开文件夹作为仓库」打开本目录即可管理知识库（markdown + YAML frontmatter）。

- **新增/修改/删除** .md 文档后，调用 `POST /api/v1/kb/reindex` 重建索引（需 `X-API-Key`）
- frontmatter 支持 `title` / `category` / `status`；`status: draft` 的文档**不会进入检索**（待审核）
- `backfill/` 目录存放「人工兜底 → 知识回填」自动生成的条目，草稿确认发布后进入检索
- 相关接口：`GET /api/v1/kb/docs` 查看全部文档
```

- [ ] **Step 4: 更新待优化清单**

`docs/optimization-todo.md`「三、生产化路径」在阶段 5 前补注:
```markdown
[ ] 阶段 4.5 知识闭环 —— ✅ 人工兜底→知识回填（draft→审核→RAG 摄入）+ 评分 5★ 自动沉淀草稿 + Obsidian 管理（2026-08-14 完成）
```

- [ ] **Step 5: 更新 CONTEXT**

`CONTEXT.md` 优化轮段落追加:
```markdown
- **知识库治理 + 回填闭环（2026-08-14）**：Obsidian 管理 knowledge_base（热重索引 `POST /kb/reindex`，跳 draft）；稳定 ID（md5 path:page）修复增量摄入覆盖；SSE `human_handoff` → 转人工弹窗 → 人工回复 → LLM 提炼草稿 → 审核发布 → RAG 摄入 + BM25 刷新 → 下次命中；评分 5★ 自动沉淀草稿候选（消息表 meta 列判定）。**面试点**：审核 gate 控 RAG 摄入、badcase 回流 + 对话挖掘、LLM 提炼知识条目、路径穿越防护。
```

- [ ] **Step 6: 提交**

```bash
git add CONTEXT.md docs/optimization-todo.md knowledge_base/README.md
git commit -m "docs: 知识库治理与回填闭环完成 + Obsidian 使用说明"
```

---

## 完成定义

- [ ] `feature/task-16-kb-backfill` 后端 pytest 全绿、前端 vitest + build 全绿
- [ ] 端到端验证：问一个知识库没有的问题 → 收到 human_handoff → 弹窗人工回答 → 沉淀 → 发布 → 重问同样问题命中 RAG 正常回答
- [ ] Obsidian 打开 `knowledge_base/` 可编辑文档，`POST /kb/reindex` 后生效
- [ ] 评分 5 星回答自动生成草稿，`GET /kb/backfill/pending` 可见
- [ ] 合并回 `main` 前跑一遍完整回归
