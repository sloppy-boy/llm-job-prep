import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.cache import cache_get, cache_set
from app.llm import chat as llm_chat
from app.agents.nodes import gate_decision, build_writer_messages
from app.agents import nodes

router = APIRouter()

class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list = []

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

def run_front(question: str, session_id: str, history) -> dict:
    """前置段：路由→工具→检索，返回含 domain/tool_results/retrieved_chunks 的状态。"""
    st = {"question": question, "session_id": session_id,
          "history": history or [], "tool_results": []}
    st.update(nodes.router_node(st))
    st.update(nodes.tool_node(st))
    st.update(nodes.retriever_node(st))
    return st

def llm_chat_stream(messages):
    return llm_chat(messages, stream=True)

@router.post("/chat")
async def chat(req: ChatRequest):
    async def gen():
        yield _sse({"type": "thinking", "status": "正在识别问题类别..."})
        # 语义缓存：精确命中直接返回缓存答案，跳过 LLM 全链路（省 token/降延迟）
        cached = cache_get(req.message)
        if cached:
            yield _sse({"type": "thinking", "status": "⚡ 命中语义缓存，直接返回"})
            yield _sse({"type": "token", "text": cached})
            yield _sse({"type": "done"})
            return
        try:
            # 前置段同步执行：路由→工具→检索，拿到领域/工具结果/检索切片后闸门判定
            st = run_front(req.message, req.session_id, req.history)
            for tool in st.get("tool_results", []):
                kind = _kind_of(tool)
                if kind:
                    yield _sse({"type": "card", "kind": kind, "data": tool})
            answer = ""
            if gate_decision(st):
                # 真流式：writer 逐 token 增量推送，前端边收边渲染
                msgs = build_writer_messages(st)
                stream_resp = llm_chat_stream(msgs)
                parts = []
                for chunk in stream_resp:
                    piece = (chunk.choices[0].delta.content or "")
                    if piece:
                        parts.append(piece)
                        yield _sse({"type": "token", "text": piece})
                answer = "".join(parts)
            else:
                # 资料不足兜底：整句一次返回（诚实话术，无需流式）
                msgs = build_writer_messages(st)
                answer = llm_chat(msgs, stream=False) or ""
                yield _sse({"type": "token", "text": answer})
            # 仅缓存确定性问答（无工具结果）；订单/物流/退款结果状态会变化，不缓存避免过时
            if not st.get("tool_results"):
                cache_set(req.message, answer)
            yield _sse({"type": "sources", "items": st.get("retrieved_chunks", [])})
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
