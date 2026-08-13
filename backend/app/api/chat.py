import asyncio
import json
import time
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from app import metrics
from app.cache import cache_get, cache_set
from app.config import settings
from app.ratelimit import get_store
from app.db.sessions import save_message
from app.llm import chat as llm_chat
from app.agents.nodes import gate_decision, build_writer_messages
from app.agents import nodes

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list = []
    user_id: str = "user-001"  # demo 默认用户；生产由鉴权上下文注入（订单归属校验依据）

def _kind_of(tool_result: dict) -> str | None:
    """推断卡片类型。error 结果或未知结构返回 None（跳过卡片，交给文本回答兜底）。

    注意：不存在的订单经工具层返回 {"error": ...}，若归为 logistics 会让前端
    (card.data || []).map 崩溃（data 是 dict 不是数组），故 error 一律不渲染卡片。
    """
    if not isinstance(tool_result, dict):
        return "logistics"  # 物流轨迹是数组
    if "error" in tool_result:
        return None
    if "refund_id" in tool_result:
        return "refund"
    if "order_id" in tool_result and ("status" in tool_result or "items" in tool_result):
        return "order"
    return None

def _sse(data: dict) -> str:
    """构造一条 SSE 事件帧：event: message + data: <json>，符合 text/event-stream 协议。"""
    return f"event: message\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

def run_front(question: str, session_id: str, history, user_id: str = "user-001") -> dict:
    """前置段：路由→工具→检索，返回含 domain/tool_results/retrieved_chunks 的状态。"""
    st = {"question": question, "session_id": session_id,
          "history": history or [], "tool_results": [], "user_id": user_id}
    st.update(nodes.router_node(st))
    st.update(nodes.tool_node(st))
    st.update(nodes.retriever_node(st))
    return st

def llm_chat_stream(messages):
    return llm_chat(messages, stream=True)

_blocking = asyncio.to_thread  # 间接层：可测"阻塞调用确实走线程池"，避免全局 patch to_thread

_END = object()  # 生成器结束哨兵

def _next_or_end(gen):
    """在 worker 线程内取下一个 chunk；StopIteration 转哨兵，避免其穿越 await 边界被转成 RuntimeError。"""
    try:
        return next(gen)
    except StopIteration:
        return _END

async def _aiter_sync(gen):
    """把同步生成器桥接成 async 迭代：每 chunk 在 worker 线程 next()，不阻塞事件循环。

    串行跨线程 next() 在 CPython GIL 下安全；结束用哨兵而非 StopIteration 信号。
    """
    while True:
        item = await _blocking(_next_or_end, gen)
        if item is _END:
            return
        yield item

@router.post("/chat")
async def chat(req: ChatRequest):
    # 用户层限流：按 user_id 独立令牌桶（与全局 X-API-Key 限流叠加，双保险）
    if settings.ratelimit_enabled:
        try:
            allowed, wait, remaining = get_store().check(
                f"user:{req.user_id}", settings.ratelimit_user_per_min)
        except Exception:
            allowed, wait, remaining = True, 0.0, 0  # 限流器故障失败开放，可用性优先
        if not allowed:
            metrics.record_rejected("ratelimit")
            reset = int(time.time()) + int(wait) + 1
            return JSONResponse(
                {"error": {"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后重试"}},
                status_code=429,
                headers={"Retry-After": str(max(1, int(wait))),
                         "X-RateLimit-Limit": str(settings.ratelimit_user_per_min),
                         "X-RateLimit-Remaining": str(int(max(0, remaining))),
                         "X-RateLimit-Reset": str(reset)})
    async def gen():
        yield _sse({"type": "thinking", "status": "正在识别问题类别..."})
        try:
            # 语义缓存：精确命中直接返回缓存答案，跳过 LLM 全链路（省 token/降延迟）
            # 注意：cache_get 也在 try 内，命中/异常都不会逃逸 gen() 导致 500
            cached = await _blocking(cache_get, req.message)
            if cached:
                yield _sse({"type": "thinking", "status": "⚡ 命中语义缓存，直接返回"})
                yield _sse({"type": "token", "text": cached})
                try:
                    await _blocking(save_message, req.session_id, "user", req.message)
                    await _blocking(save_message, req.session_id, "assistant", cached)
                except Exception:
                    pass  # 持久化失败不影响 SSE 返回
                yield _sse({"type": "done"})
                return
            # 前置段同步执行：路由→工具→检索，拿到领域/工具结果/检索切片后闸门判定
            st = await _blocking(run_front, req.message, req.session_id, req.history, req.user_id)
            for tool in st.get("tool_results", []):
                kind = _kind_of(tool)
                if kind:
                    yield _sse({"type": "card", "kind": kind, "data": tool})
            answer = ""
            if gate_decision(st):
                # 真流式：writer 逐 token 增量推送，前端边收边渲染
                msgs = build_writer_messages(st)
                stream_resp = await _blocking(llm_chat_stream, msgs)
                parts = []
                async for chunk in _aiter_sync(stream_resp):
                    if not chunk.choices:
                        continue  # include_usage 的末块 choices 为空，跳过
                    piece = (chunk.choices[0].delta.content or "")
                    if piece:
                        parts.append(piece)
                        yield _sse({"type": "token", "text": piece})
                answer = "".join(parts)
            else:
                # 资料不足兜底：整句一次返回（诚实话术，无需流式）
                msgs = build_writer_messages(st)
                answer = await _blocking(llm_chat, msgs, False) or ""
                yield _sse({"type": "token", "text": answer})
            # 仅缓存确定性问答（无工具结果）；订单/物流/退款结果状态会变化，不缓存避免过时
            if not st.get("tool_results"):
                await _blocking(cache_set, req.message, answer)
            yield _sse({"type": "sources", "items": st.get("retrieved_chunks", [])})
            # 消息持久化：失败仅吞掉，绝不让 DB 写入异常破坏 SSE 流程
            try:
                await _blocking(save_message, req.session_id, "user", req.message)
                await _blocking(save_message, req.session_id, "assistant", answer)
            except Exception:
                pass
        except Exception:
            # 整条流水线失败时绝不静默，向客户端发 error 事件兜底
            yield _sse({"type": "error", "message": "服务暂时不可用，请稍后重试或转人工"})
        yield _sse({"type": "done"})
    # 说明：因 sse_starlette 的全局 AppStatus.should_exit_event 与 TestClient 多事件循环不兼容，
    # 这里直接用 StreamingResponse 输出标准 SSE 帧，前端消费协议不变。
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
    )
