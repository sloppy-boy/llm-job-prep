from fastapi.testclient import TestClient
from app.main import app


def _post(message: str):
    """POST /api/v1/chat 的快捷方式。"""
    return TestClient(app).post("/api/v1/chat",
                                json={"session_id": "s1", "message": message},
                                headers={"X-API-Key": "dev-local-key"})


class _FakeMsg:
    def __init__(self, t):
        self.delta = type("D", (), {"content": t})()


def _make_stream(text: str):
    """把字符串逐字切成流式 chunk，模拟 llm.chat(stream=True) 的迭代器。"""
    def _stream(*a, **k):
        for ch in text:
            yield type("R", (), {"choices": [_FakeMsg(ch)]})()
    return _stream


def test_chat_returns_sse(monkeypatch):
    import app.api.chat as chat_mod
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, hist, user_id="user-001": {
        "question": q, "session_id": sid, "history": hist or [],
        "domain": "order",
        "tool_results": [{"order_id": "20260811001", "status": "已发货",
                          "items": "智能音箱", "amount": 299.0}],
        "retrieved_chunks": [{"title": "七天无理由", "text": "支持"}]})
    # 闸门走兜底整句分支：验证 card/token/sources/done 事件结构完整
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: False)
    monkeypatch.setattr(chat_mod, "llm_chat", lambda msgs, stream=False: "可以，支持7天无理由。")
    r = _post("订单到哪了")
    assert r.status_code == 200
    assert "token" in r.text and "sources" in r.text and "card" in r.text and "done" in r.text


def test_chat_error_tool_result_emits_no_card(monkeypatch):
    """不存在订单时工具返回 {"error": ...}，不得被归类为 logistics 卡片（前端会 .map 崩溃）。"""
    import app.api.chat as chat_mod
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, hist, user_id="user-001": {
        "question": q, "session_id": sid, "history": hist or [],
        "domain": "order",
        "tool_results": [{"error": "订单不存在"}],
        "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: False)
    monkeypatch.setattr(chat_mod, "llm_chat", lambda msgs, stream=False: "未找到该订单，请核实订单号。")
    r = _post("查 20260000000")
    assert r.status_code == 200
    assert "card" not in r.text, "error 结果不应渲染卡片"


def test_kind_of_returns_none_for_error_dict():
    """_kind_of 对 error dict 返回 None（跳过卡片），不兜底成 logistics。"""
    import app.api.chat as chat_mod
    assert chat_mod._kind_of({"error": "订单不存在"}) is None
    assert chat_mod._kind_of({"order_id": "1", "status": "已发货"}) == "order"
    assert chat_mod._kind_of({"refund_id": "R1", "status": "已申请"}) == "refund"
    assert chat_mod._kind_of([{"time": "08-10", "event": "已发货"}]) == "logistics"


def test_chat_cache_hit_returns_cached_without_agent(monkeypatch):
    """命中语义缓存时直接返回缓存内容，不再调用 agent 链路。"""
    import app.api.chat as chat_mod
    called = {"n": 0}
    def fake_front(q, sid, hist, user_id="user-001"):
        called["n"] += 1
        return {"domain": "policy", "tool_results": [], "retrieved_chunks": []}
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: "缓存的七天无理由答案")
    monkeypatch.setattr(chat_mod, "run_front", fake_front)
    r = _post("怎么退货")
    assert "缓存的七天无理由答案" in r.text
    assert called["n"] == 0, "命中缓存不应走 agent 链路"


def test_chat_writes_cache_only_without_tools(monkeypatch):
    """无工具结果的确定性问答写入缓存。"""
    import app.api.chat as chat_mod
    written = {}
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "cache_set", lambda q, a: written.update({q: a}))
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, hist, user_id="user-001": {
        "question": q, "session_id": sid, "history": hist or [],
        "domain": "policy", "tool_results": [], "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: False)
    monkeypatch.setattr(chat_mod, "llm_chat", lambda msgs, stream=False: "答案A")
    r = _post("怎么退货")
    assert written.get("怎么退货") == "答案A"
    # 兜底整句也走 SSE token 事件，解析拼接后比较
    import json as _json
    tokens = "".join(_json.loads(p.split("data: ", 1)[1].strip()).get("text", "")
                     for p in r.text.split("event: message")
                     if "data: " in p and _json.loads(p.split("data: ", 1)[1].strip()).get("type") == "token")
    assert tokens == "答案A"


def test_chat_does_not_cache_tool_results(monkeypatch):
    """带工具结果（订单/物流/退款）不缓存，避免状态过时。"""
    import app.api.chat as chat_mod
    written = {}
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "cache_set", lambda q, a: written.update({q: a}))
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, hist, user_id="user-001": {
        "question": q, "session_id": sid, "history": hist or [],
        "domain": "order",
        "tool_results": [{"order_id": "1", "status": "已发货"}],
        "retrieved_chunks": []})
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: True)
    monkeypatch.setattr(chat_mod, "llm_chat_stream", _make_stream("答案"))
    r = _post("查订单1")
    assert written == {}, "有工具结果不应写入缓存"


def test_chat_error_emits_error_event(monkeypatch):
    import app.api.chat as chat_mod
    def boom(q, sid, hist, user_id="user-001"):
        raise RuntimeError("boom")
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "run_front", boom)
    r = _post("hi")
    assert "error" in r.text and "done" in r.text


def test_chat_streams_tokens_incrementally(monkeypatch):
    """真流式：writer 输出逐 token 通过 SSE 增量推送，而非整句阻塞后回放。"""
    import app.api.chat as chat_mod
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: True)
    monkeypatch.setattr(chat_mod, "cache_get", lambda q: None)
    monkeypatch.setattr(chat_mod, "cache_set", lambda q, a: None)
    monkeypatch.setattr(chat_mod, "run_front", lambda q, sid, h, user_id="user-001": {
        "question": q, "session_id": sid, "history": h or [],
        "domain": "policy", "tool_results": [],
        "retrieved_chunks": [{"title": "t", "text": "x"}]})
    monkeypatch.setattr(chat_mod, "build_writer_messages", lambda s: [{"role": "user", "content": "q"}])

    def fake_stream(*a, **k):
        for ch in "流式":
            yield type("R", (), {"choices": [_FakeMsg(ch)]})()
        yield type("R", (), {"choices": []})()  # usage 末块：choices 为空

    monkeypatch.setattr(chat_mod, "llm_chat_stream", fake_stream)
    r = _post("hi")
    assert r.text.count('"type": "token"') >= 2
    assert "流" in r.text and "式" in r.text
    # include_usage 的末块 choices 为空：必须被跳过而不是触发 IndexError
    assert "error" not in r.text, "空 choices 末块被误读不应产出 error 事件"
    assert "sources" in r.text, "空 choices 块被跳过后才应继续输出 sources"


def _collect(agen):
    """asyncio.run 收集 async 迭代器结果（测试环境无 pytest-asyncio）。"""
    import asyncio
    async def _run():
        return [x async for x in agen]
    return asyncio.run(_run())


def test_aiter_sync_yields_all():
    import app.api.chat as chat_mod
    assert _collect(chat_mod._aiter_sync(iter(["a", "b", "c"]))) == ["a", "b", "c"]


def test_aiter_sync_empty():
    import app.api.chat as chat_mod
    assert _collect(chat_mod._aiter_sync(iter([]))) == []


def test_aiter_sync_propagates_non_stop_exception():
    import pytest
    import app.api.chat as chat_mod

    def gen():
        yield "a"
        yield "b"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _collect(chat_mod._aiter_sync(gen()))  # 非 StopIteration 异常向上传播，不被吞


def test_blocking_calls_go_through_thread_pool(monkeypatch):
    """阻塞调用（cache_get/run_front/llm_chat/cache_set/save_message）确实走线程池，不阻塞事件循环。"""
    import asyncio
    import app.api.chat as chat_mod
    seen = []

    async def fake_blocking(fn, *a, **k):
        seen.append(fn.__name__)
        return await asyncio.to_thread(fn, *a, **k)

    monkeypatch.setattr(chat_mod, "_blocking", fake_blocking)

    def fake_cache_get(q):
        return None

    def fake_front(q, sid, hist, user_id="user-001"):
        return {"question": q, "session_id": sid, "history": hist or [],
                "domain": "policy", "tool_results": [], "retrieved_chunks": []}

    def fake_llm_chat(msgs, stream=False):
        return "答"

    monkeypatch.setattr(chat_mod, "cache_get", fake_cache_get)
    monkeypatch.setattr(chat_mod, "run_front", fake_front)
    monkeypatch.setattr(chat_mod, "gate_decision", lambda s: False)
    monkeypatch.setattr(chat_mod, "llm_chat", fake_llm_chat)
    r = _post("hi")
    assert r.status_code == 200
    for name in ("fake_cache_get", "fake_front", "fake_llm_chat", "cache_set", "save_message"):
        assert name in seen, f"{name} 应走线程池"
