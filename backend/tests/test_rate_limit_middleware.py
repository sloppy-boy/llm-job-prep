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
