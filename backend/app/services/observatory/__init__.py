"""AI Visibility Observatory (Phase 19).

The platform layer over Beacon's AI Visibility foundation: a structured
provider result seam, a run ledger with cost, provider-reported citations
and retrieval queries, and (in later phases) shared market observations,
prompt clustering, rollups, competitor discovery, claims and scheduling.

Data-integrity vocabulary used on every surface this package feeds:
OBSERVED (the provider reported it), MEASURED (calculated from observed
rows), MODELED (estimated; formula and inputs shown), UNAVAILABLE (the
platform does not expose it; never synthesized).
"""

LABEL_OBSERVED = "OBSERVED"
LABEL_MEASURED = "MEASURED"
LABEL_MODELED = "MODELED"
LABEL_UNAVAILABLE = "UNAVAILABLE"


def utc_today():
    """Calendar date in UTC. Observatory timestamps are naive UTC, so every
    window default must be a UTC date too; the machine's local date drifts by
    a day around midnight UTC."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).date()
