from fastapi import APIRouter

from app.db.sessions import list_sessions, get_history

router = APIRouter()


@router.get("/sessions")
def sessions():
    return {"sessions": list_sessions()}


@router.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    return {"messages": get_history(session_id, limit=50)}
