# X-ray Saathi MCP server

An [MCP](https://modelcontextprotocol.io) server that lets Claude (Claude Code, Claude Desktop or any
MCP client) work with the X-ray Saathi app. It provides two kinds of tools:

- **API tools** call the X-ray Saathi HTTP API: check the server, upload a scan, get a result, get
  a Hindi translation.
- **Database tools** read the results database: list scans, open one with its audit log, count
  them, or run a read-only SQL query.

The database is always opened **read-only**, so no tool here can change or delete data.

## Tools

| Tool | What it does | Changes anything? |
|---|---|---|
| `api_health` | Checks the X-ray Saathi server is up | No |
| `api_submit_scan` | Uploads a scan image (with optional report text and scan type) and waits for the explanation. Requires `consent=true` | Yes: creates a scan, makes a paid Claude call |
| `api_get_scan` | A scan's status, photo quality and explanation | No |
| `api_translate_scan` | The explanation in Hindi (`hi`). The first time makes and saves the translation | Yes: saves a translation, makes a paid Claude call |
| `db_list_scans` | Recent scans: status, type, urgent flag, number of findings, errors. Leaves out the patient's report text | No |
| `db_get_scan` | One scan in full: quality, explanation, translations, audit log. Report text only with `include_report_text=true` | No |
| `db_stats` | Counts for the last N days: by status, by scan type, urgent, translated | No |
| `db_query` | Any single `SELECT` / `WITH` query, rows capped | No |

## Setup

Requires Python 3.11+.

```bash
cd ~/Documents/xray-saathi-mcp
python3 -m venv .venv
.venv/bin/pip install -e .              # add ".[postgres]" for a Postgres database, ".[dev]" for tests
```

Start X-ray Saathi as usual (see its README). The API tools need it running. The database tools only
need the database file.

### Settings

All settings are environment variables, passed in by the MCP client:

| Variable | Default | Purpose |
|---|---|---|
| `XRAY_SAATHI_API_URL` | `http://localhost:8000` | The X-ray Saathi server |
| `XRAY_SAATHI_DATABASE_URL` | `sqlite:///../xray-saathi/data/xray_saathi.db` (the app repo next to this one) | The app's database: `sqlite:///path` or `postgresql+psycopg://user:pass@host/db` |
| `XRAY_SAATHI_API_TIMEOUT` | `60` | Seconds for one HTTP call |
| `XRAY_SAATHI_WAIT_SECONDS` | `120` | How long `api_submit_scan` waits for the result |
| `XRAY_SAATHI_MAX_ROWS` | `200` | Most rows any database tool returns |

### Connect to Claude Code

```bash
claude mcp add xray-saathi \
  -e XRAY_SAATHI_API_URL=http://localhost:8000 \
  -e XRAY_SAATHI_DATABASE_URL=sqlite:////Users/manishgarg/Documents/xray-saathi/data/xray_saathi.db \
  -- /Users/manishgarg/Documents/xray-saathi-mcp/.venv/bin/xray-saathi-mcp
```

Run `claude mcp list` to check it's connected, then ask, for example, *"how many scans failed this
week?"* or *"show the latest urgent scan's audit log"*.

The SQLite URL needs **four** slashes for an absolute path: `sqlite:///` plus `/Users/...`.

### Connect to Claude Desktop

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json` and restart Claude Desktop:

```json
{
  "mcpServers": {
    "xray-saathi": {
      "command": "/Users/manishgarg/Documents/xray-saathi-mcp/.venv/bin/xray-saathi-mcp",
      "env": {
        "XRAY_SAATHI_API_URL": "http://localhost:8000",
        "XRAY_SAATHI_DATABASE_URL": "sqlite:////Users/manishgarg/Documents/xray-saathi/data/xray_saathi.db"
      }
    }
  }
}
```

## Adding your own calls

Tools are plain Python functions with a decorator. The function name becomes the tool name, the
docstring its description, and the type hints its input schema. Restart the MCP client after
adding one.

### An API call: in `src/xray_saathi_mcp/api.py`

Use `_call()`. It handles the base URL, timeouts and errors (the server's own message is shown to
the model).

```python
@mcp.tool(annotations=READ_ONLY)          # WRITES if the endpoint changes something
def api_list_languages() -> dict:
    """Languages the explanation can be translated into."""
    return _call("GET", "/api/languages")
```

To call a different service, add its URL to `config.py` and build another client like `client()`.

### A database call: in `src/xray_saathi_mcp/db.py`

Use `_rows()`. It runs one query on the read-only connection and returns `(columns, rows)` with
dates as text.

```python
@mcp.tool(annotations=READ_ONLY)
def db_failed_reasons(days: int = 7) -> list[dict]:
    """How often each error message happened in the last `days` days."""
    _, rows = _rows(
        "SELECT error, count(*) AS n FROM scans "
        "WHERE status = 'failed' AND created_at >= :since GROUP BY error ORDER BY n DESC",
        {"since": _since(days)},
    )
    return rows
```

Always pass values as `:named` parameters, never by formatting them into the SQL string.

**Writes:** the connection is read-only on purpose. If you ever need a tool that changes data,
give it its own connection with only the access it needs, mark it `WRITES`, and keep it narrow:
for example "delete scan X", never "run any SQL".

## Privacy and safety

- Scan results are **patient health data**. The server's instructions tell the model to show only
  what the user asked for.
- Report text the patient typed is left out of lists and only returned by `db_get_scan` on request.
- `api_submit_scan` refuses to upload without `consent=true`, and checks the file is an image first.
- `db_query` accepts one `SELECT`/`WITH` statement. Even without that check the connection itself
  is read-only (SQLite `mode=ro`, Postgres `default_transaction_read_only`).
- `api_submit_scan` and `api_translate_scan` cost money (Claude calls on the X-ray Saathi server).

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest          # API tools against a fake server, DB tools against a temp SQLite DB
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

| File | What it is |
|---|---|
| `src/xray_saathi_mcp/app.py` | The `MCPServer` object, its instructions, and shared annotations |
| `src/xray_saathi_mcp/api.py` | API tools and the `_call()` helper |
| `src/xray_saathi_mcp/db.py` | Database tools, the read-only engine and the `_rows()` helper |
| `src/xray_saathi_mcp/config.py` | Settings from environment variables |
| `src/xray_saathi_mcp/server.py` | Entry point (`xray-saathi-mcp`), stdio transport |

Built on the MCP Python SDK v2 (`mcp.server.mcpserver.MCPServer`).
