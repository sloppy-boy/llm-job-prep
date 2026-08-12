from fastapi import APIRouter

from app.db.sessions import list_sessions

router = APIRouter()


@router.get("/sessions")
def sessions():
    return {"sessions": list_sessions()}
