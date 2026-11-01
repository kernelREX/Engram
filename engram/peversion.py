"""Reading a version out of a Windows DLL, without a subprocess.

RED4ext plugins are DLLs and most of them carry a version resource. That version is the
only reliable way to tell two builds of the same plugin apart, which is the difference
between a warning the receiver should read and one they can ignore.

Everything here is best effort. A DLL with no version resource, or one laid out in a way
this parser does not expect, returns None rather than raising, because a missing version
is an ordinary outcome and never a reason to fail a share.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

_RT_VERSION = 16
_FIXED_SIGNATURE = 0xFEEF04BD

#: A version resource is never large, and this keeps a malformed file from being walked far.
_MAX_RESOURCE = 1 << 20


@dataclass(frozen=True)
class FileVersion:
    """What a DLL says about itself."""

    file_version: str | None = None
    product_version: str | None = None
    product_name: str | None = None
    fixed_version: str | None = None

    @property
    def best(self) -> str | None:
        """The version worth showing a person."""
        for candidate in (self.product_version, self.file_version, self.fixed_version):
            if candidate:
                return candidate.strip()
        return None


class _Image:
    """A PE file, with just enough structure to reach its resources."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.sections: list[tuple[int, int, int]] = []
        self.resource_rva = 0
        self._parse()

    def _u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def _parse(self) -> None:
        if self.data[:2] != b"MZ":
            raise ValueError("not a Windows binary")
        pe = self._u32(0x3C)
        if self.data[pe : pe + 4] != b"PE\0\0":
            raise ValueError("no PE header")
        section_count = self._u16(pe + 6)
        optional_size = self._u16(pe + 20)
        optional = pe + 24
        magic = self._u16(optional)
        if magic == 0x10B:
            directories = optional + 96
        elif magic == 0x20B:
            directories = optional + 112
        else:
            raise ValueError("unknown optional header")
        self.resource_rva = self._u32(directories + 2 * 8)

        table = optional + optional_size
        for index in range(section_count):
            header = table + index * 40
            virtual_size = self._u32(header + 8)
            virtual_address = self._u32(header + 12)
            raw_size = self._u32(header + 16)
            raw_pointer = self._u32(header + 20)
            span = max(virtual_size, raw_size)
            self.sections.append((virtual_address, span, raw_pointer))

    def offset_of(self, rva: int) -> int:
        for virtual_address, span, raw_pointer in self.sections:
            if virtual_address <= rva < virtual_address + span:
                return raw_pointer + (rva - virtual_address)
        raise ValueError("address outside every section")


def _resource_entries(data: bytes, base: int, directory: int) -> list[tuple[int, int, bool]]:
    """The entries of one resource directory as (id, offset, is_directory)."""
    named, numbered = struct.unpack_from("<HH", data, base + directory + 12)
    out = []
    for index in range(named + numbered):
        entry = base + directory + 16 + index * 8
        name, offset = struct.unpack_from("<II", data, entry)
        out.append((name & 0x7FFFFFFF, offset & 0x7FFFFFFF, bool(offset & 0x80000000)))
    return out


def _find_version_resource(image: _Image) -> bytes | None:
    """Walk type, name then language to the first RT_VERSION blob."""
    if not image.resource_rva:
        return None
    base = image.offset_of(image.resource_rva)
    data = image.data

    for type_id, type_offset, is_dir in _resource_entries(data, base, 0):
        if type_id != _RT_VERSION or not is_dir:
            continue
        for _, name_offset, name_is_dir in _resource_entries(data, base, type_offset):
            if not name_is_dir:
                continue
            for _, lang_offset, lang_is_dir in _resource_entries(data, base, name_offset):
                if lang_is_dir:
                    continue
                rva, size = struct.unpack_from("<II", data, base + lang_offset)
                if not 0 < size <= _MAX_RESOURCE:
                    continue
                start = image.offset_of(rva)
                return data[start : start + size]
    return None


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _read_block(blob: bytes, offset: int) -> tuple[int, int, int, str, int]:
    """One VS_VERSIONINFO style block header: length, value length, type, key, body."""
    length, value_length, value_type = struct.unpack_from("<HHH", blob, offset)
    cursor = offset + 6
    end = blob.find(b"\x00\x00", cursor)
    if end < 0:
        raise ValueError("unterminated key")
    if (end - cursor) % 2:
        end += 1
    key = blob[cursor:end].decode("utf-16-le", errors="replace")
    body = _align4(end + 2)
    return length, value_length, value_type, key, body


def _read_strings(blob: bytes, offset: int, limit: int) -> dict[str, str]:
    """Pull every name and value out of a StringFileInfo block."""
    out: dict[str, str] = {}
    cursor = offset
    while cursor + 6 <= limit:
        try:
            length, value_length, value_type, key, body = _read_block(blob, cursor)
        except (struct.error, ValueError):
            break
        if length <= 0 or cursor + length > limit:
            break
        if value_type == 1 and value_length:
            raw = blob[body : body + value_length * 2]
            out[key] = raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        else:
            out.update(_read_strings(blob, body, cursor + length))
        cursor += _align4(length)
    return out


def _fixed_version(blob: bytes, offset: int) -> str | None:
    try:
        signature = struct.unpack_from("<I", blob, offset)[0]
    except struct.error:
        return None
    if signature != _FIXED_SIGNATURE:
        return None
    try:
        high, low = struct.unpack_from("<II", blob, offset + 8)
    except struct.error:
        return None
    parts = (high >> 16, high & 0xFFFF, low >> 16, low & 0xFFFF)
    return ".".join(str(p) for p in parts)


def _parse_version_blob(blob: bytes) -> FileVersion:
    length, value_length, _, key, body = _read_block(blob, 0)
    if key != "VS_VERSION_INFO":
        raise ValueError("not a version resource")
    fixed = _fixed_version(blob, body) if value_length else None
    children = _align4(body + value_length)
    strings = _read_strings(blob, children, min(length, len(blob)))
    return FileVersion(
        file_version=strings.get("FileVersion") or None,
        product_version=strings.get("ProductVersion") or None,
        product_name=strings.get("ProductName") or None,
        fixed_version=fixed,
    )


def read_version(path: str | Path) -> FileVersion | None:
    """The version resource of a DLL or EXE, or None if there is not one to read."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    try:
        blob = _find_version_resource(_Image(data))
        if not blob:
            return None
        return _parse_version_blob(blob)
    except (ValueError, struct.error, IndexError, UnicodeDecodeError):
        return None
