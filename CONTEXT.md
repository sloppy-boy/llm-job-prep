# LLM 应用开发求职备战 —— 项目上下文

> **给 AI 的说明**：这是本求职项目的"记忆文件"。任何新会话开始，先读本文件即可完整恢复上下文。
> **给用户的说明**：关机前不用做任何事，这个文件就是你的存档。下次开机 `claude --continue` 或让 Claude 读本文件即可继续。

---

## 一、用户背景

- 中文用户，Windows 11，网络依赖 Clash Verge 代理（系统代理 127.0.0.1:7897）
- 机器已装：Python 3.13 (Anaconda, G:\anaconda)、Node 24.14、Git 2.53、conda
- 经验：**有 LangChain 基础**；用 **OpenClaw 做过较复杂的 Agent 类项目**；毕设是 **RK3588S + YOLO 水果分拣系统**（嵌入式/CV，与 LLM 无关，但体现工程能力，可作为次要加分故事）

## 二、目标

- 求职方向：**大模型应用开发岗位**（国内）
- 时间线：**约 1 个月内开始投递面试**
- 时间投入：**脱产**，每天可投入大量时间（可全速排期）
- 求职策略（已确认）：用**一个新项目的深度**换面试的宽度；不做面面俱到的学习

## 三、已做决定 ✅

1. **毕设不强行改造成 LLM 项目**（方向不符，硬包装会露馅），作为"嵌入式工程能力"次要故事
2. **新开一个项目**，RAG + 多 Agent 协作合一（朋友的工作经验提示多 Agent 是行业热点）
3. **项目已选定：A. 企业级产品客服机器人 → 具体化为「电商平台售后智能客服」**（用户嫌纯文档问答=网页版DeepSeek没区别，改为带工具调用的售后场景）
   - 多 Agent：路由（订单/政策/商品/闲聊）→ 检索 → 写作 → 审核（循环上限+自省）
   - **工具调用**（关键差异化）：查订单(mock库) · 查物流 · 发起退款 · 转人工
   - 语料：**自建"示例电商"售后政策 + 商品 FAQ**（建模自真实平台公开政策，20-40篇 markdown，故意埋大表格/嵌套条款当"硬骨头"）
   - 架构：商用级（分层 + 请求ID/日志/成本指标 + 重试/模型降级 + 会话持久化 + 语义缓存 + 向量库抽象 + 评测管线 + Docker Compose + API Key/限流）
4. 前端路线：**Next.js 前端 + Python AI 后端**（用户选择，前端锁死最小聊天界面）
5. **分支策略：GitHub Flow（feature 分支 + PR）**——真实团队常用，简历加分。Task 1（脚手架）留在 main；Task 2 起每个任务走 `feature/task-N` → 实现 → 评审 → 合并 main。本地先走分支+合并，用户配好 GitHub 远端后可推真实 PR
6. **执行方式：子代理驱动**（superpowers:subagent-driven-development），每任务独立实现子代理 + 任务评审
7. 密钥：DeepSeek Key + SiliconFlow Key 用户稍后提供；Docker Desktop 需安装（Task 4 需要 Qdrant）

## 四、待定问题 ❓（下一步决策点）

1. **选哪个项目？**（A/B/C，推荐 A）
2. 技术栈细节（DeepSeek API + LangGraph + 向量库 + FastAPI/Streamlit，待最终确认）
3. 部署目标（本机 demo / Docker 上线）

## 五、技术方向草案

- 语言：Python
- 模型 API：DeepSeek（deepseek-chat）
- 多 Agent 编排：LangGraph（Supervisor 模式）
- 向量库：Chroma（起步）→ Milvus/Qdrant（进阶）
- 检索优化：分块策略对比 + 混合检索 + Rerank
- 界面：Streamlit（快速 demo）或 FastAPI + 简单前端
- 工程化：流式、重试、并发、token 成本统计、日志、评测（20 用例量化前后对比）、Docker 部署

## 六、教学/指导原则

用户是按面试标准训练的，指导要：
- 注重**底层原理**（Function Calling 机制、embedding、RAG 全链路、上下文/KV Cache、采样、幻觉）
- 强调**工程化**（流式、重试、成本、评测、部署）
- 强调**面试表达**：3 句话讲清项目 + 量化结果 + 能应对追问
- 提醒：LangChain 权重下降，面试更认 LangGraph + 原生 SDK + 底层原理

## 七、项目状态（2026-08-12 完成 ✅ + 深化轮）

**「电商售后智能客服」求职作品集**：14 任务 + 评测修复轮 + **真流式深化轮（15 任务）**，全在 main。备份点 tag `v1.0-pre-streaming`。

**第一轮最终成绩**：
- 后端 29 个 pytest 全绿；前端 Next.js 16 build 通过；Docker Compose 校验通过
- 真实评测：25 题 / 5 类，准确率 76-92%（3 次采样，诚实口径）

**深化轮（真流式重构，2026-08-12）新增**：
- **真流式**：拆 LangGraph 一次性 invoke → 前置段（路由/工具/检索/前置质量闸门）同步 + writer 逐 token SSE 推送（可中断）；`run_agent` 保留同步接口供评测
- **审核改造**：打回循环（≤2 重写）→ **前置质量闸门**（确定性判定，资料不足直接诚实兜底），评测准确率 92% → **96%**（order 域 80%→100%）
- **会话闭环**：消息持久化接线 + `GET /api/v1/sessions` + 历史加载（前端会话列表真实化）
- **评分闭环**：`POST /api/v1/feedback` + 前端 1-5 星提交
- **前端体验**：react-markdown 渲染、生成光标、停止生成（AbortController）、错误重试
- **前端测试**：Vitest 16 用例（SSE/卡片/聊天窗口）
- **CI**：`.github/workflows/ci.yml`（pytest+build 自动、评测手动触发，配好 Secrets 即用）
- 测试：后端 **54 pytest** + 前端 **16 vitest** + build 全绿

**关键排障故事**（面试弹药）：① 评测 92%→40% 假崩 = Qdrant 本地索引被后端占用导致静默空检索（已加自检）；② 真流式 usage 末块 `choices` 空数组会 IndexError（已加防护+回归测试）；③ CI yaml 内联映射含 `${{ }}` 无效、eval 需 `QDRANT_URL=""` 本地模式。

**优化轮（2026-08-13）**：
- **#1 数据源抽象 + 订单归属校验（完成）**：`data_source.py` 定义 `OrderDataSource` 契约 + `MockOrderDataSource`，`dispatch` 依赖注入（接真实 ERP 只写新实现替换）；订单加 `user_id` 归属，`get_order`/`create_refund` 校验越权（A 查 B 的订单 → 无权限兜底）；`ChatRequest` 加 `user_id`（默认 user-001）链路透传。54 pytest 全绿 + 端到端实测越权拦截
- **限流（2026-08-14）**：令牌桶 + `RateLimitStore`（Redis Lua 原子/内存锁降级）；`RateLimitMiddleware` 全局按 Key + `/chat` 按 user_id 双层；429 带 `Retry-After`/`X-RateLimit-*` 头；metrics 拒绝计数；conftest 默认关闭避免污染既有用例。
- **知识库治理 + 回填闭环（2026-08-14）**：Obsidian 管理 knowledge_base（热重索引 `POST /kb/reindex`，跳 draft；`backend/knowledge_base/README.md` 使用说明）；稳定 ID（`md5(path:page) % 2**64`）修复增量摄入覆盖；SSE `human_handoff` → 转人工弹窗 → 人工回复 → LLM 提炼草稿 → 审核发布 → RAG 摄入 + BM25 刷新 → 下次命中；评分 5★ 自动沉淀草稿候选（消息表 meta 列判定）。**面试点**：审核 gate 控 RAG 摄入（写盘强制 draft、防 `---` 注入绕过）、badcase 回流 + 对话挖掘、LLM 提炼知识条目、路径穿越防护、内容寻址 ID 幂等。
- **优化轮 2 最终状态**：后端 **125 pytest** + 前端 **19 vitest** + build 全绿（P0 修复 80 → 加限流 95 → 加回填 125）
- **Review 修复轮（2026-08-14 晚，外部 review 后）**：① 多轮上下文真正接线（前端传 history + 后端限长/清洗，此前模型实际看不到上一轮）；② 物流查询补归属校验（`get_logistics` 带 user_id，此前漏检）；③ 模型降级改独立 provider（SiliconFlow 端点 + 独立 Key，此前主备同端点形同虚设）；④ 线上前置段改用编译后 LangGraph 图（`build_front_graph`，此前手写编排）；⑤ 转人工关键词路由到 human 域（优先于寒暄）；⑥ **域外问题（offtopic）确定性模板拦截**——不调 LLM、不进转人工（此前"写论文"类问题会触发转人工浪费人力），评测期望点同步改为"拒绝"；⑦ 成本按输入/输出分开估算；⑧ 内存缓存补 TTL；⑨ CORS 可配置 + 前端 Key 生产强制；⑩ **修 VectorStore.reset() 本地模式复活旧数据 bug**（delete+create 改 recreate_collection，实测新旧索引叠加 180 点/86 重复导致检索被污染）；⑪ **LLM-as-judge 稳定性**：推理先行 + 解析最后裁决（实测"只输出PASS/FAIL"极简 prompt 会把明确拒绝/完整覆盖的正确答案误判 FAIL）。当前状态：后端 **149 pytest** + 前端 **21 vitest** + build 全绿；**真实评测 25/25 = 100%**（3 个 badcase 全部闭环：检索污染修复 + 毕业论文域外拦截 + judge 误判修复）。
- 待优化清单见 `docs/optimization-todo.md`（下一步：**可观测完善（Prometheus + 结构化日志）→ 评测集扩充 + CI 自动跑评测**）；架构详解见 `docs/architecture.md`；**项目全案（三轮演进/决策/排障/面试叙事）见 `docs/project-overview.md`**
- ⚠️ **待用户实测**：真实 LLM 端到端（DeepSeek/SiliconFlow Key 就绪后跑通「问知识库没有的问题 → 转人工 → 回复 → 沉淀 → 发布 → 重问命中」闭环）、Docker Compose 一键起全栈、配 GitHub 远端后推真实 PR（限流 + 回填两个 merge 已有本地演练）

**如何运行（用户需在新终端操作，因 docker CLI 不在旧 PATH）**：
```bash
cd K:\claude\llm-job-prep
docker compose up --build -d
# 访问 http://localhost:3000（前端工作台）| http://localhost:8000/api/v1/health（健康检查）
```
本地开发（不用 Docker）：`cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000` + `cd frontend && npm run dev`（Qdrant 用本地模式，QDRANT_URL 已置空）。

**面试叙事弹药**（详见 README）：3 句话讲清项目、准确率 56%→76%→92% 的修复轨迹、多Agent+工具调用+RAG 三大能力、商用化工程点（评测/成本/缓存/降级/容器化）、嵌入式毕设作第二故事。

## 八、如何继续（下次开机）

```
1. 终端进入 K:\claude
2. claude --continue   （或直接输入 claude 选恢复会话）
3. 若对话已压缩/想重新开始：让 Claude 读本文件
4. 从"待定问题"第 1 条继续：敲定项目 A/B/C
```
