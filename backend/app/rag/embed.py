from openai import OpenAI
from app.config import settings

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.siliconflow_api_key,
                         base_url="https://api.siliconflow.cn/v1")
    return _client

def embed_texts(texts: list[str]) -> list[list[float]]:
    resp = _get_client().embeddings.create(model=settings.embedding_model, input=texts)
    return [d.embedding for d in resp.data]
