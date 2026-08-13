import re
import time
from pathlib import Path

from app.config import settings
from app.llm import chat as llm_chat
from app.rag.chunker import chunk_markdown, read_frontmatter, is_draft, _extract_frontmatter
from app.rag.retrieve import hybrid_search, rerank, get_store, invalidate_bm25
from app.rag.vector_store import VectorStore

KB_ROOT = Path(__file__).resolve().parents[1] / "knowledge_base"
BACKFILL_DIR = KB_ROOT / "backfill"

KB_EDITOR_SYSTEM = (
    "你是电商售后知识库编辑。把用户问题与人工客服回答提炼成一条规范的售后知识条目（markdown）。"
    "要求：\n1. 以 YAML frontmatter 开头，含 title（简明标题）、category（值固定为 backfill）、status（值固定为 draft）\n"
    "2. 正文用清晰客观的售后话术，覆盖同类问题的常见变体问法，不要出现'用户说/客服说'这类对话体\n"
    "3. 只输出 markdown 文档本身，不要任何解释"
)


def _slug(question: str) -> str:
    s = re.sub(r"[^\w一-龥]", "", question)[:12]
    return s or "question"


def _format_doc(question: str, answer: str) -> str:
    text = (llm_chat([
        {"role": "system", "content": KB_EDITOR_SYSTEM},
        {"role": "user", "content": f"问题：{question}\n人工客服回答：{answer}"},
    ], stream=False) or "").strip()
    if not text:
        raise ValueError("LLM 提炼为空")
    return text


def _fallback_doc(question: str, answer: str) -> str:
    """LLM 失败时的模板兜底，保证沉淀流程绝不中断。"""
    title = question[:20]
    return (f"---\ntitle: {title}\ncategory: backfill\nstatus: draft\n---\n\n"
            f"## {title}\n\n{answer}\n")


def _extract_title(body: str) -> str:
    meta, _ = _extract_frontmatter(body)
    return meta.get("title", "")


def draft_doc(question: str, answer: str) -> dict:
    """把问答沉淀为 draft 草稿。防重 → LLM 提炼（失败回退模板）→ 写文件。"""
    # 1) 防重：最高重排分 ≥ 语义缓存阈值视为已存在
    try:
        docs = hybrid_search(question, top_k=5)
        reranked = rerank(question, docs)
        if reranked and reranked[0].get("score", 0) >= settings.semantic_cache_threshold:
            return {"status": "exists", "doc_id": "", "path": "",
                    "title": "知识库已存在类似条目，跳过沉淀"}
    except Exception:
        pass
    # 2) 生成文档
    try:
        body = _format_doc(question, answer)
    except Exception:
        body = _fallback_doc(question, answer)
    # 3) 写文件（文件名即 doc_id，日期前缀保证可排序）
    BACKFILL_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{time.strftime('%Y%m%d')}-{_slug(question)}.md"
    path = BACKFILL_DIR / fname
    path.write_text(body, encoding="utf-8")
    return {"status": "draft", "doc_id": fname, "path": f"backfill/{fname}",
            "title": _extract_title(body) or f"售后问题：{question[:20]}"}


def approve_doc(doc_id: str) -> dict:
    """审核通过：draft → published，摄入向量库（稳定 ID）+ 刷新 BM25。路径穿越防护。"""
    path = (BACKFILL_DIR / doc_id).resolve()
    if path.name != doc_id or path.parent != BACKFILL_DIR.resolve() or not path.exists():
        raise ValueError("无效的 doc_id")
    raw = path.read_text(encoding="utf-8")
    if "status: draft" not in raw:
        return {"status": "noop", "chunk_count": 0}
    path.write_text(raw.replace("status: draft", "status: published"), encoding="utf-8")
    chunks = chunk_markdown(path)
    get_store().add([c["text"] for c in chunks],
                    [{**c["metadata"], "text": c["text"]} for c in chunks])
    invalidate_bm25()
    return {"status": "published", "chunk_count": len(chunks)}


def pending_docs() -> list[dict]:
    """待审核草稿列表（status: draft）。"""
    if not BACKFILL_DIR.exists():
        return []
    out = []
    for md in sorted(BACKFILL_DIR.rglob("*.md")):
        meta = read_frontmatter(md)
        if meta.get("status") == "draft":
            out.append({"doc_id": md.name, "path": f"backfill/{md.name}",
                        "title": meta.get("title", ""), "category": meta.get("category", "")})
    return out


def list_docs() -> list[dict]:
    """列出全部 KB 文档（path/title/category/status/chunk 数）。"""
    out = []
    for md in sorted(KB_ROOT.rglob("*.md")):
        meta = read_frontmatter(md)
        chunks = chunk_markdown(md)
        out.append({"path": str(md.relative_to(KB_ROOT)),
                    "title": meta.get("title", ""),
                    "category": meta.get("category", ""),
                    "status": meta.get("status", "published"),
                    "chunks": len(chunks)})
    return out


def reindex() -> dict:
    """全量重建索引（Obsidian 编辑后调用）。跳 draft。"""
    store = VectorStore()
    store.reset()
    texts, metas, skipped = [], [], 0
    for md in sorted(KB_ROOT.rglob("*.md")):
        if is_draft(md):
            skipped += 1
            continue
        for c in chunk_markdown(md):
            texts.append(c["text"])
            metas.append({**c["metadata"], "text": c["text"]})
    store.add(texts, metas)
    invalidate_bm25()
    return {"indexed": len(texts), "skipped_drafts": skipped}


def auto_suggest(session_id: str) -> dict | None:
    """5 星评分触发：读最近一轮，policy/非工具/非缓存 → 自动生成 draft 草稿。"""
    from app.db.sessions import get_last_round
    round_ = get_last_round(session_id)
    if not round_:
        return None
    meta = round_["meta"] or {}
    if meta.get("domain") != "policy" or meta.get("had_tools") or meta.get("cached"):
        return None
    if not round_["question"].strip() or not round_["answer"].strip():
        return None
    return draft_doc(round_["question"], round_["answer"])
