from fastapi.testclient import TestClient

from app.main import app


def test_feedback_valid(monkeypatch):
    """合法评分（1-5）：200 + {"ok": true}，并落库。"""
    import app.api.feedback as f
    saved = {}
    monkeypatch.setattr(f, "save_feedback", lambda sid, r: saved.update({sid: r}))
    c = TestClient(app)
    r = c.post("/api/v1/feedback", json={"session_id": "s1", "rating": 4},
               headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert saved.get("s1") == 4


def test_feedback_invalid_rating():
    """rating 超出 [1,5] 返回 400。"""
    c = TestClient(app)
    r = c.post("/api/v1/feedback", json={"session_id": "s1", "rating": 9},
               headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 400


def test_feedback_requires_key():
    """与其它业务接口一致，无 X-API-Key 返回 401。"""
    c = TestClient(app)
    r = c.post("/api/v1/feedback", json={"session_id": "s1", "rating": 4})
    assert r.status_code == 401


def test_feedback_boundary_ratings(monkeypatch):
    """边界值 1 和 5 均为合法评分。"""
    import app.api.feedback as f
    saved = {}
    monkeypatch.setattr(f, "save_feedback", lambda sid, r: saved.update({sid: r}))
    c = TestClient(app)
    for sid, rating in (("s-low", 1), ("s-high", 5)):
        r = c.post("/api/v1/feedback", json={"session_id": sid, "rating": rating},
                   headers={"X-API-Key": "dev-local-key"})
        assert r.status_code == 200 and r.json()["ok"] is True
    assert saved == {"s-low": 1, "s-high": 5}


def test_feedback_rating_zero_and_six_invalid():
    """0 与 6 都是非法评分，返回 400。"""
    c = TestClient(app)
    for rating in (0, 6):
        r = c.post("/api/v1/feedback", json={"session_id": "s1", "rating": rating},
                   headers={"X-API-Key": "dev-local-key"})
        assert r.status_code == 400
