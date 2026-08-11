from pathlib import Path

def _extract_frontmatter(raw: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (元数据, 正文)。"""
    meta = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            return meta, parts[2]
    return meta, raw

def _chunk(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks, step = [], size - overlap
    for i in range(0, len(text), step):
        chunks.append(text[i:i + size])
    return [c for c in chunks if c.strip()]

def chunk_markdown(path: Path, strategy="recursive", chunk_size=400, overlap=50):
    raw = path.read_text(encoding="utf-8")
    meta, body = _extract_frontmatter(raw)
    out = []
    for i, c in enumerate(_chunk(body, chunk_size, overlap)):
        out.append({"text": c, "metadata": {**meta, "page": i}})
    return out
