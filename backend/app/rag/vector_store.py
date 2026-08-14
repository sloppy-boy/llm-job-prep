import hashlib
import time
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.config import settings
from app.rag.embed import embed_texts

class VectorStore:
    def __init__(self, collection="kb", dim=1024):
        # 接口抽象：QDRANT_URL 非空走远程，空则本地文件模式（开发用，免 Docker）
        if settings.qdrant_url:
            self.client = QdrantClient(url=settings.qdrant_url)
        else:
            local_dir = str(Path(__file__).resolve().parents[2] / "qdrant_local")
            self.client = QdrantClient(path=local_dir)
        self.collection = collection
        self._ensure_collection(dim)

    def _ensure_collection(self, dim=1024):
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                self.collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    def reset(self):
        """清空并重建集合（重建 KB 前调用）。

        用 recreate_collection 原子替换：delete+create 在 qdrant 本地模式下，
        旧存储目录未清理完就重建同名集合会把旧数据"复活"（实测旧点残留，
        新旧索引叠加导致检索被重复 chunk 污染）。旧客户端回退 delete+轮询等待。
        """
        vectors_config = VectorParams(size=1024, distance=Distance.COSINE)
        if hasattr(self.client, "recreate_collection"):
            self.client.recreate_collection(self.collection, vectors_config=vectors_config)
            return
        if self.client.collection_exists(self.collection):
            self.client.delete_collection(self.collection)
            deadline = time.time() + 5
            while time.time() < deadline and self.client.collection_exists(self.collection):
                time.sleep(0.2)
        self._ensure_collection()

    def add(self, texts: list[str], metadatas: list[dict]):
        vectors = embed_texts(texts)
        points = []
        for i, (v, m) in enumerate(zip(vectors, metadatas)):
            digest = hashlib.md5(f"{m.get('path', '')}:{m.get('page', i)}".encode()).hexdigest()
            stable = int(digest, 16) % (2**64)  # 128-bit md5 取模压回 Qdrant u64 点 id 范围
            points.append(PointStruct(id=stable, vector=v, payload=m))
        self.client.upsert(self.collection, points)

    def search(self, vector: list[float], top_k=20) -> list[dict]:
        # qdrant-client 1.19 起移除了 .search()，改用 query_points()；旧版本兼容保留
        if hasattr(self.client, "query_points"):
            hits = self.client.query_points(self.collection, query=vector, limit=top_k)
            return [{"text": p.payload.get("text", ""), "title": p.payload.get("title", ""),
                     "category": p.payload.get("category", ""), "score": p.score}
                    for p in hits.points]
        hits = self.client.search(self.collection, query_vector=vector, limit=top_k)
        return [{"text": h.payload.get("text", ""), "title": h.payload.get("title", ""),
                 "category": h.payload.get("category", ""), "score": h.score} for h in hits]
