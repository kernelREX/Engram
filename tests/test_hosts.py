"""The host layer, against a local server that answers the way the real ones do.

Nothing here touches the internet. The point is the handling: what Engram does with a
sensible answer, and what it does with every unhelpful one a volunteer run service can
give.
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from engram.hosts import spec
from engram.hosts.provider import HostError, download, upload
from engram.net import USER_AGENT


class Script:
    """What the fake host should do next, and what it saw."""

    def __init__(self) -> None:
        self.status = 200
        self.body = b""
        self.headers: dict[str, str] = {}
        self.seen_agent = ""
        self.seen_fields: dict[str, str] = {}
        self.seen_bytes = 0
        self.calls = 0


@pytest.fixture
def host_server():
    script = Script()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _answer(self):
            script.calls += 1
            script.seen_agent = self.headers.get("User-Agent", "")
            self.send_response(script.status)
            for name, value in script.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(script.body)))
            self.end_headers()
            self.wfile.write(script.body)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            script.seen_bytes = len(raw)
            for name, value in re.findall(
                rb'name="([^"]+)"\r\n\r\n(.*?)\r\n--', raw, re.DOTALL
            ):
                script.seen_fields[name.decode()] = value.decode()
            self._answer()

        def do_GET(self):
            self._answer()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        yield script, base
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def litterbox_at(base: str) -> spec.HostSpec:
    return spec.LITTERBOX.replace(
        upload_url=f"{base}/api.php", url_template=base + "/{id}.bin"
    )


def nullpointer_at(base: str) -> spec.HostSpec:
    return spec.NULLPOINTER.replace(upload_url=base, url_template=base + "/{id}.bin")


def test_a_litterbox_upload_sends_what_the_host_expects(host_server):
    script, base = host_server
    host = litterbox_at(base)
    script.body = f"{base}/8kq2mz.bin".encode()

    result = upload(host, b"a sealed container")

    assert result.file_id == "8kq2mz"
    assert script.seen_fields["reqtype"] == "fileupload"
    assert script.seen_fields["time"] == "72h"
    assert script.seen_agent == USER_AGENT
    assert "Engram" in script.seen_agent and "github" in script.seen_agent


def test_a_nullpointer_upload_keeps_the_deletion_token(host_server):
    script, base = host_server
    host = nullpointer_at(base)
    script.body = f"{base}/aBc.bin".encode()
    script.headers = {"X-Token": "secret-token"}

    result = upload(host, b"a sealed container")

    assert result.file_id == "aBc"
    assert result.delete_token == "secret-token"
    assert script.seen_fields["expires"] == "72"


def test_the_whole_container_reaches_the_host(host_server):
    script, base = host_server
    script.body = f"{base}/8kq2mz.bin".encode()
    payload = bytes(range(256)) * 400
    upload(litterbox_at(base), payload)
    assert script.seen_bytes > len(payload)


def test_an_address_that_is_not_the_expected_shape_fails_at_share_time(host_server):
    """Better to fail now than to hand someone a code that cannot be resolved."""
    script, base = host_server
    script.body = b"https://somewhere.else/totally-different"
    with pytest.raises(HostError, match="not the address shape"):
        upload(litterbox_at(base), b"x")


def test_an_id_outside_the_hosts_alphabet_is_refused(host_server):
    script, base = host_server
    script.body = f"{base}/TOOLONGFORLITTERBOX.bin".encode()
    with pytest.raises(HostError):
        upload(litterbox_at(base), b"x")


def test_a_non_link_answer_is_reported_as_itself(host_server):
    script, base = host_server
    script.body = b"Service temporarily unavailable, try later"
    with pytest.raises(HostError, match="instead of a link"):
        upload(litterbox_at(base), b"x")


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, "blocking automated"),
        (418, "blocking automated"),
        (429, "rate limiting"),
        (413, "too large"),
        (500, "having trouble"),
        (503, "having trouble"),
    ],
)
def test_each_refusal_is_explained_in_plain_words(host_server, status, expected):
    script, base = host_server
    script.status = status
    script.body = b"no"
    with pytest.raises(HostError, match=expected):
        upload(litterbox_at(base), b"x")


def test_an_expired_code_says_that_codes_expire(host_server):
    script, base = host_server
    script.status = 404
    with pytest.raises(HostError, match="expire"):
        download(litterbox_at(base), "8kq2mz")


def test_a_download_comes_back_whole(host_server):
    script, base = host_server
    script.body = bytes(range(256)) * 100
    assert download(litterbox_at(base), "8kq2mz") == script.body


def test_one_attempt_per_upload_and_no_retry_loop(host_server):
    script, base = host_server
    script.status = 500
    with pytest.raises(HostError):
        upload(litterbox_at(base), b"x")
    assert script.calls == 1


def test_a_file_bigger_than_the_host_takes_never_leaves_the_machine(host_server):
    script, base = host_server
    host = litterbox_at(base).replace(max_bytes=16)
    with pytest.raises(HostError, match="takes files up to"):
        upload(host, b"x" * 64)
    assert script.calls == 0


def test_an_unreachable_host_says_so():
    host = spec.LITTERBOX.replace(upload_url="http://127.0.0.1:1/api.php")
    with pytest.raises(HostError, match="could not reach"):
        upload(host, b"x")


def test_every_host_declares_an_uploader():
    from engram.hosts.provider import UPLOADERS

    for host in spec.HOSTS:
        assert host.key in UPLOADERS
        assert host.upload_url.startswith("https://")
