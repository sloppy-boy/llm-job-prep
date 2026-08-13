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
