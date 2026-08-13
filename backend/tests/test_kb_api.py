from fastapi.testclient import TestClient
from app.main import app
from app import kb


def _c():
    return TestClient(app)


def test_kb_docs_lists(monkeypatch):
    monkeypatch.setattr(kb, "list_docs",
                        lambda: [{"path": "policies/a.md", "status": "published"}])
    r = _c().get("/api/v1/kb/docs", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["docs"][0]["path"] == "policies/a.md"


def test_kb_backfill_calls_draft(monkeypatch):
    monkeypatch.setattr(kb, "draft_doc",
                        lambda q, a: {"status": "draft", "doc_id": "x.md", "title": "t"})
    r = _c().post("/api/v1/kb/backfill", json={"question": "q", "answer": "a"},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["status"] == "draft"


def test_kb_approve_ok(monkeypatch):
    monkeypatch.setattr(kb, "approve_doc",
                        lambda doc_id: {"status": "published", "chunk_count": 2})
    r = _c().post("/api/v1/kb/backfill/x.md/approve",
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["status"] == "published"


def test_kb_approve_404_on_bad_doc(monkeypatch):
    def boom(doc_id): raise ValueError("无效的 doc_id")
    monkeypatch.setattr(kb, "approve_doc", boom)
    r = _c().post("/api/v1/kb/backfill/x.md/approve",
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 404


def test_kb_pending_lists(monkeypatch):
    monkeypatch.setattr(kb, "pending_docs",
                        lambda: [{"doc_id": "20260814-a.md", "title": "A"}])
    r = _c().get("/api/v1/kb/backfill/pending", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200 and r.json()["pending"][0]["doc_id"] == "20260814-a.md"


def test_human_reply_saves_message(monkeypatch):
    import app.api.kb as kb_api
    saved = {}
    monkeypatch.setattr(kb_api, "save_message",
                        lambda sid, role, content: saved.update(
                            {"sid": sid, "role": role, "content": content}))
    r = _c().post("/api/v1/sessions/s9/human-reply",
                  json={"question": "q", "answer": "人工答复"},
                  headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    assert saved["content"] == "（人工客服）人工答复"
