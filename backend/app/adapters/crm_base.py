"""Transport-agnostic CRM adapter interface (build plan Phase 5).

An adapter maps raw CRM records into NormalizedLead values. Records arrive as
{canonical_field: raw_string} dicts; today they come from manual CSV exports,
and a future CRM API feed (see CLAUDE.md, placeholder only) would produce the
same dicts, so adapters never know or care about the transport.

Value-level knowledge (status vocabularies, date formats, source taxonomies)
lives in the adapter. Header-level mapping is declared as column_aliases and
applied by the shared CRM ingester.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

from app.models import LeadStatus


@dataclass(frozen=True)
class NormalizedLead:
    external_lead_id: str
    lead_source_raw: str
    status: LeadStatus
    first_contact_date: date
    lead_source_normalized: str | None = None
    tour_date: date | None = None
    application_date: date | None = None
    lease_signed_date: date | None = None
    move_in_date: date | None = None


@dataclass(frozen=True)
class SkippedRecord:
    reason: str


class CRMAdapter(ABC):
    key: str
    label: str
    # True while the adapter's field mapping has not been verified against real
    # export samples. Surfaced as an upload warning and in error messages.
    is_placeholder: bool = False

    REQUIRED_FIELDS = (
        "external_lead_id",
        "lead_source_raw",
        "status",
        "first_contact_date",
    )

    @property
    @abstractmethod
    def column_aliases(self) -> dict[str, str]:
        """Normalized source header -> canonical field name (see REQUIRED_FIELDS
        plus optional tour_date, application_date, lease_signed_date,
        move_in_date, lead_source_normalized)."""

    @abstractmethod
    def normalize(self, record: dict[str, str]) -> NormalizedLead | SkippedRecord:
        """Map one canonical-keyed raw record to a NormalizedLead, or explain
        why it cannot be (SkippedRecord); never guess at ambiguous values."""

    def missing_columns(self, colmap: dict[str, list[str]]) -> list[str]:
        return [f for f in self.REQUIRED_FIELDS if f not in colmap]
