"""The reusable deterministic recommendation-gating utility and program-status
integrity rule."""

from app.services.property_context import (
    ALLOWED,
    CAUTION,
    SUPPRESSED,
    compliance_advisory,
    config,
    effective_regulatory,
    gate,
    gate_text,
)


def ctx(**kw):
    base = {
        "property_id": 1,
        "property_name": "Test",
        "configured": True,
        "property_type": None,
        "target_audience": None,
        "is_regulated": None,
        "regulatory_programs": [],
        "marketing_restriction_flags": [],
        "marketing_restriction_notes": None,
    }
    base.update(kw)
    base["effective_regulatory"] = effective_regulatory(
        base["is_regulated"], base["regulatory_programs"]
    )
    return base


def test_regulated_suppresses_restricted_themes_with_reason():
    c = ctx(is_regulated=True, property_type="affordable")
    for theme in ("exclusivity", "young_professional", "demographic_targeting"):
        result = gate(c, theme)
        assert result.status == SUPPRESSED
        assert "fair-housing" in result.reason.lower()


def test_senior_suppresses_young_and_nightlife():
    c = ctx(property_type="senior", is_regulated=False)
    assert gate(c, "nightlife").status == SUPPRESSED
    assert gate(c, "young_professional").status == SUPPRESSED


def test_active_adult_suppresses_nightlife():
    c = ctx(property_type="active_adult", is_regulated=False)
    assert gate(c, "nightlife").status == SUPPRESSED


def test_student_quiet_community_is_caution_only():
    c = ctx(property_type="student", is_regulated=False)
    r = gate(c, "quiet_community")
    assert r.status == CAUTION
    assert "student" in r.reason.lower()


def test_unknown_status_withholds_compliance_sensitive():
    c = ctx()  # is_regulated None, no programs -> unknown
    assert c["effective_regulatory"] == "unknown"
    r = gate(c, "exclusivity")
    assert r.status == SUPPRESSED
    assert r.reason == config()["unknown_status_message"]


def test_unknown_status_allows_non_compliance_theme():
    # quiet_community is not compliance-sensitive; unknown status does not block it.
    c = ctx()
    assert gate(c, "quiet_community").status == ALLOWED


def test_fail_safe_programs_imply_regulated():
    # is_regulated unset but a program is manually flagged -> more restrictive.
    c = ctx(regulatory_programs=["LIHTC"])
    assert c["effective_regulatory"] == "regulated"
    assert gate(c, "exclusivity").status == SUPPRESSED


def test_not_regulated_conventional_allows_exclusivity():
    c = ctx(property_type="conventional", is_regulated=False)
    assert gate(c, "exclusivity").status == ALLOWED


def test_restriction_flag_suppresses_mapped_theme():
    c = ctx(property_type="conventional", is_regulated=False,
            marketing_restriction_flags=["no_nightlife_framing"])
    r = gate(c, "nightlife")
    assert r.status == SUPPRESSED
    assert "no_nightlife_framing" in r.reason


def test_gate_is_deterministic():
    c = ctx(is_regulated=True, property_type="affordable")
    assert gate(c, "exclusivity") == gate(c, "exclusivity")
    # Run many times; always identical.
    results = {gate(c, "young_professional").status for _ in range(50)}
    assert results == {SUPPRESSED}


def test_gate_text_returns_most_restrictive():
    c = ctx(is_regulated=True, property_type="affordable")
    r = gate_text(c, "Enjoy exclusive, upscale living for young professionals.")
    assert r.status == SUPPRESSED


def test_never_regulated_is_not_unknown_default():
    # Explicit False must stay not_regulated, never coerced to unknown/regulated.
    assert effective_regulatory(False, []) == "not_regulated"
    assert effective_regulatory(None, []) == "unknown"
    assert effective_regulatory(True, []) == "regulated"


def test_compliance_advisory_states():
    assert compliance_advisory(ctx())["level"] == "withheld"
    assert compliance_advisory(ctx(is_regulated=True))["level"] == "caution"
    assert compliance_advisory(ctx(is_regulated=False))["level"] == "clear"
    assert (
        compliance_advisory(ctx())["message"] == config()["unknown_status_message"]
    )
