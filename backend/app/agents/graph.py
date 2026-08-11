from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents import nodes

def should_retry(state: AgentState) -> str:
    """审核打回且未超上限 → 重写；否则结束。chitchat 不走审核循环。"""
    if state["domain"] == "chitchat":
        return "end"
    if state["review_status"] == "rejected" and state["iteration"] < 2:
        return "rewrite"
    return "end"

def build_graph():
    g = StateGraph(AgentState)
    g.add_node("router", nodes.router_node)
    g.add_node("retriever", nodes.retriever_node)
    g.add_node("writer", nodes.writer_node)
    g.add_node("reviewer", nodes.reviewer_node)
    g.add_edge(START, "router")
    g.add_edge("router", "retriever")
    g.add_edge("retriever", "writer")
    g.add_edge("writer", "reviewer")
    g.add_conditional_edges("reviewer", should_retry, {"rewrite": "writer", "end": END})
    return g.compile()

def run_agent(question: str, session_id: str, history=None) -> dict:
    graph = build_graph()
    return graph.invoke({
        "question": question, "session_id": session_id,
        "history": history or [], "iteration": 0, "review_status": "",
        "tool_results": [],
    })
