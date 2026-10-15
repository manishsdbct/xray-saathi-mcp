"""The MCP server object. Tool modules (api.py, db.py) import it and register their tools on it."""

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer(
    "xray-saathi",
    instructions=(
        "Tools for the X-ray Saathi app. api_* tools call its HTTP API (the server must be running); "
        "db_* tools read its results database, read-only. Scan results are patient health data: "
        "show only what the user asked for, and never upload an image without the patient's consent."
    ),
)

# Shared tool annotations: they tell the client which tools only read.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
