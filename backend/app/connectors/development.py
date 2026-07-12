"""DevelopmentDataProvider: the current connector, reading the local SQLite data
ingested through manual CSV uploads. Implements every connector interface so it
is the single source future modules read from today.

Reviews and content have no ingestion path yet, so those return empty lists.
They are real extension points: when review or content ingestion is added, only
this class (or a new provider) changes, not the consumers.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.connectors.base import (
    ContentProvider,
    ContentRecord,
    LeadProvider,
    LeadRecord,
    LeaseProvider,
    LeaseRecord,
    ReviewProvider,
    ReviewRecord,
    TrafficProvider,
    TrafficRecord,
)
from app.models import CRMLead, GA4SessionsDaily, PropertyContent, PropertyReview


class DevelopmentDataProvider(
    TrafficProvider, LeadProvider, LeaseProvider, ReviewProvider, ContentProvider
):
    name = "development"

    def get_traffic(
        self,
        db: Session,
        property_id: int,
        start: date | None = None,
        end: date | None = None,
    ) -> list[TrafficRecord]:
        query = db.query(GA4SessionsDaily).filter_by(property_id=property_id)
        if start is not None:
            query = query.filter(GA4SessionsDaily.date >= start)
        if end is not None:
            query = query.filter(GA4SessionsDaily.date <= end)
        return [
            TrafficRecord(
                property_id=r.property_id,
                date=r.date,
                source=r.session_source,
                medium=r.session_medium,
                sessions=r.sessions,
                is_ai_referral=r.is_ai_referral,
                ai_platform=r.ai_platform,
            )
            for r in query.all()
        ]

    def get_leads(self, db: Session, property_id: int) -> list[LeadRecord]:
        rows = db.query(CRMLead).filter_by(property_id=property_id).all()
        return [
            LeadRecord(
                property_id=r.property_id,
                external_id=r.external_lead_id,
                source=r.lead_source_raw,
                status=r.status.value,
                first_contact_date=r.first_contact_date,
            )
            for r in rows
        ]

    def get_leases(self, db: Session, property_id: int) -> list[LeaseRecord]:
        rows = (
            db.query(CRMLead)
            .filter(
                CRMLead.property_id == property_id,
                CRMLead.lease_signed_date.isnot(None),
            )
            .all()
        )
        return [
            LeaseRecord(
                property_id=r.property_id,
                external_id=r.external_lead_id,
                lease_signed_date=r.lease_signed_date,
                move_in_date=r.move_in_date,
            )
            for r in rows
        ]

    def get_reviews(self, db: Session, property_id: int) -> list[ReviewRecord]:
        rows = (
            db.query(PropertyReview)
            .filter_by(property_id=property_id)
            .order_by(PropertyReview.review_date, PropertyReview.id)
            .all()
        )
        from datetime import datetime, time

        return [
            ReviewRecord(
                property_id=r.property_id,
                rating=r.rating,
                text=r.body,
                published_at=(
                    datetime.combine(r.review_date, time.min)
                    if r.review_date
                    else None
                ),
                review_id=r.id,
                external_review_id=r.external_review_id,
                provider=r.provider,
                title=r.title,
                author_name=r.author_name,
                response_text=r.response_text,
                source_url=r.source_url,
            )
            for r in rows
        ]

    def get_content(self, db: Session, property_id: int) -> list[ContentRecord]:
        rows = (
            db.query(PropertyContent)
            .filter_by(property_id=property_id)
            .order_by(PropertyContent.page)
            .all()
        )
        return [
            ContentRecord(
                property_id=r.property_id,
                page=r.page,
                title=r.title,
                body=r.body,
                updated_at=r.updated_at,
                mapped_keyword=r.mapped_keyword,
                source_url=r.source_url,
            )
            for r in rows
        ]
