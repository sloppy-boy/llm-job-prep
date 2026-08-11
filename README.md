# 电商售后智能客服（LLM 应用开发求职作品集）

面向大模型应用开发岗位的求职作品集项目：一个带**工具调用**的电商售后智能客服。
用户问订单 / 物流 / 退换货问题时，系统不仅能基于知识库准确回答，还能实际**查订单、查物流、发起退款申请**，并带审核机制的多 Agent 协作。

## 架构一句话

`Next.js 前端（SSE 流式）→ FastAPI + LangGraph 多 Agent（路由→检索→写作→审核）→ Qdrant 向量库 / Postgres 会话 / Redis 语义缓存 / 工具调用（mock 订单库）`，全部经 Docker Compose 一键部署。

## 快速启动

前置：安装 Docker Desktop（Windows/macOS 自带 Compose）。

```bash
# 1. 配置密钥：把 .env.example 复制为 backend/.env，填入真实 Key
cp .env.example backend/.env

# 2. 一键起全栈（首次会构建镜像，建库需 1-2 分钟）
docker compose up --build -d

# 3. 查看日志，等后端完成知识库建索引后再使用
docker compose logs -f backend
```

## 访问地址

| 服务 | 地址 |
|------|------|
| 前端客服工作台 | http://localhost:3000 |
| 后端健康检查 | http://localhost:8000/api/v1/health |
| 后端指标 | http://localhost:8000/api/v1/metrics |
| Qdrant 控制台 | http://localhost:6333/dashboard |

## Key 配置

所有模型走国内云 API（DeepSeek / SiliconFlow）。Key 只存在于 `backend/.env`（docker 经 `env_file` 注入，不进镜像 / 代码）。

```bash
cp .env.example backend/.env
# 编辑 backend/.env 填入：
#   DEEPSEEK_API_KEY=sk-xxx
#   SILICONFLOW_API_KEY=sk-xxx
```

本地开发（不起 docker）时，后端默认降级为本地文件模式（`QDRANT_URL` 留空走 `qdrant_local/`，`DATABASE_URL` 默认 SQLite）。

## 评测跑法

```bash
cd backend && .venv/Scripts/python -m eval.judge
```

## 面试叙事（3 句话）

1. 这是一个**带工具调用的电商售后智能客服**：用户问订单 / 物流 / 退款时，系统不止基于知识库回答，还能真实查订单、查物流、发起退款申请，并带审核机制的多 Agent 协作。
2. 技术上采用 **RAG + LangGraph 多 Agent + Function Calling 工具调用 + 商用工程化**：检索路由→向量召回→工具执行→写作→审核（循环上限 + 自省），叠加会话持久化、语义缓存、请求日志 / token 成本指标、模型重试与降级、SSE 流式前端。
3. 关键数据：自建 25 题评测集 + LLM-as-judge 四维打分，**答案准确率 76–92%**；全链路 Docker Compose 一键部署。

## GitHub Flow

本项目按真实团队协作的 **GitHub Flow** 开发：每个任务走 `feature/task-N` 分支 → 实现 → 评审 → 合并回 `main`；本地已全量演练，配置好 GitHub 远端后可推真实 PR。
