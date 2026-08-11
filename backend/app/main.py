import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.middleware import ObservabilityMiddleware
from app.api import health

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="电商售后智能客服", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(ObservabilityMiddleware)
app.include_router(health.router, prefix="/api/v1")
