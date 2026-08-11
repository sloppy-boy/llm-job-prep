#!/bin/sh
# 等待 Qdrant 就绪（容器启动竞态兜底）
# python:slim 镜像无 curl，改用 python urllib 探测 /healthz
python - <<'PY'
import os, time, urllib.request

base = os.environ.get("QDRANT_URL", "http://qdrant:6333").rstrip("/")
ready = False
for i in range(1, 11):
    try:
        urllib.request.urlopen(base + "/healthz", timeout=2)
        ready = True
        break
    except Exception:
        pass
    print(f"waiting for qdrant... ({i}/10)")
    time.sleep(2)
if not ready:
    print("WARNING: qdrant not reachable after retries, continuing anyway")
PY

# 建知识库向量索引（幂等：清空集合后重建）
python - <<'PY'
from app.rag.vector_store import VectorStore
store = VectorStore()
if store.client.collection_exists(store.collection):
    store.client.delete_collection(store.collection)
    print("cleared collection:", store.collection)
PY
python scripts/build_kb.py

# 启动 API
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
