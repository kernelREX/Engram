"""What Engram needs to know about a file host in order to put it in a code.

A host hands back a URL. Only a short id inside that URL is unique, so the id is what the
code carries. Ids are not in an alphabet anyone can read aloud, so each host declares the
alphabet and width of its own ids and the id travels as an integer in Crockford base32.

Each host also declares the shape of the URL it produces. `share` checks the URL the host
actually returned against that shape, so a host quietly changing its scheme fails at the
moment of sharing rather than handing out a code that does not work.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

from ..crockford import width_for

BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

#: The longest host assigned id the variable width encoding will carry.
MAX_ID_LENGTH = 31


@dataclass(frozen=True)
class HostSpec:
    """A host, described well enough to build and read a code without touching it."""

    tag: str
    key: str
    label: str
    url_template: str
    id_charset: str
    upload_filename: str
    upload_url: str = ""
    id_width: int | None = None
    max_bytes: int = 1024 * 1024 * 1024
    expiry: str = ""
    note: str = ""

    def expiry_spelling(self, hours: int) -> str:
        """How this host spells a lifetime of `hours`.

        Litterbox wants "72h" and only accepts 1, 12, 24 and 72, so anything else is
        pulled up to the next value it does accept rather than being refused. 0x0.st takes
        a plain number of hours.
        """
        if self.key == "litterbox":
            for step in (1, 12, 24, 72):
                if hours <= step:
                    return f"{step}h"
            return "72h"
        return str(max(1, hours))

    def replace(self, **changes) -> "HostSpec":
        """A copy with some fields overridden, for the config file to adjust a host."""
        return replace(self, **changes)

    def __post_init__(self) -> None:
        if len(self.tag) != 1:
            raise ValueError("a host tag is one character")
        if "{id}" not in self.url_template:
            raise ValueError("a URL template needs an {id} placeholder")

    @property
    def is_fixed_width(self) -> bool:
        return self.id_width is not None

    def chars_for_id_of_length(self, length: int) -> int:
        """How many code characters an id of `length` host characters occupies."""
        bits = math.ceil(length * math.log2(len(self.id_charset)))
        return width_for(bits)

    @property
    def id_chars(self) -> int:
        """Code characters taken by the id, for a fixed width host."""
        if self.id_width is None:
            raise ValueError(f"{self.key} has variable width ids")
        return self.chars_for_id_of_length(self.id_width)

    def url_for(self, file_id: str) -> str:
        return self.url_template.format(id=file_id)

    def id_from_url(self, url: str) -> str | None:
        """Pull the id back out of a URL this host returned, or None if it does not fit."""
        head, _, tail = self.url_template.partition("{id}")
        pattern = f"^{re.escape(head)}([{re.escape(self.id_charset)}]+){re.escape(tail)}$"
        match = re.match(pattern, url.strip())
        return match.group(1) if match else None

    def validate_id(self, file_id: str) -> None:
        if not file_id:
            raise ValueError(f"{self.label} returned an empty file id")
        bad = [c for c in file_id if c not in self.id_charset]
        if bad:
            raise ValueError(
                f"{self.label} returned the file id {file_id!r}, which contains "
                f"{bad[0]!r}, outside the alphabet Engram knows for this host"
            )
        if self.id_width is not None and len(file_id) != self.id_width:
            raise ValueError(
                f"{self.label} returned a {len(file_id)} character file id, but Engram "
                f"expects {self.id_width}. The host has changed; update the host list."
            )
        if self.id_width is None and len(file_id) > MAX_ID_LENGTH:
            raise ValueError(
                f"{self.label} returned a file id longer than {MAX_ID_LENGTH} characters"
            )


LITTERBOX = HostSpec(
    tag="C",
    key="litterbox",
    label="Litterbox",
    url_template="https://litter.catbox.moe/{id}.bin",
    id_charset=BASE36,
    id_width=6,
    upload_filename="engram.bin",
    upload_url="https://litterbox.catbox.moe/resources/internals/api.php",
    max_bytes=1024 * 1024 * 1024,
    expiry="72h",
    note="run by catbox.moe, expires on a timer between 1 and 72 hours",
)

NULLPOINTER = HostSpec(
    tag="N",
    key="nullpointer",
    label="0x0.st",
    url_template="https://0x0.st/{id}.bin",
    id_charset=BASE62,
    id_width=None,
    upload_filename="engram.bin",
    upload_url="https://0x0.st",
    max_bytes=512 * 1024 * 1024,
    expiry="72",
    note="retention scales down with file size",
)

X0AT = HostSpec(
    tag="X",
    key="x0at",
    label="x0.at",
    url_template="https://x0.at/{id}.bin",
    id_charset=BASE62,
    id_width=None,
    upload_filename="engram.bin",
    upload_url="https://x0.at",
    max_bytes=512 * 1024 * 1024,
    expiry="72",
    note="speaks the same plain text protocol as 0x0.st",
)

#: Hosts in the order Engram tries them when sharing. Three rather than two, because these
#: are free services run by volunteers and a share that found both of the first two
#: unwilling had nowhere else to go.
HOSTS: tuple[HostSpec, ...] = (LITTERBOX, NULLPOINTER, X0AT)

_BY_TAG = {h.tag: h for h in HOSTS}
_BY_KEY = {h.key: h for h in HOSTS}


def by_tag(tag: str) -> HostSpec | None:
    return _BY_TAG.get(tag.upper())


def by_key(key: str) -> HostSpec | None:
    return _BY_KEY.get(key.lower())


def known_keys() -> list[str]:
    return [h.key for h in HOSTS]
