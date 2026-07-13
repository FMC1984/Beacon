"""'If I Were Your Marketing Strategist' (Phase 17D).

The briefing's one sanctioned LLM step, held to Nora's discipline:

- The model sees ONLY deterministic, numbered facts composed from the briefing
  (module health, story items, corroborated actions, top priorities, strategic
  questions). It is never asked to know anything on its own.
- Every recommendation must cite the numbered facts it rests on. Grounding is
  enforced IN CODE after generation: a recommendation citing no valid fact is
  dropped, and the citations shown are assembled from the fact list, never
  trusted from model output.
- Below a minimum of grounded signal, a fixed insufficient-data template is
  returned and the LLM is never called (the same philosophy as Nora's
  hard-coded correlation gate).
- Demo mode is deterministic: recommendations are templated from the
  Opportunity Engine's top actions, no model call.
- Generation is MANUAL (a button, like AI Visibility runs) because it spends
  OpenAI budget.
"""

import json
import re

from app.providers.base import MissingAPIKeyError
from app.providers.registry import get_llm_provider

from app.config import settings

MAX_RECOMMENDATIONS = 5
# Fewer grounded facts than this and advice would be vibes, not synthesis.
MIN_FACTS_FOR_SYNTHESIS = 3

MODEL_DISCLOSURE = (
    "Drafted by Beacon's assistant from the numbered facts shown; every "
    "recommendation cites the facts it rests on. Beacon drops any "
    "recommendation that does not cite them."
)

INSUFFICIENT_TEMPLATE = (
    "Beacon does not have enough grounded signal this month to act as your "
    "strategist honestly. Connect more data sources or wait for another month "
    "of history, then generate again."
)


def _facts(briefing: dict) -> list[dict]:
    """Flatten the briefing into numbered, citable facts. Deterministic order."""
    facts: list[dict] = []

    def add(kind, text, href):
        facts.append({"n": len(facts) + 1, "kind": kind, "text": text, "href": href})

    for m in briefing["health"]["modules"]:
        if m["status"] not in ("not_connected", "not_enough_data"):
            add("health", f"{m['label']}: {m['status_label']}. {m['reason']}", m["details_href"])
    for group in ("wins", "risks", "trends"):
        for i in briefing.get("story", {}).get(group, []):
            add(group, i["text"], i["link"]["href"])
    for ins in briefing.get("cross_system", {}).get("insights", []):
        for o in ins["observations"]:
            add("cross_system", o["text"], o["link"]["href"])
    for a in briefing.get("top_priorities", []):
        why = f" {a['explanation']}" if a.get("explanation") else ""
        add("priority", f"Recommended action: {a['title']}.{why}", "/opportunities")
    for q in briefing.get("strategic_questions", []):
        add("question", q["text"], q["link"]["href"])

    # Dedup on text; keep first occurrence (stable numbering).
    seen, out = set(), []
    for f in facts:
        if f["text"] not in seen:
            seen.add(f["text"])
            out.append(f)
    for i, f in enumerate(out, 1):
        f["n"] = i
    return out


def _system_prompt() -> str:
    return (
        "You are an experienced multifamily marketing strategist. You are "
        "given numbered FACTS from a property's monthly data. Answer: if you "
        "only had four hours to improve this property this month, what would "
        "you do? Respond with STRICT JSON only: a list of at most "
        f"{MAX_RECOMMENDATIONS} objects, each with keys: title (imperative, "
        "under 15 words), why (1-2 sentences), impact (High/Medium/Low), "
        "effort (High/Medium/Low), facts (list of fact numbers you used). "
        "Rules: use ONLY the facts given; never invent numbers or claims; if "
        "the facts are thin, return fewer recommendations; no causal claims "
        "about past performance, only forward-looking actions."
    )


def _user_prompt(briefing: dict, facts: list[dict]) -> str:
    lines = [
        f"Property: {briefing['property_name']}",
        f"Month: {briefing['period']['label']} (vs {briefing['comparison_period']['label']})",
        "FACTS:",
    ]
    lines += [f"{f['n']}. [{f['kind']}] {f['text']}" for f in facts]
    lines.append("Return the JSON list now.")
    return "\n".join(lines)


def _parse_and_ground(raw: str, facts: list[dict]) -> list[dict]:
    """Parse the model's JSON and enforce grounding in code. Anything that
    fails to parse, exceeds the cap, or cites no valid fact is dropped."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    by_n = {f["n"]: f for f in facts}
    out = []
    for item in items[:MAX_RECOMMENDATIONS]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        cited = [by_n[n] for n in item.get("facts", []) if isinstance(n, int) and n in by_n]
        if not cited:
            continue  # ungrounded advice is dropped, not shown
        out.append({
            "title": str(item["title"])[:200],
            "why": str(item.get("why", ""))[:500],
            "impact": item.get("impact") if item.get("impact") in ("High", "Medium", "Low") else None,
            "effort": item.get("effort") if item.get("effort") in ("High", "Medium", "Low") else None,
            # Citations assembled from OUR fact list, never trusted from output.
            "grounding": [
                {"n": f["n"], "text": f["text"], "href": f["href"]} for f in cited
            ],
        })
    return out


def _demo_recommendations(briefing: dict, facts: list[dict]) -> list[dict]:
    """Deterministic, keyless: template the top priorities as the strategist's
    picks, grounded in their own priority facts."""
    priority_facts = [f for f in facts if f["kind"] == "priority"]
    out = []
    for a, f in zip(briefing.get("top_priorities", []), priority_facts):
        out.append({
            "title": a["title"],
            "why": a.get("explanation") or "Top-ranked by the Opportunity Engine.",
            "impact": a.get("impact"),
            "effort": a.get("effort"),
            "grounding": [{"n": f["n"], "text": f["text"], "href": f["href"]}],
        })
    return out[:MAX_RECOMMENDATIONS]


def build_strategist(briefing: dict, llm=None) -> dict:
    facts = _facts(briefing)
    base = {
        "property_id": briefing["property_id"],
        "period": briefing["period"],
        "facts": facts,
        "disclosure": MODEL_DISCLOSURE,
    }

    if len(facts) < MIN_FACTS_FOR_SYNTHESIS:
        # The gate: no LLM call below the minimum grounded signal.
        return {
            **base,
            "state": "insufficient_data",
            "message": INSUFFICIENT_TEMPLATE,
            "recommendations": [],
        }

    if settings.demo_mode and llm is None:
        return {
            **base,
            "state": "ok",
            "provider": "demo (deterministic)",
            "recommendations": _demo_recommendations(briefing, facts),
        }

    try:
        provider = llm or get_llm_provider()
    except MissingAPIKeyError as exc:
        return {
            **base,
            "state": "unavailable",
            "message": str(exc),
            "recommendations": [],
        }

    raw = provider.generate(_system_prompt(), _user_prompt(briefing, facts))
    recs = _parse_and_ground(raw, facts)
    return {
        **base,
        "state": "ok" if recs else "no_grounded_output",
        "provider": provider.name,
        "message": (
            None if recs else
            "The model returned no recommendation that cited the facts, so "
            "nothing is shown. Try again."
        ),
        "recommendations": recs,
    }
