"""Settings come from environment variables, which the MCP client passes in (see README)."""

import os
from dataclasses import dataclass
from pathlib import Path

# The X-ray Saathi repo is expected next to this one: ~/Documents/xray-saathi and xray-saathi-mcp.
_SIBLING_DB = Path(__file__).resolve().parents[3] / "xray-saathi" / "data" / "xray_saathi.db"


@dataclass(frozen=True)
class Settings:
    api_url: str  # X-ray Saathi server, e.g. http://localhost:8000
    api_timeout: float  # seconds for one HTTP call
    wait_seconds: float  # how long submit_scan(wait=True) waits for a result
    database_url: str  # SQLAlchemy URL; opened read-only
    max_rows: int  # cap on rows any DB tool returns


def settings() -> Settings:
    """Read on every call, so tests and a restarted client always see the current environment."""
    env = os.environ.get
    return Settings(
        api_url=env("XRAY_SAATHI_API_URL", "http://localhost:8000").rstrip("/"),
        api_timeout=float(env("XRAY_SAATHI_API_TIMEOUT", "60")),
        wait_seconds=float(env("XRAY_SAATHI_WAIT_SECONDS", "120")),
        database_url=env("XRAY_SAATHI_DATABASE_URL", f"sqlite:///{_SIBLING_DB}"),
        max_rows=int(env("XRAY_SAATHI_MAX_ROWS", "200")),
    )
