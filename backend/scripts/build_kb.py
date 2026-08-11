import sys
from pathlib import Path

# 直接运行本脚本时 sys.path[0] 是 scripts/，把 backend/ 加进去以便导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.chunker import chunk_markdown
from app.rag.vector_store import VectorStore

def main():
    store = VectorStore()
    kb = Path(__file__).resolve().parents[1] / "knowledge_base"
    all_texts, all_meta = [], []
    for md in sorted(kb.rglob("*.md")):
        for c in chunk_markdown(md):
            all_texts.append(c["text"])
            all_meta.append({**c["metadata"], "text": c["text"]})
    store.add(all_texts, all_meta)
    print(f"入库 {len(all_texts)} 个分块")

if __name__ == "__main__":
    main()
