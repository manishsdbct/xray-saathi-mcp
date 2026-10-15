"""Database tools: read X-ray Saathi's results database (tables `scans` and `audit_events`).

The connection is opened read-only (SQLite mode=ro, Postgres read-only transactions), so no tool
here can change data, whatever SQL it is given.

To add a DB call, write a function that uses _rows() and decorate it with @mcp.tool(...).
"""

import json
import re
from functools import lru_cache

from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from .app import READ_ONLY, mcp
from .config import settings

# Columns safe to list. report_text is the patient's own report: only db_get_scan returns it, on request.
SCAN_COLUMNS = "id, status, scan_type, error, created_at, updated_at"


@lru_cache
def engine(url: str) -> Engine:
    if url.startswith("sqlite:///"):
        path = url.removeprefix("sqlite:///")
        return create_engine(f"sqlite:///file:{path}?mode=ro&uri=true")
    if url.startswith("postgresql"):
        return create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})
    raise ToolError("XRAY_SAATHI_DATABASE_URL must be a sqlite:/// or postgresql URL.")


def _rows(sql: str, params: dict | None = None, limit: int | None = None) -> tuple[list[str], list[dict]]:
    """Run one read-only query; returns (column names, rows as dicts with JSON-safe values)."""
    s = settings()
    limit = min(limit or s.max_rows, s.max_rows)
    try:
        with engine(s.database_url).connect() as conn:
            result = conn.execute(text(sql), params or {})
            cols = list(result.keys())
            rows = [dict(zip(cols, map(_plain, r), strict=True)) for r in result.fetchmany(limit + 1)]
    except SQLAlchemyError as e:
        raise ToolError(f"Database error: {type(e).__name__}: {getattr(e, 'orig', None) or e}") from e
    return cols, rows


def _plain(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _urgent(result_json: str | None) -> bool | None:
    return json.loads(result_json).get("urgent") if result_json else None


@mcp.tool(annotations=READ_ONLY)
def db_list_scans(limit: int = 20, status: str = "") -> list[dict]:
    """Most recent scans first: id, status, scan type, error, times, urgent flag and number of findings.
    status: optional filter, one of "queued", "processing", "done", "failed"."""
    where = "WHERE status = :status" if status else ""
    _, rows = _rows(
        f"SELECT {SCAN_COLUMNS}, result_json FROM scans {where} ORDER BY created_at DESC LIMIT :n",
        {"status": status, "n": max(1, limit)},
        limit,
    )
    for r in rows:
        result = r.pop("result_json")
        r["urgent"] = _urgent(result)
        r["findings"] = len(json.loads(result).get("findings", [])) if result else None
    return rows[:limit]


@mcp.tool(annotations=READ_ONLY)
def db_get_scan(scan_id: str, include_report_text: bool = False) -> dict:
    """One scan's full record: quality check, explanation, saved translations and audit log.
    include_report_text: also return the report text the patient typed (sensitive; only if needed)."""
    cols = SCAN_COLUMNS + ", quality_json, result_json, translations_json, input_hash"
    if include_report_text:
        cols += ", report_text"
    _, rows = _rows(f"SELECT {cols} FROM scans WHERE id = :id", {"id": scan_id})
    if not rows:
        raise ToolError(f"No scan with id {scan_id}.")
    scan = rows[0]
    for key in ("quality_json", "result_json", "translations_json"):
        raw = scan.pop(key)
        scan[key.removesuffix("_json")] = json.loads(raw) if raw else None
    _, scan["audit"] = _rows(
        "SELECT event, detail, at FROM audit_events WHERE scan_id = :id ORDER BY at, id", {"id": scan_id}
    )
    return scan


@mcp.tool(annotations=READ_ONLY)
def db_stats(days: int = 7) -> dict:
    """Counts for the last `days` days: scans by status and by scan type, urgent results,
    and how many were translated."""
    _, rows = _rows(
        "SELECT status, scan_type, result_json, translations_json, created_at FROM scans "
        "WHERE created_at >= :since",
        {"since": _since(days)},
        limit=1_000_000,  # counted here, not returned
    )
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        kind = r["scan_type"] or "not sure"
        by_type[kind] = by_type.get(kind, 0) + 1
    return {
        "days": days,
        "scans": len(rows),
        "by_status": by_status,
        "by_scan_type": by_type,
        "urgent": sum(1 for r in rows if _urgent(r["result_json"])),
        "translated": sum(1 for r in rows if r["translations_json"]),
    }


def _since(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days)).isoformat(sep=" ")


_READ_SQL = re.compile(r"^\s*(select|with|pragma\s+table_info|explain)\b", re.I)


@mcp.tool(annotations=READ_ONLY)
def db_query(sql: str, limit: int = 50) -> dict:
    """Run one read-only SQL query (SELECT or WITH) on the results database.
    Tables: scans(id, status, report_text, scan_type, quality_json, result_json, translations_json,
    input_hash, error, created_at, updated_at) and audit_events(id, scan_id, event, detail, at).
    Returns columns, rows (at most `limit`, capped by XRAY_SAATHI_MAX_ROWS) and whether it was cut short."""
    body = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";")
    if ";" in body:
        raise ToolError("Send one statement at a time.")
    if not _READ_SQL.match(body):
        raise ToolError("Only read queries (SELECT or WITH) are allowed; the database is opened read-only.")
    limit = max(1, min(limit, settings().max_rows))
    cols, rows = _rows(body, limit=limit)
    return {"columns": cols, "rows": rows[:limit], "truncated": len(rows) > limit}
