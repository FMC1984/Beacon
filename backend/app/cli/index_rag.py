"""Build or refresh the RAG index from ingested data.

    .venv/bin/python -m app.cli.index_rag

Requires BEACON_OPENAI_API_KEY in backend/.env (embeddings are the only
network call; chunk text itself is deterministic and local).
"""

import sys

from app.db import SessionLocal
from app.services.rag.embedder import MissingAPIKeyError, get_embedder
from app.services.rag.indexer import build_index


def main() -> None:
    try:
        embedder = get_embedder()
    except MissingAPIKeyError as exc:
        print(f"Cannot build index: {exc}")
        sys.exit(1)

    db = SessionLocal()
    try:
        summary = build_index(db, embedder)
    finally:
        db.close()

    print(f"Embedder: {summary['embedder']}")
    print(f"Chunks total: {summary['chunks_total']}")
    print(f"Newly embedded: {summary['embedded']}")
    print(f"Unchanged (skipped): {summary['unchanged']}")
    print(f"Removed stale: {summary['removed']}")


if __name__ == "__main__":
    main()
