import asyncio

import httpx
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from xray_saathi_mcp import api
from xray_saathi_mcp.server import mcp


@pytest.fixture
def server(monkeypatch):
    """A fake X-ray Saathi API. Records requests; scan s1 becomes done on the second poll."""
    seen = []
    polls = {"n": 0}

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        path = req.url.path
        if path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/api/scans" and req.method == "POST":
            return httpx.Response(202, json={"id": "s1", "status": "queued"})
        if path == "/api/scans/s1":
            polls["n"] += 1
            status = "done" if polls["n"] >= 2 else "processing"
            return httpx.Response(200, json={"id": "s1", "status": status})
        if path == "/api/scans/s1/translations/hi":
            return httpx.Response(200, json={"summary": "छाती का एक्स-रे।"})
        if path == "/api/scans/s1/translations/xx":
            return httpx.Response(404, json={"detail": "That language is not available."})
        return httpx.Response(404, json={"detail": "Scan not found."})

    monkeypatch.setattr(
        api, "client", lambda: httpx.Client(base_url="http://test", transport=httpx.MockTransport(handle))
    )
    monkeypatch.setattr(api.time, "sleep", lambda s: None)
    return seen


@pytest.fixture
def image(tmp_path):
    p = tmp_path / "chest.jpg"
    p.write_bytes(b"\xff\xd8fake")
    return p


def test_health(server):
    assert api.api_health() == {"ok": True}


def test_submit_sends_form_and_waits_for_result(server, image):
    out = api.api_submit_scan(str(image), consent=True, report_text="Opacity", scan_type="xray")
    assert out == {"id": "s1", "status": "done"}
    upload = server[0]
    assert upload.method == "POST" and upload.url.path == "/api/scans"
    body = upload.content
    assert b'name="consent"\r\n\r\ntrue' in body and b'name="scan_type"\r\n\r\nxray' in body
    assert b'filename="chest.jpg"' in body and b"image/jpeg" in body
    assert [r.url.path for r in server[1:]] == ["/api/scans/s1", "/api/scans/s1"]


def test_submit_without_wait_returns_queued(server, image):
    assert api.api_submit_scan(str(image), consent=True, wait=False)["status"] == "queued"


@pytest.mark.parametrize(
    "kwargs, msg",
    [
        ({"consent": False}, "Consent"),
        ({"consent": True, "scan_type": "xr"}, "scan_type"),
    ],
)
def test_submit_checks_before_uploading(server, image, kwargs, msg):
    with pytest.raises(ToolError, match=msg):
        api.api_submit_scan(str(image), **kwargs)
    assert server == []


def test_submit_needs_an_image_file(server, tmp_path):
    with pytest.raises(ToolError, match="No file"):
        api.api_submit_scan(str(tmp_path / "missing.jpg"), consent=True)
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(ToolError, match="not a supported image"):
        api.api_submit_scan(str(tmp_path / "notes.txt"), consent=True)


def test_errors_carry_the_servers_message(server):
    with pytest.raises(ToolError, match="404: Scan not found"):
        api.api_get_scan("nope")
    with pytest.raises(ToolError, match="not available"):
        api.api_translate_scan("s1", "xx")
    assert api.api_translate_scan("s1")["summary"].startswith("छाती")


def test_server_down_is_explained(monkeypatch):
    monkeypatch.setenv("XRAY_SAATHI_API_URL", "http://127.0.0.1:9")
    with pytest.raises(ToolError, match="Is the server running"):
        api.api_health()


def test_tools_are_registered_with_read_only_hints():
    async def tools():
        async with Client(mcp) as c:
            return (await c.list_tools()).tools

    by_name = {t.name: t for t in asyncio.run(tools())}
    assert set(by_name) == {
        "api_health",
        "api_submit_scan",
        "api_get_scan",
        "api_translate_scan",
        "db_list_scans",
        "db_get_scan",
        "db_stats",
        "db_query",
    }
    assert by_name["db_query"].annotations.read_only_hint is True
    assert by_name["api_submit_scan"].annotations.read_only_hint is False
    assert by_name["api_submit_scan"].input_schema["required"] == ["image_path", "consent"]
