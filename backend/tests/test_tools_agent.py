from app.tools import order_tools
from app.agents import nodes

def test_dispatch_query_order():
    r = order_tools.dispatch("query_order", {"order_id": "20260811001"})
    assert '"已发货"' in r

def test_dispatch_missing_order():
    r = order_tools.dispatch("query_order", {"order_id": "999999"})
    assert "error" in r

def test_dispatch_unknown():
    r = order_tools.dispatch("nope", {})
    assert "error" in r

def test_dispatch_denied_for_other_user():
    """越权：user-002 查 user-001 的订单 → 无权限"""
    r = order_tools.dispatch("query_order", {"order_id": "20260811001"}, user_id="user-002")
    assert "无权限" in r

def test_dispatch_logistics_denied_for_other_user():
    """越权：user-002 查 user-001 的物流 → 无权限（物流归属校验与订单一致）"""
    r = order_tools.dispatch("query_logistics", {"order_id": "20260811001"}, user_id="user-002")
    assert "无权限" in r

def test_dispatch_logistics_own_order():
    """自己的订单 → 返回物流轨迹列表"""
    r = order_tools.dispatch("query_logistics", {"order_id": "20260811001"}, user_id="user-001")
    assert "已发货" in r

def test_dispatch_uses_injected_data_source():
    """数据源抽象：注入自定义实现，dispatch 不依赖 mock_db"""
    class FakeDS:
        def get_order(self, order_id, user_id):
            return {"order_id": order_id, "status": "来自注入源"}
        def get_logistics(self, order_id, user_id):
            return [{"time": "08-10", "event": "已发货"}]
        def create_refund(self, order_id, reason, user_id):
            return {"refund_id": "R999"}
        def escalate(self, session_id):
            return {"status": "已转人工"}
    r = order_tools.dispatch("query_order", {"order_id": "X1"}, user_id="u1", ds=FakeDS())
    assert "注入源" in r
    # 物流同样走注入源（契约带 user_id）
    r2 = order_tools.dispatch("query_logistics", {"order_id": "X1"}, user_id="u1", ds=FakeDS())
    assert "已发货" in r2

def _base_state(**kw):
    s = {"question": "", "session_id": "s", "history": [], "domain": "policy",
         "retrieved_chunks": [], "tool_results": [], "draft_answer": ""}
    s.update(kw)
    return s

def test_tool_node_order_domain(monkeypatch):
    monkeypatch.setattr(nodes, "chat_with_tools",
                        lambda msgs, tools: ("", [{"name": "query_order", "arguments": {"order_id": "20260811001"}}]))
    out = nodes.tool_node(_base_state(domain="order", question="订单20260811001到哪了"))
    assert out["tool_results"][0]["status"] == "已发货"

def test_tool_node_non_order():
    out = nodes.tool_node(_base_state(domain="policy", question="怎么退货"))
    assert out["tool_results"] == []

def test_writer_order_uses_tool_authority(monkeypatch):
    """order 域工具成功：只以工具结果为权威，忽略无关检索 chunk。"""
    captured = {}
    def fake_chat(msgs, **kw):
        captured["user"] = msgs[-1]["content"]
        return "订单已发货"
    monkeypatch.setattr(nodes, "chat", fake_chat)
    out = nodes.writer_node(_base_state(
        domain="order",
        question="订单20260811001到哪了",
        retrieved_chunks=[{"title": "常见问题", "text": "请提供订单号，客服会为您查询"}],
        tool_results=[{"order_id": "20260811001", "status": "已发货", "items": "智能音箱 x1", "amount": 299.0, "created": "2026-08-10"}],
    ))
    assert "工具查询结果" in captured["user"]
    assert "请提供订单号" not in captured["user"]  # 检索 chunk 被忽略
    assert out["draft_answer"] == "订单已发货"

def test_writer_order_tool_error_falls_back(monkeypatch):
    """order 域工具失败：走"转人工不编造"兜底。"""
    captured = {}
    def fake_chat(msgs, **kw):
        captured["user"] = msgs[-1]["content"]
        return "暂时没有找到相关说明"
    monkeypatch.setattr(nodes, "chat", fake_chat)
    out = nodes.writer_node(_base_state(
        domain="order", question="订单999999什么状态",
        retrieved_chunks=[], tool_results=[{"error": "订单不存在"}],
    ))
    assert "转人工" in captured["user"]  # error 时走诚实话术
    assert out["draft_answer"] == "暂时没有找到相关说明"
