import enum
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.uploads import str_enum


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class NoraConversation(Base):
    __tablename__ = "nora_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str | None] = mapped_column(String(300))
    # Scope: null means portfolio-wide conversation.
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class NoraMessage(Base):
    __tablename__ = "nora_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("nora_conversations.id")
    )
    role: Mapped[MessageRole] = mapped_column(str_enum(MessageRole, "message_role"))
    content: Mapped[str] = mapped_column(Text)
    # List of {property, date_range, source_table, source_ref}; assembled from
    # rag_chunks provenance, never from model output.
    citations: Mapped[dict | None] = mapped_column(JSON)
    # Set on assistant messages whose answer touched correlation claims.
    gate_passed: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
