import pytest
from app import kb as kb_mod


@pytest.fixture
def kb_env(tmp_path, monkeypatch):
    monkeypatch.setattr(kb_mod, "KB_ROOT", tmp_path)
    monkeypatch.setattr(kb_mod, "BACKFILL_DIR", tmp_path / "backfill")
    (tmp_path / "policies").mkdir()
    (tmp_path / "policies" / "refund.md").write_text(
        "---\ntitle: 退货政策\ncategory: policies\nstatus: published\n---\n\n七天无理由退货。",
        encoding="utf-8")
    (tmp_path / "policies" / "draft.md").write_text(
        "---\ntitle: 草稿\nstatus: draft\n---\n\n草稿内容。", encoding="utf-8")
    return tmp_path


def test_reindex_skips_drafts(kb_env, monkeypatch):
    calls = {}
    class FakeStore:
        def reset(self): calls["reset"] = True
        def add(self, texts, metadatas): calls["texts"] = list(texts)
    monkeypatch.setattr(kb_mod, "VectorStore", lambda: FakeStore())
    monkeypatch.setattr(kb_mod, "invalidate_bm25", lambda: None)
    res = kb_mod.reindex()
    assert res["skipped_drafts"] == 1
    assert all("草稿" not in t for t in calls["texts"])
    assert any("七天无理由" in t for t in calls["texts"])


def test_draft_doc_writes_file(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [])
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: 测试\ncategory: backfill\nstatus: draft\n---\n\n正文。")
    res = kb_mod.draft_doc("怎么开发票", "请提供发票抬头。")
    assert res["status"] == "draft"
    assert res["doc_id"].endswith(".md")
    assert (kb_mod.BACKFILL_DIR / res["doc_id"]).exists()


def test_draft_doc_dedup_on_high_score(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [{"score": 0.99}])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [{"score": 0.99}])
    res = kb_mod.draft_doc("怎么退货", "答案")
    assert res["status"] == "exists"


def test_draft_doc_falls_back_on_llm_failure(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [])
    def boom(q, a): raise RuntimeError("llm down")
    monkeypatch.setattr(kb_mod, "_format_doc", boom)
    res = kb_mod.draft_doc("怎么开发票", "答案")
    assert res["status"] == "draft"


def test_approve_publishes_and_ingests(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "hybrid_search", lambda q, top_k=5: [])
    monkeypatch.setattr(kb_mod, "rerank", lambda q, docs: [])
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: T\ncategory: backfill\nstatus: draft\n---\n\n正文内容若干。")
    res = kb_mod.draft_doc("q", "a")
    added = {}
    class FakeStore:
        def add(self, texts, metadatas): added["n"] = len(texts)
    monkeypatch.setattr(kb_mod, "get_store", lambda: FakeStore())
    monkeypatch.setattr(kb_mod, "invalidate_bm25", lambda: None)
    out = kb_mod.approve_doc(res["doc_id"])
    assert out["status"] == "published"
    assert added["n"] >= 1
    raw = (kb_mod.BACKFILL_DIR / res["doc_id"]).read_text(encoding="utf-8")
    assert "status: published" in raw


def test_approve_rejects_path_traversal(kb_env, monkeypatch):
    with pytest.raises(ValueError):
        kb_mod.approve_doc("../../etc/passwd")


def test_pending_docs_lists_drafts(kb_env):
    (kb_mod.BACKFILL_DIR).mkdir(exist_ok=True)
    (kb_mod.BACKFILL_DIR / "20260814-a.md").write_text(
        "---\ntitle: A\nstatus: draft\n---\n\nx", encoding="utf-8")
    pending = kb_mod.pending_docs()
    assert len(pending) == 1 and pending[0]["doc_id"] == "20260814-a.md"
