from app.agents import nodes

def test_retriever_fallback_on_error(monkeypatch):
    """跨任务契约：RAG 抛异常时兜底为空列表，不中断流程。"""
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(nodes, "hybrid_search", boom)
    monkeypatch.setattr(nodes, "rerank", boom)
    out = nodes.retriever_node({"domain": "policy", "question": "怎么退货",
                                "retrieved_chunks": [], "tool_results": [], "history": []})
    assert out["retrieved_chunks"] == []

def test_run_agent_produces_answer(monkeypatch):
    from app.agents import nodes
    monkeypatch.setattr(nodes, "router_node", lambda s: {"domain": "policy"})
    monkeypatch.setattr(nodes, "tool_node", lambda s: {"tool_results": []})
    monkeypatch.setattr(nodes, "retriever_node", lambda s: {"retrieved_chunks": [{"title": "t", "text": "资料"}]})
    monkeypatch.setattr(nodes, "writer_node", lambda s: {"draft_answer": "基于资料的回答"})
    from app.agents.graph import run_agent
    r = run_agent("七天无理由", "s1")
    assert r["draft_answer"] == "基于资料的回答"
    assert r["tool_results"] == [] and len(r["retrieved_chunks"]) == 1

def test_gate_passes_when_tools_ok():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "order", "tool_results": [{"order_id": "1", "status": "已发货"}]}) is True

def test_gate_passes_when_retrieved():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "policy", "retrieved_chunks": [{"title": "x", "text": "y"}]}) is True

def test_gate_blocks_no_data():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "policy", "retrieved_chunks": []}) is False
    assert gate_decision({"domain": "order", "tool_results": [{"error": "订单不存在"}]}) is False

def test_gate_passes_chitchat():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "chitchat", "retrieved_chunks": []}) is True
