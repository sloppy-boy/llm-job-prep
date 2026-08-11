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

def test_chat_error_emits_error_event(monkeypatch):
    import app.api.chat as chat_mod
    def boom(q, sid, hist):
        raise RuntimeError("boom")
    monkeypatch.setattr(chat_mod, "_async_run", boom)
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "hi"},
               headers={"X-API-Key": "dev-local-key"})
    assert "error" in r.text and "done" in r.text
