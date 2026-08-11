import json
from app.tools import mock_db

# OpenAI 兼容的工具 schema，供 LLM 结构化调用
TOOLS = [
    {"type": "function", "function": {"name": "query_order",
        "description": "查询订单状态", "parameters": {"type": "object",
        "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {"name": "query_logistics",
        "description": "查询物流轨迹", "parameters": {"type": "object",
        "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {"name": "request_refund",
        "description": "发起退款申请", "parameters": {"type": "object",
        "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["order_id", "reason"]}}},
    {"type": "function", "function": {"name": "escalate_to_human",
        "description": "转人工客服", "parameters": {"type": "object",
        "properties": {"session_id": {"type": "string"}}, "required": ["session_id"]}}},
]

def dispatch(name: str, args: dict) -> str:
    """执行工具，返回 JSON 字符串。未知工具/异常均返回 error，不让上层崩。"""
    try:
        if name == "query_order":
            data = mock_db.get_order(args.get("order_id"))
            return json.dumps(data if data is not None else {"error": "订单不存在"}, ensure_ascii=False)
        if name == "query_logistics":
            return json.dumps(mock_db.get_logistics(args.get("order_id")), ensure_ascii=False)
        if name == "request_refund":
            return json.dumps(mock_db.create_refund(args.get("order_id"), args.get("reason", "")), ensure_ascii=False)
        if name == "escalate_to_human":
            return json.dumps(mock_db.escalate(args.get("session_id")), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    return json.dumps({"error": "unknown tool"}, ensure_ascii=False)
