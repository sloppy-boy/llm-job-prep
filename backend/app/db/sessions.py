from app.db.models import SessionLocal, Message

def save_message(session_id: str, role: str, content: str) -> None:
    db = SessionLocal()
    try:
        db.add(Message(session_id=session_id, role=role, content=content))
        db.commit()
    finally:
        db.close()

def get_history(session_id: str, limit: int = 10) -> list[dict]:
    db = SessionLocal()
    try:
        rows = db.query(Message).filter_by(session_id=session_id)\
                .order_by(Message.id.desc()).limit(limit).all()
        return [{"role": m.role, "content": m.content} for m in reversed(rows)]
    finally:
        db.close()
