from langgraph.graph import StateGraph, START, END
from app.agents.state import AgentState
from app.agents import nodes

def build_graph():
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

def run_agent(question: str, session_id: str, history=None) -> dict:
    graph = build_graph()
    return graph.invoke({
        "question": question, "session_id": session_id,
        "history": history or [],
        "tool_results": [],
    })
