# 真流式重构 + 会话闭环 + 前端优化 + CI 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把电商售后客服从「伪流式」改为真流式（前置质量闸门替换打回循环），打通会话/评分闭环，补齐前端体验优化与前端测试，备好 CI 文件。

**Architecture:** 拆开 LangGraph 一次性 `invoke`，改为「前置段（路由→工具→检索→确定性闸门）同步 + writer 流式段」。`run_agent` 保留同步接口供评测/现有测试。会话持久化模块接线，前端 SessionList/评分真实化，react-markdown 渲染回答。

**Tech Stack:** Python 3.13 / FastAPI / LangGraph / openai SDK / Next.js 16 (Turbopack) / react-markdown / Vitest / GitHub Actions

## Global Constraints

- 回滚点：`git checkout v1.0-pre-streaming`
- 每个 Task 走 `feature/streaming-refactor-<n>` 分支 → 合并 `main`
- TDD：先写失败测试（红）→ 实现 → 全绿 → 提交
- 后端 `run_agent` 返回结构不变：`{"draft_answer", "tool_results", "retrieved_chunks"}`
- SSE 事件类型保持前端兼容：`thinking / token / card / sources / error / done`
- 评测 25 题需重跑确认 92% 不掉（Task 5 / 15）
- 后端测试：`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`
- 前端 build：`cd frontend && npm run build`；前端 dev 与本任务无关时保持运行

---

## Phase A: 后端真流式核心

### Task 1: llm 流式接口测试

**Files:**
- Test: `backend/tests/test_llm.py`（追加）

**Interfaces:**
- Produces: 确认 `llm.chat(messages, stream=True)` 返回逐 token 迭代器（`resp` 的 `.choices[0].delta.content`）

- [ ] **Step 1: 写失败测试**

```python
def test_chat_stream_yields_tokens(monkeypatch):
    """stream=True 返回可迭代响应，逐 token 产出 delta.content。"""
    import app.llm as llm_mod
    class FakeMsg:  # 模拟一个流式响应块
        def __init__(self, t): self.delta = type("D", (), {"content": t})()
    def fake_chunks(*a, **k):
        yield type("R", (), {"choices": [FakeMsg("你")]})()
        yield type("R", (), {"choices": [FakeMsg("好")]})()
    monkeypatch.setattr(llm_mod, "_chat_once", fake_chunks)
    resp = llm_mod.chat([{"role": "user", "content": "hi"}], stream=True)
    out = "".join(c.choices[0].delta.content for c in resp)
    assert out == "你好"
```

- [ ] **Step 2: 跑测试确认通过或修复 mock**

Run: `pytest tests/test_llm.py::test_chat_stream_yields_tokens -v`
Expected: PASS（llm.py 已支持 stream=True，此测试锁定契约）

- [ ] **Step 3: 如失败则修正 `_finalize` 对 stream 的原样返回**

`app/llm.py` 已满足，无需改动。

- [ ] **Step 4: 提交**

```bash
git add backend/tests/test_llm.py
git commit -m "test: 锁定 llm.chat stream=True 流式契约"
```

### Task 2: 前置质量闸门

**Files:**
- Modify: `backend/app/agents/nodes.py`
- Test: `backend/tests/test_graph.py`

**Interfaces:**
- Produces: `gate_decision(state) -> bool`（True=资料足够可流式；False=兜底话术）

- [ ] **Step 1: 写失败测试**

```python
def test_gate_passes_when_tools_ok():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "order", "tool_results": [{"order_id": "1", "status": "已发货"}]}) is True

def test_gate_passes_when_retrieved():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "policy", "retrieved_chunks": [{"title": "x", "text": "y"}]}) is True

def test_gate_blocks_no_data():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "policy", "retrieved_chunks": []}) is False
    assert gate_decision({"domain": "order", "tool_results": [{"error": "订单不存在"}]}) is False

def test_gate_passes_chitchat():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "chitchat", "retrieved_chunks": []}) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_graph.py::test_gate_passes_when_tools_ok -v`
Expected: FAIL（gate_decision 未定义）

- [ ] **Step 3: 实现 gate_decision**

在 `backend/app/agents/nodes.py` 追加：

```python
def gate_decision(state: AgentState) -> bool:
    """前置质量闸门：资料足够才流式生成，否则走诚实兜底话术。
    order 域看工具结果（error 视为不足）；policy/product 看检索命中；chitchat 恒通过。"""
    if state["domain"] == "chitchat":
        return True
    if state["domain"] == "order":
        return bool(state.get("tool_results") and isinstance(state["tool_results"][0], dict)
                    and "error" not in state["tool_results"][0])
    return bool(state.get("retrieved_chunks"))
```

- [ ] **Step 4: 跑全部 gate 测试确认通过**

Run: `pytest tests/test_graph.py -q`
Expected: 新增 4 个 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/nodes.py backend/tests/test_graph.py
git commit -m "feat: 前置质量闸门 gate_decision（资料足够判定）"
```

### Task 3: run_agent 同步重构（移除打回循环）

**Files:**
- Modify: `backend/app/agents/graph.py`、`backend/app/agents/nodes.py`
- Test: `backend/tests/test_graph.py`（迁移打回测试）、`backend/tests/test_tools_agent.py`

**Interfaces:**
- Consumes: `gate_decision(state) -> bool`（Task 2）
- Produces: `run_agent(question, session_id, history=None) -> dict`（`draft_answer`/`tool_results`/`retrieved_chunks`）；`writer_node` 支持 `stream` 参数返回迭代器或字符串

- [ ] **Step 1: 迁移 writer_node 支持 stream**

`nodes.py` 中 writer_node 改为可流式。拆分消息构建为 `build_writer_messages(state) -> list[dict]`（复用现有 msgs 组装逻辑，删除 review_comment 分支），writer_node 调它：

```python
def build_writer_messages(state: AgentState) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}]
    msgs.extend(state.get("history", []))
    tool_text = ""
    if state.get("tool_results"):
        tool_text = "\n工具查询结果：" + str(state["tool_results"])
    if state["domain"] == "chitchat":
        user = f"用户寒暄：{state['question']}\n请礼貌简短回应，并引导用户提出售后问题。"
    elif state["domain"] == "order" and state.get("tool_results") and \
            isinstance(state["tool_results"][0], dict) and "error" not in state["tool_results"][0]:
        user = (f"系统已查询到订单信息。请**只基于以下工具结果**如实回答用户，"
                f"不要编造，不要被其他检索内容干扰。{tool_text}\n问题：{state['question']}")
    elif not state.get("retrieved_chunks"):
        user = f"知识库没有检索到相关内容。请如实告诉用户'暂时没有找到相关说明，可转人工处理'，不要编造。{tool_text}\n问题：{state['question']}"
    else:
        ctx = "\n\n".join(f"[{d['title']}]\n{d['text']}" for d in state["retrieved_chunks"])
        user = f"检索资料：\n{ctx}{tool_text}\n\n问题：{state['question']}"
    msgs.append({"role": "user", "content": user})
    return msgs
```

`nodes.py` 删除 `reviewer_node` 与 `SYSTEM` 之上的 import 里不再用到的引用。

- [ ] **Step 2: 重构 graph.py**

`build_graph()` 简化为 前置段（router→tool→retriever）→ writer；删除 reviewer 节点与 `should_retry`：

```python
from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents import nodes

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("router", nodes.router_node)
    g.add_node("tool", nodes.tool_node)
    g.add_node("retriever", nodes.retriever_node)
    g.add_node("writer", nodes.writer_node)
    g.add_edge(START, "router")
    g.add_edge("router", "tool")
    g.add_edge("tool", "retriever")
    g.add_edge("retriever", "writer")
    g.add_edge("writer", END)
    return g.compile()

def run_agent(question: str, session_id: str, history=None) -> dict:
    graph = build_graph()
    return graph.invoke({
        "question": question, "session_id": session_id,
        "history": history or [],
        "tool_results": [],
    })
```

- [ ] **Step 3: 迁移打回测试为闸门测试**

`test_graph.py` 中删除 `test_reviewer_increments_iteration`、`test_retry_boundary`；`test_retriever_fallback_on_error` 保留。新增同步链路测试：

```python
def test_run_agent_produces_answer(monkeypatch):
    from app.agents import nodes
    monkeypatch.setattr(nodes, "router_node", lambda s: {"domain": "policy"})
    monkeypatch.setattr(nodes, "tool_node", lambda s: {"tool_results": []})
    monkeypatch.setattr(nodes, "retriever_node", lambda s: {"retrieved_chunks": [{"title": "t", "text": "资料"}]})
    monkeypatch.setattr(nodes, "writer_node", lambda s: {"draft_answer": "基于资料的回答"})
    from app.agents.graph import run_agent
    r = run_agent("七天无理由", "s1")
    assert r["draft_answer"] == "基于资料的回答"
    assert r["tool_results"] == [] and len(r["retrieved_chunks"]) == 1
```

- [ ] **Step 4: 跑全量后端测试**

Run: `pytest tests/ -q`
Expected: 通过（删除打回测试后数量下降属预期；`test_tools_agent.py` 若引用 reviewer 相关则同步清理）

- [ ] **Step 5: 提交**

```bash
git add backend/app/agents/graph.py backend/app/agents/nodes.py backend/tests/
git commit -m "refactor: run_agent 改为前置段+writer，移除打回循环"
```

### Task 4: chat.py 真流式 gen()

**Files:**
- Modify: `backend/app/api/chat.py`
- Test: `backend/tests/test_chat.py`

**Interfaces:**
- Consumes: `gate_decision`（Task 2）、`build_writer_messages`（Task 3）、`llm.chat(stream=True)`
- Produces: `/api/v1/chat` SSE 流式端点（thinking/token/card/sources/error/done 事件不变）

- [ ] **Step 1: 写失败测试（流式 token 来自 stream，缓存命中也产出 token）**

```python
def test_chat_streams_tokens_incrementally(monkeypatch):
    import app.api.chat as chat_mod
    def fake_gate(s): return True
    monkeypatch.setattr(chat_mod, "gate_decision", fake_gate)
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "cache_set", lambda q, a: None)
    # 前置段同步返回
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h: {
        "domain": "policy", "tool_results": [], "retrieved_chunks": [{"title": "t", "text": "x"}]})
    def fake_build(state): return [{"role": "user", "content": "q"}]
    monkeypatch.setattr(chat_mod, "build_writer_messages", fake_build)
    class FakeMsg:
        def __init__(self, t): self.delta = type("D", (), {"content": t})()
    def fake_stream(*a, **k):
        for ch in "流式": yield type("R", (), {"choices": [FakeMsg(ch)])()
    monkeypatch.setattr(chat_mod, "llm_chat_stream", fake_stream)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "hi"},
               headers={"X-API-Key": "dev-local-key"})
    # 逐 token 事件：至少出现两次独立 token 帧
    assert r.text.count('"type": "token"') >= 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_chat.py::test_chat_streams_tokens_incrementally -v`
Expected: FAIL（chat_mod 缺 gate_decision / run_front / llm_chat_stream）

- [ ] **Step 3: 重构 chat.py gen()**

新增模块级辅助并重构 `gen()`：

```python
from app.agents.nodes import gate_decision, build_writer_messages
from app.agents.graph import run_agent
from app.llm import chat as llm_chat
from app.llm import chat_with_tools

def run_front(question: str, session_id: str, history) -> dict:
    """前置段：路由→工具→检索，返回 domain/tool_results/retrieved_chunks。"""
    from app.agents.state import AgentState
    from app.agents import nodes
    st: AgentState = {"question": question, "session_id": session_id,
                      "history": history or [], "tool_results": []}
    st.update(nodes.router_node(st))
    st.update(nodes.tool_node(st))
    st.update(nodes.retriever_node(st))
    return st

def llm_chat_stream(messages):
    return llm_chat(messages, stream=True)
```

`gen()` 主体（保留缓存、thinking、cards、sources、done、error 结构）：

```python
async def gen():
    yield _sse({"type": "thinking", "status": "正在识别问题类别..."})
    cached = cache_get(req.message)
    if cached:
        yield _sse({"type": "thinking", "status": "⚡ 命中语义缓存，直接返回"})
        yield _sse({"type": "token", "text": cached})
        yield _sse({"type": "done"})
        return
    try:
        st = run_front(req.message, req.session_id, req.history)
        for tool in st.get("tool_results", []):
            kind = _kind_of(tool)
            if kind:
                yield _sse({"type": "card", "kind": kind, "data": tool})
        if gate_decision(st):
            msgs = build_writer_messages(st)
            stream_resp = llm_chat_stream(msgs)
            answer_parts = []
            for chunk in stream_resp:
                piece = (chunk.choices[0].delta.content or "")
                if piece:
                    answer_parts.append(piece)
                    yield _sse({"type": "token", "text": piece})
            answer = "".join(answer_parts)
        else:
            msgs = build_writer_messages(st)
            answer = llm_chat(msgs, stream=False)
            yield _sse({"type": "token", "text": answer})
        if not st.get("tool_results"):
            cache_set(req.message, answer)
        yield _sse({"type": "sources", "items": st.get("retrieved_chunks", [])})
    except Exception:
        yield _sse({"type": "error", "message": "服务暂时不可用，请稍后重试或转人工"})
    yield _sse({"type": "done"})
```

注意：删除 `_async_run`（改为 `run_front` + 流式）；`llm_chat` 返回 `None` 时兜底为空字符串。

- [ ] **Step 4: 更新既有 chat 测试（原基于 `_async_run` monkeypatch 的改用 `run_front` + `llm_chat_stream`），跑全量**

Run: `pytest tests/ -q`
Expected: 全部通过（cache 三测、error、kind_of 保留）

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/chat.py backend/tests/test_chat.py
git commit -m "feat: /chat 真流式——前置段同步 + writer 逐 token SSE 推送"
```

### Task 5: 重跑评测确认 92% 不掉

- [ ] **Step 1: 停后端（Qdrant 独占）→ 跑评测**

```bash
# 先停 8000 端口进程
cd backend && PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m eval.judge > eval_result.txt 2>&1
```

Expected: 总准确率 ≥ 90%（现 92% 基线）。若低于 90%，检查 `build_writer_messages` 兜底分支是否破坏诚实话术，修正后重跑。

- [ ] **Step 2: 重启后端**

```bash
cd backend && ./.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

---

## Phase B: 会话 + 评分闭环

### Task 6: 后端会话 API + 消息保存接线

**Files:**
- Create: `backend/app/api/sessions.py`
- Modify: `backend/app/api/chat.py`、`backend/app/db/sessions.py`
- Test: `backend/tests/test_sessions.py`

**Interfaces:**
- Produces: `GET /api/v1/sessions` → `[{session_id, updated_at, preview}]`；`save_message` 在 chat 流式/兜底/缓存命中后都被调用

- [ ] **Step 1: db 层加 `list_sessions()`**

`backend/app/db/sessions.py`（按现有表结构实现，取按 updated_at 倒序的去重会话）：

```python
def list_sessions(limit: int = 20) -> list[dict]:
    """返回会话列表 [{session_id, updated_at, preview}]，按最近更新倒序。"""
    from app.db.models import SessionLocal, Message
    with SessionLocal() as db:
        rows = db.query(Message.session_id, Message.created).order_by(
            Message.created.desc()).all()
        seen, out = {}, []
        for sid, created in rows:
            if sid not in seen:
                seen[sid] = created
        for sid in list(seen)[:limit]:
            preview = db.query(Message.content).filter(Message.session_id == sid,
                                                       Message.role == "user").order_by(
                Message.id.desc()).first()
            out.append({"session_id": sid, "updated_at": seen[sid],
                        "preview": (preview[0][:30] if preview else "")})
        return out
```

（如 `models.py` 无 `created` 列，改用 `id` 倒序；以实际 schema 为准调整。）

- [ ] **Step 2: 新建 `api/sessions.py`**

```python
from fastapi import APIRouter
from app.db.sessions import list_sessions
router = APIRouter()

@router.get("/sessions")
def sessions():
    return {"sessions": list_sessions()}
```

在 `app/main.py` 注册该 router。

- [ ] **Step 3: chat.py 接线 save_message**

在 `gen()` 的流式/兜底/缓存命中三个出口前，调用 `save_message` 保存 user 与 assistant：

```python
from app.db.sessions import save_message
# 在 yield done 前（流式完成 / 兜底完成 / 缓存命中）统一：
save_message(req.session_id, "user", req.message)
save_message(req.session_id, "assistant", answer_or_cached)
```

（实现时在 gen 内维护 `final_answer` 变量，各出口赋值后在 `yield done` 前保存。）

- [ ] **Step 4: 写测试**

`test_sessions.py`：
```python
def test_sessions_list_returns(monkeypatch):
    import app.api.sessions as s
    monkeypatch.setattr(s, "list_sessions", lambda: [{"session_id": "s1", "updated_at": "t", "preview": "hi"}])
    c = TestClient(app)
    r = c.get("/api/v1/sessions", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["sessions"][0]["session_id"] == "s1"

def test_chat_persists_messages(monkeypatch):
    import app.api.chat as cm
    saved = []
    monkeypatch.setattr(cm, "save_message", lambda sid, role, content: saved.append((sid, role, content)))
    monkeypatch.setattr(cm, "cache_get", lambda q: None)
    monkeypatch.setattr(cm, "run_front", lambda q, sid, h: {"domain": "chitchat", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(cm, "gate_decision", lambda s: True)
    monkeypatch.setattr(cm, "build_writer_messages", lambda s: [{"role": "user", "content": "hi"}])
    def fake_stream(*a, **k):
        yield type("R", (), {"choices": [type("C", (), {"delta": type("D", (), {"content": "好"})()})()]})()
    monkeypatch.setattr(cm, "llm_chat_stream", fake_stream)
    c = TestClient(app)
    c.post("/api/v1/chat", json={"session_id": "s1", "message": "hi"}, headers={"X-API-Key": "dev-local-key"})
    assert ("s1", "user", "hi") in saved and any(role == "assistant" for _, role, _ in saved)
```

- [ ] **Step 5: 跑全量 → 提交**

Run: `pytest tests/ -q` → 全绿后 `git add backend/ && git commit -m "feat: 会话列表 API + 消息持久化接线"`

### Task 7: 后端评分 API

**Files:**
- Create: `backend/app/api/feedback.py`
- Modify: `backend/app/db/models.py`（Feedback 表）
- Test: `backend/tests/test_feedback.py`

**Interfaces:**
- Produces: `POST /api/v1/feedback` body `{session_id, rating}` → `{ok: true}`

- [ ] **Step 1: models.py 加 Feedback 表**（对齐现有 Base/engine 模式）
- [ ] **Step 2: api/feedback.py**：校验 `rating` 为 1-5，存库
- [ ] **Step 3: main.py 注册 router；写 test_feedback.py**（POST 合法 200 / 非法 rating 400）
- [ ] **Step 4: 全量 → 提交** `git commit -m "feat: 评分反馈 API"`

### Task 8: 前端会话列表 + 历史加载

**Files:**
- Modify: `frontend/components/SessionList.tsx`、`frontend/components/ChatWindow.tsx`、`frontend/app/page.tsx`
- Test: `frontend/tests/SessionList.test.tsx`（Task 13 搭测试框架后补，此处先实现）

**Interfaces:**
- Consumes: `GET /api/v1/sessions`（Task 6）
- Produces: SessionList 拉真实会话；`onSelect(sessionId)` 切换时 ChatWindow 从 `GET /api/v1/sessions/{id}/messages` 或复用 `get_history` 加载历史

- [ ] **Step 1: 前端加 `GET /api/v1/sessions/{id}/messages` 代理（lib/api.ts）**，或直接 fetch 后端（dev 时经 Next.js 无代理，直接请求 `http://localhost:8000` + `X-API-Key`）
- [ ] **Step 2: SessionList 用 fetch 拉列表渲染**，`onNew` 调后端无关（前端新建本地会话），`onSelect` 触发父组件切换
- [ ] **Step 3: page.tsx 持 sessionId → 切换时 ChatWindow 重新初始化消息（加载历史）**
- [ ] **Step 4: 浏览器手测**：新建/切换会话显示真实历史；`npm run build` 通过
- [ ] **Step 5: 提交** `git commit -m "feat: 前端真实会话列表与历史加载"`

### Task 9: 前端评分闭环

**Files:**
- Modify: `frontend/components/ChatWindow.tsx`、`frontend/lib/api.ts`

**Interfaces:**
- Consumes: `POST /api/v1/feedback`（Task 7）
- Produces: 1-5 星点击 → POST 成功后禁用

- [ ] **Step 1: 评分按钮 onClick 调 `POST /api/v1/feedback`**，成功后 `setRating` 并禁用
- [ ] **Step 2: 失败时保留可再点**（提示「提交失败」）
- [ ] **Step 3: build 通过 → 提交** `git commit -m "feat: 评分反馈前端闭环"`

---

## Phase C: 前端体验优化 + 前端测试

### Task 10: Markdown 渲染 + 生成光标

**Files:**
- Modify: `frontend/components/ChatWindow.tsx`、`frontend/package.json`

**Interfaces:**
- Produces: assistant 消息用 `ReactMarkdown` 渲染（`remark-gfm` 支持表格）；`busy` 时最后一条 assistant 消息尾部显示闪烁光标

- [ ] **Step 1: 装依赖** `npm i react-markdown remark-gfm`
- [ ] **Step 2: ChatWindow 中 assistant 消息内容**：user 消息保持纯文本，assistant 用 `<ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>`（外层 `prose` 类或自定义样式）
- [ ] **Step 3: busy 光标**：消息列表末尾加 `<span className="animate-pulse">▍</span>`（仅 busy 时）
- [ ] **Step 4: build 通过 → 浏览器验证**粗体/表格渲染；提交 `git commit -m "feat: 回答 Markdown 渲染 + 生成光标"`

### Task 11: 停止生成（AbortController）

**Files:**
- Modify: `frontend/lib/sse.ts`、`frontend/components/ChatWindow.tsx`

**Interfaces:**
- Produces: `streamChat(...)` 返回 `{ cancel }`；`AbortController` 中断 fetch

- [ ] **Step 1: sse.ts 内建 AbortController**，`fetch` 传 `signal`；`streamChat` 返回 `{ cancel }`，`onDone`/`onError` 兜底清理 busy
- [ ] **Step 2: ChatWindow 存 `cancelRef`**；`busy` 时输入区旁显示「⏹ 停止」按钮，点击 `cancel()` + `setBusy(false)`
- [ ] **Step 3: build → 手测**（生成中可中断）；提交 `git commit -m "feat: 流式生成可中断（AbortController）"`

### Task 12: 错误重试

**Files:**
- Modify: `frontend/components/ChatWindow.tsx`

**Interfaces:**
- Produces: `onError` 后该用户消息下方显示「重试」，点击重发该消息

- [ ] **Step 1: ChatWindow 记录**失败消息的 `retry` 状态（消息对象加 `failed: true` 或独立 state）
- [ ] **Step 2: 重试按钮**复用 `send(userText)` 重发，成功后清 failed
- [ ] **Step 3: build → 提交** `git commit -m "feat: 回答失败可重试"`

### Task 13: 前端测试（Vitest）

**Files:**
- Create: `frontend/tests/sse.test.ts`、`frontend/tests/MessageCard.test.tsx`、`frontend/tests/ChatWindow.test.tsx`
- Modify: `frontend/package.json`、`frontend/vitest.config.ts`

- [ ] **Step 1: 装依赖** `npm i -D vitest @testing-library/react @testing-library/jest-dom jsdom` + `vitest.config.ts`（react + jsdom 环境）
- [ ] **Step 2: sse.test.ts**：mock `global.fetch` 返回 ReadableStream，断言 `streamChat` 解析 token/card/sources/done、畸形帧跳过、`cancel` 可中断
- [ ] **Step 3: MessageCard.test.tsx**：order/logistics（含空数组「暂无物流轨迹」）/refund/未知形状不崩溃
- [ ] **Step 4: ChatWindow.test.tsx**：发送后自动滚动（mock scrollHeight）、错误重试按钮出现
- [ ] **Step 5: package.json 加 `"test": "vitest run"`**；跑通 `npm test` → 提交 `git commit -m "test: 前端 Vitest 测试（sse/card/chatwindow）"`

---

## Phase D: CI + 端到端收尾

### Task 14: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: 写 workflow**（backend pytest + frontend build 两 job；eval job 手动触发 + Secrets）

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

jobs:
  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -r backend/requirements.txt
      - run: python -m pytest backend/tests -q
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "24" }
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build
  eval:
    runs-on: ubuntu-latest
    needs: [backend]
    if: github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }
      - run: pip install -r backend/requirements.txt
      - run: python backend/scripts/build_kb.py
        env: { SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }} }
      - run: python -m eval.judge
        working-directory: backend
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
```

- [ ] **Step 2: 校验 YAML**（`python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`）
- [ ] **Step 3: 提交** `git commit -m "ci: GitHub Actions（pytest + build + 手动评测）"`

### Task 15: 端到端验证 + 全量回归 + 提交

- [ ] **Step 1: 全量后端 pytest**（`PYTHONIOENCODING=utf-8 ./.venv/Scripts/python -m pytest tests/ -q`，全绿）
- [ ] **Step 2: 前端 build + `npm test`**（build 通过 + Vitest 全绿）
- [ ] **Step 3: agent-browser 端到端**：① 真流式（消息逐字+生成中光标+可停止）② 会话新建/切换加载历史 ③ 评分提交 ④ 缓存命中「⚡ 命中语义缓存」 ⑤ 不存在订单不崩
- [ ] **Step 4: 重跑评测**（停后端 → `eval.judge` → 确认 92% 不掉 → 重启后端）
- [ ] **Step 5: 更新 README/CONTEXT**（真流式、会话、评分、CI、评测跑法）
- [ ] **Step 6: 合并所有 feature 分支到 main**；`git log` 确认全量提交；给用户完整总结
