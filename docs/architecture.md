# 电商售后智能客服 — 架构详解

> 面向「熟悉本项目架构」的完整文档。对应 main 分支当前代码（含真流式深化轮）。
> 阅读建议：先看「整体架构图」→ 再跟「一次请求数据流」→ 然后逐层深入。

---

## 0. 项目一句话

**带工具调用的电商售后智能客服**：用户问订单/物流/退款时，系统不止基于知识库回答，还能真实查订单、查物流、发起退款申请；回答为 SSE 真流式逐字输出；多 Agent 分工 + RAG + 前置质量闸门 + 商用工程化。

**技术栈**：Python 3.13 / FastAPI / LangGraph / openai SDK / Qdrant / SQLite(本地)·Postgres(Docker) / Redis / Next.js 16 / Tailwind / Docker Compose / GitHub Actions

---

## 1. 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│ 前端 Next.js 三栏工作台（:3000）                                  │
│  ChatWindow  消息区/流式渲染/停止/重试/评分                          │
│  SessionList 真实会话列表 + 切换加载历史                            │
│  ContextPanel 「RAG 知识命中」来源展示                              │
│  lib/sse.ts  SSE 协议解析 + AbortController 中断 + 逐 token 渲染    │
│  lib/api.ts  会话列表/历史/评分 API 封装                            │
└──────────────┬──────────────────────────────────────────────────┘
               │ fetch POST /api/v1/chat  (SSE 流式, X-API-Key)
┌──────────────▼──────────────────────────────────────────────────┐
│ API 层 FastAPI（:8000）  main.py                                 │
│  ObservabilityMiddleware: 鉴权(除/health) + 请求日志 + 延迟指标     │
│  routes: /chat(真流式)  /sessions(+/{id}/messages)  /feedback     │
└──────────────┬──────────────────────────────────────────────────┘
               │ chat.py gen() 编排
┌──────────────▼──────────────────────────────────────────────────┐
│ ① 语义缓存 cache_get(question) —— 命中直接返回（省 LLM）          │
│ ② 前置段 run_front() 同步执行                                     │
│     router_node → tool_node(order域) → retriever_node            │
│ ③ gate_decision 前置质量闸门                                     │
│     够资料 → writer 流式逐 token SSE                             │
│     不足   → 诚实兜底话术（整句）                                 │
│ ④ 缓存写入(仅无工具结果) + save_message 持久化                    │
└──────────────┬──────────────────────────────────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┬───────────────┐
   ▼           ▼           ▼              ▼               ▼
 LLM 层       RAG 层      工具层          会话/评分         观测
 llm.py     retrieve.py  order_tools    db/sessions.py   middleware
 重试/降级    hybrid+rerank dispatch→     save/get/list    metrics.py
 流式/工具     embed/vector  mock_db       models(表)      成本统计
              chunker     (4 工具)       feedback.py
```

---

## 2. 一次完整请求数据流

### 场景 A：查订单/物流（走工具调用 + 真流式）

```
用户: 查一下订单 20260811001 的物流
① ChatWindow.send() → streamChat(sse.ts) → fetch POST /api/v1/chat
② middleware: X-API-Key 校验通过 → 记日志
③ gen(): 发 SSE「thinking: 正在识别问题类别...」
④ cache_get(该问题) → 未命中（订单类不缓存）
⑤ run_front 前置段:
   router_node   → 关键词含"订单/物流" → domain=order
   tool_node     → LLM 提取订单号 + 选 query_logistics → mock_db 查到轨迹
                   → tool_results=[{...物流列表...}]
   retriever_node→ 检索 FAQ 佐证
⑥ gen(): 发「card: logistics」→ 前端渲染 🚚 物流轨迹卡片
⑦ gate_decision: order 且工具成功 → True → 流式段
⑧ build_writer_messages: 提示词强调「工具结果是权威，只基于它回答」
⑨ llm_chat(stream=True) → for chunk 逐 token → 前端 flushSync 逐字打字
⑩ 有工具结果 → 不写缓存；发 sources；save_message 持久化；发 done
```

### 场景 B：政策问答（RAG + 真流式）

```
用户: 七天无理由退货条件是什么？
①-③ 同上
④ cache_get 未命中
⑤ run_front: router→policy; tool→空; retriever→hybrid_search 召回→rerank top3
⑥ 无工具结果 → 无 card
⑦ gate_decision: policy 且 retrieved_chunks 非空 → True → 流式
⑧ writer 提示词放检索资料 → 流式回答（含 markdown 表格）
⑨ 无工具结果 → cache_set 写缓存（下次同问命中）
```

### 场景 C：缓存命中（第二次同问）

```
① 发 thinking
② cache_get 命中 → 发「⚡ 命中语义缓存」→ token(整句缓存答案) → save → done
③ 不经过前置段/LLM —— 提速约 20 倍（实测 5.1s → 0.25s）
```

### 场景 D：资料不足（诚实兜底，不编造）

```
例: 查不存在的订单 20260000000
⑤ tool_node → mock_db 返回 {"error": "订单不存在"}
⑦ gate_decision: order 工具 error → False → 兜底
⑧ llm_chat(stream=False) 整句：礼貌告知查不到 + 建议核对/转人工
（不流式——没有内容可流，且兜底话术短）
```

---

## 3. 分层详解

### 3.1 前端层（`frontend/`）

| 文件 | 职责 | 关键点 |
|------|------|--------|
| `components/ChatWindow.tsx` | 消息列表核心 | `flushSync` 逐 token 渲染；`cancelRef` 停止；`retry` 重试；`submitFeedback` 评分 |
| `components/SessionList.tsx` | 真实会话列表 | 挂载 fetch `/sessions`；`onSelect` 切会话 |
| `components/ContextPanel.tsx` | RAG 命中展示 | 显示检索来源 title/category |
| `components/MessageCard.tsx` | 工具结果卡片 | order/logistics/refund 三形态；**任意 data 形状不崩**（防御渲染） |
| `lib/sse.ts` | SSE 客户端 | `AbortController` 中断；`isAbortError` 区分主动取消；**token 帧间 `await 16ms` 让出浏览器 paint** |
| `lib/api.ts` | API 封装 | `fetchSessions` / `fetchHistory` / `submitFeedback` |

**真流式渲染关键**（两个层次的问题都解决）：
1. React 18 自动批处理合并同批 setState → `flushSync` 强制同步提交
2. 浏览器 paint 时机 → 一次 `reader.read()` 返回多帧时，同 JS 任务处理完所有 token，浏览器只在任务结束 paint 一次 → **token 帧间 `await setTimeout(16ms)`** 让出事件循环，形成打字机节奏

### 3.2 API 层（`backend/app/api/`）

| 文件 | 路由 | 说明 |
|------|------|------|
| `main.py` | — | 注册 4 router，前缀 `/api/v1`；CORS + Observability 中间件 |
| `middleware.py` | — | `ObservabilityMiddleware`：非 `/health` 强制 `X-API-Key`（hmac 比较）；请求日志 `req=... path=... status=... latency_ms=...`；记录延迟指标 |
| `chat.py` | `POST /chat` | **编排核心**（见 §4） |
| `sessions.py` | `GET /sessions` `GET /sessions/{id}/messages` | 会话列表（倒序+preview）与历史（复用 `get_history` limit=50） |
| `feedback.py` | `POST /feedback` | 校验 rating∈[1,5] 否则 400；`save_feedback` 存库返回 `{ok:true}` |
| `health.py` | `GET /health` | 健康检查（鉴权豁免） |

### 3.3 Agent 节点层（`backend/app/agents/nodes.py`）

多 Agent 的「角色」——每个节点是纯函数，输入 state dict，输出增量写入 state：

| 节点 | 职责 | 确定性 or LLM |
|------|------|--------------|
| `router_node` | 关键词分类：含「你好/在吗/谢谢」→chitchat；含「订单/物流/发货」→order；否则 policy | **规则**（省 token、稳定） |
| `tool_node` | order 域：`chat_with_tools` 让 LLM 提取订单号+选工具 → `order_tools.dispatch` 执行 → JSON 解析 | **LLM 工具调用** |
| `retriever_node` | `hybrid_search` + `rerank`；异常兜底 `[]`（绝不中断流程） | 混合检索 |
| `gate_decision` | 前置闸门：chitchat 恒通过；order 看工具结果非 error；其他看检索非空 | **规则** |
| `build_writer_messages` | 组装 writer 提示词（按域分 4 分支，见下） | — |
| `writer_node` | 同步生成（供评测 `run_agent` 用） | LLM |

**`build_writer_messages` 的 4 个分支**（决定提示词怎么组装）：
1. **chitchat**：寒暄 → 简短回应 + 引导提售后问题
2. **order + 工具成功**：工具结果是权威，「只基于工具结果回答，不被检索干扰」
3. **无检索**：诚实话术「没找到相关说明，可转人工，不编造」
4. **有检索**：拼接 top3 检索块 → 基于资料回答

### 3.4 能力层

**LLM 层 `app/llm.py`**
- `_retry`：主模型指数退避重试 3 次（`sleep(2^attempt)`）→ 失败降级备用模型
- `chat(messages, stream=False)`：非流式，记录 token 用量
- `chat(messages, stream=True)`：返回 openai 流式迭代器（`_finalize` 原样返回）
- `chat_with_tools(messages, tools)`：非流式 + 解析 `tool_calls` → `[{name, arguments}]`

**RAG 层 `app/rag/`**（完整见 `docs/rag-notes` 或本文 §5）
- `chunker.py`：frontmatter 解析 + 字符级滑动窗口分块（400 字 / 50 重叠）
- `embed.py`：bge-m3 embedding（SiliconFlow，1024 维）
- `vector_store.py`：Qdrant 本地/远程抽象，COSINE，payload 存元数据
- `retrieve.py`：`hybrid_search`（向量召回 + 关键词加权）→ `rerank`（精排 top3）

**工具层 `app/tools/`**
- `order_tools.py`：4 个工具 schema（query_order/query_logistics/request_refund/escalate_to_human）+ `dispatch(name,args)` 统一入口，未知/异常返回 `{"error":...}` 不让上层崩
- `mock_db.py`：SQLite mock 订单/物流/退款数据；`get_order` 未命中返回 None

### 3.5 基础设施层

**语义缓存 `app/cache.py`**
- key = `md5(question)`（**精确匹配**，非语义）
- Redis 可用则 Redis（TTL 1h），运行时故障**自动降级内存**
- 仅缓存无工具结果的确定性问答（订单状态会变，不缓存）

**会话/评分 `app/db/`**
- `models.py`：SQLAlchemy，`Message`/`Feedback` 表；`create_all` import 时建表；DB 抽象（SQLite 本地 / Postgres Docker）
- `sessions.py`：`save_message` / `get_history` / `list_sessions`（id 倒序近似时间）

**观测 `app/metrics.py` + `middleware.py`**
- 线程安全计数器：requests / avg_latency_ms / total_tokens / 估算成本
- 暴露在 `GET /api/v1/metrics`

---

## 4. 编排核心：`chat.py` 的 `gen()`（真流式）

关键设计：**拆 LangGraph 一次性 invoke → 前置段同步 + 流式段**。

```python
async def gen():
    yield thinking("正在识别问题类别...")
    cached = cache_get(req.message)          # ① 缓存（try 内，异常不逃逸）
    if cached:
        yield thinking("⚡ 命中语义缓存"); yield token(cached); yield done; return
    st = run_front(...)                      # ② 前置段：router→tool→retriever
    for tool in st["tool_results"]:          #   发 card 事件（工具卡片）
        kind = _kind_of(tool); yield card
    if gate_decision(st):                    # ③ 闸门
        for chunk in llm_chat_stream(msgs):  #   真流式逐 token
            if chunk.choices: yield token(delta.content)   # 跳过 usage 空块
    else:
        answer = llm_chat(msgs)              #   兜底整句
        yield token(answer)
    if not st["tool_results"]: cache_set(...) # ④ 缓存（仅确定性）
    yield sources; save_message(...)         #   sources + 持久化
    yield done
```

**为什么这样拆**：路由/工具/检索不产生大文本（毫秒级），只有写作需要流式——所以前置同步跑，写作边生成边推。评测 `run_agent` 保留同步接口（前置 + 非流式 writer）复用同一套节点函数。

---

## 5. RAG 全链路详解

```
语料构建（离线一次，scripts/build_kb.py）：
knowledge_base/*.md（12 篇，frontmatter: title/category/order）
  → chunk_markdown: 解析 frontmatter + 滑动窗口分块(400/50)
  → embed_texts: bge-m3 → 1024 维
  → VectorStore.add: 向量+payload 存 Qdrant

查询链路（在线）：
question → embed → Qdrant 向量召回 top20（COSINE）
  → _keyword_boost: score = 向量分×0.6 + 关键词命中数×0.4（简化启发式，非标准 BM25）
  → rerank: bge-reranker-v2-m3 交叉编码精排 → top3
  → 送 writer
```

**设计权衡**：
- 分块 400/50：字符级滑动窗口（诚实：非语义分块），重叠防边界切断
- 混合检索：向量管语义 + 关键词管字面精确匹配
- rerank 取 top3：控制送入 LLM 的 token 量
- 评测集 25 题验证准确率 96%

---

## 6. 关键设计决策（面试重点）

1. **真流式 = 前置同步 + 写作流式**：不产生大文本的步骤同步跑，只有写作流式
2. **前置质量闸门替代打回循环**：真流式下「生成完再打回」不可能（已发出）→ 生成前判定资料够不够；评测 92%→96%（order 域提升）
3. **确定性 vs LLM 分工**：路由/闸门用规则（稳省 token），工具/写作用 LLM（需理解）
4. **环境抽象**：Qdrant/DB/Redis 一套代码两后端（本地文件 vs Docker 服务），环境变量切换
5. **纵深防御**：工具 error 不推卡片（后端）+ 前端卡片任意 data 形状不崩；LLM 重试降级；DB 写失败不破坏 SSE

---

## 7. 目录结构总览

```
llm-job-prep/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + 路由注册
│   │   ├── middleware.py      # 鉴权/日志/指标
│   │   ├── config.py          # 全部配置（Key/模型/URL）
│   │   ├── llm.py             # LLM 封装：重试/降级/流式/工具
│   │   ├── cache.py           # 语义缓存（Redis/内存降级）
│   │   ├── metrics.py         # 请求/成本指标
│   │   ├── api/               # chat / sessions / feedback / health
│   │   ├── agents/            # nodes.py 多Agent + graph.py(评测) + state.py
│   │   ├── rag/               # chunker / embed / vector_store / retrieve
│   │   ├── tools/             # order_tools + mock_db
│   │   └── db/                # models + sessions
│   ├── knowledge_base/        # 12 篇语料（5 类）
│   ├── eval/                  # judge.py + questions.json（评测管线）
│   ├── scripts/               # build_kb.py（建索引）/ seed_mock.py
│   ├── tests/                 # 50 个 pytest
│   └── Dockerfile + entrypoint.sh
├── frontend/
│   ├── app/ components/ lib/  # Next.js 工作台 + sse.ts + api.ts
│   ├── tests/                 # 16 个 Vitest
│   └── Dockerfile
├── docs/                      # 本文档 + superpowers（spec/plan）
├── docker-compose.yml         # qdrant + postgres + redis + backend + frontend
├── .github/workflows/ci.yml   # pytest + vitest + build（eval 手动触发）
└── README.md / CONTEXT.md
```

---

## 8. 已知局限（面试诚实清单）

- 分块是字符级滑动窗口（非语义分块），可能切断表格
- `_keyword_boost` 是字符命中简化启发式，非标准 BM25
- 缓存是精确 md5 匹配（非语义缓存）
- 评测集仅 25 题，96% 统计波动大（错 1 题掉 4%）
- `run_front`/流式同步阻塞事件循环（demo 可接受，真并发是瓶颈）
- 单 `_client` 固定 DeepSeek，降级切 SiliconFlow 时未按 provider 拆 client
