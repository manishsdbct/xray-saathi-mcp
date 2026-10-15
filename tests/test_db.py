import sqlite3

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from xray_saathi_mcp import db as tools


def test_list_scans_newest_first_without_report_text(db):
    rows = tools.db_list_scans()
    assert [r["id"] for r in rows] == ["s1", "s2", "s3", "old"]
    assert rows[0]["urgent"] is True and rows[0]["findings"] == 1
    assert rows[2]["urgent"] is None and rows[2]["error"] == "Blank photo."
    assert all("report_text" not in r for r in rows)
    assert [r["id"] for r in tools.db_list_scans(status="failed")] == ["s3"]
    assert len(tools.db_list_scans(limit=2)) == 2


def test_get_scan_parses_json_and_includes_audit(db):
    scan = tools.db_get_scan("s1")
    assert scan["result"]["urgent"] is True
    assert scan["quality"] == {"verdict": "good"} and scan["translations"] == {"hi": {}}
    assert [e["event"] for e in scan["audit"]] == ["created", "done"]
    assert "report_text" not in scan
    assert tools.db_get_scan("s1", include_report_text=True)["report_text"] == "Right pneumothorax."
    with pytest.raises(ToolError, match="No scan"):
        tools.db_get_scan("nope")


def test_stats_counts_recent_scans(db):
    s = tools.db_stats(days=7)
    assert s["scans"] == 3
    assert s["by_status"] == {"done": 2, "failed": 1}
    assert s["by_scan_type"] == {"xray": 1, "not sure": 1, "mri": 1}
    assert s["urgent"] == 1 and s["translated"] == 1


def test_query_reads_and_caps_rows(db, monkeypatch):
    out = tools.db_query("SELECT id FROM scans ORDER BY id -- newest\n;", limit=2)
    assert out == {"columns": ["id"], "rows": [{"id": "old"}, {"id": "s1"}], "truncated": True}
    monkeypatch.setenv("XRAY_SAATHI_MAX_ROWS", "1")
    assert len(tools.db_query("WITH x AS (SELECT id FROM scans) SELECT * FROM x", limit=50)["rows"]) == 1


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM scans",
        "UPDATE scans SET status='x'",
        "SELECT 1; DROP TABLE scans",
        "/* hi */ INSERT INTO scans (id) VALUES ('x')",
    ],
)
def test_query_refuses_writes(db, sql):
    with pytest.raises(ToolError):
        tools.db_query(sql)


def test_connection_is_read_only_even_if_sql_check_were_bypassed(db):
    with pytest.raises(ToolError, match="readonly|read-only|attempt to write"):
        tools._rows("UPDATE scans SET status = 'x'")
    con = sqlite3.connect(db)
    assert con.execute("SELECT count(*) FROM scans WHERE status = 'x'").fetchone() == (0,)


def test_bad_sql_is_a_tool_error(db):
    with pytest.raises(ToolError, match="Database error"):
        tools.db_query("SELECT nope FROM scans")
