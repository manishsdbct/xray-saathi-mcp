"""Entry point: `xray-saathi-mcp` (or `python -m xray_saathi_mcp.server`) runs the server over stdio."""

from . import api, db  # noqa: F401  (importing registers their tools)
from .app import mcp


def main() -> None:
    mcp.run()  # stdio, which is what Claude Code and Claude Desktop launch


if __name__ == "__main__":
    main()
