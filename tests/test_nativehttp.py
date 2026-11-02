"""The native upload, against a local server that answers the way the real hosts do.

The hosts refused a real share and the message said only that one of them was having
trouble. Before blaming them, the request itself has to be proved correct: a malformed
multipart body is exactly the sort of thing a server answers with a 5xx.

So this stands a server in front of the native uploader, parses what arrives with Python's
own multipart parser, and checks every part of it. Nothing here touches the internet.
"""

from __future__ import annotations

import re
import subprocess
import threading
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

HARNESS = (
    Path(__file__).resolve().parents[1] / "native" / "build" / "Release" / "engram_harness.exe"
)

pytestmark = pytest.mark.skipif(
    not HARNESS.is_file(),
    reason="native harness not built: cmake --build native/build --config Release",
)


class Seen:
    """What the fake host received, and what it should answer with."""

    def __init__(self) -> None:
        self.status = 200
        self.body = b""
        self.headers: dict[str, str] = {}
        self.fields: dict[str, str] = {}
        self.file_name = ""
        self.file_bytes = b""
        self.file_content_type = ""
        self.user_agent = ""
        self.content_type = ""
        self.calls = 0


@pytest.fixture
def host():
    seen = Seen()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.calls += 1
            seen.user_agent = self.headers.get("User-Agent", "")
            seen.content_type = self.headers.get("Content-Type", "")
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))

            # Parse it the way a real server would, rather than by hand.
            document = BytesParser().parsebytes(
                b"Content-Type: " + seen.content_type.encode() + b"\r\n\r\n" + raw
            )
            for part in document.get_payload():
                name = part.get_param("name", header="content-disposition")
                filename = part.get_param("filename", header="content-disposition")
                payload = part.get_payload(decode=True)
                if filename:
                    seen.file_name = filename
                    seen.file_bytes = payload
                    seen.file_content_type = part.get_content_type()
                else:
                    seen.fields[name] = payload.decode("utf-8")

            self.send_response(seen.status)
            for key, value in seen.headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(seen.body)))
            self.end_headers()
            self.wfile.write(seen.body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield seen, base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def upload(host_key: str, base: str, path: Path, hours: int = 72):
    return subprocess.run(
        [str(HARNESS), "upload", host_key, f"{base}/api", f"{base}/", str(path), str(hours)],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def payload(tmp_path):
    target = tmp_path / "sealed.engram"
    data = bytes((i * 37) % 256 for i in range(200000))
    target.write_bytes(data)
    return target, data


# ---------------------------------------------------------------- the request itself


def test_the_request_is_well_formed_multipart(host, payload):
    seen, base = host
    target, data = payload
    seen.body = f"{base}/8kq2mz.bin".encode()

    result = upload("litterbox", base, target)
    assert result.returncode == 0, result.stdout + result.stderr

    assert seen.calls == 1
    assert seen.content_type.startswith("multipart/form-data; boundary=")
    assert seen.file_bytes == data, "the file arrived altered or truncated"
    assert seen.file_name == "engram.bin"
    assert seen.file_content_type == "application/octet-stream"


def test_litterbox_gets_the_fields_it_documents(host, payload):
    seen, base = host
    target, _ = payload
    seen.body = f"{base}/8kq2mz.bin".encode()

    assert upload("litterbox", base, target, 24).returncode == 0
    assert seen.fields == {"reqtype": "fileupload", "time": "24h"}


def test_nullpointer_gets_the_fields_it_documents(host, payload):
    seen, base = host
    target, _ = payload
    seen.body = f"{base}/aBc.bin".encode()

    assert upload("nullpointer", base, target, 24).returncode == 0
    assert seen.fields == {"expires": "24"}


def test_the_user_agent_says_what_we_are(host, payload):
    seen, base = host
    target, _ = payload
    seen.body = f"{base}/8kq2mz.bin".encode()

    assert upload("litterbox", base, target).returncode == 0
    assert "Engram/" in seen.user_agent
    assert "github.com/tfthushaar/Engram" in seen.user_agent


def test_a_chosen_lifetime_reaches_the_host(host, payload):
    seen, base = host
    target, _ = payload
    seen.body = f"{base}/8kq2mz.bin".encode()

    for hours, expected in ((1, "1h"), (12, "12h"), (24, "24h"), (72, "72h")):
        seen.fields = {}
        assert upload("litterbox", base, target, hours).returncode == 0
        assert seen.fields["time"] == expected


def test_the_file_id_and_token_come_back(host, payload):
    seen, base = host
    target, _ = payload
    seen.body = f"{base}/aBc.bin".encode()
    seen.headers = {"X-Token": "a-delete-token"}

    result = upload("nullpointer", base, target)
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "aBc"
    assert lines[1] == f"{base}/aBc.bin"
    assert lines[2] == "a-delete-token"


# ------------------------------------------------------------- what the host answers


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, "blocking automated"),
        (418, "blocking automated"),
        (429, "rate limiting"),
        (413, "too large"),
        (500, "their end"),
        (503, "their end"),
    ],
)
def test_each_refusal_is_explained(host, payload, status, expected):
    seen, base = host
    target, _ = payload
    seen.status = status
    seen.body = b"no"

    result = upload("litterbox", base, target)
    assert result.returncode != 0
    assert expected in result.stdout


def test_the_hosts_own_explanation_is_quoted_back(host, payload):
    """Without this a failure is unreportable: the host usually says why in the body."""
    seen, base = host
    target, _ = payload
    seen.status = 503
    seen.body = b"upload quota exceeded for your address\nsecond line ignored"

    result = upload("litterbox", base, target)
    assert result.returncode != 0
    assert "upload quota exceeded for your address" in result.stdout
    assert "second line ignored" not in result.stdout
    assert "503" in result.stdout


def test_a_silent_refusal_still_reads_sensibly(host, payload):
    seen, base = host
    target, _ = payload
    seen.status = 500
    seen.body = b""

    result = upload("litterbox", base, target)
    assert result.returncode != 0
    assert "It said" not in result.stdout
    assert "500" in result.stdout


def test_an_answer_that_is_not_a_link_is_reported(host, payload):
    seen, base = host
    target, _ = payload
    seen.body = b"Service temporarily unavailable"

    result = upload("litterbox", base, target)
    assert result.returncode != 0
    assert "not a link" in result.stdout


def test_an_address_of_the_wrong_shape_fails_at_share_time(host, payload):
    """Better than handing somebody a code that cannot be resolved."""
    seen, base = host
    target, _ = payload
    seen.body = b"https://somewhere.else/totally-different"

    result = upload("litterbox", base, target)
    assert result.returncode != 0
    assert "does not recognise" in result.stdout


def test_an_unreachable_host_says_so(payload):
    target, _ = payload
    result = subprocess.run(
        [
            str(HARNESS), "upload", "litterbox",
            "http://127.0.0.1:1/api", "http://127.0.0.1:1/", str(target), "72",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0
    assert "could not reach" in result.stdout or "Check the connection" in result.stdout
