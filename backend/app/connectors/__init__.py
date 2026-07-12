"""Connector architecture: where Beacon's data comes from is hidden behind
interfaces. The rest of the app asks a TrafficProvider / LeadProvider /
LeaseProvider / ReviewProvider / ContentProvider for normalized records and
never knows whether they came from local CSV imports, a CRM API, or a future
Marketing IQ feed.

Current implementation: DevelopmentDataProvider (reads the local SQLite data
ingested via manual uploads). Future implementations (MarketingIQProvider,
HubSpotProvider, SalesforceProvider, CSVProvider, GoogleAnalyticsProvider,
GoogleSearchConsoleProvider) implement the same interfaces with no change to
consumers.
"""

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
from app.connectors.development import DevelopmentDataProvider

__all__ = [
    "TrafficProvider",
    "LeadProvider",
    "LeaseProvider",
    "ReviewProvider",
    "ContentProvider",
    "TrafficRecord",
    "LeadRecord",
    "LeaseRecord",
    "ReviewRecord",
    "ContentRecord",
    "DevelopmentDataProvider",
]
