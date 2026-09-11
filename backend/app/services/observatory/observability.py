"""Structured logging for Observatory events (Phase 19). One JSON line per
event with the fields the spec asks operators to be able to grep for:
provider, run_id, organization_id, market_id, property_id, prompt_id,
latency_ms, status, tokens, search_operations, estimated_cost, retry_count."""

import json
import logging

logger = logging.getLogger("beacon.observatory")


def log_event(event: str, **fields) -> None:
    payload = {"event": event}
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    logger.info(json.dumps(payload, default=str, sort_keys=True))
