from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents import nodes


def build_graph():
    """全链路图（评测用）：路由→工具→检索→写作，一次性 invoke 返回 draft_answer。"""
    g = StateGraph(AgentState)
    g.add_node("router", nodes.router_node)
    g.add_node("tool", nodes.tool_node)
    g.add_node("retriever", nodes.retriever_node)
    g.add_node("writer", nodes.writer_node)
    g.add_edge(START, "router")
    g.add_edge("router", "tool")
    g.add_edge("tool", "retriever")
    g.add_edge("retriever", "writer")
    g.add_edge("writer", END)
    return g.compile()


def build_front_graph():
    """前置段图（线上 /chat 用）：路由→工具→检索，同步 invoke 拿到领域/工具结果/检索切片。

    真流式拆分的另一半：写作因需要逐 token 推送，留在 chat.py 里流式执行，
    前置段（不产生大文本）用编译后的 LangGraph 图跑，LangGraph 就是线上编排载体。
    """
    g = StateGraph(AgentState)
    g.add_node("router", nodes.router_node)
    g.add_node("tool", nodes.tool_node)
    g.add_node("retriever", nodes.retriever_node)
    g.add_edge(START, "router")
    g.add_edge("router", "tool")
    g.add_edge("tool", "retriever")
    g.add_edge("retriever", END)
    return g.compile()


def run_agent(question: str, session_id: str, history=None, user_id: str = "user-001") -> dict:
    graph = build_graph()
    return graph.invoke({
        "question": question, "session_id": session_id,
        "history": history or [],
        "user_id": user_id,
        "tool_results": [],
        "retrieved_chunks": [],
    })
