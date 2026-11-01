"""The code. It is the whole address, so there is nothing to look it up in.

    C 8KQ2MZ7 FPR4TQXA
    | |       |
    | |       the secret: derives the key, never leaves either machine
    | the host's own file id, re-encoded so it can be read aloud
    the host

Said aloud in groups of four. Read back case insensitively, with or without the dashes.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from . import crockford
from .crockford import CrockfordError
from .hosts import spec

#: Characters of secret. Forty bits, stretched by scrypt in `engram.crypto`.
SECRET_CHARS = 8

#: Characters per spoken group.
GROUP = 4


class CodeError(ValueError):
    """A code that cannot be read."""


@dataclass(frozen=True)
class Code:
    """A parsed code: which host, which file, and the secret that unlocks it."""

    host: spec.HostSpec
    file_id: str
    secret: str

    @property
    def url(self) -> str:
        return self.host.url_for(self.file_id)

    def text(self, grouped: bool = True) -> str:
        return format_code(self.host, self.file_id, self.secret, grouped=grouped)

    def __str__(self) -> str:
        return self.text()


def new_secret() -> str:
    """A fresh secret, uniform over the whole space."""
    return crockford.encode_int(secrets.randbelow(32 ** SECRET_CHARS), SECRET_CHARS)


def group(text: str, size: int = GROUP) -> str:
    return "-".join(text[i : i + size] for i in range(0, len(text), size))


def format_code(
    host: spec.HostSpec, file_id: str, secret: str, grouped: bool = True
) -> str:
    """Build a code out of a host, the id it gave us, and our secret."""
    host.validate_id(file_id)
    secret = crockford.normalise(secret)
    if len(secret) != SECRET_CHARS:
        raise CodeError(f"a secret is {SECRET_CHARS} characters, not {len(secret)}")

    value = _id_to_int(host, file_id)
    if host.is_fixed_width:
        body = crockford.encode_int(value, host.id_chars)
    else:
        chars = host.chars_for_id_of_length(len(file_id))
        body = crockford.encode_int(len(file_id), 1) + crockford.encode_int(value, chars)

    text = host.tag + body + secret
    return group(text) if grouped else text


def parse_code(text: str) -> Code:
    """Read a code back. Accepts any casing, any dashes, and explains a pasted link."""
    raw = (text or "").strip()
    if not raw:
        raise CodeError("no code given")
    if "://" in raw:
        raise CodeError(
            "that is the download link, not the code. The link alone cannot open the "
            "save, because the last eight characters of the code never left the sender's "
            "machine. Ask them for the whole code."
        )

    try:
        body = crockford.normalise(raw)
    except CrockfordError as exc:
        raise CodeError(str(exc)) from None

    if not body:
        raise CodeError("no code given")

    host = spec.by_tag(body[0])
    if host is None:
        raise CodeError(
            f"a code starting with {body[0]!r} is for a host this version does not know. "
            f"Engram knows: " + ", ".join(f"{h.tag} ({h.label})" for h in spec.HOSTS)
        )

    rest = body[1:]
    if host.is_fixed_width:
        id_chars = host.id_chars
        id_part, rest = rest[:id_chars], rest[id_chars:]
        if len(id_part) != id_chars:
            raise CodeError(_too_short(host))
        length = host.id_width
    else:
        if not rest:
            raise CodeError(_too_short(host))
        length = crockford.decode_int(rest[0])
        rest = rest[1:]
        if not 1 <= length <= spec.MAX_ID_LENGTH:
            raise CodeError("the code's second character is not a sensible id length")
        id_chars = host.chars_for_id_of_length(length)
        id_part, rest = rest[:id_chars], rest[id_chars:]
        if len(id_part) != id_chars:
            raise CodeError(_too_short(host))

    if len(rest) != SECRET_CHARS:
        raise CodeError(
            f"this code should be {1 + (0 if host.is_fixed_width else 1) + id_chars + SECRET_CHARS}"
            f" characters and it is {len(body)}. Count the groups: there should be "
            f"{-(-(1 + (0 if host.is_fixed_width else 1) + id_chars + SECRET_CHARS) // GROUP)}."
        )

    file_id = _int_to_id(host, crockford.decode_int(id_part), length)
    return Code(host=host, file_id=file_id, secret=rest)


def _too_short(host: spec.HostSpec) -> str:
    return f"this code is too short to be a {host.label} code"


def _id_to_int(host: spec.HostSpec, file_id: str) -> int:
    base = len(host.id_charset)
    value = 0
    for ch in file_id:
        value = value * base + host.id_charset.index(ch)
    return value


def _int_to_id(host: spec.HostSpec, value: int, length: int) -> str:
    base = len(host.id_charset)
    out = []
    for _ in range(length):
        out.append(host.id_charset[value % base])
        value //= base
    if value:
        raise CodeError("the code's middle does not decode to a file id")
    return "".join(reversed(out))
