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
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: 测试\ncategory: backfill\nstatus: draft\n---\n\n正文。")
    res = kb_mod.draft_doc("怎么开发票", "请提供发票抬头。")
    assert res["status"] == "draft"
    assert res["doc_id"].endswith(".md")
    assert (kb_mod.BACKFILL_DIR / res["doc_id"]).exists()


def test_draft_doc_dedup_on_high_cosine(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "embed_texts", lambda q: [[0.1] * 4])
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: T\ncategory: backfill\nstatus: draft\n---\n\n正文。")
    class HighStore:
        def search(self, vec, top_k=1): return [{"score": 0.95, "text": "x"}]
    monkeypatch.setattr(kb_mod, "get_store", lambda: HighStore())
    assert kb_mod.draft_doc("怎么退货", "a")["status"] == "exists"
    class LowStore:
        def search(self, vec, top_k=1): return [{"score": 0.5, "text": "x"}]
    monkeypatch.setattr(kb_mod, "get_store", lambda: LowStore())
    assert kb_mod.draft_doc("怎么退货", "a")["status"] == "draft"


def test_draft_doc_unique_filename_for_same_slug(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: T\ncategory: backfill\nstatus: draft\n---\n\n正文。")
    r1 = kb_mod.draft_doc("怎么开发票流程应该如何进行第一条", "a")
    r2 = kb_mod.draft_doc("怎么开发票流程应该如何进行第二条", "b")
    assert r1["doc_id"] != r2["doc_id"]
    assert (kb_mod.BACKFILL_DIR / r1["doc_id"]).exists()
    assert (kb_mod.BACKFILL_DIR / r2["doc_id"]).exists()


def test_draft_doc_falls_back_on_llm_failure(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    def boom(q, a): raise RuntimeError("llm down")
    monkeypatch.setattr(kb_mod, "_format_doc", boom)
    res = kb_mod.draft_doc("怎么开发票", "答案")
    assert res["status"] == "draft"


def test_approve_publishes_and_ingests(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
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


def test_approve_handles_noncanonical_status(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    (kb_mod.BACKFILL_DIR).mkdir(exist_ok=True)
    path = kb_mod.BACKFILL_DIR / "20260814-x.md"
    path.write_text("---\ntitle: T\ncategory: backfill\nstatus:draft\n---\n\n正文内容若干。", encoding="utf-8")
    added = {}
    class FakeStore:
        def add(self, texts, metadatas): added["n"] = len(texts)
    monkeypatch.setattr(kb_mod, "get_store", lambda: FakeStore())
    monkeypatch.setattr(kb_mod, "invalidate_bm25", lambda: None)
    out = kb_mod.approve_doc("20260814-x.md")
    assert out["status"] == "published"
    assert added["n"] >= 1
    assert "status: published" in path.read_text(encoding="utf-8")


def test_approve_rejects_path_traversal(kb_env, monkeypatch):
    with pytest.raises(ValueError):
        kb_mod.approve_doc("../../etc/passwd")


def test_pending_docs_lists_drafts(kb_env):
    (kb_mod.BACKFILL_DIR).mkdir(exist_ok=True)
    (kb_mod.BACKFILL_DIR / "20260814-a.md").write_text(
        "---\ntitle: A\nstatus: draft\n---\n\nx", encoding="utf-8")
    pending = kb_mod.pending_docs()
    assert len(pending) == 1 and pending[0]["doc_id"] == "20260814-a.md"


def test_draft_doc_forces_draft_status_even_if_llm_outputs_published(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    monkeypatch.setattr(kb_mod, "_format_doc",
                        lambda q, a: "---\ntitle: 越权\ncategory: backfill\nstatus: published\n---\n\n正文内容若干。")
    res = kb_mod.draft_doc("q", "a")
    assert res["status"] == "draft"
    written = (kb_mod.BACKFILL_DIR / res["doc_id"]).read_text(encoding="utf-8")
    assert "status: draft" in written
    assert kb_mod.is_draft(kb_mod.BACKFILL_DIR / res["doc_id"]) is True


def test_draft_doc_prepends_frontmatter_when_llm_omits(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    monkeypatch.setattr(kb_mod, "_format_doc", lambda q, a: "正文没有 frontmatter。")
    res = kb_mod.draft_doc("q", "a")
    written = (kb_mod.BACKFILL_DIR / res["doc_id"]).read_text(encoding="utf-8")
    assert written.startswith("---")
    assert "status: draft" in written


def test_draft_doc_title_with_frontmatter_delimiter_does_not_bypass_gate(kb_env, monkeypatch):
    monkeypatch.setattr(kb_mod, "_already_exists", lambda q: False)
    monkeypatch.setattr(kb_mod, "_format_doc", lambda q, a: "正文无 frontmatter。")
    # 问题前 20 字符含 ---，且 LLM 未提供 title → 旧实现会把 --- 注入手拼 frontmatter 导致 is_draft False
    res = kb_mod.draft_doc("退款---说明怎么操作", "答案")
    written = (kb_mod.BACKFILL_DIR / res["doc_id"]).read_text(encoding="utf-8")
    assert "status: draft" in written
    assert kb_mod.is_draft(kb_mod.BACKFILL_DIR / res["doc_id"]) is True
