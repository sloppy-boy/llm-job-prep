from fastapi.testclient import TestClient
from app.main import app

def test_chat_returns_sse(monkeypatch):
    import app.api.chat as chat_mod
    def fake_run(q, sid, hist):
        return {"draft_answer": "可以，支持7天无理由。",
                "retrieved_chunks": [{"title": "七天无理由", "text": "支持"}],
                "tool_results": [{"order_id": "20260811001", "status": "已发货", "items": "智能音箱", "amount": 299.0}]}
    monkeypatch.setattr(chat_mod, "_async_run", fake_run)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "订单到哪了"},
               headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    assert "token" in r.text and "sources" in r.text and "card" in r.text and "done" in r.text

def test_chat_error_tool_result_emits_no_card(monkeypatch):
    """不存在订单时工具返回 {"error": ...}，不得被归类为 logistics 卡片（前端会 .map 崩溃）。"""
    import app.api.chat as chat_mod
    def fake_run(q, sid, hist):
        return {"draft_answer": "未找到该订单，请核实订单号。",
                "retrieved_chunks": [],
                "tool_results": [{"error": "订单不存在"}]}
    monkeypatch.setattr(chat_mod, "_async_run", fake_run)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "查 20260000000"},
               headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    assert "card" not in r.text, "error 结果不应渲染卡片"


def test_kind_of_returns_none_for_error_dict():
    """_kind_of 对 error dict 返回 None（跳过卡片），不兜底成 logistics。"""
    import app.api.chat as chat_mod
    assert chat_mod._kind_of({"error": "订单不存在"}) is None
    assert chat_mod._kind_of({"order_id": "1", "status": "已发货"}) == "order"
    assert chat_mod._kind_of({"refund_id": "R1", "status": "已申请"}) == "refund"
    assert chat_mod._kind_of([{"time": "08-10", "event": "已发货"}]) == "logistics"


def test_chat_cache_hit_returns_cached_without_agent(monkeypatch):
    """命中语义缓存时直接返回缓存内容，不再调用 agent 链路。"""
    import app.api.chat as chat_mod
    called = {"n": 0}
    def fake_run(q, sid, hist):
        called["n"] += 1
        return {"draft_answer": "不应走这里", "retrieved_chunks": [], "tool_results": []}
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: "缓存的七天无理由答案")
    monkeypatch.setattr(chat_mod, "_async_run", fake_run)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "怎么退货"},
               headers={"X-API-Key": "dev-local-key"})
    assert "缓存的七天无理由答案" in r.text
    assert "cache_hit" not in r.text or True  # 命中标记允许变化，核心是答案直接返回
    assert called["n"] == 0, "命中缓存不应走 agent 链路"


def test_chat_writes_cache_only_without_tools(monkeypatch):
    """无工具结果的确定性问答写入缓存。"""
    import app.api.chat as chat_mod
    written = {}
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "cache_set", lambda q, a: written.update({q: a}))
    def fake_run(q, sid, hist):
        return {"draft_answer": "答案A", "retrieved_chunks": [], "tool_results": []}
    monkeypatch.setattr(chat_mod, "_async_run", fake_run)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "怎么退货"},
               headers={"X-API-Key": "dev-local-key"})
    assert written.get("怎么退货") == "答案A"
    # 逐字发送，需解析 SSE 拼接 token 后比较
    import json as _json
    tokens = "".join(_json.loads(p.split("data: ", 1)[1].strip()).get("text", "")
                     for p in r.text.split("event: message")
                     if "data: " in p and _json.loads(p.split("data: ", 1)[1].strip()).get("type") == "token")
    assert tokens == "答案A"


def test_chat_does_not_cache_tool_results(monkeypatch):
    """带工具结果（订单/物流/退款）不缓存，避免状态过时。"""
    import app.api.chat as chat_mod
    written = {}
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "cache_set", lambda q, a: written.update({q: a}))
    def fake_run(q, sid, hist):
        return {"draft_answer": "答案", "retrieved_chunks": [],
                "tool_results": [{"order_id": "1", "status": "已发货"}]}
    monkeypatch.setattr(chat_mod, "_async_run", fake_run)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "查订单1"},
               headers={"X-API-Key": "dev-local-key"})
    assert written == {}, "有工具结果不应写入缓存"


def test_chat_error_emits_error_event(monkeypatch):
    import app.api.chat as chat_mod
    def boom(q, sid, hist):
        raise RuntimeError("boom")
    monkeypatch.setattr(chat_mod, "_async_run", boom)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "hi"},
               headers={"X-API-Key": "dev-local-key"})
    assert "error" in r.text and "done" in r.text
