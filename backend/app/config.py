from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    deepseek_api_key: str = ""
    siliconflow_api_key: str = ""
    qdrant_url: str = "http://localhost:6333"
    database_url: str = "sqlite:///./mock_orders.db"
    redis_url: str = "redis://localhost:6379"
    # 主模型走 SiliconFlow：DeepSeek-V4-Flash
    primary_base_url: str = "https://api.siliconflow.cn/v1"
    model_primary: str = "deepseek-ai/DeepSeek-V4-Flash"
    # 备用模型保持原配置；主模型失败后切换到不同模型
    fallback_base_url: str = "https://api.siliconflow.cn/v1"
    model_fallback: str = "deepseek-ai/DeepSeek-V3"
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_top_k: int = 3
    semantic_cache_threshold: float = 0.90
    semantic_cache_max: int = 500
    api_key: str = "dev-local-key"
    cors_origins: list[str] = ["*"]  # demo 默认全开；生产收紧为前端域名
    ratelimit_enabled: bool = True
    ratelimit_global_per_min: int = 120
    ratelimit_user_per_min: int = 30
    retrieval_gate_threshold: float = 0.60  # policy 闸门：top 重排相关度低于此值视为资料不足→转人工

settings = Settings()
