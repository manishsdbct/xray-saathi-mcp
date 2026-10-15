"""API tools: call the X-ray Saathi HTTP API (backend/app/main.py in the app repo).

To add an API call, write a function that uses _call() and decorate it with @mcp.tool(...).
The docstring and type hints become the tool's description and input schema.
"""

import mimetypes
import time
from pathlib import Path

import httpx
from mcp.server.mcpserver.exceptions import ToolError

from .app import READ_ONLY, WRITES, mcp
from .config import settings

SCAN_TYPES = ("", "xray", "ct", "mri")
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def client() -> httpx.Client:
    """One place to build the HTTP client, so tests can swap in a fake transport."""
    s = settings()
    return httpx.Client(base_url=s.api_url, timeout=s.api_timeout)


def _call(method: str, path: str, **kwargs) -> dict:
    """Make one API call. Failures become ToolError with the server's own message for the model."""
    try:
        with client() as c:
            r = c.request(method, path, **kwargs)
    except httpx.ConnectError as e:
        raise ToolError(
            f"Can't reach X-ray Saathi at {settings().api_url}. Is the server running? ({e})"
        ) from e
    except httpx.TimeoutException as e:
        raise ToolError(f"X-ray Saathi did not answer within {settings().api_timeout:.0f} s.") from e
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise ToolError(f"{method} {path} failed with {r.status_code}: {detail}")
    return r.json()


@mcp.tool(annotations=READ_ONLY)
def api_health() -> dict:
    """Check that the X-ray Saathi server is up. Returns {"ok": true} when it is."""
    return _call("GET", "/api/health")


@mcp.tool(annotations=WRITES)
def api_submit_scan(
    image_path: str,
    consent: bool,
    report_text: str = "",
    scan_type: str = "",
    wait: bool = True,
) -> dict:
    """Upload a scan image to X-ray Saathi for a plain-language explanation.

    image_path: a local image file (jpg, png, webp or heic). Names and IDs on the film should be
        cropped out first.
    consent: must be true. Only set it when the patient has agreed to their image being processed.
    report_text: optional radiology report text; explanations are much more accurate with it.
    scan_type: "xray", "ct", "mri", or "" if not sure.
    wait: if true, wait for the result (up to XRAY_SAATHI_WAIT_SECONDS) instead of returning
        the queued scan at once.

    Every upload is a paid Claude call on the server, unless the same upload was cached.
    """
    if not consent:
        raise ToolError("Consent is required: the patient must agree before their image is uploaded.")
    if scan_type not in SCAN_TYPES:
        raise ToolError(f"scan_type must be one of {', '.join(repr(t) for t in SCAN_TYPES)}.")
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise ToolError(f"No file at {path}.")
    if path.suffix.lower() not in IMAGE_TYPES:
        raise ToolError(f"{path.name} is not a supported image ({', '.join(sorted(IMAGE_TYPES))}).")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    scan = _call(
        "POST",
        "/api/scans",
        files={"image": (path.name, path.read_bytes(), mime)},
        data={"report_text": report_text, "scan_type": scan_type, "consent": "true"},
    )
    return _wait_for(scan["id"]) if wait else scan


def _wait_for(scan_id: str, poll: float = 1.5) -> dict:
    deadline = time.monotonic() + settings().wait_seconds
    while True:
        scan = _call("GET", f"/api/scans/{scan_id}")
        if scan["status"] in ("done", "failed") or time.monotonic() >= deadline:
            return scan
        time.sleep(poll)


@mcp.tool(annotations=READ_ONLY)
def api_get_scan(scan_id: str) -> dict:
    """Get a scan's status ("queued", "processing", "done" or "failed"), photo quality and,
    when done, the full explanation shown to the patient."""
    return _call("GET", f"/api/scans/{scan_id}")


@mcp.tool(annotations=WRITES)
def api_translate_scan(scan_id: str, lang: str = "hi") -> dict:
    """Get a finished explanation in another language ("hi" = Hindi). The first request makes the
    translation (a paid Claude call) and saves it; later requests return the saved one."""
    return _call("POST", f"/api/scans/{scan_id}/translations/{lang}")
