"""Uploading to and downloading from the hosts, behind one interface.

Nothing above this layer knows which host a save went to. That is what makes the host tag
in the code worth having: the default can change and old codes keep working.

Each provider does one upload attempt and checks the URL it gets back against the shape its
spec declares. A host that quietly changes its URL scheme fails here, at the moment of
sharing, rather than handing somebody a code that does not resolve three days later.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import net
from ..net import NetworkError
from .spec import HostSpec


class HostError(Exception):
    """A host that would not take the file, or gave back something unusable."""


@dataclass(frozen=True)
class Upload:
    """What came back from a successful upload."""

    host: HostSpec
    file_id: str
    url: str
    delete_token: str = ""


def _check_size(host: HostSpec, content: bytes) -> None:
    if len(content) > host.max_bytes:
        raise HostError(
            f"{host.label} takes files up to {host.max_bytes // 1048576} MB and this one "
            f"is {len(content) // 1048576} MB"
        )


def _id_from(host: HostSpec, url: str) -> str:
    file_id = host.id_from_url(url)
    if file_id is None:
        raise HostError(
            f"{host.label} answered with {url!r}, which is not the address shape Engram "
            f"expects ({host.url_template}). The host has changed. Use another host, or "
            "fix the host list in the config file."
        )
    try:
        host.validate_id(file_id)
    except ValueError as exc:
        raise HostError(str(exc)) from None
    return file_id


def upload_litterbox(host: HostSpec, content: bytes) -> Upload:
    """Litterbox takes an anonymous multipart post and expires the file on a timer."""
    _check_size(host, content)
    try:
        response = net.post_multipart(
            host.upload_url,
            fields={"reqtype": "fileupload", "time": host.expiry or "72h"},
            file_field="fileToUpload",
            filename=host.upload_filename,
            content=content,
        )
    except NetworkError as exc:
        raise HostError(str(exc)) from None

    url = response.text
    if not url.startswith("http"):
        raise HostError(
            f"{host.label} answered {url[:200]!r} instead of a link. "
            "The host may be refusing uploads right now."
        )
    return Upload(host=host, file_id=_id_from(host, url), url=url)


def upload_nullpointer(host: HostSpec, content: bytes) -> Upload:
    """0x0.st takes the same shape of post and hands back a deletion token in a header."""
    _check_size(host, content)
    fields = {}
    if host.expiry:
        fields["expires"] = host.expiry
    try:
        response = net.post_multipart(
            host.upload_url,
            fields=fields,
            file_field="file",
            filename=host.upload_filename,
            content=content,
        )
    except NetworkError as exc:
        raise HostError(str(exc)) from None

    url = response.text
    if not url.startswith("http"):
        raise HostError(
            f"{host.label} answered {url[:200]!r} instead of a link. "
            "The host may be refusing uploads right now."
        )
    return Upload(
        host=host,
        file_id=_id_from(host, url),
        url=url,
        delete_token=response.headers.get("x-token", ""),
    )


#: One uploader per host key.
UPLOADERS = {
    "litterbox": upload_litterbox,
    "nullpointer": upload_nullpointer,
}


def upload(host: HostSpec, content: bytes) -> Upload:
    """Put a container on one host. One attempt, no retry loop."""
    uploader = UPLOADERS.get(host.key)
    if uploader is None:
        raise HostError(f"no uploader for {host.key!r}")
    return uploader(host, content)


def download(host: HostSpec, file_id: str) -> bytes:
    """Fetch a container back off a host."""
    url = host.url_for(file_id)
    try:
        return net.get_bytes(url)
    except NetworkError as exc:
        raise HostError(str(exc)) from None
