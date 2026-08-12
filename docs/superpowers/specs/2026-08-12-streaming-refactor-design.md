# 真流式重构 + 会话闭环 + CI 设计

日期：2026-08-12
状态：已批准（用户确认方案 A）
备份点：`v1.0-pre-streaming`（回滚用 `git checkout v1.0-pre-streaming`）

## 背景与目标

项目已完成（多 Agent + RAG + 工具调用 + 评测 92% + 语义缓存）。深化方向选 **B 工程硬实力**：
1. **真流式**：消除「伪流式」露馅点（LLM 调用仍是阻塞式，前端是逐字回放而非真生成）
2. **会话闭环**：`save_message`/`get_history` 模块存在但从未接线，前端 SessionList 是硬编码假会话
3. **CI 文件**：补 GitHub Actions workflow 备用（配好远端即点亮真 CI）
4. **前端优化**：Markdown 渲染、停止生成、生成光标、错误重试、评分闭环、前端测试

已有成果**全部保留**：多 Agent 节点、RAG（bge-m3 + Qdrant 混合检索 + rerank）、工具调用、评测管线、语义缓存、SSE 前端。

## 现状与问题

| 问题 | 现状 | 后果 |
|------|------|------|
| 伪流式 | `chat.py:gen()` 同步调 `graph.invoke()`，完整答案生成完再逐字回放 | 首 token 延迟=完整生成时间（5-10s）；面试被问「stream=True 吗 / TTFT」即露馅；无流式中断/断开处理 |
| 审核与流式互斥 | reviewer 打回循环要求「生成完→打回→重写」，与「边生成边推」冲突 | 需改为前置质量闸门 |
| 假会话 | `save_message`/`get_history` 零调用点；`SessionList.tsx` 硬编码 `["会话 1","会话 2","会话 3"]`，`onSelect` 空实现 | 后端有持久化但前端假列表，简历「会话持久化」名不副实 |
| 无 CI | 无 `.github/workflows/` | 测试/评测全靠手动 |

## 设计

### 一、真流式 + 前置质量闸门

**编排重构**：拆掉「graph 一次 invoke + 打回循环」，改为两段：

```
chat.py gen()（SSE）
├─ 前置段（同步，快，不产生大文本）：
│   router_node → tool_node(order域) → retriever_node → 前置闸门
│   闸门判定：
│   ├─ 资料足够（order工具成功 或 有检索命中）→ 进入流式段
│   └─ 资料不足（order工具error 或 检索空）→ 发诚实兜底话术（短文本，不流式）
└─ 流式段：
    writer 用 llm.chat(msgs, stream=True) 边生成边 SSE 推 token
    （`for chunk in resp:` 取 `choices[0].delta.content`）
```

**关键决策**：
- **前置闸门用确定性判定**（不引入额外 LLM 预检调用）：order 域工具成功即放行（工具结果权威）；policy/product 有 `retrieved_chunks` 即放行；否则兜底。这保留「不编造」的诚实性，移除打回循环。
- **`run_agent` 保留**同步接口（前置段 + `chat(stream=False)` writer），供评测 judge.py 与现有测试复用，返回结构不变（`draft_answer`/`tool_results`/`retrieved_chunks`）。
- **reviewer 打回逻辑移除**（`review_status`/`iteration`/`review_comment` 不再作为回答路径）；对应 `test_graph.py` 的 3 个打回测试迁移为闸门测试。
- **语义缓存保留**：命中时仍直接返回（缓存的是完整答案，不冲突）。
- **流式中断兜底**：writer 流式若中途异常，SSE 发 error 事件（沿用现有 `gen()` 的 try/except 结构）。

### 二、会话闭环

后端（`app/db/sessions.py` 已有模块，接线）：
- `chat.py` 每次对话结束调用 `save_message(session_id, "user", message)` 与 `save_message(session_id, "assistant", answer)`（流式命中缓存也保存）。
- 新增 `GET /api/v1/sessions`：返回会话列表（`[{session_id, updated_at, preview}]`，按时间倒序）。
- 复用 `get_history(session_id, limit)` 供前端加载历史。

前端：
- `SessionList.tsx`：改为从 `GET /api/v1/sessions` 拉列表；`onNew` 新建；`onSelect(sessionId)` 切换。
- `ChatWindow.tsx`：切换会话时通过后端 `get_history` 接口加载历史消息初始化 `messages`。
- 新会话的当前历史随 `streamChat` 的 `history` 字段传递（现有 `run_agent` 已接收 history）。

### 三、CI 文件

`.github/workflows/ci.yml`：
- `backend` job：checkout → setup-python 3.13 → pip install -r requirements.txt → `pytest -q`
- `frontend` job：setup-node 24 → npm ci → `npm run build`
- `eval` job（可选）：`workflow_dispatch` 手动触发；需 Secrets `DEEPSEEK_API_KEY`/`SILICONFLOW_API_KEY`；跑评测需先建索引（`scripts/build_kb.py`）；注：CI 干净环境无 Qdrant 并发冲突，评测可用。

### 四、前端优化（配合真流式）

| 项 | 实现 | 说明 |
|----|------|------|
| **Markdown 渲染** | 引入 `react-markdown` + `remark-gfm` | assistant 消息内容用 Markdown 渲染（粗体/列表/表格/代码块）；user 消息保持纯文本。流式 token 增长时重复渲染可接受（文本量小） |
| **停止生成** | `sse.ts` 的 `streamChat` 改用 `AbortController`，返回 `{ cancel }`；ChatWindow 生成中显示「停止」按钮，点击 `cancel()` 中断 fetch | 真流式配套，面试可讲中断处理 |
| **生成中光标** | `busy` 状态时最后一个 assistant 消息尾部显示 CSS 闪烁光标 /「正在生成…」 | 流式感知 |
| **错误重试** | `onError` 时该消息下方显示「重试」按钮，点击重发该用户消息 | 不干等 |
| **评分闭环** | 新增 `POST /api/v1/feedback`（`session_id` + `rating`），前端 1-5 星点击后调后端记录（存 DB），已评后禁用 | 反馈数据驱动优化，面试可讲 |
| **前端测试** | Vitest + Testing Library + jsdom；覆盖 `sse.ts` 解析（mock fetch）、`MessageCard` 各卡片渲染、ChatWindow 滚动/错误重试 | 补「0 前端测试」缺口 |

### 五、测试与验证策略

- TDD：先写失败测试再实现
- 新增/迁移测试：
  - 闸门：资料足→流式段；资料不足→兜底文本（迁移原打回测试）
  - 真流式：`llm.chat(stream=True)` 返回迭代器并逐 token 产出（test_llm.py）
  - 会话：save_message 被调用、列表接口返回、历史加载
  - 缓存：命中时也保存会话消息
- **重跑 25 题评测**，确认 92% 不掉；若下降，迭代闸门判定/prompt
- 全量 `pytest` 全绿 + 前端 `npm run build` 通过 + agent-browser 端到端复验（流式真打字、会话切换、缓存命中）

## 文件变更清单

后端：
- `backend/app/api/chat.py`：编排重构（前置段+流式段+会话保存）
- `backend/app/agents/nodes.py`：writer 支持 stream 参数；移除 reviewer 打回路径
- `backend/app/agents/graph.py`：`run_agent` 保留同步接口（前置段 + 非流式 writer）
- `backend/app/api/sessions.py`（新）：`GET /api/v1/sessions` + db 层 `list_sessions()`
- `backend/app/api/feedback.py`（新）：`POST /api/v1/feedback` 记录评分
- `backend/app/db/sessions.py`：加 `list_sessions()`；确认 save 调用点
- `backend/tests/test_chat.py`、`test_graph.py`、`test_llm.py`、新增 `test_sessions.py`、`test_feedback.py`

前端：
- `frontend/lib/sse.ts`：AbortController + 返回 `{ cancel }`
- `frontend/components/ChatWindow.tsx`：Markdown 渲染、停止按钮、生成光标、错误重试、评分闭环、历史加载
- `frontend/components/SessionList.tsx`：真实会话列表
- `frontend/package.json`：新增 react-markdown、remark-gfm、vitest 等依赖
- `frontend/tests/`（新）：`sse.test.ts`、`MessageCard.test.tsx`、`ChatWindow.test.tsx`

CI：
- `.github/workflows/ci.yml`（新）：backend pytest + frontend build + eval（手动触发，Secrets）

## 回滚

任何时间点 `git checkout v1.0-pre-streaming` 回滚到重构前完整状态。
