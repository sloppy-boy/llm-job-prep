from app.rag.chunker import chunk_markdown, read_frontmatter, is_draft, _split_sentences, _units_of


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_frontmatter_metadata_preserved(tmp_path):
    md = _write(tmp_path, "a.md", "---\ntitle: 退款政策\ncategory: policies\n---\n\n正文第一段。")
    chunks = chunk_markdown(md)
    assert chunks and all(c["metadata"]["title"] == "退款政策" for c in chunks)
    assert [c["metadata"]["page"] for c in chunks] == list(range(len(chunks)))
    assert all("title:" not in c["text"] for c in chunks)


def test_table_block_kept_whole(tmp_path):
    rows = "\n".join(f"| 规则{i} | 说明内容占位文字若干 |" for i in range(6))
    md = _write(tmp_path, "t.md", "## 表格\n\n" + rows + "\n")
    chunks = chunk_markdown(md, chunk_size=400)
    holder = [c for c in chunks if "规则0" in c["text"]]
    assert len(holder) == 1
    text = holder[0]["text"]
    assert "规则5" in text  # 整表落在同一个 chunk
    for line in text.splitlines():
        if line.strip().startswith("|"):
            assert line.strip().endswith("|")  # 行完整，未被切断


def test_overlong_table_split_by_rows_with_header(tmp_path):
    rows = "\n".join(f"| 列A{i} | 列B{i} | 较长填充文本让总长度超过 400 字符" for i in range(12))
    md = _write(tmp_path, "t2.md", "## 大表格\n\n" + rows + "\n")
    chunks = chunk_markdown(md, chunk_size=400)
    big = [c for c in chunks if "列A0" in c["text"]]
    assert big, "表格应被拆成若干片"
    header = "| 列A0 | 列B0 | 较长填充文本让总长度超过 400 字符"
    assert all(header in c["text"] for c in big)  # 每片都含表头
    assert sum(c["text"].count(header) for c in big) == len(big)  # 表头每片恰好一次
    assert "".join(c["text"] for c in big).count("列A11") == 1  # 最后一行不丢


def test_sentence_boundary_not_cut(tmp_path):
    sentences = [f"第{i}个完整句子，" + "内容内容" * 12 + "结尾。" for i in range(10)]
    body = "".join(sentences)
    md = _write(tmp_path, "s.md", "## 长段落\n\n" + body + "\n")
    chunks = chunk_markdown(md, chunk_size=400)
    assert len(chunks) >= 2  # 段落超长被切分
    for c in chunks:
        text = c["text"]
        if "\n" in text:
            text = text.split("\n", 1)[1]  # 去掉标题行
        assert text.endswith("。")  # 每片都由完整句子组成，不切句子
    joined = "".join(c["text"] for c in chunks)
    for s in sentences:
        assert s in joined  # 每个完整句子都完整出现


def test_chunks_respect_size_bound(tmp_path):
    body = "\n\n".join(f"段落{i}：" + "内容" * 40 for i in range(20))
    md = _write(tmp_path, "b.md", "## 标题\n\n" + body + "\n")
    chunks = chunk_markdown(md, chunk_size=400)
    assert chunks
    # 标题前缀很短（2 字符），允许少量溢出
    for c in chunks:
        assert len(c["text"]) <= 400 + 4


def test_overlong_paragraph_kept_whole_without_sentence_boundary(tmp_path):
    long_line = "长" * 600  # 无句读的单行，无法按句拆
    md = _write(tmp_path, "o.md", "## 标题\n\n" + long_line + "\n")
    chunks = chunk_markdown(md, chunk_size=400)
    assert any("长" * 600 in c["text"] for c in chunks)  # 整段保留，未截断


def test_heading_context_carried(tmp_path):
    md = _write(tmp_path, "h.md", "# 退货规则\n\n" + "\n\n".join(f"内容{i}：" + "字" * 50 for i in range(20))
        + "\n\n# 退款时效\n\n" + "\n\n".join(f"退款{i}：" + "字" * 50 for i in range(20)) + "\n")
    chunks = chunk_markdown(md, chunk_size=200)
    seg1 = [c for c in chunks if "内容0" in c["text"]]
    seg2 = [c for c in chunks if "退款0" in c["text"]]
    assert seg1 and seg2
    assert all("# 退货规则" in c["text"] for c in seg1)  # 标题跨块重复携带
    assert all("# 退款时效" in c["text"] for c in seg2)


def test_empty_body_returns_empty(tmp_path):
    md = _write(tmp_path, "e.md", "---\ntitle: 空文档\n---\n")
    assert chunk_markdown(md) == []


def test_signature_backcompat(tmp_path):
    md = _write(tmp_path, "c.md", "## 兼容\n\n正文内容若干。" * 30)
    assert chunk_markdown(md) == chunk_markdown(md, strategy="recursive")
    assert _split_sentences("句子一。句子二！句子三？") == ["句子一。", "句子二！", "句子三？"]
    assert _units_of("## 标题\n\n段落一\n\n| a | b |\n| c | d |") == ["## 标题", "段落一", "| a | b |\n| c | d |"]


def test_chunk_metadata_includes_path(tmp_path):
    md = _write(tmp_path, "a.md", "# 标题\n\n正文。")
    chunks = chunk_markdown(md)
    assert chunks[0]["metadata"]["path"] == str(md)


def test_read_frontmatter_and_is_draft(tmp_path):
    d = _write(tmp_path, "d.md", "---\ntitle: x\nstatus: draft\n---\n\n正文")
    p = _write(tmp_path, "p.md", "---\ntitle: x\nstatus: published\n---\n\n正文")
    assert read_frontmatter(d)["status"] == "draft"
    assert is_draft(d) is True
    assert is_draft(p) is False
