"""Property context: operator-asserted metadata + the reusable deterministic
recommendation-gating utility that Content Intelligence and (Phase 11) Review
Intelligence both call.

Program-status integrity (hard rule): regulatory status, program status, and
property type are ALWAYS operator-provided. Nothing here infers them. A null
`is_regulated` means UNKNOWN and is never treated as "not regulated". When
status is unknown, compliance-sensitive guidance is withheld with a fixed
message. When the field is empty but a manual regulatory signal exists
(regulatory_programs set), we fail safe toward the more restrictive "regulated".

Gating is deterministic: identical (context, theme) always yields identical
output. Rules and vocabulary live in reference_data/property_context.json.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Property, PropertyProfile

_REFERENCE = (
    Path(__file__).resolve().parent.parent / "reference_data" / "property_context.json"
)

ALLOWED = "allowed"
SUPPRESSED = "suppressed"
CAUTION = "caution-only"

REGULATED = "regulated"
NOT_REGULATED = "not_regulated"
UNKNOWN = "unknown"


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(_REFERENCE.read_text())


@dataclass(frozen=True)
class GateResult:
    status: str  # ALLOWED | SUPPRESSED | CAUTION
    reason: str
    theme: str | None = None


class ContextValidationError(ValueError):
    """Invalid enum/program/flag against the JSON vocabulary."""


def validate_assignment(
    property_type: str | None,
    regulatory_programs: list[str] | None,
    restriction_flags: list[str] | None,
) -> None:
    c = config()
    if property_type is not None and property_type not in c["property_types"]:
        raise ContextValidationError(
            "Invalid property_type. Allowed: " + ", ".join(c["property_types"])
        )
    for p in regulatory_programs or []:
        if p not in c["regulatory_programs"]:
            raise ContextValidationError(
                "Invalid regulatory program '" + p + "'. Allowed: "
                + ", ".join(c["regulatory_programs"])
            )
    for f in restriction_flags or []:
        if f not in c["restriction_flags"]:
            raise ContextValidationError(
                "Invalid restriction flag '" + f + "'. Allowed: "
                + ", ".join(c["restriction_flags"])
            )


def effective_regulatory(
    is_regulated: bool | None, regulatory_programs: list[str] | None
) -> str:
    """Never inferred from derived signals. Only operator-set fields. Fail safe:
    an empty is_regulated with a manually set regulatory program is treated as
    regulated (more restrictive)."""
    if is_regulated is True:
        return REGULATED
    if is_regulated is False:
        return NOT_REGULATED
    # is_regulated is None (UNKNOWN)
    if regulatory_programs:
        return REGULATED  # fail safe toward the more restrictive guidance
    return UNKNOWN


def get_property_context(db: Session, property_id: int) -> dict:
    """Normalized context downstream modules read. Honest defaults when the
    property has no profile row (never a guessed value)."""
    prop = db.get(Property, property_id)
    profile = (
        db.query(PropertyProfile).filter_by(property_id=property_id).one_or_none()
    )
    programs = (profile.regulatory_programs if profile else None) or []
    flags = (profile.marketing_restriction_flags if profile else None) or []
    is_regulated = profile.is_regulated if profile else None
    return {
        "property_id": property_id,
        "property_name": prop.name if prop else None,
        # Client/site type from the Property (distinct from property_type below,
        # which is the regulatory/marketing type). Lets Nora frame answers.
        "site_type": (getattr(prop, "property_type", None) or "multifamily_apartment") if prop else None,
        "configured": profile is not None,
        "property_type": profile.property_type if profile else None,
        "target_audience": profile.target_audience if profile else None,
        "is_regulated": is_regulated,
        "regulatory_programs": programs,
        "marketing_restriction_flags": flags,
        "marketing_restriction_notes": (
            profile.marketing_restriction_notes if profile else None
        ),
        "effective_regulatory": effective_regulatory(is_regulated, programs),
    }


def gate(context: dict, theme: str) -> GateResult:
    """Deterministically gate a candidate marketing theme against context."""
    c = config()
    eff = context["effective_regulatory"]
    ptype = context.get("property_type")
    flags = context.get("marketing_restriction_flags") or []

    # 1. Explicit operator restriction flags suppress their mapped themes.
    for flag in flags:
        if theme in c["restriction_flag_themes"].get(flag, []):
            return GateResult(
                SUPPRESSED,
                f"Operator marketing restriction '{flag}' prohibits {theme} framing.",
                theme,
            )

    # 2. Configured gating rules (regulated / property-type based).
    for rule in c["gating_rules"]:
        when = rule["when"]
        if "is_regulated" in when and not (
            when["is_regulated"] is True and eff == REGULATED
        ):
            continue
        if "property_type" in when and ptype not in when["property_type"]:
            continue
        if theme in rule["themes"]:
            return GateResult(rule["status"], rule["reason"], theme)

    # 3. Unknown status: withhold compliance-sensitive themes.
    if theme in c["compliance_sensitive_themes"] and eff == UNKNOWN:
        return GateResult(SUPPRESSED, c["unknown_status_message"], theme)

    return GateResult(ALLOWED, "No restriction applies to this theme.", theme)


def gate_text(context: dict, text: str) -> GateResult:
    """Detect known themes in free text and return the most restrictive gate."""
    lowered = text.lower()
    detected = [
        t["key"]
        for t in config()["themes"]
        if any(p in lowered for p in t["phrases"])
    ]
    order = {SUPPRESSED: 3, CAUTION: 2, ALLOWED: 1}
    results = [gate(context, t) for t in detected]
    if not results:
        return GateResult(ALLOWED, "No gated theme detected in the text.")
    return max(results, key=lambda r: order[r.status])


def compliance_advisory(context: dict) -> dict:
    """One-line compliance posture derived only from operator-set status."""
    eff = context["effective_regulatory"]
    if eff == UNKNOWN:
        return {"level": "withheld", "message": config()["unknown_status_message"]}
    if eff == REGULATED:
        return {
            "level": "caution",
            "message": (
                "Regulated property: marketing copy must avoid exclusivity, "
                "demographic-targeting, and young-professional framing "
                "(fair-housing risk)."
            ),
        }
    return {
        "level": "clear",
        "message": "No regulatory restrictions specified for marketing copy.",
    }


def marketing_guidance(context: dict) -> list[dict]:
    """Gate the standard marketing themes; return the non-allowed ones so
    downstream modules can show which angles to avoid or use with caution."""
    guidance = []
    for theme in config()["themes"]:
        result = gate(context, theme["key"])
        if result.status != ALLOWED:
            guidance.append(
                {
                    "theme": theme["key"],
                    "label": theme["label"],
                    "status": result.status,
                    "reason": result.reason,
                }
            )
    return guidance


def _fmt(value, empty="unspecified") -> str:
    if value is None or value == [] or value == "":
        return empty
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)


def property_context_chunk_text(context: dict) -> str:
    """Verbatim context so Nora grounds answers in retrieved text, not
    inference. Regulatory status is stated explicitly, including 'unknown'."""
    eff = context["effective_regulatory"]
    status_line = {
        REGULATED: "regulated",
        NOT_REGULATED: "not regulated",
        UNKNOWN: "unknown (not specified by the operator)",
    }[eff]
    notes = context.get("marketing_restriction_notes")
    from app.services.property_types import label as site_type_label

    site = context.get("site_type") or "multifamily_apartment"
    return "\n".join(
        [
            f"Property context for {context['property_name']} (operator-provided).",
            f"Client/site type: {site_type_label(site)}.",
            f"Property type: {_fmt(context['property_type'])}.",
            f"Target audience: {_fmt(context['target_audience'])}.",
            f"Regulatory status: {status_line}.",
            f"Regulatory programs: {_fmt(context['regulatory_programs'], 'none specified')}.",
            f"Marketing restrictions: {_fmt(context['marketing_restriction_flags'], 'none specified')}"
            + (f"; notes: {notes}" if notes else "")
            + ".",
            "Note: Program and regulatory status is operator-asserted and never inferred by Beacon.",
        ]
    )
