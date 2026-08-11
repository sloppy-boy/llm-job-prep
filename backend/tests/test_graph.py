from app.agents import nodes
from app.agents.graph import should_retry

def test_retry_boundary():
    """审核打回循环边界：iteration<2 重写，达到上限结束，chitchat 结束。"""
    assert should_retry({"domain": "policy", "review_status": "rejected", "iteration": 1}) == "rewrite"
    assert should_retry({"domain": "policy", "review_status": "rejected", "iteration": 2}) == "end"
    assert should_retry({"domain": "chitchat", "review_status": "passed", "iteration": 0}) == "end"

def test_reviewer_increments_iteration(monkeypatch):
    """打回路径 iteration 递增——锁住循环最多 2 次的防死循环机制。"""
    monkeypatch.setattr(nodes, "chat", lambda msgs, **kw: "[驳回] 回答遗漏关键点")
    out = nodes.reviewer_node({
        "question": "q", "session_id": "s", "history": [], "domain": "policy",
        "retrieved_chunks": [{"title": "t", "text": "x"}], "tool_results": [],
        "draft_answer": "a", "iteration": 0, "review_status": "", "review_comment": "",
    })
    assert out["iteration"] == 1 and out["review_status"] == "rejected"

def test_retriever_fallback_on_error(monkeypatch):
    """跨任务契约：RAG 抛异常时兜底为空列表，不中断流程。"""
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(nodes, "hybrid_search", boom)
    monkeypatch.setattr(nodes, "rerank", boom)
    out = nodes.retriever_node({"domain": "policy", "question": "怎么退货",
                                "retrieved_chunks": [], "tool_results": [], "history": []})
    assert out["retrieved_chunks"] == []
