"""Correlation engine and the hard gate (CLAUDE.md hard rule 5).

The gate is code, not a prompt instruction. Nora calls it before producing any
AI-traffic-to-lease language; when it returns False the fixed insufficient-data
template is used and the model never sees correlation statistics at all.

Inputs are computed at a monthly grain over all ingested data in scope:
  - ai_sessions: total AI referral sessions (GA4, Tier 1 stamped)
  - leases: leads with a signed lease date
  - r: Pearson correlation between monthly AI sessions and monthly leases,
    over months where both GA4 and CRM data exist; 0.0 when undefined
  - periods_confirmed: number of months with BOTH GA4 data and CRM data
    present (a zero in a covered month is confirmed data; a missing month is
    not evidence)
"""

from dataclasses import dataclass, field
from statistics import StatisticsError, correlation

from sqlalchemy.orm import Session

from app.models import CRMLead, GA4SessionsDaily

MIN_AI_SESSIONS = 30
MIN_LEASES = 5
MIN_ABS_R = 0.5
MIN_PERIODS = 2


def can_claim_correlation(ai_sessions, leases, r, periods_confirmed) -> bool:
    return ai_sessions >= 30 and leases >= 5 and abs(r) >= 0.5 and periods_confirmed >= 2


@dataclass
class CorrelationInputs:
    ai_sessions: int
    leases: int
    r: float
    periods_confirmed: int
    monthly: list[dict] = field(default_factory=list)


def _month(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def compute_correlation_inputs(
    db: Session, property_id: int | None = None
) -> CorrelationInputs:
    ga4_q = db.query(GA4SessionsDaily)
    crm_q = db.query(CRMLead)
    if property_id is not None:
        ga4_q = ga4_q.filter(GA4SessionsDaily.property_id == property_id)
        crm_q = crm_q.filter(CRMLead.property_id == property_id)

    ga4_months: dict[str, int] = {}
    for row in ga4_q.all():
        month = _month(row.date)
        ga4_months.setdefault(month, 0)
        if row.is_ai_referral:
            ga4_months[month] += row.sessions

    crm_months: dict[str, int] = {}
    total_leases = 0
    for lead in crm_q.all():
        crm_months.setdefault(_month(lead.first_contact_date), 0)
        if lead.lease_signed_date is not None:
            month = _month(lead.lease_signed_date)
            crm_months.setdefault(month, 0)
            crm_months[month] += 1
            total_leases += 1

    confirmed = sorted(set(ga4_months) & set(crm_months))
    ai_series = [ga4_months[m] for m in confirmed]
    lease_series = [crm_months[m] for m in confirmed]

    r = 0.0
    if len(confirmed) >= 2:
        try:
            r = correlation(ai_series, lease_series)
        except StatisticsError:
            r = 0.0  # zero variance in one series; correlation undefined

    return CorrelationInputs(
        ai_sessions=sum(ga4_months.values()),
        leases=total_leases,
        r=round(r, 4),
        periods_confirmed=len(confirmed),
        monthly=[
            {"month": m, "ai_sessions": a, "leases": l}
            for m, a, l in zip(confirmed, ai_series, lease_series)
        ],
    )


def unmet_requirements(ci: CorrelationInputs) -> list[str]:
    """Human-readable list of gate thresholds not yet met. No em dashes."""
    unmet = []
    if ci.ai_sessions < MIN_AI_SESSIONS:
        unmet.append(
            f"at least {MIN_AI_SESSIONS} AI referral sessions "
            f"(currently {ci.ai_sessions})"
        )
    if ci.leases < MIN_LEASES:
        unmet.append(f"at least {MIN_LEASES} signed leases (currently {ci.leases})")
    if abs(ci.r) < MIN_ABS_R:
        unmet.append(
            f"a correlation of at least {MIN_ABS_R} in absolute value "
            f"(currently {ci.r})"
        )
    if ci.periods_confirmed < MIN_PERIODS:
        unmet.append(
            f"at least {MIN_PERIODS} periods with both traffic and CRM data "
            f"(currently {ci.periods_confirmed})"
        )
    return unmet
