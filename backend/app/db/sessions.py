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

def list_sessions(limit: int = 20) -> list[dict]:
    """返回会话列表 [{session_id, updated_at, preview}]，按最近更新倒序。

    - updated_at：该会话最新一条消息的时间（created_at，SQLite server_default 可能为空，则用 id 近似）
    - preview：该会话最新一条 user 消息的前 30 字；无 user 消息则为空串
    用 id 倒序遍历（id 自增可作时间单调近似），首见即最新。
    """
    with SessionLocal() as db:
        rows = db.query(Message.session_id, Message.id, Message.role,
                        Message.content, Message.created_at)\
                 .order_by(Message.id.desc()).all()
    latest: dict[str, str] = {}
    previews: dict[str, str] = {}
    order: list[str] = []
    for sid, mid, role, content, created_at in rows:
        if sid not in latest:
            latest[sid] = created_at.isoformat() if created_at else str(mid)
            order.append(sid)
        if role == "user" and sid not in previews:
            previews[sid] = (content or "")[:30]
    return [
        {"session_id": sid, "updated_at": latest[sid], "preview": previews.get(sid, "")}
        for sid in order[:limit]
    ]
