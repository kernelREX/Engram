"""The small amount of HTTP Engram needs, on the standard library.

These are volunteer run services doing us a favour, so this file is written to be a good
guest: one request per attempt, no retry loops, a user agent that says plainly what is
calling and where to complain about it, and a hard ceiling on what will be downloaded.
"""

from __future__ import annotations

import mimetypes
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__

#: Says what we are and where to find us, so a host operator can get in touch rather than
#: guess. Several hosts refuse a default library user agent outright.
USER_AGENT = f"Engram/{__version__} (+https://github.com/tfthushaar/Engram)"

CONNECT_TIMEOUT = 30
TRANSFER_TIMEOUT = 300

#: Never pull down more than this, whatever a host claims the length is.
MAX_DOWNLOAD = 256 * 1024 * 1024

_CHUNK = 256 * 1024


class NetworkError(Exception):
    """A request that did not get where it was going."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace").strip()


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.HTTPSHandler())


def _request(
    url: str,
    data: bytes | None = None,
    content_type: str | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: int = TRANSFER_TIMEOUT,
) -> Response:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if content_type:
        headers["Content-Type"] = content_type
    headers.update(extra_headers or {})

    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with _opener().open(request, timeout=timeout) as response:
            body = _read_capped(response)
            return Response(
                status=response.status,
                body=body,
                headers={k.lower(): v for k, v in response.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(2048).decode("utf-8", errors="replace").strip()
        except Exception:
            pass
        raise NetworkError(_explain_status(url, exc.code, detail)) from None
    except urllib.error.URLError as exc:
        raise NetworkError(f"could not reach {_host_of(url)}: {exc.reason}") from None
    except TimeoutError:
        raise NetworkError(f"{_host_of(url)} did not answer in time") from None
    except OSError as exc:
        raise NetworkError(f"could not reach {_host_of(url)}: {exc}") from None


def _read_capped(stream) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = stream.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_DOWNLOAD:
            raise NetworkError(
                "the download is far larger than any save, so it was stopped"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _host_of(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url


def _explain_status(url: str, code: int, detail: str) -> str:
    host = _host_of(url)
    short = detail.splitlines()[0][:160] if detail else ""
    if code == 404:
        return (
            f"{host} has no file at that address. Codes expire, so this one has most "
            "likely run out, or the middle of the code was misheard."
        )
    if code in (403, 418):
        return (
            f"{host} refused the request ({code}). The host may be blocking automated "
            "uploads. Try the other host, or share the file directly."
        )
    if code == 429:
        return (
            f"{host} is rate limiting this connection. Wait a few minutes rather than "
            "retrying, or use the other host."
        )
    if code == 413:
        return f"{host} says the file is too large"
    if 500 <= code < 600:
        return f"{host} is having trouble ({code}). Try the other host."
    return f"{host} answered {code}" + (f": {short}" if short else "")


def post_multipart(
    url: str,
    fields: dict[str, str],
    file_field: str,
    filename: str,
    content: bytes,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    """One multipart upload, built in memory because a save is only a few megabytes."""
    boundary = "----EngramBoundary" + secrets.token_hex(16)
    guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
            f"Content-Type: {guessed}\r\n\r\n"
        ).encode("utf-8")
    )
    parts.append(content)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

    return _request(
        url,
        data=b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
        extra_headers=extra_headers,
    )


def get_bytes(url: str) -> bytes:
    """Download a file, with a ceiling on how much of it is read."""
    return _request(url, timeout=TRANSFER_TIMEOUT).body
