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

## 七、设计流程状态

当前处于 **头脑风暴阶段**（superpowers:brainstorming），task #2（逐个澄清问题）进行中。
已完成：项目上下文探索。下一步：敲定项目选择 → 提出 2-3 种架构方案 → 呈现设计 → 写设计文档 → 用户审阅 → 转 writing-plans。

## 八、如何继续（下次开机）

```
1. 终端进入 K:\claude
2. claude --continue   （或直接输入 claude 选恢复会话）
3. 若对话已压缩/想重新开始：让 Claude 读本文件
4. 从"待定问题"第 1 条继续：敲定项目 A/B/C
```
