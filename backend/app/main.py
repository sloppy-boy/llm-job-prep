import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware import ObservabilityMiddleware, RateLimitMiddleware
from app.api import health
from app.api import chat as chat_api
from app.api import sessions as sessions_api
from app.api import feedback as feedback_api

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="电商售后智能客服", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.include_router(health.router, prefix="/api/v1")
app.include_router(chat_api.router, prefix="/api/v1")
app.include_router(sessions_api.router, prefix="/api/v1")
app.include_router(feedback_api.router, prefix="/api/v1")
