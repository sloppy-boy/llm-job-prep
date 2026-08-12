from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db.models import SessionLocal, Feedback

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
    return {"ok": True}
