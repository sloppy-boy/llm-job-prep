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
    assert gate_decision({"domain": "policy",
                          "retrieved_chunks": [{"title": "x", "text": "y", "score": 0.8}]}) is True

def test_gate_blocks_weak_relevance():
    """检索命中但 top 相关度低于阈值（0.60）→ 资料不足，走转人工（保证知识缺口能触发回填闭环）。"""
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "policy",
                          "retrieved_chunks": [{"title": "x", "text": "y", "score": 0.3}]}) is False

def test_gate_blocks_no_data():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "policy", "retrieved_chunks": []}) is False
    assert gate_decision({"domain": "order", "tool_results": [{"error": "订单不存在"}]}) is False

def test_gate_passes_chitchat():
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "chitchat", "retrieved_chunks": []}) is True

def test_router_human_domain():
    """显式转人工请求 → human 域（不再是 policy 域被检索逻辑处理）"""
    from app.agents.nodes import router_node
    assert router_node({"question": "我要转人工"})["domain"] == "human"
    assert router_node({"question": "找人工客服投诉"})["domain"] == "human"
    assert router_node({"question": "请帮我转真人客服"})["domain"] == "human"
    assert router_node({"question": "订单到哪了"})["domain"] == "order"
    # 转人工意图优先于寒暄词："你好，帮我转人工" 含你好但意图是转人工
    assert router_node({"question": "你好，帮我转人工"})["domain"] == "human"
    assert router_node({"question": "你好，在吗？"})["domain"] == "chitchat"

def test_router_offtopic_domain():
    """售后范围之外的问题 → offtopic 域（确定性挡掉，不进转人工）"""
    from app.agents.nodes import router_node
    assert router_node({"question": "帮我写一篇5000字的毕业论文"})["domain"] == "offtopic"
    assert router_node({"question": "今天天气怎么样"})["domain"] == "offtopic"
    assert router_node({"question": "能帮我翻译这段英文吗"})["domain"] == "offtopic"
    # 域外优先于寒暄："你好，今天天气" 意图是天气 → offtopic
    assert router_node({"question": "你好，今天天气怎么样"})["domain"] == "offtopic"
    # 售后问题不受影响
    assert router_node({"question": "订单到哪了"})["domain"] == "order"
    assert router_node({"question": "七天无理由退货条件是什么"})["domain"] == "policy"

def test_retriever_skips_human_and_offtopic(monkeypatch):
    """human/offtopic 域跳过检索（与 chitchat 同），省一次 embedding/rerank 调用"""
    from app.agents.nodes import retriever_node
    called = {"n": 0}
    def boom(*a, **k):
        called["n"] += 1
        raise RuntimeError("should not be called")
    monkeypatch.setattr("app.agents.nodes.hybrid_search", boom)
    assert retriever_node({"domain": "human", "question": "转人工"})["retrieved_chunks"] == []
    assert retriever_node({"domain": "offtopic", "question": "写论文"})["retrieved_chunks"] == []
    assert called["n"] == 0

def test_gate_human_always_handoff():
    """human 域恒走转人工流程（即使检索相关度很高也不放行写作）"""
    from app.agents.nodes import gate_decision
    assert gate_decision({"domain": "human",
                          "retrieved_chunks": [{"title": "x", "text": "y", "score": 0.99}]}) is False

def test_writer_human_branch_confirms_transfer():
    """human 域 writer：礼貌确认正在转接人工客服，不编造"""
    from app.agents.nodes import build_writer_messages
    msgs = build_writer_messages({"question": "我要转人工", "domain": "human",
                                  "history": [], "tool_results": [], "retrieved_chunks": []})
    assert "转" in msgs[-1]["content"] and "人工" in msgs[-1]["content"]

def test_writer_no_retrieval_requires_human_transfer():
    """兜底话术硬约束：资料不足时提示词必须强制要求提到'转人工'（售后域内知识缺口→转人工）"""
    from app.agents.nodes import build_writer_messages
    msgs = build_writer_messages({"question": "电子发票怎么开", "domain": "policy",
                                  "history": [], "tool_results": [], "retrieved_chunks": []})
    assert "转人工" in msgs[-1]["content"]

def test_writer_offtopic_refuses_without_extra_advice():
    """offtopic 域 writer（评测图路径）：礼貌拒绝，不给售后以外的建议"""
    from app.agents.nodes import build_writer_messages
    msgs = build_writer_messages({"question": "帮我写毕业论文", "domain": "offtopic",
                                  "history": [], "tool_results": [], "retrieved_chunks": []})
    assert "售后" in msgs[-1]["content"]
    assert "无法协助" in msgs[-1]["content"]

def test_writer_offtopic_is_deterministic_template(monkeypatch):
    """offtopic 域 writer_node 直接返回确定性模板，不调 LLM——
    评测路径与线上 chat 路径行为一致，杜绝 judge 对自由生成结果的随机误判。"""
    from app.agents.nodes import writer_node, OFFTOPIC_REPLY
    called = {"n": 0}
    monkeypatch.setattr("app.agents.nodes.chat",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or "不应被调用")
    out = writer_node({"question": "帮我写毕业论文", "domain": "offtopic",
                       "history": [], "tool_results": [], "retrieved_chunks": []})
    assert out["draft_answer"] == OFFTOPIC_REPLY
    assert called["n"] == 0, "offtopic 不应调用 LLM"

def test_build_front_graph_runs_nodes_in_order(monkeypatch):
    """线上前置段图：路由→工具→检索按序执行，返回合并后的状态（LangGraph 是线上编排载体）。"""
    from app.agents.graph import build_front_graph
    from app.agents import nodes
    order = []
    monkeypatch.setattr(nodes, "router_node",
                        lambda s: order.append("router") or {"domain": "order"})
    monkeypatch.setattr(nodes, "tool_node",
                        lambda s: order.append("tool") or {"tool_results": [{"order_id": "1", "status": "已发货"}]})
    monkeypatch.setattr(nodes, "retriever_node",
                        lambda s: order.append("retriever") or {"retrieved_chunks": []})
    g = build_front_graph()
    st = g.invoke({"question": "订单1", "session_id": "s", "history": [], "user_id": "u1",
                   "tool_results": [], "retrieved_chunks": []})
    assert order == ["router", "tool", "retriever"]
    assert st["domain"] == "order"
    assert st["tool_results"][0]["status"] == "已发货"
