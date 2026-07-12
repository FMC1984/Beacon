"""Keyless local providers for tests and demo mode.

These make the full pipeline (chunk -> embed -> store -> retrieve -> generate)
runnable and deterministic without any network call. They are NOT semantically
meaningful and never impersonate live output: the demo LLM labels itself.
"""

import hashlib
import math
from collections.abc import Iterator

from app.providers.base import EmbeddingProvider, LLMProvider

DEMO_PREFIX = (
    "Demo mode: this is a deterministic local summary of the retrieved data, "
    "not live model output."
)

# Chunk lines worth surfacing in a demo answer, in display order.
_DEMO_FACT_PREFIXES = (
    "Total sessions:",
    "AI referral sessions:",
    "AI platform breakdown:",
    "Organic clicks:",
    "Search impressions:",
    "Paid media by platform:",
    "Leads:",
    "Lead sources",
    # Content Intelligence summary lines (Phase 10).
    "Content Intelligence score:",
    "Question coverage:",
    "Missing renter questions:",
    "Neighborhood coverage:",
    "Content freshness:",
    "Keyword intent:",
    "Top opportunities:",
    # Property context lines (Phase 10.5).
    "Property type:",
    "Regulatory status:",
    "Marketing restrictions:",
    "Target audience:",
    # Review Intelligence summary lines (Phase 11).
    "Review Health Score:",
    "Reviews:",
    "Sentiment:",
    "Top resident complaints:",
    "Top resident praise:",
    "Priority opportunities:",
    "Review trends:",
)


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Stable token-hash pseudo-vectors; test/dev only."""

    name = "deterministic"
    version = "v1"

    def __init__(self, dims: int = 128):
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dims
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode()).digest()
                idx = int.from_bytes(digest[:4], "big") % self.dims
                sign = 1.0 if digest[4] % 2 else -1.0
                vec[idx] += sign
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors

    def dimension(self) -> int:
        return self.dims


class DemoLLMProvider(LLMProvider):
    """Composes a labeled answer from the retrieved excerpts with plain string
    handling. Citations, gate handling, and disclosures still flow through the
    normal Nora assembly; only the prose is deterministic and local."""

    name = "demo"

    def generate(self, system: str, user: str) -> str:
        lines = []
        current_ref = None
        for raw in user.splitlines():
            line = raw.strip()
            if line.startswith("[") and "]" in line and "(" in line:
                current_ref = line.split("]")[0] + "]"
            elif any(line.startswith(p) for p in _DEMO_FACT_PREFIXES):
                lines.append(f"{line} {current_ref or ''}".strip())
        if not lines:
            return (
                f"{DEMO_PREFIX}\nThe retrieved excerpts do not contain key "
                "figures for this question."
            )
        facts = "\n".join(f"- {line}" for line in lines[:10])
        return f"{DEMO_PREFIX}\nKey figures from the retrieved data:\n{facts}"

    def stream(self, system: str, user: str) -> Iterator[str]:
        for line in self.generate(system, user).splitlines(keepends=True):
            yield line
