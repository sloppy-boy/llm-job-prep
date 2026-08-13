import re
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

def read_frontmatter(path: Path) -> dict:
    """读取 md 的 YAML frontmatter 元数据（轻量，供列表/过滤用）。"""
    meta, _ = _extract_frontmatter(path.read_text(encoding="utf-8"))
    return meta


def is_draft(path: Path) -> bool:
    """frontmatter status == draft 视为草稿（不进检索/语料/索引）。"""
    return read_frontmatter(path).get("status") == "draft"

def _split_sentences(text: str) -> list[str]:
    """按句子结束标点切分（保留标点），返回 >=1 个片段。"""
    parts = re.split(r"(?<=[。！？.!?])", text)
    return [p for p in parts if p.strip()]

def _split_overlong(unit: str, chunk_size: int, heading: str | None) -> list[str]:
    """超长原子单元的拆块策略：段落按句边界拆；表格按行拆且每片重复首行表头。"""
    stripped = unit.strip()
    pieces = []
    if stripped.startswith("|"):
        lines = unit.splitlines()
        if not lines:
            return []
        header, body = lines[0], lines[1:] or []
        current, current_len = [header], len(header)
        for row in body:
            if current_len + len(row) + 1 <= chunk_size:
                current.append(row)
                current_len += len(row) + 1
            else:
                pieces.append("\n".join(current))
                current, current_len = [header, row], len(header) + len(row) + 1
        pieces.append("\n".join(current))
    else:
        current = ""
        for s in _split_sentences(unit):
            if len(current) + len(s) <= chunk_size:
                current += s
            else:
                if current.strip():
                    pieces.append(current)
                current = s
        if current.strip():
            pieces.append(current)
    if heading:
        pieces = [heading + "\n" + p for p in pieces]
    return pieces

def _units_of(body: str) -> list[str]:
    """把正文切成原子单元：标题、段落（空行分隔）、表格块（连续 | 行）、代码围栏。"""
    lines = body.splitlines()
    units, i, n = [], 0, len(lines)
    while i < n:
        line, stripped = lines[i], lines[i].strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):  # 代码围栏整体保留
            buf = [line]
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i]); i += 1
            if i < n:
                buf.append(lines[i]); i += 1
            units.append("\n".join(buf))
            continue
        if stripped.startswith("|"):  # 表格块：连续 | 行
            buf = [line]
            i += 1
            while i < n and lines[i].strip().startswith("|"):
                buf.append(lines[i]); i += 1
            units.append("\n".join(buf))
            continue
        if stripped.startswith("#"):  # 标题单独成单元
            units.append(line)
            i += 1
            continue
        buf = [line]  # 普通段落：收集到空行
        i += 1
        while i < n and lines[i].strip():
            buf.append(lines[i]); i += 1
        units.append("\n".join(buf))
    return units

def chunk_markdown(path: Path, strategy="recursive", chunk_size=400, overlap=50):
    """结构感知分块：按标题/段落/表格/代码围栏切原子单元，贪心打包成 <=chunk_size 的块。

    标题作为章节上下文前缀重复携带（利于检索命中）；超长段落按句边界拆、
    超长表格按行拆（重复表头）。strategy 参数保留用于兼容，当前仅实现结构感知 recursive。
    """
    raw = path.read_text(encoding="utf-8")
    meta, body = _extract_frontmatter(raw)
    units = _units_of(body)
    chunks = []
    pending, pending_len = [], 0
    current_heading = None

    def flush():
        nonlocal pending, pending_len
        if pending:
            text = "\n\n".join(pending).strip()
            if text:
                chunks.append(text)
        pending, pending_len = [], 0

    def start_chunk():
        nonlocal pending, pending_len
        pending = [current_heading] if current_heading else []
        pending_len = len(current_heading) if current_heading else 0

    for u in units:
        if u.strip().startswith("#"):
            flush()
            current_heading = u.strip()
            continue  # 标题不单独成块，作为后续内容单元的前缀
        if len(u) > chunk_size:  # 超长单元单独处理（_split_overlong 自带标题前缀）
            flush()
            chunks.extend(_split_overlong(u, chunk_size, current_heading))
            continue
        if not pending and current_heading:  # 标题随首个内容单元一起成块
            start_chunk()
        if pending_len + len(u) + 2 <= chunk_size:
            pending.append(u)
            pending_len += len(u) + 2
        else:
            flush()
            start_chunk()
            pending.append(u)
            pending_len = len(u)
    flush()

    return [{"text": c, "metadata": {**meta, "path": str(path), "page": i}} for i, c in enumerate(chunks)]
