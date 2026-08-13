from sqlalchemy import create_engine, Column, String, Integer, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# 开发用 SQLite，部署时可切 Postgres（SQLAlchemy 抽象，代码不变）
engine = create_engine(settings.database_url)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True)
    role = Column(String(16))
    content = Column(String(4000))
    meta = Column(String, nullable=True)  # 每轮 domain/had_tools/cached 标记（自动沉淀判定依据）
    created_at = Column(DateTime, server_default=func.now())

class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(64), index=True)
    rating = Column(Integer)
    created_at = Column(DateTime, server_default=func.now())

Base.metadata.create_all(engine)

# 轻量迁移：既有 SQLite 库补 meta 列（create_all 不会 ALTER 已有表）
def _ensure_meta_column() -> None:
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN meta VARCHAR"))
            conn.commit()
    except Exception:
        pass  # 已存在则忽略

_ensure_meta_column()
