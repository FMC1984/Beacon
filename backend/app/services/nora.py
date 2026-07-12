"""Nora: retrieval-grounded analyst. Response assembly enforces the hard rules
in code, never by prompt alone:

  rule 5: the correlation gate runs BEFORE generation. Correlation questions
          with a failed gate get the fixed template and the model is never
          called; when the gate fails, generation prompts for other questions
          forbid the topic and include no correlation statistics.
  rule 6: citations come from the rag_chunks registry via the retriever and
          are attached in code; the model cannot invent or drop them.
  rule 3: any answer grounded in GA4 AI-traffic chunks carries the undercount
          disclosure in the API response.
  rule 7: em dashes are stripped from generated text in code.
"""

import re
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import MessageRole, NoraConversation, NoraMessage
from app.services.correlation import (
    can_claim_correlation,
    compute_correlation_inputs,
    unmet_requirements,
)
from app.services.nora_llm import NoraLLM
from app.services.rag.embedder import Embedder
from app.services.rag.retriever import retrieve

_CORRELATION_TOPIC = re.compile(
    r"correlat|caus|convert|conversion|lease|leases|lead|leads|outcome|roi|"
    r"drive|driving|impact|result",
    re.IGNORECASE,
)
_AI_TOPIC = re.compile(
    r"\bai\b|chatgpt|perplexity|copilot|gemini|claude|grok|assistant|llm",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You are Nora, the analyst inside Beacon, an AI performance
intelligence dashboard for multifamily marketing. Rules, all mandatory:
- Answer ONLY from the numbered data excerpts provided. If they do not contain
  the answer, say plainly that the data ingested so far does not cover it.
- Reference excerpts inline as [1], [2] and so on when you use their numbers.
- Report numbers exactly as they appear in the excerpts. Never invent,
  extrapolate, or estimate figures.
- No recommendations that are not directly supported by the excerpts.
- Do not use em dashes. Use commas or periods instead.
- Be concise and direct. Plain prose, no headers unless asked."""

GATE_FAILED_PROMPT = """
- You must NOT claim or imply any relationship, correlation, or causation
  between AI traffic and leads, leases, or outcomes. If asked, state that
  there is not enough data yet to make that claim."""

GATE_PASSED_PROMPT = """
- A code-verified correlation exists between monthly AI referral sessions and
  monthly leases: r = {r} across {periods} periods ({ai_sessions} AI sessions,
  {leases} leases). You may describe this as correlation. Never present it as
  causation."""


def sanitize(text: str) -> str:
    """Code enforcement of hard rule 7: no em dashes in generated copy."""
    text = re.sub(r"\s*—\s*", ", ", text)
    return text.replace("—", ", ")


def is_correlation_question(question: str) -> bool:
    return bool(
        _CORRELATION_TOPIC.search(question) and _AI_TOPIC.search(question)
    )


def insufficient_data_template(unmet: list[str]) -> str:
    lines = "\n".join(f"- {item}" for item in unmet)
    return (
        "There is not enough data yet to make any claim about how AI traffic "
        "relates to leads or leases. Before that claim can be made, Beacon "
        "needs:\n"
        f"{lines}\n"
        "Keep uploading GA4 and CRM exports and ask again once more periods "
        "of data are in."
    )


NO_DATA_ANSWER = (
    "I do not have any ingested data that covers this question yet. Upload "
    "GA4, Search Console, Business Profile, paid media, or CRM exports on the "
    "Uploads page and ask me again."
)


def ask(
    db: Session,
    question: str,
    llm: NoraLLM,
    embedder: Embedder,
    property_id: int | None = None,
    conversation_id: int | None = None,
    chroma_dir: str | None = None,
) -> dict:
    conversation = (
        db.get(NoraConversation, conversation_id) if conversation_id else None
    )
    if conversation is None:
        conversation = NoraConversation(
            title=question[:200], property_id=property_id
        )
        db.add(conversation)
        db.flush()

    db.add(
        NoraMessage(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content=question,
        )
    )

    # Hard gate first: computed in code before any generation happens.
    inputs = compute_correlation_inputs(db, property_id)
    gate_passed = can_claim_correlation(
        inputs.ai_sessions, inputs.leases, inputs.r, inputs.periods_confirmed
    )
    unmet = [] if gate_passed else unmet_requirements(inputs)

    chunks = retrieve(
        db, embedder, question, property_id=property_id, chroma_dir=chroma_dir
    )
    citations = [asdict(c.citation) for c in chunks]
    ga4_grounded = any(
        c.citation.source_table == "ga4_sessions_daily" for c in chunks
    )

    correlation_q = is_correlation_question(question)
    if correlation_q and not gate_passed:
        # Fixed template; the model is never called on this path.
        answer = insufficient_data_template(unmet)
    elif not chunks:
        answer = NO_DATA_ANSWER
    else:
        system = SYSTEM_PROMPT + (
            GATE_PASSED_PROMPT.format(
                r=inputs.r,
                periods=inputs.periods_confirmed,
                ai_sessions=inputs.ai_sessions,
                leases=inputs.leases,
            )
            if gate_passed
            else GATE_FAILED_PROMPT
        )
        excerpts = "\n\n".join(
            f"[{i}] ({c.citation.source_table}, "
            f"{c.citation.property_name or 'portfolio'}, "
            f"{c.citation.date_range})\n{c.text}"
            for i, c in enumerate(chunks, start=1)
        )
        user = f"Data excerpts:\n\n{excerpts}\n\nQuestion: {question}"
        answer = sanitize(llm.generate(system, user))

    disclosure = (
        AI_TRAFFIC_DISCLOSURE if (ga4_grounded or correlation_q) else None
    )

    db.add(
        NoraMessage(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=answer,
            citations=citations,
            gate_passed=gate_passed,
        )
    )
    db.commit()

    from app.config import settings

    return {
        "conversation_id": conversation.id,
        "answer": answer,
        "citations": citations,
        "disclosure": disclosure,
        "mode": "demo" if settings.demo_mode else "live",
        "gate": {
            "passed": gate_passed,
            "ai_sessions": inputs.ai_sessions,
            "leases": inputs.leases,
            "r": inputs.r,
            "periods_confirmed": inputs.periods_confirmed,
            "unmet": unmet,
        },
    }
