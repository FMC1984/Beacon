"""Deterministic, context-aware hallucination-check HOOK (Phase 11.5).

This is the detection MECHANISM only - a flag with a reason. Interpretation and
recommendations are Phase 12's job. It compares specific factual claims in a
stored AI response against data Beacon already holds with confidence:

  - property name and city (presence checks: is the known value stated),
  - state (contradiction check via a controlled vocabulary of US states),
  - property type (contradiction check via the property_type synonyms in
    ai_visibility.json, only when Property Context supplies the type).

Hard rules honored:
  - If the relevant fact is not populated (no Property Context, no city, etc.),
    the check returns "cannot_verify" - never a silent skip, never an assumption.
  - Beacon never INFERS a property fact to enable a check; it only compares
    against values it already stores.
  - Fully deterministic: identical (response, property, context) always yields
    identical checks. State contradiction uses full state NAMES only (not
    2-letter abbreviations, which collide with common English words like IN/OR).
"""

from app.services.ai_visibility.parsing import _phrase_present
from app.services.ai_visibility.reference import config

CONSISTENT = "consistent"
CONTRADICTED = "contradicted"
NOT_MENTIONED = "not_mentioned"
CANNOT_VERIFY = "cannot_verify"

# Full state names -> USPS abbreviation. Names only are used for contradiction
# detection to avoid abbreviation/English-word collisions.
_STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_ABBR_TO_NAME = {v: k for k, v in _STATES.items()}


def _check_name(text: str, name: str | None) -> dict:
    if not name:
        return {"field": "name", "known_value": None, "status": CANNOT_VERIFY,
                "evidence": "Beacon has no property name on file."}
    present = _phrase_present(text, name)
    return {
        "field": "name",
        "known_value": name,
        "status": CONSISTENT if present else NOT_MENTIONED,
        "evidence": ("Property name appears in the response."
                     if present else "Property name not found in the response."),
    }


def _check_city(text: str, city: str | None) -> dict:
    if not city:
        return {"field": "city", "known_value": None, "status": CANNOT_VERIFY,
                "evidence": "No city on file for this property."}
    present = _phrase_present(text, city)
    return {
        "field": "city",
        "known_value": city,
        "status": CONSISTENT if present else NOT_MENTIONED,
        "evidence": ("City appears in the response."
                     if present else "City not found in the response."),
    }


def _check_state(text: str, state: str | None) -> dict:
    if not state:
        return {"field": "state", "known_value": None, "status": CANNOT_VERIFY,
                "evidence": "No state on file for this property."}
    known_abbr = state.strip().upper()
    known_name = _ABBR_TO_NAME.get(known_abbr)
    if known_name is None:
        return {"field": "state", "known_value": state, "status": CANNOT_VERIFY,
                "evidence": f"'{state}' is not a recognized US state code."}
    if _phrase_present(text, known_name):
        return {"field": "state", "known_value": known_abbr, "status": CONSISTENT,
                "evidence": f"Response states the property is in {known_name.title()}."}
    others = sorted(
        name.title() for name in _STATES if name != known_name and _phrase_present(text, name)
    )
    if others:
        return {
            "field": "state", "known_value": known_abbr, "status": CONTRADICTED,
            "evidence": (f"Response mentions {', '.join(others)} but not the "
                         f"property's state ({known_name.title()})."),
        }
    return {"field": "state", "known_value": known_abbr, "status": NOT_MENTIONED,
            "evidence": "No state mentioned in the response."}


def _check_property_type(text: str, ptype: str | None) -> dict:
    if not ptype:
        return {
            "field": "property_type", "known_value": None, "status": CANNOT_VERIFY,
            "evidence": ("Property Context does not specify a property type, so "
                         "type claims cannot be verified."),
        }
    synonyms = config().get("property_type_synonyms", {})
    own = synonyms.get(ptype, [ptype]) + [ptype]
    if any(_phrase_present(text, term) for term in own):
        return {"field": "property_type", "known_value": ptype, "status": CONSISTENT,
                "evidence": f"Response describes the property consistent with '{ptype}'."}
    for other_type, terms in synonyms.items():
        if other_type == ptype:
            continue
        hit = next((t for t in terms + [other_type] if _phrase_present(text, t)), None)
        if hit:
            return {
                "field": "property_type", "known_value": ptype, "status": CONTRADICTED,
                "evidence": (f"Response describes the property as '{hit}' "
                             f"({other_type}), which contradicts the operator-set "
                             f"type '{ptype}'."),
            }
    return {"field": "property_type", "known_value": ptype, "status": NOT_MENTIONED,
            "evidence": "Response makes no verifiable property-type claim."}


def check_response_against_context(response_text: str, prop, context: dict) -> dict:
    """Return {checks, flags, context_configured}. `flags` are the contradicted
    checks. A missing fact yields 'cannot_verify', never a silent skip."""
    ptype = context.get("property_type") if context else None
    checks = [
        _check_name(response_text, getattr(prop, "name", None)),
        _check_city(response_text, getattr(prop, "city", None)),
        _check_state(response_text, getattr(prop, "state", None)),
        _check_property_type(response_text, ptype),
    ]
    return {
        "checks": checks,
        "flags": [c for c in checks if c["status"] == CONTRADICTED],
        "context_configured": bool(context and context.get("configured")),
    }
