from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NoraConversation, NoraMessage, Property
from app.services import nora
from app.services.nora_llm import get_llm
from app.services.rag.embedder import MissingAPIKeyError, get_embedder

router = APIRouter(prefix="/nora", tags=["nora"])


class AskRequest(BaseModel):
    question: str
    property_id: int | None = None
    conversation_id: int | None = None


@router.post("/ask")
def ask(payload: AskRequest, db: Session = Depends(get_db)):
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="Question is empty.")
    if (
        payload.property_id is not None
        and db.get(Property, payload.property_id) is None
    ):
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        llm = get_llm()
        embedder = get_embedder()
    except MissingAPIKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    try:
        return nora.ask(
            db,
            payload.question,
            llm,
            embedder,
            property_id=payload.property_id,
            conversation_id=payload.conversation_id,
        )
    except Exception as exc:  # surface OpenAI billing/model errors readably
        import openai

        if isinstance(exc, openai.OpenAIError):
            db.rollback()
            raise HTTPException(
                status_code=502,
                detail=f"OpenAI request failed: {exc}",
            )
        raise


@router.get("/conversations")
def conversations(
    property_id: int | None = None,
    scope: str | None = None,
    db: Session = Depends(get_db),
):
    """List saved conversations. Pass property_id to get just that property's
    chats; pass scope=portfolio to get only the portfolio-wide (unscoped)
    ones. With neither, returns everything, newest first."""
    query = db.query(NoraConversation)
    if property_id is not None:
        query = query.filter(NoraConversation.property_id == property_id)
    elif scope == "portfolio":
        query = query.filter(NoraConversation.property_id.is_(None))
    rows = query.order_by(
        NoraConversation.created_at.desc(), NoraConversation.id.desc()
    ).all()
    return [
        {
            "id": c.id,
            "title": c.title,
            "property_id": c.property_id,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


@router.get("/conversations/{conversation_id}")
def conversation_messages(conversation_id: int, db: Session = Depends(get_db)):
    if db.get(NoraConversation, conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    rows = (
        db.query(NoraMessage)
        .filter_by(conversation_id=conversation_id)
        .order_by(NoraMessage.id)
        .all()
    )
    return [
        {
            "id": m.id,
            "role": m.role.value,
            "content": m.content,
            "citations": m.citations,
            "gate_passed": m.gate_passed,
            "created_at": m.created_at.isoformat(),
        }
        for m in rows
    ]


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(NoraConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    db.query(NoraMessage).filter_by(conversation_id=conversation_id).delete()
    db.delete(conversation)
    db.commit()
