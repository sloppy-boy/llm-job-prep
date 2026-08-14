import json
from app.tools.data_source import MockOrderDataSource, OrderDataSource

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

def dispatch(name: str, args: dict, user_id: str = "user-001", ds: OrderDataSource | None = None) -> str:
    """执行工具，返回 JSON 字符串。未知工具/异常均返回 error，不让上层崩。

    - user_id：请求用户（demo 默认 user-001，生产由鉴权上下文注入）
    - ds：数据源（默认 mock 实现；接真实系统时注入真实实现，上层不变）
    """
    ds = ds or MockOrderDataSource()
    try:
        if name == "query_order":
            data = ds.get_order(args.get("order_id"), user_id)
            return json.dumps(data if data is not None else {"error": "订单不存在"}, ensure_ascii=False)
        if name == "query_logistics":
            return json.dumps(ds.get_logistics(args.get("order_id"), user_id), ensure_ascii=False)
        if name == "request_refund":
            return json.dumps(ds.create_refund(args.get("order_id"), args.get("reason", ""), user_id), ensure_ascii=False)
        if name == "escalate_to_human":
            return json.dumps(ds.escalate(args.get("session_id")), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    return json.dumps({"error": "unknown tool"}, ensure_ascii=False)
