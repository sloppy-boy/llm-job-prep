# 优化轮 2 设计：限流 + 知识库治理与回填闭环

> 日期：2026-08-14
> 范围：在「电商售后智能客服」上补三块工作——限流（工程完整度）、Obsidian 知识库治理（管理体验）、人工兜底→知识回填闭环（自增长知识库）。
> 目标：把项目从「Demo」推向「带生产意识的 Demo」，面试能讲清楚每块的**底层原理**与**与成熟产品的差距及映射**。

---

## 一、限流（Rate Limiting）

### 1.1 目标
- 工程完整度补齐（README 提过但没实现）
- 成本控制：防整服务被刷 + 防单用户刷爆 token 成本
- 面试点：令牌桶惰性注水 O(1)；Redis 分布式原子性（Lua）；内存锁与 Redis Lua 是同一语义的两种实现

### 1.2 算法：令牌桶（Token Bucket）
- `TokenBucket(rate, capacity)`：惰性注水 `tokens = min(capacity, tokens + Δt * rate)`，`consume()` 返回（是否放行、需等待秒数、剩余 token）
- 纯逻辑、无 IO，可单测（注水/突发/耗尽）
- 每桶一把锁；`dict[key -> TokenBucket]` + 全局锁

### 1.3 存储：Redis 优先，内存降级
- `RateLimitStore.check(key, per_min) -> (allowed, retry_after, remaining)` 统一入口
- `MemoryRateLimitStore`：内存令牌桶（dict + `threading.Lock`）
- `RedisRateLimitStore`：令牌桶 Lua 脚本（原子 read-modify-write，key `rl:<key>`），Redis 可用则优先
- 可用性探测沿用 `cache.py` 的 `_available` 模式：启动探测 + 运行时故障降级内存
- 配置（`config.py` 新增）：
  - `ratelimit_enabled: bool = True`
  - `ratelimit_global_per_min: int = 120`（每 API Key，覆盖全部 API）
  - `ratelimit_user_per_min: int = 30`（每 user_id，仅 /chat）

### 1.4 两层限流
- **全局层**：新 `RateLimitMiddleware` 读 `X-API-Key` 头，覆盖所有非 `/health` 路由（防整服务被刷）
  - 中间件顺序：`add_middleware(RateLimitMiddleware)` 先、`add_middleware(ObservabilityMiddleware)` 后 → **Observability 最外**，被限的请求仍被日志和 metrics 记录
- **用户层**：`/chat` 处理器内按 `ChatRequest.user_id` 检查（默认 user-001，生产由鉴权上下文注入）

### 1.5 429 响应
- 沿用现有错误形状：`{"error": {"code": "RATE_LIMITED", "message": "..."}}`，status 429
- 响应头：`Retry-After`（秒）、`X-RateLimit-Limit`、`X-RateLimit-Remaining`、`X-RateLimit-Reset`（unix 时间戳）

### 1.6 可观测
- `metrics.py` 加 `record_rejected(reason)` 计数，`/metrics` 增加 `rejected`（区分 ratelimit/auth）

---

## 二、Obsidian 知识库治理 + 稳定 ID 修复

### 2.1 Obsidian 管理知识库
- `knowledge_base/` 本身就是 Obsidian 兼容的 vault：markdown + YAML frontmatter（chunker 已支持）
- 新增 `knowledge_base/README.md`：说明用 Obsidian「打开文件夹作为仓库」→ 增删改 md → 调 reindex 生效
- **零代码依赖**（Obsidian 只是编辑器，不引入包）

### 2.2 接口
- `POST /api/v1/kb/reindex`：全量重建（reset + 全量摄入），**跳过 `status: draft` 的文档**——Obsidian 编辑后一键生效，不必重启
- `GET /api/v1/kb/docs`：列出 KB 文件（path / title / category / chunk 数 / status），供管理视图

### 2.3 🔧 稳定 ID 修复（技术硬核）
- 现状问题：`VectorStore.add()` 用 `enumerate` 自增 ID → **增量/重复摄入会覆盖已有 point**
- 改法：chunker 携带 `path`，`PointStruct(id = md5(f"{path}:{page}") % 2**64)`（内容寻址稳定 ID，**取模压回 Qdrant u64 点 id 范围**——128-bit md5 直接转 int 在 grpc 传输 `PointId.num` 会越界抛错）
  - 增量入库不碰撞
  - 同一文件重新摄入幂等：编辑后同 path+page → upsert 覆盖，不留孤儿
- 面试点：内容寻址 vs 自增 ID，增量索引的幂等性

### 2.4 BM25 同步
- `_load_corpus()`（BM25 语料）同样跳过 `status: draft`
- 新增 `invalidate_bm25()`，供回填发布后刷新（置 `_bm25 = None`，下次懒重建）

---

## 三、人工兜底 → 知识回填闭环（自增长知识库）

> 核心原则：**审核 gate 控制 RAG 摄入**——草稿不进检索，确认发布后才进向量库 + BM25。gate 是真机制，不是贴标签。

### 3.1 数据流
```
无法解决(gate 失败) → SSE human_handoff 事件 → 转人工 → 人工回答(human-reply)
→ 沉淀(kb/backfill 生成 draft) → 审核(kb/backfill/{id}/approve)
→ 摄入向量库+刷新 BM25 → 下次同样问题命中 RAG 正常回答
```

### 3.2 后端接口

| 接口 | 作用 |
|------|------|
| `POST /api/v1/sessions/{sid}/human-reply` `{question, answer}` | 模拟人工回复，存为 assistant 消息（带「（人工客服）」标记） |
| `POST /api/v1/kb/backfill` `{question, answer}` | LLM 把问答提炼成规范 md（frontmatter: `title / category: backfill / status: draft / date` + 精炼正文），写入 `knowledge_base/backfill/<slug>-<date>.md`，**不摄入**。返回 `{doc_id, path, title, status}` |
| `POST /api/v1/kb/backfill/{doc_id}/approve` | 改 frontmatter `draft → published` → 分块 → 向量入库（稳定 ID）→ `invalidate_bm25()` |
| `GET /api/v1/kb/backfill/pending` | 待审核草稿列表（含自动沉淀来源） |

**入库前防重**：backfill 前先 `hybrid_search` 一次，最高重排分 `score ≥ 0.90`（复用语义缓存阈值）→ 判定已存在 → 返回「知识库已存在类似条目」，拒绝重复沉淀。

**SSE 信号**：`/chat` 里 `gate_decision` 判定资料不足时，流里多发 `{"type":"human_handoff"}` 事件（不靠文字嗅探）。

### 3.3 评分驱动自动沉淀（自增长）
- 钩子：现有 `POST /api/v1/feedback` 评分闭环
- 前置：消息表加 `meta` JSON 列，chat 保存消息时记录该轮 `{domain, had_tools, cached}`（每轮一次，随 assistant 消息写入）——这是自动沉淀的判定依据
- 规则：`rating == 5` → 读该会话最近一轮 Q&A + `meta` → 满足条件（`domain == policy` 且 `had_tools == false` 且 `cached == false`）→ 自动生成草稿条目（`source: auto-suggest`）进待审列表
- 人工在待审列表批量「确认发布 / 丢弃」
- 保留 gate 的理由（面试口径）：全自动无审核入库危险——一次幻觉回答被打 5 星就进库会污染后续所有用户；真实产品都是「自动生成候选 + 人工闸」= badcase 回流 + 对话挖掘的结合

### 3.4 前端（ChatWindow + 弹窗）
1. Bot 答不出 → 流式收到 `human_handoff` → 该消息下方出现「🤝 转人工」按钮
2. 点击 → 弹窗：用户原问题 + 文本框（模拟人工客服输入）
3. 「回复」→ POST human-reply → 追加带「（人工客服）」标记的 assistant 消息
4. 弹窗出现「📥 沉淀到知识库」→ POST backfill → 显示标题/路径/草稿状态
5. 「确认发布」→ POST approve → toast「已发布，下次命中知识库」
6. 验证：重问同样问题 → RAG 命中 → 正常回答（闭环成立）

---

## 四、测试

- **限流**：TokenBucket 单测（注水/突发/耗尽）；集成——超限 429 + 头、health 豁免、按 user 429、被限请求仍进 metrics
- **稳定 ID**：同 path 重入幂等（不重复）；增量不覆盖
- **回填**：draft 不进检索、approve 后进；backfill 格式（mock LLM）；防重（已存在 → 拒绝）；自动沉淀触发规则（mock feedback）
- **前端**：vitest 补 human_handoff 事件 + 弹窗流程（2-3 例）
- **回归**：后端现有 54 pytest 全绿；前端 build 通过

## 五、实施边界

- 3 块工作分 **2 个 feature 分支**（GitHub Flow）：
  - `feature/task-15-ratelimit`（Part 1）
  - `feature/task-16-kb-backfill`（Part 2 + 3）
- 写前端前先读 `frontend/AGENTS.md` 指向的 Next.js 16 内置文档（有破坏性变更）
- Obsidian 零代码依赖，只加文档 + reindex 接口
