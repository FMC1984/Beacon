"""Citation extraction, URL normalization, classification and persistence
(Phase 19).

Provider-reported citations are OBSERVED (capture_method provider_annotation
/ grounding_chunk). When a provider exposes none, Beacon falls back to the
URLs present in the prose (capture_method prose_regex), the same deterministic
extraction the legacy sources_cited list used. Classification reuses
source_classifier so owned / competitor / directory / government / review /
media / unknown mean the same thing everywhere in Beacon.
"""

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy.orm import Session

from app.connectors.base import ProviderResult
from app.models import AICitation, AIRun, AIVisibilityQuery, Competitor, Property
from app.models.ai_citations import CAPTURE_PROSE_REGEX
from app.services.ai_visibility.parsing import extract_urls
from app.services.source_classifier import classify_domain

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "ref", "ref_src", "srsltid"}
# Second-level labels under which the registrable domain is three labels
# deep (example.co.uk). Deliberately short; unknown patterns fall back to
# two labels, which is right for every .com/.org/.gov domain Beacon sees.
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


@dataclass(frozen=True)
class CitationDraft:
    url: str
    normalized_url: str
    domain: str
    root_domain: str
    path: str | None
    title: str | None
    citation_order: int
    citation_position: int | None
    end_position: int | None
    capture_method: str


_REDIRECT_HOSTS = {"vertexaisearch.cloud.google.com"}


def normalize_url(url: str) -> tuple[str, str, str, str]:
    """(normalized_url, domain, root_domain, path). Lowercases the host,
    strips www., fragments, tracking params and a trailing slash. A bare
    domain is accepted. Unparsable input yields empty strings."""
    raw = (url or "").strip().rstrip(".,);]\"'")
    if not raw:
        return "", "", "", ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "", "", "", ""
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return "", "", "", ""
    path = parts.path or ""
    if path.endswith("/") and len(path) > 1:
        path = path[:-1]
    if path == "/":
        path = ""
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)
    normalized = host + path + (("?" + query) if query else "")
    labels = host.split(".")
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL:
        root = ".".join(labels[-3:])
    else:
        root = ".".join(labels[-2:])
    return normalized, host, root, path or None


def domain_of_url(url: str | None) -> str | None:
    if not url:
        return None
    _, host, _, _ = normalize_url(url)
    return host or None


def owned_domains_for(prop: Property) -> set[str]:
    d = domain_of_url(getattr(prop, "website_url", None))
    return {d} if d else set()


def competitor_domains_for(competitors: list[Competitor]) -> set[str]:
    out: set[str] = set()
    for c in competitors:
        d = domain_of_url(c.domain)
        if d:
            out.add(d)
    return out


def extract_citations(result: ProviderResult, fallback_text: str) -> list[CitationDraft]:
    """Provider citations when present (de-duplicated by normalized URL,
    provider order kept); otherwise the prose-regex fallback. Never both:
    mixing capture methods would double count a source."""
    drafts: list[CitationDraft] = []
    seen: set[str] = set()

    if result.citations:
        for c in result.citations:
            normalized, host, root, path = normalize_url(c.url)
            if host in _REDIRECT_HOSTS and c.title:
                # Gemini grounding chunks link through a Google redirect; the
                # chunk title is the source domain Gemini reports.
                _, t_host, t_root, _ = normalize_url(c.title)
                if t_host and "." in t_host:
                    host, root, path = t_host, t_root, None
            if not host or normalized in seen:
                continue
            seen.add(normalized)
            drafts.append(
                CitationDraft(
                    url=c.url, normalized_url=normalized, domain=host,
                    root_domain=root, path=path, title=c.title,
                    citation_order=len(drafts), citation_position=c.start_index,
                    end_position=c.end_index, capture_method=c.capture_method,
                )
            )
        return drafts

    for url in extract_urls(fallback_text or ""):
        normalized, host, root, path = normalize_url(url)
        if not host or normalized in seen:
            continue
        seen.add(normalized)
        position = (fallback_text or "").find(url)
        drafts.append(
            CitationDraft(
                url=url, normalized_url=normalized, domain=host, root_domain=root,
                path=path, title=None, citation_order=len(drafts),
                citation_position=position if position >= 0 else None,
                end_position=None, capture_method=CAPTURE_PROSE_REGEX,
            )
        )
    return drafts


def classify_citation(domain: str, owned: set[str], competitor: set[str]) -> str:
    return classify_domain(domain, owned, competitor)


def citation_domains(drafts: list[CitationDraft]) -> list[str]:
    return sorted({d.domain for d in drafts if d.domain})


def persist_citations(
    db: Session,
    response: AIVisibilityQuery,
    run: AIRun | None,
    drafts: list[CitationDraft],
    owned: set[str],
    competitor: set[str],
) -> list[AICitation]:
    """Idempotent: replaces the response's citation rows."""
    db.query(AICitation).filter_by(response_id=response.id).delete()
    rows: list[AICitation] = []
    for d in drafts:
        row = AICitation(
            response_id=response.id,
            run_id=run.id if run else None,
            organization_id=run.organization_id if run else None,
            market_id=run.market_id if run else None,
            url=d.url,
            normalized_url=d.normalized_url,
            domain=d.domain,
            root_domain=d.root_domain,
            path=d.path,
            title=d.title,
            citation_order=d.citation_order,
            citation_position=d.citation_position,
            end_position=d.end_position,
            source_type=classify_citation(d.domain, owned, competitor),
            capture_method=d.capture_method,
        )
        db.add(row)
        rows.append(row)
    return rows
