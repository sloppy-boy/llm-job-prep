from app import llm

def test_chat_returns_text(monkeypatch):
    """非流式返回 str：mock _chat_once，验证 chat 返回文本。"""
    class FakeMsg:
        content = "你好"
    class FakeResp:
        usage = None
        choices = [type("C", (), {"message": FakeMsg()})]
    monkeypatch.setattr(llm, "_chat_once", lambda *a, **k: FakeResp())
    assert llm.chat([{"role": "user", "content": "hi"}]) == "你好"

def test_chat_retries_then_fallback(monkeypatch):
    """_retry 内部主模型 3 次失败后走降级模型。mock _chat_once，仍应 4 次调用。"""
    calls = []
    def flaky_once(messages, tools, model, stream):
        calls.append(model)
        if model == "deepseek-chat":
            raise RuntimeError("boom")
        return "fallback-ok"
    monkeypatch.setattr(llm, "_chat_once", flaky_once)
    monkeypatch.setattr(llm.settings, "model_fallback", "deepseek-reasoner")
    assert llm.chat([{"role": "user", "content": "hi"}]) == "fallback-ok"
    assert len(calls) == 4  # 3 次主 + 1 次降级

def test_chat_with_tools(monkeypatch):
    """chat_with_tools 解析结构化 tool_calls，返回 (content, tool_calls)。"""
    import json
    class FakeFunction:
        name = "query_order"
        arguments = json.dumps({"order_id": "20260811001"})
    class FakeToolCall:
        function = FakeFunction()
    class FakeMsg:
        content = ""
        tool_calls = [FakeToolCall()]
    class FakeResp:
        usage = None
        choices = [type("C", (), {"message": FakeMsg()})]
    monkeypatch.setattr(llm, "_retry", lambda *a, **k: FakeResp())
    content, tool_calls = llm.chat_with_tools([], [])
    assert content == ""
    assert tool_calls == [{"name": "query_order", "arguments": {"order_id": "20260811001"}}]

def test_chat_with_tools_no_tool_calls(monkeypatch):
    """chat_with_tools 无工具调用时返回 (content, 空列表)。"""
    class FakeMsg:
        content = "普通回复"
        tool_calls = None
    class FakeResp:
        usage = None
        choices = [type("C", (), {"message": FakeMsg()})]
    monkeypatch.setattr(llm, "_retry", lambda *a, **k: FakeResp())
    content, tool_calls = llm.chat_with_tools([], [])
    assert content == "普通回复"
    assert tool_calls == []

def test_chat_stream_yields_tokens(monkeypatch):
    """stream=True 返回可迭代响应，逐 token 产出 delta.content。"""
    import app.llm as llm_mod
    class FakeMsg:  # 模拟一个流式响应块
        def __init__(self, t): self.delta = type("D", (), {"content": t})()
    def fake_chunks(*a, **k):
        yield type("R", (), {"choices": [FakeMsg("你")]})()
        yield type("R", (), {"choices": [FakeMsg("好")]})()
    monkeypatch.setattr(llm_mod, "_chat_once", fake_chunks)
    resp = llm_mod.chat([{"role": "user", "content": "hi"}], stream=True)
    out = "".join(c.choices[0].delta.content for c in resp)
    assert out == "你好"
