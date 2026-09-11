"""Normalization + hashing of a ProviderResult (Phase 19).

`normalize_result` produces the schema-versioned dict stored on
AIVisibilityQuery.normalized_response so readers never parse raw provider
payloads. `compress_payload` keeps the full raw payload (audit evidence)
small enough for the 1 GB disk.
"""

import hashlib
import json
import zlib
from dataclasses import asdict

from app.connectors.base import ProviderResult

SCHEMA_VERSION = 1
PAYLOAD_ENCODING = "zlib-json"


def response_hash(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def normalize_result(result: ProviderResult) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": result.provider,
        "platform": result.platform,
        "model": result.model,
        "text": result.text,
        "citations": [asdict(c) for c in result.citations],
        "search_queries": list(result.search_queries),
        "usage": asdict(result.usage),
        "search_operations": result.search_operations,
        "browsed": result.browsed,
        "latency_ms": result.latency_ms,
        "provider_response_id": result.provider_response_id,
        "location": result.location,
    }


def compress_payload(payload: dict | None) -> bytes | None:
    if payload is None:
        return None
    text = json.dumps(payload, default=str, separators=(",", ":"))
    return zlib.compress(text.encode("utf-8"), level=6)


def decompress_payload(blob: bytes | None) -> dict | None:
    if not blob:
        return None
    return json.loads(zlib.decompress(blob).decode("utf-8"))
