"""Fetch a live webpage and extract its visible text as property content.

This is data collection, not analysis: a plain HTTP GET plus HTML text
extraction, no external AI involved (consistent with Content Intelligence's
"no external calls for analysis" rule - this only gathers the source text,
the same role a manual copy-paste or a CSV upload plays elsewhere in Beacon).

Known limitations, stated plainly rather than silently masked:
- JavaScript-rendered pages (SPAs) will extract little or no text, since this
  does not run a browser. The response says how many characters were found so
  a suspiciously empty fetch is visible immediately.
- No crawling: exactly one URL is fetched per call. Beacon does not guess or
  discover subpages; the operator supplies each page's URL explicitly, same as
  it never infers property type or regulatory status.
- Sites that block automated requests (403s, bot walls) will fail with a
  readable error rather than a silent empty result.
"""

import re

import httpx
from bs4 import BeautifulSoup

MAX_BODY_CHARS = 20_000
FETCH_TIMEOUT_SECONDS = 15
USER_AGENT = "Mozilla/5.0 (compatible; BeaconContentFetch/1.0; +internal tool)"

# Tags whose text is never part of the visible reading content.
_STRIP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "svg", "form")


class ContentFetchError(ValueError):
    """Fetch or extraction failed; message is shown to the user verbatim."""


def _validate_url(url: str) -> None:
    url = (url or "").strip()
    if not url:
        raise ContentFetchError("No URL provided.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise ContentFetchError(
            "URL must start with http:// or https://. Got: " + url
        )


def fetch_page_content(url: str) -> dict:
    """Fetch `url` and return {title, body, char_count}. Raises
    ContentFetchError with a plain-language reason on any failure."""
    _validate_url(url)

    try:
        response = httpx.get(
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
    except httpx.TimeoutException:
        raise ContentFetchError(f"Timed out fetching {url} after {FETCH_TIMEOUT_SECONDS}s.")
    except httpx.RequestError as exc:
        raise ContentFetchError(f"Could not reach {url}: {exc}")

    if response.status_code >= 400:
        raise ContentFetchError(
            f"{url} returned HTTP {response.status_code}. The site may block "
            "automated requests, or the page may not exist."
        )

    content_type = response.headers.get("content-type", "")
    if "html" not in content_type.lower():
        raise ContentFetchError(
            f"{url} did not return an HTML page (content-type: {content_type or 'unknown'})."
        )

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else ""
    body_root = soup.find("main") or soup.body or soup
    text = body_root.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()

    truncated = len(text) > MAX_BODY_CHARS
    if truncated:
        text = text[:MAX_BODY_CHARS].rsplit(" ", 1)[0]

    return {
        "title": title,
        "body": text,
        "char_count": len(text),
        "truncated": truncated,
    }
