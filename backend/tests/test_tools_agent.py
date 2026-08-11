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

def _base_state(**kw):
    s = {"question": "", "session_id": "s", "history": [], "domain": "policy",
         "retrieved_chunks": [], "tool_results": [], "draft_answer": "",
         "review_comment": "", "iteration": 0, "review_status": ""}
    s.update(kw)
    return s

def test_tool_node_order_domain(monkeypatch):
    def fake_chat(msgs, **kw):
        return '{"name": "query_order", "args": {"order_id": "20260811001"}}'
    monkeypatch.setattr(nodes, "chat", fake_chat)
    out = nodes.tool_node(_base_state(domain="order", question="订单20260811001到哪了"))
    assert out["tool_results"][0]["status"] == "已发货"

def test_tool_node_non_order():
    out = nodes.tool_node(_base_state(domain="policy", question="怎么退货"))
    assert out["tool_results"] == []
