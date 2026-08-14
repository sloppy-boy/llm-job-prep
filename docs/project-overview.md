# 电商售后智能客服 —— 项目全案

> **用途**：把项目跨多轮对话（2026-08-11 → 2026-08-14）的全部工作、决策、排障、成绩整理成一份完整文档，供复习与面试准备。
> **对应代码**：main 分支当前状态。测试全绿：后端 129 pytest + 前端 19 vitest。
> **阅读路径**：本文档总览 → `docs/architecture.md`（代码架构逐层详解）→ `docs/optimization-todo.md`（差距与 roadmap）。

---

## 一、项目定位

**一句话**：一个带**工具调用**的电商售后智能客服——用户问订单/物流/退款时，系统不止基于知识库回答，还能**真实查订单、查物流、发起退款申请**，并带多 Agent 协作与**知识自增长闭环**。

**核心差异化**：机器人能「办事」不只是「说话」。区别于纯文档问答（=网页版 DeepSeek），这是有动作能力的智能体。

**项目性质**：大模型应用开发岗位的求职作品集（非商业项目）。目标是用**一个项目的深度**换面试的宽度——做深做透，能应对追问。

**作者背景**（面试第二故事）：RK3588S + YOLO 水果分拣毕设（嵌入式/CV，体现工程能力）；OpenClaw 做过较复杂 Agent 项目；有 LangChain 基础。

---

## 二、技术栈

| 层 | 选型 |
|----|------|
| 前端 | Next.js 16 (Turbopack) + React 19 + Tailwind，三栏客服工作台 |
| 后端 | FastAPI (Python 3.13) + pydantic-settings，SSE 真流式 |
| 编排 | LangGraph（节点式多 Agent） |
| 对话模型 | DeepSeek `deepseek-chat`（主），指数退避重试 3 次后降级备用模型 |
| Embedding | `BAAI/bge-m3`（SiliconFlow，1024 维） |
| Rerank | `BAAI/bge-reranker-v2-m3`（SiliconFlow，精排 top3） |
| 向量库 | Qdrant（本地文件模式 / Docker 服务，一套代码两后端） |
| 数据 | SQLite（本地会话/mock 订单）· Postgres（Docker 会话）· Redis（缓存/限流） |
| 测试 | pytest（后端 129）+ Vitest + Testing Library（前端 19） |
| CI/部署 | GitHub Actions + Docker Compose（qdrant+postgres+redis+backend+frontend） |

---

## 三、系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│ 前端 Next.js 三栏工作台（:3000）                              │
│  ChatWindow  消息区/SSE流式渲染/停止/重试/评分/转人工弹窗        │
│  SessionList 真实会话列表 + 切换加载历史                       │
│  ContextPanel「RAG 知识命中」来源展示                          │
│  lib/sse.ts  SSE 协议解析 + AbortController 中断 + 逐token渲染 │
│  lib/api.ts  会话/历史/评分/回填 API 封装                      │
└──────────────┬──────────────────────────────────────────────┘
               │ fetch POST /api/v1/chat (SSE, X-API-Key)
┌──────────────▼──────────────────────────────────────────────┐
│ API 层 FastAPI（:8000）                                      │
│  RateLimitMiddleware（令牌桶·API Key 全局）→ ObservabilityMiddleware（鉴权/日志/指标） │
│  routes: /chat(真流式) /sessions /feedback /kb/* /human-reply │
└──────────────┬──────────────────────────────────────────────┘
               │ chat.py gen() 编排
┌──────────────▼──────────────────────────────────────────────┐
│ ① 语义缓存 cache_get —— 命中直接返回（省 LLM）                 │
│ ② 前置段 run_front() 同步执行                                  │
│     router_node → tool_node(order域) → retriever_node          │
│ ③ 用户层限流（按 user_id）+ gate_decision 前置质量闸门          │
│     够资料 → writer 流式逐 token SSE                           │
│     不足   → human_handoff 事件 + 诚实兜底（不写缓存）          │
│ ④ 缓存写入(仅资料够且无工具) + save_message(带 meta) 持久化      │
└──────────────┬──────────────────────────────────────────────┘
               │
   ┌───────────┼───────────┬──────────────┬───────────────┐
   ▼           ▼           ▼              ▼               ▼
 LLM 层       RAG 层      工具层          会话/评分        知识库闭环
 llm.py     retrieve.py  order_tools    db/sessions.py  kb.py
 重试/降级    hybrid+rerank dispatch→     save/get/list   draft/approve/
 流式/工具     embed/vector  mock_db     models(表)       reindex/pending
             chunker     (4 工具)        feedback.py      auto_suggest
             (稳定ID/草稿)               (meta 列)
```

### 3.2 一次请求数据流

```
用户：查一下订单 20260811001 的物流
① ChatWindow.send() → streamChat(sse.ts) → fetch POST /api/v1/chat
② RateLimitMiddleware（按 API Key 限全局）→ Observability（鉴权+日志）
③ gen(): 发 SSE「thinking」；chat 内按 user_id 二次限流
④ cache_get(问题) → 订单类不缓存 → 未命中
⑤ run_front 前置段：
   router_node   → 关键词含"订单/物流" → domain=order
   tool_node     → LLM 提取订单号 + 选 query_logistics → mock_db 查轨迹
                   → tool_results=[{...物流...}]
   retriever_node→ 检索 FAQ 佐证
⑥ 发「card: logistics」→ 前端渲染 🚚 物流卡片
⑦ gate_decision: order 且工具成功 → True → 流式段
⑧ build_writer_messages: 提示词「工具结果是权威，只基于它回答」
⑨ llm.chat(stream=True) → 逐 token SSE → 前端 flushSync 逐字打字
⑩ 有工具结果 → 不写缓存；发 sources；save_message(带 meta)；发 done
```

### 3.3 分层模块

| 层 | 关键文件 | 职责 |
|----|---------|------|
| 前端 | `components/ChatWindow.tsx` `lib/sse.ts` `lib/api.ts` | 流式聊天、停止、重试、评分、转人工弹窗（回复→沉淀→发布） |
| API | `api/chat.py` `api/kb.py` `api/sessions.py` `api/feedback.py` | 编排 + 知识库接口 + 会话 + 评分 |
| Agent | `agents/nodes.py` | 路由/工具/检索/闸门/写作（节点化纯函数） |
| RAG | `rag/chunker.py` `retrieve.py` `vector_store.py` | 结构分块、混合检索+rerank、稳定 ID 向量库 |
| 工具 | `tools/order_tools.py` `data_source.py` `mock_db.py` | 查单/物流/退款/转人工（数据源抽象注入） |
| 知识库闭环 | `kb.py` | 沉淀草稿/审核发布/重索引/自动沉淀 |
| 基础设施 | `cache.py` `db/` `metrics.py` `ratelimit.py` | 缓存/持久化/观测/限流 |

---

## 四、三轮演进史（全部工作脉络）

### 轮 1：地基搭建（2026-08-11 ~ 08-12，14 任务）

**做了什么**：
- 自建语料 `knowledge_base/`（12 篇 / 5 类：policies/logistics/products/misc），**故意埋硬骨头**（大表格运费表、嵌套条款、长条款）制造分块与检索优化空间
- mock 订单库（SQLite：orders/logistics/refunds）
- FastAPI 骨架 + API Key 鉴权 + 请求日志 + 指标
- RAG 模块：分块 → bge-m3 向量化 → Qdrant → 混合检索 + rerank
- LangGraph 多 Agent：路由 → 检索 → 工具执行 → 写作 → 审核（打回循环 ≤2 次）
- SSE 流式 + 语义缓存 + 会话持久化 + Docker Compose
- 评测管线：25 题 / 5 类 / LLM-as-judge 四维打分

**成绩**：后端 29 pytest；评测 76% → 92%（工具修复后）

**关键排障**：order 域工具生产不可用——DeepSeek 返回 `tool_calls` 但 content 空，`_finalize` 丢弃 tool_calls → 单独修复分支；Qdrant 本地索引被后端占用导致静默空检索（假性准确率暴跌）→ 加自检。

### 轮 2：真流式重构 + 会话闭环（2026-08-12，15 任务）

**做了什么**：
- **真流式**：拆「graph 一次性 invoke + 逐字回放」→「前置段（路由/工具/检索/闸门）同步 + 写作流式逐 token」；`run_agent` 保留同步接口供评测
- **审核改造**：打回循环 → **前置质量闸门**（确定性判定：order 工具成功 / 有检索命中 → 流式；否则诚实兜底）
- **会话闭环**：`save_message` 接线 + `GET /sessions` + 前端会话列表/历史加载
- **评分闭环**：`POST /feedback` + 前端 1-5 星
- **前端体验**：react-markdown 渲染、停止生成（AbortController）、生成光标、错误重试
- **前端测试**：Vitest 16 用例
- **CI**：GitHub Actions（pytest + build 自动、评测手动触发）

**成绩**：评测 92% → **96%**（order 域 80%→100%）；后端 54 pytest + 前端 16 vitest

**关键排障**（面试弹药）：
1. 流式 `usage` 末块 `choices` 空数组 → IndexError（加防护 + 回归测试）
2. 打字效果"一次性蹦出"：React 批处理 + 一次 `reader.read()` 返回多帧同 JS 任务处理 → `flushSync` 强制同步 + **token 帧间 `await 16ms` 让出浏览器 paint**

### 轮 3：优化轮 2（2026-08-13 ~ 14，16 任务 = 本轮）

**做了什么**（两个 feature 分支，全流程子代理驱动 + 评审）：
- **P0 技术硬伤修复**（5 项）：事件循环阻塞（`asyncio.to_thread` 卸载阻塞调用）、结构感知分块（标题/段落/表格）、真 BM25 + jieba 混合检索、语义缓存（精确 + 余弦扫描）、死代码清理
- **优化 #1 数据源抽象 + 订单归属校验**：`OrderDataSource` 契约 + `MockOrderDataSource` 注入；订单加 `user_id` 归属校验（A 不能查 B 的单）
- **限流**：令牌桶 + `RateLimitStore`（Redis Lua 原子 / 内存锁降级）；`RateLimitMiddleware` 全局按 Key + `/chat` 按 user_id 双层；429 四头 + metrics 拒绝计数
- **Obsidian 知识库治理**：`knowledge_base/` 即 vault；`POST /kb/reindex` 热重索引（跳 draft）；`GET /kb/docs`；**稳定 ID**（`md5(path:page) % 2**64` 内容寻址，增量幂等、压回 Qdrant u64）
- **回填闭环**（自增长知识库核心）：SSE `human_handoff` → 前端转人工弹窗 → 人工回复 → `draft_doc`（LLM 提炼成规范条目，强制 `status: draft`）→ `approve`（发布 → 摄入 RAG + 刷新 BM25）→ **重问命中**
- **评分 5★ 自动沉淀**：消息表 `meta` 列记 `{domain, had_tools, cached}` → 5★ 且 policy/无工具/非缓存 → 自动生成草稿候选
- **相关度闸门**：policy 域 gate 从「有 chunk 就过」改为「top 重排相关度 ≥ 0.60 才过」→ 真·知识缺口触发转人工

**成绩**：后端 **129 pytest** + 前端 **19 vitest** 全绿；评测需重跑确认不回归

**本轮实测又修 5 个真 bug**：
1. chat 兜底 `False` 落进 `tools` 位置参（`llm.chat(msgs, False)` 第二参是 tools）→ DeepSeek 400 `tools: boolean false`
2. 兜底/转人工回答误写缓存 → 回填发布后重问命中过时"答不出"
3. policy 闸门只看命中数 → 知识缺口不触发转人工（相关度闸门解决）
4. reindex 新建 `VectorStore()` 与运行中后端 qdrant_local 持锁冲突 → 复用单例
5. approve 正则 `\s*` 吞 status 行尾换行 → `status: published---` 粘连

---

## 五、当前功能清单（最终状态）

| 能力 | 说明 |
|------|------|
| 流式聊天 | SSE 真流式逐 token、停止、重试、Markdown、评分 1-5 星 |
| 工具调用 | 查订单/查物流/发起退款/转人工；数据源抽象注入；订单归属校验 |
| RAG | 结构感知分块、向量+BM25 混合检索、rerank 精排、相关度闸门、语义缓存、引用溯源 |
| 会话闭环 | 会话持久化、真实会话列表、历史加载 |
| 限流 | 令牌桶双层（API Key 全局 + user_id 用户）、Redis Lua/内存降级、429 标准头 |
| 知识库治理 | Obsidian vault、热重索引（跳 draft）、文档列表、稳定 ID |
| 回填闭环 | 答不出→转人工→人工回答→LLM 沉淀草稿→审核发布→RAG 摄入→下次命中 |
| 自动沉淀 | 5★ 评分 → 自动生成草稿候选（policy/非工具/非缓存） |
| 观测 | 请求/延迟/token/成本指标、拒绝计数、请求日志 |
| 工程 | CI（pytest+vite+build+评测）、Docker Compose、评测管线 |

---

## 六、关键设计决策（面试重点）

1. **真流式 = 前置同步 + 写作流式**：不产生大文本的步骤（路由/工具/检索）同步跑，只有写作边生成边推；首 token 延迟 ≈ 前置段耗时而非完整生成时间
2. **前置质量闸门替代打回循环**：真流式下"生成完再打回"不可能（已发出）→ 生成前确定性判定资料够不够；评测 92%→96%
3. **确定性 vs LLM 分工**：路由/闸门用规则（省 token、稳定、可测）；工具/写作用 LLM（需理解）
4. **审核 gate 是真机制**：`status: draft` 不进检索（reindex/BM25/build_kb 三路都跳过），approve 才摄入——防止错误答案污染知识库；写盘强制 draft + title 转义 `---` 防绕过（评审实测四种绕过全封死）
5. **稳定 ID 内容寻址**：`md5(path:page) % 2**64`——增量摄入幂等、编辑后覆盖不留孤儿、压回 Qdrant u64 范围（128-bit 直接转 int 在 grpc 会越界）
6. **限流两层 + 原子性**：全局按 Key 中间件 + 用户层在 chat；Redis 用 Lua 保证 read-modify-write 原子（分布式并发不重复放行），内存用锁同语义；故障失败开放（可用性优先）
7. **相关度闸门**：policy 域看 top 重排真实相关度 ≥ 0.6 而非"有 chunk 就过"——真·知识缺口才触发转人工
8. **环境抽象**：Qdrant/DB/Redis 一套代码两后端（本地文件 vs Docker），环境变量切换；数据源接口抽象（接真实 ERP 只写新实现替换注入）
9. **纵深防御**：工具 error 不推卡片 + 前端卡片任意 data 形状不崩；LLM 重试降级；DB 写失败不破坏 SSE；限流器/检索失败不 500
10. **诚实兜底**：资料不足明确说不知道 + 建议转人工，绝不编造（系统提示词 + 闸门双保险）

---

## 七、关键排障故事（面试弹药）

| # | 问题 | 根因 | 解法 |
|---|------|------|------|
| 1 | 评测 92%→40% 假崩 | Qdrant 本地索引被后端占用 → 静默空检索 | 评测自检：被占用直接报错 |
| 2 | 流式末块 IndexError | `include_usage` 的 usage 块 `choices` 为空数组 | `if not chunk.choices: continue` + 回归测试 |
| 3 | 回答一次性蹦出 | React 批处理 + 一次 read() 返回多帧同任务处理 | `flushSync` + token 帧间 `await 16ms` 让浏览器 paint |
| 4 | order 工具生产不可用 | DeepSeek 返回 tool_calls 但 content 空，`_finalize` 丢弃 | 修复工具调用解析 + 权威化 writer |
| 5 | chat 兜底 400 | `_blocking(llm_chat, msgs, False)` 的 `False` 落进 `tools` 位置参 | 改 `stream=False` 关键字 + 回归测试 |
| 6 | 回填后重问命中过时答案 | 兜底回答也被写缓存 | 仅缓存"资料够"的确定性回答 |
| 7 | 知识缺口不触发转人工 | gate 只看 `bool(retrieved_chunks)`，rerank 永远返回 top3 | 相关度闸门（top 分 ≥0.6） |
| 8 | reindex 与运行中后端冲突 | `VectorStore()` 新建 client 再开 qdrant_local 锁 | 复用 `get_store()` 单例 |
| 9 | frontmatter 粘连 | approve 正则 `\s*` 含 `\n` 吞掉 status 行尾换行 | 改 `[^\S\n]` 仅水平空白 |
| 10 | 向量 ID 超 u64 | `md5(...)` 128-bit 直接转 int，grpc 越界 | `% 2**64` 取模压回 |
| 11 | 回填环静默停摆 | 防重用归一化融合分（BM25 命中时 top 恒 1.0）误判 exists | 改用向量原始余弦 ≥0.90 |
| 12 | gate 被绕过 | LLM 输出 published/省略 frontmatter/`---` 注入 | 写盘强制 draft + title 转义 + 正则容错 |

---

## 八、工程质量体系

- **流程**：GitHub Flow（feature 分支 → 实现 → 评审 → 合并 main）；子代理驱动开发（SDD）——每任务独立实现子代理 + 独立评审（spec 合规 + 代码质量双结论），整支最终评审把关
- **方法**：TDD 红绿循环（先失败测试 → 实现 → 全绿 → 提交）
- **测试**：后端 129 pytest（限流/闸门/草稿过滤/稳定 ID/审核 gate/SSE/meta/自动沉淀）+ 前端 19 vitest（SSE 解析/卡片/聊天窗口/弹窗流程）+ build
- **CI**：`.github/workflows/ci.yml`（pytest + build 自动；评测手动触发，配 Secrets 即用）
- **评测**：25 题 / 5 类 / LLM-as-judge 四维打分，96%（样本小，面试如实回应 + 强调 5 类覆盖率）
- **文档**：CONTEXT.md（会话记忆）、docs/（本全案 + architecture + optimization-todo + superpowers spec/plan）、SDD 账本 `.superpowers/sdd/progress.md`

---

## 九、面试叙事

**3 句话**：
1. 这是一个带工具调用的电商售后智能客服：问订单/物流/退款时，系统能真实查单、查物流、发起退款，并带多 Agent 协作。
2. 技术栈是 RAG + LangGraph 多 Agent + Function Calling + 商用工程化：检索路由→向量召回→工具执行→相关度闸门→SSE 真流式写作，叠加限流、语义缓存、会话/评分闭环、知识自增长闭环（答不出→人工→沉淀→审核→发布→下次命中）。
3. 关键数据：自建 25 题评测集准确率 96%，129 pytest + 19 vitest 全绿，Docker Compose 一键部署。

**被追问弹药**：为什么用多 Agent？（分工、可测、可替换）怎么防死循环？（闸门确定性判定替代打回）成本怎么控？（语义缓存 + 路由规则 + 检索 top3 控 token + 限流）检索怎么优化？（分块策略对比 → 混合检索 → rerank → 相关度闸门，准确率轨迹 56%→92%→96%）生产还差什么？（见下节诚实清单）

**第二故事**：RK3588S + YOLO 水果分拣（嵌入式/CV 工程能力）。

---

## 十、已知局限与生产化差距（诚实清单）

| 维度 | 本项目（Demo/作品集级） | 成熟生产系统 |
|------|----------------------|-------------|
| 数据 | mock 订单库（SQLite） | 真实 ERP/订单/物流系统 |
| 鉴权 | 固定 X-API-Key | OAuth/会话 + 订单归属校验（已做数据源层） |
| 限流 | 令牌桶双层（已完成） | 分布式配额 + 成本控制（已基本对齐） |
| 可观测 | metrics 端点（内存计数） | Prometheus + Grafana / 结构化日志 / trace / 告警 |
| 安全 | 无注入防护 | prompt 注入防护 / PII 脱敏 / 权限隔离 |
| 部署 | 本机 / Docker Compose | 云上多副本 / 负载均衡 / HTTPS / 灰度回滚 |
| DB 治理 | `create_all` 建表 | Alembic 迁移 / 备份 / 连接池 |
| 质量门禁 | 25 题评测 + 129 测试 | 千级评测集 + 自动化回归 + 人工标注 |
| 检索 | 结构分块 + 混合检索 + rerank | 实时索引更新 / 增量学习 / 知识图谱 |

**面试口径**：作品集/演示级，展示能力不宣称可上线；**能讲清差距和生产要补什么**这本身是加分项。

**已完成的工程点**（比纯 demo 强）：接口抽象（数据源）、双层限流、审核 gate、稳定 ID 增量索引、语义缓存、LLM 重试降级、评测管线、容器化、CI、订单归属校验。

---

## 十一、下一步 Roadmap（待办）

按 `docs/optimization-todo.md` 推荐优先级：

| 顺序 | 项 | 价值 |
|------|-----|------|
| 1 | ✅ 数据真实化 + 鉴权/归属校验 | 已完成 |
| 2 | ✅ 限流 | 已完成 |
| 3 | ⬜ **可观测完善**（Prometheus + 结构化 JSON 日志 + request-id 链路 + 告警） | 讲"生产可观测"，1 天 |
| 4 | ⬜ **评测集扩充**（25 → 100+ 题，分类回归集，badcase 追踪）+ CI 自动跑评测 | 把 CI 接上质量门禁，1 天 |
| 5 | ⬜ 对抗测试（prompt 注入自动化）| 安全深度 |
| 6 | ⬜ 部署（云服务器 + HTTPS + CI/CD 灰度回滚）| 上线 |

**⚠️ 建议重跑评测**确认相关度闸门改动（0.60）不使 96% 回归。

---

## 十二、如何运行 / 恢复

**一键起全栈**（需新终端，docker CLI 不在旧 PATH）：
```bash
cd K:\claude\llm-job-prep
docker compose up --build -d
# 前端 http://localhost:3000 | 健康 http://localhost:8000/api/v1/health
```

**本地开发**（不起 Docker）：
```bash
# 后端（Qdrant 本地模式，QDRANT_URL 已置空；首次建索引）
cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000
# 另开终端
cd frontend && npm run dev
```

**评测跑法**：`cd backend && .venv/Scripts/python -m eval.judge`（**先停后端**，Qdrant 本地单进程）。

**恢复会话**：`claude --continue` 或让 Claude 读 `CONTEXT.md`。

**测试指南**：见对话中「回填闭环测试指南」——核心验证「答不出→转人工→沉淀→发布→重问命中」。

---

## 十三、目录结构

```
llm-job-prep/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + 路由注册
│   │   ├── middleware.py      # RateLimit + Observability（鉴权/日志/指标）
│   │   ├── config.py          # 全部配置（Key/模型/限流阈值/闸门阈值）
│   │   ├── llm.py             # LLM 封装：重试/降级/流式/工具
│   │   ├── cache.py           # 语义缓存（精确 + 余弦扫描；Redis/内存降级）
│   │   ├── ratelimit.py       # 令牌桶 + RateLimitStore（Redis Lua/内存）
│   │   ├── metrics.py         # 请求/成本/拒绝指标
│   │   ├── kb.py              # 知识库闭环：draft/approve/reindex/pending/auto_suggest
│   │   ├── api/               # chat / sessions / feedback / kb / health
│   │   ├── agents/            # nodes.py 多Agent + graph.py(评测) + state.py
│   │   ├── rag/               # chunker / embed / vector_store / retrieve
│   │   ├── tools/             # data_source(抽象) + order_tools + mock_db
│   │   └── db/                # models(+meta列) + sessions(+get_last_round)
│   ├── knowledge_base/        # 语料（Obsidian vault）+ backfill/（回填条目）
│   ├── eval/                  # judge.py + questions.json（评测管线）
│   ├── scripts/               # build_kb.py / seed_mock.py
│   ├── tests/                 # 129 个 pytest
│   └── Dockerfile + entrypoint.sh
├── frontend/
│   ├── app/ components/ lib/  # Next.js 工作台 + sse.ts + api.ts
│   ├── tests/                 # 19 个 Vitest
│   └── Dockerfile
├── docs/                      # 本全案 + architecture + optimization-todo + superpowers
├── .github/workflows/ci.yml   # pytest + vitest + build（eval 手动触发）
├── docker-compose.yml         # qdrant + postgres + redis + backend + frontend
└── README.md / CONTEXT.md
```
