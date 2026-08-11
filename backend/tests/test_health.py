from fastapi.testclient import TestClient
from app.main import app

def test_health():
    c = TestClient(app)
    r = c.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

def test_metrics_requires_key():
    c = TestClient(app)
    assert c.get("/api/v1/metrics").status_code == 401

def test_metrics_401_has_request_id():
    c = TestClient(app)
    r = c.get("/api/v1/metrics")
    assert r.status_code == 401 and r.headers.get("X-Request-ID")

def test_metrics_with_key():
    c = TestClient(app)
    r = c.get("/api/v1/metrics", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and "requests" in r.json()
