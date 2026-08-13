from typing import TypedDict

class AgentState(TypedDict):
    question: str
    session_id: str
    history: list
    domain: str
    retrieved_chunks: list
    tool_results: list
    draft_answer: str
