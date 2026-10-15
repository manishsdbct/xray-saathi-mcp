import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

# The app's schema (backend/app/db.py), as SQLite creates it.
SCHEMA = """
CREATE TABLE scans (
    id VARCHAR(36) PRIMARY KEY, status VARCHAR(16), report_text TEXT, scan_type VARCHAR(8),
    quality_json TEXT, result_json TEXT, translations_json TEXT, input_hash VARCHAR(64), error TEXT,
    created_at DATETIME, updated_at DATETIME
);
CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id VARCHAR(36), event VARCHAR(64), detail TEXT, at DATETIME
);
"""


def _when(hours_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S.%f")


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "xray_saathi.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    urgent = {"urgent": True, "summary": "Air around the right lung.", "findings": [{"name": "A"}]}
    normal = {"urgent": False, "summary": "Nothing obvious.", "findings": []}
    con.executemany(
        "INSERT INTO scans VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "s1",
                "done",
                "Right pneumothorax.",
                "xray",
                '{"verdict": "good"}',
                json.dumps(urgent),
                '{"hi": {}}',
                "h1",
                None,
                _when(1),
                _when(1),
            ),
            ("s2", "done", "", "", None, json.dumps(normal), None, "h2", None, _when(2), _when(2)),
            ("s3", "failed", "", "mri", None, None, None, None, "Blank photo.", _when(3), _when(3)),
            (
                "old",
                "done",
                "",
                "ct",
                None,
                json.dumps(normal),
                None,
                None,
                None,
                _when(24 * 30),
                _when(24 * 30),
            ),
        ],
    )
    con.executemany(
        "INSERT INTO audit_events (scan_id, event, detail, at) VALUES (?,?,?,?)",
        [("s1", "created", "", _when(1)), ("s1", "done", "urgent=True", _when(0.9))],
    )
    con.commit()
    con.close()
    monkeypatch.setenv("XRAY_SAATHI_DATABASE_URL", f"sqlite:///{path}")
    return path
