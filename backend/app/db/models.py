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
    created_at = Column(DateTime, server_default=func.now())

Base.metadata.create_all(engine)
