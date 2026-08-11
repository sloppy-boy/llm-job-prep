from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    deepseek_api_key: str = ""
    siliconflow_api_key: str = ""
    qdrant_url: str = "http://localhost:6333"
    database_url: str = "sqlite:///./mock_orders.db"
    redis_url: str = "redis://localhost:6379"
    model_primary: str = "deepseek-chat"
    model_fallback: str = "deepseek-chat"
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_k: int = 3
    max_review_rounds: int = 2
    api_key: str = "dev-local-key"

settings = Settings()
