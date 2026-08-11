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
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection,
                vectors_config=VectorParams(size=dim, distance=Distance.COSINE))

    def add(self, texts: list[str], metadatas: list[dict]):
        vectors = embed_texts(texts)
        points = [PointStruct(id=i, vector=v, payload=m)
                  for i, (v, m) in enumerate(zip(vectors, metadatas))]
        self.client.upsert(self.collection, points)

    def search(self, vector: list[float], top_k=20) -> list[dict]:
        hits = self.client.search(self.collection, query_vector=vector, limit=top_k)
        return [{"text": h.payload.get("text", ""), "title": h.payload.get("title", ""),
                 "category": h.payload.get("category", ""), "score": h.score} for h in hits]
