"""Durable jobs (Phase 19, slice 1b): enqueue with an idempotency key, lease
one job at a time with an atomic conditional update, retry with backoff,
reclaim expired leases, park at dead after max_attempts. One runner, many
callers: the in-process startup loop, the CLI worker, and tests."""
