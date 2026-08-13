from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import kb
from app.db.sessions import save_message

router = APIRouter()


class BackfillRequest(BaseModel):
    question: str
    answer: str


class HumanReplyRequest(BaseModel):
    question: str
    answer: str


@router.get("/kb/docs")
def kb_docs():
    return {"docs": kb.list_docs()}


@router.post("/kb/reindex")
def kb_reindex():
    res = kb.reindex()
    return {"ok": True, **res}


@router.post("/kb/backfill")
def kb_backfill(req: BackfillRequest):
    return kb.draft_doc(req.question, req.answer)


@router.get("/kb/backfill/pending")
def kb_pending():
    return {"pending": kb.pending_docs()}


@router.post("/kb/backfill/{doc_id}/approve")
def kb_approve(doc_id: str):
    try:
        return kb.approve_doc(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/human-reply")
def human_reply(session_id: str, req: HumanReplyRequest):
    save_message(session_id, "assistant", f"（人工客服）{req.answer}")
    return {"ok": True}
