"""The `.engram` file: one save, its manifest, and nothing a host can read.

    magic    8 bytes   ENGRAM\\0\\1, the last byte being the format version
    length   4 bytes   little endian length of the header
    header   JSON      how the body is sealed, and nothing about the save
    body               a zip, or that zip sealed with AES-256-GCM

The header is plaintext because it has to be read before the key exists, and it is fed to
the cipher as associated data, so editing it breaks the tag rather than changing how the
body is read.

The same format carries a save on a USB stick and a save through a file host. A local file
can be left unsealed, because the person holding it already has the save. Anything going to
somebody else's server is always sealed.
"""

from __future__ import annotations

import io
import json
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import crypto
from .crypto import DecryptionError, KeyParams
from .manifest import Manifest, ManifestError
from .manifest import build as build_manifest
from .mods import ModSet
from .saves import SaveSlot, metadata_path

MAGIC = b"ENGRAM\x00\x01"
FORMAT_VERSION = 1

ENCRYPTION_NONE = "none"
ENCRYPTION_AES = "aes-256-gcm"

MANIFEST_NAME = "manifest.json"
SAVE_PREFIX = "save/"

#: Ordinary saves are about 6 MB. This is the ceiling on what will be unpacked, so a
#: hostile or broken container cannot be made to fill memory.
MAX_PAYLOAD = 256 * 1024 * 1024

#: And the ceiling on the sealed form, which is the same thing plus overhead.
MAX_CONTAINER = MAX_PAYLOAD + (1 << 20)

_HEADER_LIMIT = 64 * 1024


class ContainerError(Exception):
    """A container that cannot be read."""


@dataclass
class Bundle:
    """What comes out of a container: the manifest, and the save's own files."""

    manifest: Manifest
    files: dict[str, bytes]

    @property
    def total_bytes(self) -> int:
        return sum(len(data) for data in self.files.values())


def _zip_payload(manifest: Manifest, files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(MANIFEST_NAME, manifest.to_bytes())
        for name in sorted(files):
            archive.writestr(SAVE_PREFIX + name, files[name])
    return buffer.getvalue()


def _read_payload(payload: bytes) -> Bundle:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        raise ContainerError("the container's body is not a readable archive") from None

    with archive:
        names = archive.namelist()
        if MANIFEST_NAME not in names:
            raise ContainerError("the container has no manifest")

        total = sum(info.file_size for info in archive.infolist())
        if total > MAX_PAYLOAD:
            raise ContainerError(
                f"the container unpacks to {total / 1048576:.0f} MB, which is far larger "
                "than a save, so Engram will not unpack it"
            )

        try:
            manifest = Manifest.from_bytes(archive.read(MANIFEST_NAME))
        except ManifestError as exc:
            raise ContainerError(str(exc)) from None

        files: dict[str, bytes] = {}
        for name in names:
            if name == MANIFEST_NAME:
                continue
            if not name.startswith(SAVE_PREFIX) or name.endswith("/"):
                raise ContainerError(f"the container holds an unexpected entry: {name}")
            plain = name[len(SAVE_PREFIX) :]
            if "/" in plain or "\\" in plain or plain in ("", ".", ".."):
                raise ContainerError(f"the container holds an unsafe file name: {name}")
            files[plain] = archive.read(name)

    if not files:
        raise ContainerError("the container holds a manifest but no save")
    return Bundle(manifest=manifest, files=files)


def _header_bytes(header: dict) -> bytes:
    return json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")


def collect(slot: SaveSlot) -> dict[str, bytes]:
    """Read a save's files off disk, under their plain names."""
    files: dict[str, bytes] = {}
    meta = metadata_path(slot.path)
    for item in slot.files():
        try:
            files[item.name] = item.read_bytes()
        except OSError as exc:
            raise ContainerError(f"could not read {item.name}: {exc}") from None
    if meta is None or meta.name not in files:
        raise ContainerError(f"{slot.folder_name} has no metadata file to pack")
    return files


def pack(
    slot: SaveSlot,
    mods: ModSet,
    secret: str | None = None,
    context: str = "",
) -> tuple[bytes, Manifest]:
    """Build a container for one save. With a secret, the body is sealed."""
    files = collect(slot)
    manifest = build_manifest(slot, mods, files)
    payload = _zip_payload(manifest, files)
    if len(payload) > MAX_PAYLOAD:
        raise ContainerError("this save is far larger than Engram will carry")

    if secret is None:
        header = {"enc": ENCRYPTION_NONE, "format": FORMAT_VERSION}
        body = payload
    else:
        params = KeyParams()
        key = crypto.derive_key(secret, context, params)
        header = {
            "enc": ENCRYPTION_AES,
            "format": FORMAT_VERSION,
            "kdf": params.to_json(),
            "context": context,
        }
        probe = _header_bytes({**header, "nonce": ""})
        nonce, sealed = crypto.encrypt(payload, key, aad=MAGIC + probe)
        header["nonce"] = nonce.hex()
        body = sealed

    head = _header_bytes(header)
    return MAGIC + struct.pack("<I", len(head)) + head + body, manifest


def read_header(data: bytes) -> tuple[dict, int]:
    """The container's header, and where the body starts."""
    if len(data) < len(MAGIC) + 4:
        raise ContainerError("this file is too short to be an Engram container")
    if data[: len(MAGIC)] != MAGIC:
        if data[:6] == MAGIC[:6]:
            raise ContainerError(
                f"this container is format version {data[7]} and this Engram reads "
                f"{FORMAT_VERSION}. Update Engram."
            )
        raise ContainerError("this file is not an Engram container")

    (length,) = struct.unpack_from("<I", data, len(MAGIC))
    if not 0 < length <= _HEADER_LIMIT:
        raise ContainerError("the container's header length is not sensible")
    start = len(MAGIC) + 4
    raw = data[start : start + length]
    if len(raw) != length:
        raise ContainerError("the container's header is truncated")
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ContainerError("the container's header is not readable") from None
    if not isinstance(header, dict):
        raise ContainerError("the container's header is not an object")
    return header, start + length


def is_encrypted(data: bytes) -> bool:
    header, _ = read_header(data)
    return str(header.get("enc", ENCRYPTION_NONE)) != ENCRYPTION_NONE


def unpack(data: bytes, secret: str | None = None) -> Bundle:
    """Open a container, verifying the manifest's hashes before returning anything."""
    if len(data) > MAX_CONTAINER:
        raise ContainerError("this file is far larger than any save, so it is not opened")

    header, offset = read_header(data)
    body = data[offset:]
    encryption = str(header.get("enc", ENCRYPTION_NONE))

    if encryption == ENCRYPTION_NONE:
        payload = body
    elif encryption == ENCRYPTION_AES:
        if secret is None:
            raise ContainerError(
                "this container is sealed and no code was given, so there is no key to "
                "open it with"
            )
        try:
            params = KeyParams.from_json(header.get("kdf") or {})
        except (KeyError, TypeError, ValueError) as exc:
            raise ContainerError(f"the container's key settings are unreadable: {exc}") from None
        try:
            nonce = bytes.fromhex(str(header.get("nonce") or ""))
        except ValueError:
            raise ContainerError("the container's nonce is unreadable") from None

        context = str(header.get("context") or "")
        key = crypto.derive_key(secret, context, params)
        probe = _header_bytes({**{k: v for k, v in header.items() if k != "nonce"}, "nonce": ""})
        payload = crypto.decrypt(body, key, nonce, aad=MAGIC + probe)
    else:
        raise ContainerError(
            f"this container is sealed with {encryption!r}, which this Engram does not "
            "know. Update Engram."
        )

    bundle = _read_payload(payload)
    try:
        bundle.manifest.verify(bundle.files)
    except ManifestError as exc:
        raise ContainerError(str(exc)) from None
    return bundle


def write(path: str | Path, data: bytes) -> Path:
    """Write a container to disk without leaving a half file behind on failure."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".part")
    try:
        staging.write_bytes(data)
        staging.replace(target)
    except OSError:
        staging.unlink(missing_ok=True)
        raise
    return target


def read(path: str | Path) -> bytes:
    target = Path(path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise ContainerError(f"could not read {target}: {exc}") from None
    if size > MAX_CONTAINER:
        raise ContainerError(f"{target.name} is far larger than any save")
    return target.read_bytes()
