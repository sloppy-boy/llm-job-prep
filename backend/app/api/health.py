from fastapi import APIRouter
from app import metrics

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok"}

@router.get("/metrics")
async def metrics_endpoint():
    return metrics.snapshot()
