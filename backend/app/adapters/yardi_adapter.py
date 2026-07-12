"""Yardi CRM adapter.

###############################################################################
#                                                                             #
#  WARNING: EVERY FIELD NAME AND STATUS VALUE IN THIS FILE IS A FAKE          #
#  PLACEHOLDER (CLAUDE.md hard rule 4).                                       #
#                                                                             #
#  No real Yardi export has been seen yet. These mappings are deliberately    #
#  written as PLACEHOLDER_* strings so they CANNOT silently ingest a real     #
#  file or be mistaken for a working integration. Do NOT replace them with    #
#  plausible-looking Yardi column names from memory or documentation; only    #
#  replace them by reading actual export samples from Tina's Yardi account,   #
#  then set is_placeholder = False and update the tests.                      #
#                                                                             #
###############################################################################
"""

from app.adapters.crm_base import CRMAdapter, NormalizedLead, SkippedRecord
from app.models import LeadStatus
from app.services.ingestion.common import parse_export_date

PLACEHOLDER_WARNING = (
    "The Yardi field mapping is a PLACEHOLDER with fake column names. "
    "Real Yardi exports cannot be ingested until the mapping is rebuilt from "
    "actual export samples."
)


class YardiAdapter(CRMAdapter):
    key = "yardi"
    label = "Yardi (PLACEHOLDER mapping)"
    is_placeholder = True

    # Fake source headers -> canonical fields. Keys are compared lowercased.
    _COLUMN_ALIASES = {
        "placeholder_lead_id_column": "external_lead_id",
        "placeholder_lead_source_column": "lead_source_raw",
        "placeholder_status_column": "status",
        "placeholder_first_contact_date_column": "first_contact_date",
        "placeholder_tour_date_column": "tour_date",
        "placeholder_application_date_column": "application_date",
        "placeholder_lease_signed_date_column": "lease_signed_date",
        "placeholder_move_in_date_column": "move_in_date",
    }

    # Fake status vocabulary -> Beacon lead statuses.
    _STATUS_VALUES = {
        "placeholder_status_lead": LeadStatus.LEAD,
        "placeholder_status_tour": LeadStatus.TOUR,
        "placeholder_status_application": LeadStatus.APPLICATION,
        "placeholder_status_lease": LeadStatus.LEASE,
        "placeholder_status_lost": LeadStatus.LOST,
    }

    @property
    def column_aliases(self) -> dict[str, str]:
        return dict(self._COLUMN_ALIASES)

    def normalize(self, record: dict[str, str]) -> NormalizedLead | SkippedRecord:
        lead_id = record.get("external_lead_id", "").strip()
        if not lead_id:
            return SkippedRecord("empty lead id")
        source_raw = record.get("lead_source_raw", "").strip()
        if not source_raw:
            return SkippedRecord("empty lead source")

        status = self._STATUS_VALUES.get(record.get("status", "").strip().lower())
        if status is None:
            return SkippedRecord(
                f"unmapped status value '{record.get('status', '')}' "
                "(placeholder mapping)"
            )

        first_contact = parse_export_date(record.get("first_contact_date", ""))
        if first_contact is None:
            return SkippedRecord(
                f"unparseable first contact date "
                f"'{record.get('first_contact_date', '')}'"
            )

        def optional_date(field: str):
            raw = record.get(field, "").strip()
            return parse_export_date(raw) if raw else None

        return NormalizedLead(
            external_lead_id=lead_id,
            lead_source_raw=source_raw,
            # Source taxonomy mapping is deliberately not attempted while the
            # mapping is a placeholder; raw values are preserved for later.
            lead_source_normalized=None,
            status=status,
            first_contact_date=first_contact,
            tour_date=optional_date("tour_date"),
            application_date=optional_date("application_date"),
            lease_signed_date=optional_date("lease_signed_date"),
            move_in_date=optional_date("move_in_date"),
        )
