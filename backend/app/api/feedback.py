from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.models import SessionLocal, Feedback
from app import kb as kb_mod

router = APIRouter()

class FeedbackRequest(BaseModel):
    session_id: str
    rating: int

def save_feedback(session_id: str, rating: int) -> None:
    """把一条评分写入 feedback 表。独立成函数便于测试 monkeypatch。"""
    db = SessionLocal()
    try:
        db.add(Feedback(session_id=session_id, rating=rating))
        db.commit()
    finally:
        db.close()

@router.post("/feedback")
def feedback(req: FeedbackRequest):
    if req.rating < 1 or req.rating > 5:
        raise HTTPException(status_code=400, detail="rating 必须在 1-5 之间")
    save_feedback(req.session_id, req.rating)
    suggested = None
    if req.rating == 5:
        try:
            suggested = kb_mod.auto_suggest(req.session_id)
        except Exception:
            suggested = None  # 自动沉淀失败不影响评分闭环
    return {"ok": True, "suggested": suggested}
