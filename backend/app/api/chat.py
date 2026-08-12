import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.agents.graph import run_agent
from app.cache import cache_get, cache_set

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
            result = _async_run(req.message, req.session_id, req.history)
            for tool in result.get("tool_results", []):
                kind = _kind_of(tool)
                if kind:
                    yield _sse({"type": "card", "kind": kind, "data": tool})
            # 仅缓存确定性问答（无工具结果）；订单/物流/退款结果状态会变化，不缓存避免过时
            if not result.get("tool_results"):
                cache_set(req.message, result.get("draft_answer", ""))
            # 逐字发送：中文整句无空格，若按空格切分会一次送达；逐字可让前端平滑呈现打字效果
            for ch in result.get("draft_answer", ""):
                yield _sse({"type": "token", "text": ch})
            yield _sse({"type": "sources", "items": result.get("retrieved_chunks", [])})
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

def _async_run(message: str, session_id: str, history: list):
    # 阻塞式 LLM 简化版：后续可改真流式。异常向上抛，由 gen 兜底为 error 事件。
    # 返回 run_agent 的原始结果（draft_answer / retrieved_chunks / tool_results），
    # 与测试 monkeypatch 的同步桩返回结构一致；若后续改真流式可升级为 async 并在 gen 内 await。
    return run_agent(message, session_id, history)
