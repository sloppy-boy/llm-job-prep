from app.rag.vector_store import VectorStore


class FakeClient:
    """模拟 QdrantClient：记录调用顺序，删除同步生效。"""

    def __init__(self, exists=False):
        self.events = []
        self.exists = exists

    def collection_exists(self, name):
        return self.exists

    def delete_collection(self, name):
        self.events.append("delete")
        self.exists = False

    def create_collection(self, *a, **k):
        self.events.append("create")
        self.exists = True


def _make_store(exists=False):
    store = VectorStore.__new__(VectorStore)
    store.collection = "kb"
    store.client = FakeClient(exists)
    return store


def test_reset_delete_then_create():
    store = _make_store(exists=True)
    store.reset()
    assert store.client.events == ["delete", "create"]


def test_reset_skips_delete_when_missing():
    store = _make_store(exists=False)
    store.reset()
    assert store.client.events == ["create"]  # 不存在则只建


def test_ensure_collection_reuses_existing():
    store = _make_store(exists=True)
    store._ensure_collection()
    assert store.client.events == []  # 已存在则不动


class _FakeUpsertClient:
    def __init__(self):
        self.points = []

    def upsert(self, collection, points):
        self.points = points


def test_add_uses_stable_content_addressed_ids(monkeypatch):
    from app.rag.vector_store import VectorStore
    store = VectorStore.__new__(VectorStore)
    store.collection = "kb"
    store.client = _FakeUpsertClient()
    monkeypatch.setattr("app.rag.vector_store.embed_texts", lambda texts: [[0.1] * 4 for _ in texts])
    meta1 = [{"path": "backfill/20260814-a.md", "page": 0, "text": "x"},
             {"path": "backfill/20260814-a.md", "page": 1, "text": "y"}]
    meta2 = [{"path": "backfill/20260814-a.md", "page": 0, "text": "x"},
             {"path": "backfill/20260814-b.md", "page": 0, "text": "z"}]
    store.add(["x", "y"], meta1)
    ids1 = [p.id for p in store.client.points]
    store.add(["x", "z"], meta2)
    ids2 = [p.id for p in store.client.points]
    assert ids1[0] == ids2[0], "同 path+page 重入必须同 id（幂等覆盖）"
    assert ids1[1] != ids2[1], "不同 path 的 id 必须不同"
    assert ids1[0] != ids1[1], "同文件不同 page 的 id 必须不同"
    for p in ids1 + ids2:
        assert 0 <= p < 2**64, "Qdrant 点 id 必须落在 u64 范围"
