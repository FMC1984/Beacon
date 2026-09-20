from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Principal, assert_property_access, current_principal, require_role
from app.db import get_db
from app.models import NoraConversation, NoraMessage
from app.services import nora
from app.services.nora_llm import get_llm
from app.services.observatory.tenancy import org_property_ids, property_org_id
from app.services.rag.embedder import MissingAPIKeyError, get_embedder

router = APIRouter(prefix="/nora", tags=["nora"])


class AskRequest(BaseModel):
    question: str
    property_id: int | None = None
    conversation_id: int | None = None


def _allowed_ids(db: Session, principal: Principal) -> list[int] | None:
    """None = every property (platform admin across organizations)."""
    if principal.org_id is not None:
        return org_property_ids(db, principal.org_id)
    return None if principal.is_platform_admin else []


def _own_conversation(db: Session, principal: Principal, conversation_id: int) -> NoraConversation:
    conversation = db.get(NoraConversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if principal.org_id is not None:
        owner = conversation.organization_id
        if owner is None and conversation.property_id is not None:
            owner = property_org_id(db, conversation.property_id)
        if owner != principal.org_id:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    elif not principal.is_platform_admin:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conversation


@router.post("/ask", dependencies=[Depends(require_role("viewer"))])
def ask(payload: AskRequest, db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    if not payload.question.strip():
        raise HTTPException(status_code=422, detail="Question is empty.")
    if payload.property_id is not None:
        assert_property_access(db, principal, payload.property_id)
    if payload.conversation_id is not None:
        _own_conversation(db, principal, payload.conversation_id)
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
            property_ids=_allowed_ids(db, principal),
            organization_id=principal.org_id,
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


@router.get("/conversations", dependencies=[Depends(require_role("viewer"))])
def conversations(
    property_id: int | None = None,
    scope: str | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    """List saved conversations. Pass property_id to get just that property's
    chats; pass scope=portfolio to get only the portfolio-wide (unscoped)
    ones. With neither, returns everything the organization can see, newest first."""
    query = db.query(NoraConversation)
    if property_id is not None:
        assert_property_access(db, principal, property_id)
        query = query.filter(NoraConversation.property_id == property_id)
    elif scope == "portfolio":
        query = query.filter(NoraConversation.property_id.is_(None))
    if principal.org_id is not None:
        allowed = org_property_ids(db, principal.org_id)
        query = query.filter(
            (NoraConversation.organization_id == principal.org_id)
            | ((NoraConversation.organization_id.is_(None)) & NoraConversation.property_id.in_(allowed or [-1]))
        )
    elif not principal.is_platform_admin:
        query = query.filter(NoraConversation.id < 0)
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


@router.get("/conversations/{conversation_id}", dependencies=[Depends(require_role("viewer"))])
def conversation_messages(conversation_id: int, db: Session = Depends(get_db),
                          principal: Principal = Depends(current_principal)):
    _own_conversation(db, principal, conversation_id)
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


@router.delete("/conversations/{conversation_id}", status_code=204, dependencies=[Depends(require_role("admin"))])
def delete_conversation(conversation_id: int, db: Session = Depends(get_db),
                        principal: Principal = Depends(current_principal)):
    conversation = _own_conversation(db, principal, conversation_id)
    db.query(NoraMessage).filter_by(conversation_id=conversation_id).delete()
    db.delete(conversation)
    db.commit()
