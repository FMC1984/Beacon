"""Connector interfaces and the normalized records they return.

Records are provider-neutral: a HubSpot lead and a Yardi lead both become a
LeadRecord. Consumers (chunker, sync service, future intelligence modules)
depend only on these shapes.

Each provider method takes an open Session because the current implementation
reads local data; API-backed implementations may ignore it. Optional date
bounds narrow the window; None means all available.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class TrafficRecord:
    property_id: int
    date: date
    source: str
    medium: str
    sessions: int
    is_ai_referral: bool
    ai_platform: str | None


@dataclass(frozen=True)
class LeadRecord:
    property_id: int
    external_id: str
    source: str
    status: str
    first_contact_date: date


@dataclass(frozen=True)
class LeaseRecord:
    property_id: int
    external_id: str
    lease_signed_date: date
    move_in_date: date | None


@dataclass(frozen=True)
class ReviewRecord:
    property_id: int
    # rating is nullable (reviews may omit a star rating) and published_at may be
    # absent. The extra fields below were added additively in Phase 11; the
    # original four positional fields are unchanged for back-compat.
    rating: float | None
    text: str
    published_at: datetime | None
    review_id: int | None = None
    external_review_id: str | None = None
    provider: str | None = None
    title: str | None = None
    author_name: str | None = None
    response_text: str | None = None
    source_url: str | None = None


@dataclass(frozen=True)
class AIVisibilityRecord:
    """One stored external-AI query and its verbatim response. The response is
    the evidentiary record; brand_mentioned / sources_cited are deterministically
    parsed from it (Phase 11.5)."""

    property_id: int
    query_id: int
    platform: str
    prompt_text: str
    raw_response_text: str
    executed_at: datetime
    brand_mentioned: bool
    sources_cited: list[str]


@dataclass(frozen=True)
class ContentRecord:
    property_id: int
    page: str  # e.g. "homepage", "faq", "amenities", "neighborhood"
    title: str
    body: str
    updated_at: datetime | None
    mapped_keyword: str | None = None
    source_url: str | None = None


class TrafficProvider(ABC):
    @abstractmethod
    def get_traffic(
        self,
        db: Session,
        property_id: int,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TrafficRecord]: ...


class LeadProvider(ABC):
    @abstractmethod
    def get_leads(self, db: Session, property_id: int) -> list[LeadRecord]: ...


class LeaseProvider(ABC):
    @abstractmethod
    def get_leases(self, db: Session, property_id: int) -> list[LeaseRecord]: ...


class ReviewProvider(ABC):
    @abstractmethod
    def get_reviews(self, db: Session, property_id: int) -> list[ReviewRecord]: ...


class ContentProvider(ABC):
    @abstractmethod
    def get_content(self, db: Session, property_id: int) -> list[ContentRecord]: ...


class AIVisibilityQueryProvider(ABC):
    """Seam for querying external AI platforms and reading stored results.

    `execute_query` is the ONLY non-deterministic operation in the whole system:
    it calls out to an external AI platform and returns whatever text comes
    back. Everything downstream of the stored response (mention detection,
    source extraction, scoring) is deterministic. `get_queries` is a pure,
    deterministic read of previously stored rows, property-scoped. Designed for
    multiple platform connectors from the start even though one is implemented
    now; existing behavior stays stable when a property has no queries."""

    @abstractmethod
    def execute_query(self, prompt: str, platform: str) -> str: ...

    @abstractmethod
    def get_queries(
        self, db: Session, property_id: int
    ) -> list["AIVisibilityRecord"]: ...
