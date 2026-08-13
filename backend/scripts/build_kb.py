import sys
from pathlib import Path

# 直接运行本脚本时 sys.path[0] 是 scripts/，把 backend/ 加进去以便导入 app 包
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.chunker import chunk_markdown, is_draft
from app.rag.vector_store import VectorStore

def main():
    store = VectorStore()
    store.reset()  # 重建前清空：分块边界可能变化，避免陈旧 chunk 残留
    kb = Path(__file__).resolve().parents[1] / "knowledge_base"
    all_texts, all_meta = [], []
    for md in sorted(kb.rglob("*.md")):
        if is_draft(md):
            continue
        for c in chunk_markdown(md):
            all_texts.append(c["text"])
            all_meta.append({**c["metadata"], "text": c["text"]})
    store.add(all_texts, all_meta)
    print(f"入库 {len(all_texts)} 个分块")

if __name__ == "__main__":
    main()
