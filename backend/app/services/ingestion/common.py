"""Shared helpers for export-file parsers.

Manual UI exports are messy: GA4 prepends comment lines, numbers carry thousands
separators, GSC formats CTR as a percentage string. Parsers here are tolerant of
formatting but strict about meaning: files missing required dimensions fail loudly
instead of being guessed at (CLAUDE.md working style: flag, don't silently guess).
"""

import csv
import io
import re
from datetime import date, datetime


class UploadValidationError(ValueError):
    """File cannot be ingested as-is; message is shown to the user verbatim."""


DATE_FORMATS = ("%Y%m%d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")


def parse_export_date(raw: str) -> date | None:
    raw = raw.strip().strip('"')
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    # GA4 "Date + hour (YYYYMMDDHH)" and similar concatenations: the calendar
    # date is the leading 8 digits. Tolerate 10/12/14-digit all-numeric values.
    if raw.isdigit() and len(raw) in (10, 12, 14):
        try:
            return datetime.strptime(raw[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


_START_DATE_RE = re.compile(r"start date:\s*(\S+)", re.IGNORECASE)
_END_DATE_RE = re.compile(r"end date:\s*(\S+)", re.IGNORECASE)


def parse_preamble_date_range(data: bytes) -> tuple[date, date] | None:
    """Google's GA4/GSC UI exports carry '# Start date: YYYYMMDD' / '# End date:
    YYYYMMDD' comment lines above the header. When a file has no per-row Date
    column (e.g. a Queries or Landing page export), this is the only honest way
    to know what period it covers. Used to accept such exports as period
    snapshots instead of rejecting them outright."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    start = end = None
    for line in text.splitlines()[:20]:  # preamble is always near the top
        if start is None:
            m = _START_DATE_RE.search(line)
            if m:
                start = parse_export_date(m.group(1))
        if end is None:
            m = _END_DATE_RE.search(line)
            if m:
                end = parse_export_date(m.group(1))
        if start and end:
            break
    return (start, end) if start and end else None


def parse_int(raw: str) -> int:
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return 0
    return int(float(raw))


def parse_float(raw: str) -> float:
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return 0.0
    return float(raw)


def parse_ctr(raw: str) -> float:
    """GSC exports CTR as e.g. '3.53%'; APIs give a 0-1 fraction. Normalize to 0-1."""
    raw = (raw or "").strip()
    if not raw:
        return 0.0
    if raw.endswith("%"):
        return float(raw[:-1].replace(",", "")) / 100
    return float(raw)


def parse_money(raw: str) -> float:
    """Ad platform spend like '$1,234.56' or '1234.56 USD' -> 1234.56."""
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    raw = raw.replace("USD", "").strip()
    if not raw:
        return 0.0
    return float(raw)


def normalize_header(cell: str) -> str:
    """Header cells compared after lowercasing, en/em dash -> hyphen, and
    whitespace collapse, so 'Google Search – Desktop' matches its alias."""
    cell = cell.strip().lower().replace("–", "-").replace("—", "-")
    return " ".join(cell.split())


def read_csv_rows(
    data: bytes, column_aliases: dict[str, str]
) -> tuple[dict[str, list[str]], list[dict], int]:
    """Decode an export file and return (column map, data rows, header line no).

    Skips comment/preamble lines before the header (anything starting with '#',
    blank, or matching fewer than two known aliases; ad platform exports often
    lead with title lines). The header is the first line where at least two
    cells match known aliases. The returned column map is {canonical_name:
    [actual header cells]} - a list because some exports split one metric across
    several columns (e.g. GBP 'Google Search - Desktop' / '- Mobile') that the
    caller may want to sum. Rows are DictReader dicts keyed by the actual header
    cells. The header line number is 1-based and counts the skipped preamble, so
    callers can stamp each row with its real line in the source file (RAG
    readiness: source row identifier).
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = next(csv.reader([line]))
        matches = [c for c in cells if normalize_header(c) in column_aliases]
        if len(matches) >= 2:
            header_idx = i
            break
    if header_idx is None:
        raise UploadValidationError(
            "Could not find a header row. Expected a CSV export with column "
            "headers such as: " + ", ".join(sorted(set(column_aliases))[:8]) + "."
        )

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    colmap: dict[str, list[str]] = {}
    for cell in reader.fieldnames or []:
        canonical = column_aliases.get(normalize_header(cell))
        if canonical:
            colmap.setdefault(canonical, []).append(cell)
    return colmap, list(reader), header_idx + 1


def read_csv_matrix(
    data: bytes, column_aliases: dict[str, str]
) -> tuple[dict[str, list[int]], list[list[str]], int]:
    """Positional variant of read_csv_rows for messy exports.

    Returns (column index map, data rows as lists, header line no). The index
    map is {canonical_name: [column positions]}. Unlike the DictReader path,
    this survives DUPLICATE header names (GA4 free-form explorations repeat
    "Sessions"/"Key events" once per segment), because access is by position.
    Preamble/segment/blank lines before the header are skipped exactly as in
    read_csv_rows: the header is the first line with >= 2 known-alias cells.
    """
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")

    lines = text.splitlines()
    header_idx = None
    header_cells: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = next(csv.reader([line]))
        matches = [c for c in cells if normalize_header(c) in column_aliases]
        if len(matches) >= 2:
            header_idx = i
            header_cells = cells
            break
    if header_idx is None:
        raise UploadValidationError(
            "Could not find a header row. Expected a CSV export with column "
            "headers such as: " + ", ".join(sorted(set(column_aliases))[:8]) + "."
        )

    col_index: dict[str, list[int]] = {}
    for j, cell in enumerate(header_cells):
        canonical = column_aliases.get(normalize_header(cell))
        if canonical:
            col_index.setdefault(canonical, []).append(j)

    data_rows = list(csv.reader(io.StringIO("\n".join(lines[header_idx + 1:]))))
    return col_index, data_rows, header_idx + 1
