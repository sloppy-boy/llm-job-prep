from fastapi.testclient import TestClient
from app.main import app
import app.config as cfg


def _enable(monkeypatch, per_min=3, api_key="rl-test-key"):
    monkeypatch.setattr(cfg.settings, "ratelimit_enabled", True)
    monkeypatch.setattr(cfg.settings, "ratelimit_global_per_min", per_min)
    monkeypatch.setattr(cfg.settings, "api_key", api_key)


def test_global_rate_limit_429_after_quota(monkeypatch):
    _enable(monkeypatch, per_min=3)
    c = TestClient(app)
    for _ in range(3):
        assert c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"}).status_code == 200
    r = c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"})
    assert r.status_code == 429
    assert r.headers.get("Retry-After")
    assert "X-RateLimit-Limit" in r.headers
    assert "X-RateLimit-Remaining" in r.headers
    assert "RATE_LIMITED" in r.text


def test_health_exempt_from_ratelimit(monkeypatch):
    _enable(monkeypatch, per_min=2)
    c = TestClient(app)
    for _ in range(5):
        assert c.get("/api/v1/health").status_code == 200


def test_rate_limited_requests_recorded_in_metrics(monkeypatch):
    import app.metrics as m
    m._state["rejected"] = {"ratelimit": 0, "auth": 0}
    _enable(monkeypatch, per_min=1)
    c = TestClient(app)
    c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"})
    r = c.get("/api/v1/metrics", headers={"X-API-Key": "rl-test-key"})
    assert r.status_code == 429
    assert m.snapshot()["rejected"]["ratelimit"] >= 1


def test_chat_per_user_rate_limit(monkeypatch):
    monkeypatch.setattr(cfg.settings, "ratelimit_enabled", True)
    monkeypatch.setattr(cfg.settings, "ratelimit_user_per_min", 2)
    monkeypatch.setattr(cfg.settings, "api_key", "rl-user-key")
    import app.api.chat as chat_mod
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h, uid: {
        "question": q, "session_id": sid, "history": h or [],
        "domain": "chitchat", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: True)
    monkeypatch.setattr(chat_mod, "llm_chat_stream", lambda m: iter([]))
    c = TestClient(app)
    body = {"session_id": "s1", "message": "hi", "user_id": "rl-u-1"}
    for _ in range(2):
        assert c.post("/api/v1/chat", json=body,
                      headers={"X-API-Key": "rl-user-key"}).status_code == 200
    r = c.post("/api/v1/chat", json=body, headers={"X-API-Key": "rl-user-key"})
    assert r.status_code == 429
    assert "RATE_LIMITED" in r.text


def test_chat_user_limit_fails_open_on_store_error(monkeypatch):
    import app.config as cfg
    import app.api.chat as chat_mod
    monkeypatch.setattr(cfg.settings, "ratelimit_enabled", True)
    monkeypatch.setattr(cfg.settings, "ratelimit_user_per_min", 30)
    monkeypatch.setattr(cfg.settings, "api_key", "rl-failopen-key")
    class BoomStore:
        def check(self, key, per_min): raise RuntimeError("store down")
    monkeypatch.setattr(chat_mod, "get_store", lambda: BoomStore())
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h, uid: {
        "question": q, "session_id": sid, "history": h or [],
        "domain": "chitchat", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: True)
    monkeypatch.setattr(chat_mod, "llm_chat_stream", lambda m: iter([]))
    c = TestClient(app)
    r = c.post("/api/v1/chat", json={"session_id": "s1", "message": "hi", "user_id": "u1"},
               headers={"X-API-Key": "rl-failopen-key"})
    assert r.status_code == 200  # 限流器故障 → 放行，不 500
