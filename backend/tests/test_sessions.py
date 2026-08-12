from fastapi.testclient import TestClient

from app.db.sessions import save_message, get_history
from app.main import app


def test_save_and_get():
    save_message("sess-test", "user", "你好")
    hist = get_history("sess-test")
    assert hist[-1]["content"] == "你好"
    assert hist[-1]["role"] == "user"


def test_sessions_list_returns(monkeypatch):
    """GET /api/v1/sessions 返回会话列表，字段为 session_id/updated_at/preview。"""
    import app.api.sessions as s
    monkeypatch.setattr(s, "list_sessions", lambda: [
        {"session_id": "s1", "updated_at": "t", "preview": "hi"}])
    c = TestClient(app)
    r = c.get("/api/v1/sessions", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    assert r.json()["sessions"][0]["session_id"] == "s1"


def test_sessions_list_requires_key():
    """会话列表与其它业务接口一致，需 X-API-Key。"""
    c = TestClient(app)
    assert c.get("/api/v1/sessions").status_code == 401


def test_session_messages_returns_history(monkeypatch):
    """GET /api/v1/sessions/{id}/messages 返回该会话历史，字段为 role/content。"""
    import app.api.sessions as s
    monkeypatch.setattr(s, "get_history", lambda sid, limit=10: [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "您好，有什么可以帮您？"},
    ])
    c = TestClient(app)
    r = c.get("/api/v1/sessions/s1/messages", headers={"X-API-Key": "dev-local-key"})
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0] == {"role": "user", "content": "你好"}
    assert msgs[1]["role"] == "assistant"


def test_session_messages_requires_key():
    """历史消息接口与其它业务接口一致，需 X-API-Key。"""
    c = TestClient(app)
    assert c.get("/api/v1/sessions/s1/messages").status_code == 401


def test_list_sessions_empty_db(tmp_path, monkeypatch):
    """list_sessions 对空库返回 []；用临时 SQLite 隔离，避免污染真实 DB。"""
    import app.db.sessions as s
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base
    engine = create_engine(f"sqlite:///{tmp_path / 'sessions_empty.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(s, "SessionLocal", sessionmaker(bind=engine))
    assert s.list_sessions() == []


def test_list_sessions_preview_is_latest_user_message(tmp_path, monkeypatch):
    """preview 取最新一条 user 消息前 30 字；updated_at 取最新消息时间。

    构造 用户问->助手答->用户再问 三条消息，最新一条是 user，
    验证 preview 来自它而非助手答句。
    """
    import app.db.sessions as s
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db.models import Base, Message
    engine = create_engine(f"sqlite:///{tmp_path / 'sessions_prev.db'}")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    sess.add_all([
        Message(session_id="s-prev", role="user", content="你好"),
        Message(session_id="s-prev", role="assistant", content="你好，请问有什么可以帮您？"),
        Message(session_id="s-prev", role="user", content="我想申请七天无理由退货，请告诉我流程"),
    ])
    sess.commit()
    sess.close()

    monkeypatch.setattr(s, "SessionLocal", sessionmaker(bind=engine))
    rows = s.list_sessions()
    assert len(rows) == 1
    assert rows[0]["session_id"] == "s-prev"
    assert rows[0]["preview"] == "我想申请七天无理由退货，请告诉我流程"[:30]
    assert "updated_at" in rows[0]
