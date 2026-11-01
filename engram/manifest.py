"""The manifest: everything the receiver needs to judge a save before opening it.

It travels inside the container, so it is encrypted with the save and authenticated by the
same tag. The hashes are what make the rest of it mean anything, because a manifest that
does not match the files beside it is a manifest about some other save.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import __version__
from .mods import ModSet
from .saves import SaveSlot

#: Bumped when the shape of the manifest changes in a way an older Engram cannot read.
MANIFEST_VERSION = 1

#: The first four bytes of a Cyberpunk save, which is a cheap check that a file is one.
SAV_MAGIC = b"VASC"

#: The fields of `metadata.9.json` worth carrying in the manifest itself.
_SAVE_FIELDS = (
    "name",
    "buildPatch",
    "gameVersion",
    "saveVersion",
    "playthroughID",
    "isModded",
    "level",
    "streetCred",
    "lifePath",
    "difficulty",
    "playTime",
    "playthroughTime",
    "timestampString",
    "locationName",
    "trackedQuest",
    "additionalContentIds",
    "platform",
    "isEndGameSave",
    "isPointOfNoReturn",
)


class ManifestError(Exception):
    """A manifest that cannot be read or does not match its files."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Manifest:
    """What the sender says about the save, and the hashes that back it up."""

    save: dict = field(default_factory=dict)
    mods: ModSet = field(default_factory=ModSet)
    hashes: dict[str, str] = field(default_factory=dict)
    exported_at: str = field(default_factory=now_iso)
    engram_version: int = MANIFEST_VERSION
    engram_release: str = __version__
    source_folder: str = ""

    @property
    def needs_phantom_liberty(self) -> bool:
        ids = [str(i) for i in (self.save.get("additionalContentIds") or [])]
        return "EP1" in ids

    @property
    def display_name(self) -> str:
        return str(self.save.get("name") or self.source_folder or "a save")

    @property
    def requires(self) -> dict:
        return {
            "phantomLiberty": self.needs_phantom_liberty,
            "gameVersion": int(self.save.get("gameVersion") or 0),
            "buildPatch": str(self.save.get("buildPatch") or ""),
        }

    def describe(self) -> str:
        level = int(float(self.save.get("level") or 0))
        life = self.save.get("lifePath") or "unknown"
        seconds = int(float(self.save.get("playTime") or 0))
        hours, minutes = divmod(seconds // 60, 60)
        when = self.save.get("timestampString") or "unknown date"
        return f"level {level} {life}, {hours}h {minutes:02d}m played, saved {when}"

    def to_json(self) -> dict:
        return {
            "engramVersion": self.engram_version,
            "engramRelease": self.engram_release,
            "exportedAt": self.exported_at,
            "sourceFolder": self.source_folder,
            "save": self.save,
            "requires": self.requires,
            "phantomLiberty": self.mods.phantom_liberty,
            "mods": [entry.to_json() for entry in self.mods],
            "sha256": self.hashes,
        }

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_json(), indent=2, sort_keys=False).encode("utf-8")

    @classmethod
    def from_json(cls, data: dict) -> "Manifest":
        if not isinstance(data, dict):
            raise ManifestError("the manifest is not an object")
        version = int(data.get("engramVersion") or 0)
        if version > MANIFEST_VERSION:
            raise ManifestError(
                f"this save was packed by a newer Engram (manifest version {version}, "
                f"this one reads {MANIFEST_VERSION}). Update Engram."
            )
        hashes = data.get("sha256") or {}
        if not isinstance(hashes, dict):
            raise ManifestError("the manifest's sha256 block is not an object")
        return cls(
            save=dict(data.get("save") or {}),
            mods=ModSet.from_json(
                {
                    "mods": data.get("mods") or [],
                    "phantomLiberty": data.get(
                        "phantomLiberty", (data.get("requires") or {}).get("phantomLiberty")
                    ),
                }
            ),
            hashes={str(k): str(v) for k, v in hashes.items()},
            exported_at=str(data.get("exportedAt") or ""),
            engram_version=version or MANIFEST_VERSION,
            engram_release=str(data.get("engramRelease") or ""),
            source_folder=str(data.get("sourceFolder") or ""),
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> "Manifest":
        try:
            return cls.from_json(json.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ManifestError(f"the manifest is not readable JSON: {exc}") from None

    def verify(self, files: dict[str, bytes]) -> None:
        """Check the files against the hashes, and refuse anything that does not match."""
        if not self.hashes:
            raise ManifestError("the manifest carries no hashes, so nothing can be checked")

        missing = sorted(set(self.hashes) - set(files))
        if missing:
            raise ManifestError(
                "the manifest lists files that are not in the container: "
                + ", ".join(missing)
            )
        unlisted = sorted(set(files) - set(self.hashes))
        if unlisted:
            raise ManifestError(
                "the container holds files the manifest does not list: "
                + ", ".join(unlisted)
            )
        for name, expected in sorted(self.hashes.items()):
            actual = sha256(files[name])
            if actual != expected:
                raise ManifestError(
                    f"{name} does not match its hash. The file was altered after it was "
                    "packed, so Engram will not write it."
                )
        sav = files.get("sav.dat")
        if sav is not None and not sav.startswith(SAV_MAGIC):
            raise ManifestError(
                "sav.dat does not start like a Cyberpunk save. Engram will not hand that "
                "to the game."
            )


def save_summary(slot: SaveSlot) -> dict:
    """The part of a save's metadata worth repeating in the manifest."""
    meta = slot.meta
    out = {}
    for key in _SAVE_FIELDS:
        if key in meta:
            out[key] = meta[key]
    out.setdefault("name", slot.name)
    return out


def build(slot: SaveSlot, mods: ModSet, files: dict[str, bytes]) -> Manifest:
    """Describe a save that is about to travel."""
    return Manifest(
        save=save_summary(slot),
        mods=mods,
        hashes={name: sha256(data) for name, data in sorted(files.items())},
        source_folder=slot.folder_name,
    )
