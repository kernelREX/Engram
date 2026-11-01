"""Turning the spoken half of a code into a key, and sealing a save with it.

The secret is eight Crockford characters, which is forty bits. One hash of that would be
cheap to exhaust for anybody holding the download link, so the secret goes through scrypt
instead. The cost is a fraction of a second once, and a very large number multiplied across
an exhaustive search. The host's file id is mixed into the salt so work spent on one code
buys nothing against another.

The parameters travel inside the container header, so raising them later does not strand
files written today.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, asdict

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Bound on the memory scrypt is allowed, large enough for the parameters below.
_MAXMEM = 256 * 1024 * 1024

NONCE_BYTES = 12
KEY_BYTES = 32


class DecryptionError(Exception):
    """The key did not open the payload, or the payload was altered."""


@dataclass(frozen=True)
class KeyParams:
    """scrypt cost, recorded alongside the data it was used on."""

    kdf: str = "scrypt"
    n: int = 1 << 16
    r: int = 8
    p: int = 1

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "KeyParams":
        kdf = data.get("kdf", "scrypt")
        if kdf != "scrypt":
            raise DecryptionError(
                f"this file was written with the {kdf!r} key derivation, which this "
                "version of Engram does not know. Update Engram."
            )
        return cls(kdf=kdf, n=int(data["n"]), r=int(data["r"]), p=int(data["p"]))


def salt_for(context: str) -> bytes:
    """A deterministic salt, so the receiver can derive the same key from the code alone."""
    return hashlib.sha256(b"engram-v1-salt\x00" + context.encode("utf-8")).digest()


def derive_key(secret: str, context: str, params: KeyParams | None = None) -> bytes:
    """Derive the content key from the secret half of a code."""
    params = params or KeyParams()
    if params.n * params.r * 128 > _MAXMEM:
        raise DecryptionError(
            "this file asks for more memory to open than Engram will allocate"
        )
    return hashlib.scrypt(
        secret.encode("utf-8"),
        salt=salt_for(context),
        n=params.n,
        r=params.r,
        p=params.p,
        dklen=KEY_BYTES,
        maxmem=_MAXMEM,
    )


def encrypt(plaintext: bytes, key: bytes, aad: bytes = b"") -> tuple[bytes, bytes]:
    """Seal `plaintext`. Returns the nonce and the ciphertext with its tag appended."""
    if len(key) != KEY_BYTES:
        raise ValueError(f"a key is {KEY_BYTES} bytes")
    nonce = os.urandom(NONCE_BYTES)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def decrypt(ciphertext: bytes, key: bytes, nonce: bytes, aad: bytes = b"") -> bytes:
    """Open a sealed payload, or say plainly that the key is wrong."""
    if len(key) != KEY_BYTES:
        raise ValueError(f"a key is {KEY_BYTES} bytes")
    if len(nonce) != NONCE_BYTES:
        raise DecryptionError("the file's nonce is the wrong length")
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise DecryptionError(
            "the file downloaded, but the secret did not open it. The last eight "
            "characters of the code are wrong, or the file was altered on the host."
        ) from None
