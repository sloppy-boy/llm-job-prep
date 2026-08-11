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
    """主模型 3 次失败后走降级模型。"""
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
