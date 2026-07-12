"""ChromaDB persistent store for chunk vectors and text.

Vectors and chunk text live here; provenance lives in SQLite (rag_chunks) so
citations resolve against real rows. The collection is recreated only when the
embedder changes (vectors from different embedders are not comparable).
"""

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

COLLECTION = "beacon_chunks"


def get_collection(chroma_dir: str | None = None, embedder_key: str = ""):
    client = chromadb.PersistentClient(
        path=chroma_dir or settings.chroma_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        COLLECTION, metadata={"embedder": embedder_key or "unset"}
    )
    if embedder_key and collection.metadata.get("embedder") not in (
        embedder_key,
        "unset",
    ):
        client.delete_collection(COLLECTION)
        collection = client.create_collection(
            COLLECTION, metadata={"embedder": embedder_key}
        )
    return collection
