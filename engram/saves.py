"""Reading the save folder, and writing into it without ever losing anything.

A save is a folder of three files: `sav.dat`, `metadata.9.json` and `screenshot.png`. The
metadata is plain JSON and carries everything the game's load menu shows, which is also
everything needed to decide whether a save will load on another machine.

Writing is the dangerous half. An incoming save is assembled under a temporary name and
only renamed into place once every file is written, so the game never sees a half save, and
an existing folder is copied aside before anything touches it.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

SAV = "sav.dat"
SCREENSHOT = "screenshot.png"
METADATA_GLOB = "metadata*.json"

#: The default metadata file name, used when writing a save that somehow lacks one.
DEFAULT_METADATA = "metadata.9.json"

#: Shared by every save, carries no playthrough state, and is never copied.
ENABLED_MODS = "EnabledMods.json"

#: Prefix for slots Engram creates.
INCOMING_PREFIX = "EngramSave"

_PARTIAL_SUFFIX = ".engram-incoming"

_TIMESTAMP = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}),\s*(\d{1,2})\.(\d{1,2})\.(\d{4})$")


class SaveError(Exception):
    """A save folder that cannot be read or written."""


def metadata_path(folder: Path) -> Path | None:
    """The metadata file in a save folder, whatever version suffix it carries."""
    found = sorted(folder.glob(METADATA_GLOB))
    return found[0] if found else None


def is_save_folder(folder: Path) -> bool:
    return folder.is_dir() and (folder / SAV).is_file() and metadata_path(folder) is not None


def _metadata_block(raw: dict) -> dict:
    """The useful part of the metadata container."""
    block = raw.get("Data", {}).get("metadata")
    if not isinstance(block, dict):
        raise SaveError("the metadata file has no Data.metadata block")
    return block


@dataclass
class SaveSlot:
    """One save on disk, with the fields that decide whether it travels."""

    path: Path
    raw: dict

    @property
    def folder_name(self) -> str:
        return self.path.name

    @property
    def meta(self) -> dict:
        return _metadata_block(self.raw)

    @property
    def name(self) -> str:
        return str(self.meta.get("name") or self.folder_name)

    @property
    def level(self) -> int:
        return int(float(self.meta.get("level") or 0))

    @property
    def street_cred(self) -> int:
        return int(float(self.meta.get("streetCred") or 0))

    @property
    def life_path(self) -> str:
        return str(self.meta.get("lifePath") or "unknown")

    @property
    def difficulty(self) -> str:
        return str(self.meta.get("difficulty") or "unknown")

    @property
    def play_time(self) -> float:
        return float(self.meta.get("playTime") or 0.0)

    @property
    def build_patch(self) -> str:
        return str(self.meta.get("buildPatch") or "")

    @property
    def game_version(self) -> int:
        return int(self.meta.get("gameVersion") or 0)

    @property
    def save_version(self) -> int:
        return int(self.meta.get("saveVersion") or 0)

    @property
    def playthrough_id(self) -> str:
        return str(self.meta.get("playthroughID") or "")

    @property
    def is_modded(self) -> bool:
        return bool(self.meta.get("isModded"))

    @property
    def additional_content_ids(self) -> list[str]:
        ids = self.meta.get("additionalContentIds") or []
        return [str(i) for i in ids]

    @property
    def needs_phantom_liberty(self) -> bool:
        """The game's own test, from SaveMetadataInfo.IsEp1Save in the script source."""
        return "EP1" in self.additional_content_ids

    @property
    def location_name(self) -> str:
        return str(self.meta.get("locationName") or "")

    @property
    def tracked_quest(self) -> str:
        return str(self.meta.get("trackedQuest") or "")

    @property
    def timestamp_string(self) -> str:
        return str(self.meta.get("timestampString") or "")

    @property
    def saved_at(self) -> datetime | None:
        """The save's own timestamp, which is local time in its own format."""
        match = _TIMESTAMP.match(self.timestamp_string.strip())
        if not match:
            return None
        hour, minute, second, day, month, year = (int(g) for g in match.groups())
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None

    @property
    def sort_key(self) -> float:
        when = self.saved_at
        if when is not None:
            return when.timestamp()
        try:
            return (self.path / SAV).stat().st_mtime
        except OSError:
            return 0.0

    @property
    def size_bytes(self) -> int:
        total = 0
        for item in self.files():
            try:
                total += item.stat().st_size
            except OSError:
                pass
        return total

    @property
    def screenshot(self) -> Path | None:
        shot = self.path / SCREENSHOT
        return shot if shot.is_file() else None

    def files(self) -> list[Path]:
        """Every file that belongs to this save, metadata first for predictability."""
        out = []
        meta = metadata_path(self.path)
        if meta:
            out.append(meta)
        for name in (SAV, SCREENSHOT):
            item = self.path / name
            if item.is_file():
                out.append(item)
        return out

    def describe(self) -> str:
        hours, minutes = divmod(int(self.play_time) // 60, 60)
        when = self.timestamp_string or "unknown date"
        return (
            f"level {self.level} {self.life_path}, {hours}h {minutes:02d}m played, {when}"
        )


def read_slot(folder: Path) -> SaveSlot:
    """Load one save folder."""
    meta = metadata_path(folder)
    if meta is None:
        raise SaveError(f"{folder} has no metadata file, so it is not a save")
    if not (folder / SAV).is_file():
        raise SaveError(f"{folder} has no {SAV}, so it is not a save")
    try:
        raw = json.loads(meta.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SaveError(f"could not read {meta.name} in {folder.name}: {exc}") from None
    _metadata_block(raw)
    return SaveSlot(path=folder, raw=raw)


def iter_slots(save_dir: Path) -> Iterator[SaveSlot]:
    for folder in sorted(save_dir.iterdir()):
        if not is_save_folder(folder):
            continue
        try:
            yield read_slot(folder)
        except SaveError:
            continue


def list_saves(save_dir: Path) -> list[SaveSlot]:
    """Every readable save, newest first."""
    return sorted(iter_slots(save_dir), key=lambda s: s.sort_key, reverse=True)


def find_save(save_dir: Path, wanted: str) -> SaveSlot:
    """Resolve what the user typed to one save, by folder name or displayed name."""
    slots = list_saves(save_dir)
    if not slots:
        raise SaveError(f"no saves in {save_dir}")
    lowered = wanted.strip().lower()
    for slot in slots:
        if slot.folder_name.lower() == lowered:
            return slot
    matches = [s for s in slots if s.name.lower() == lowered]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(s.folder_name for s in matches)
        raise SaveError(f"{wanted!r} matches more than one save: {names}")
    partial = [s for s in slots if lowered in s.folder_name.lower()]
    if len(partial) == 1:
        return partial[0]
    listed = ", ".join(s.folder_name for s in slots[:8])
    raise SaveError(f"no save called {wanted!r}. Saves here include: {listed}")


def free_slot_name(save_dir: Path, prefix: str = INCOMING_PREFIX) -> str:
    """A slot name nothing occupies, so an import never overwrites a save."""
    taken = {p.name.lower() for p in save_dir.iterdir()} if save_dir.is_dir() else set()
    index = 1
    while True:
        candidate = f"{prefix}-{index}"
        if candidate.lower() not in taken:
            return candidate
        index += 1
        if index > 9999:
            raise SaveError("could not find a free save slot name")


def back_up(folder: Path, backup_root: Path) -> Path:
    """Copy a save folder aside before anything writes over it."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_root / f"{stamp}-{folder.name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(folder, target)
    return target


def install_save(
    save_dir: Path,
    slot_name: str,
    files: dict[str, bytes],
    rename_in_metadata: bool = True,
) -> Path:
    """Write a save into the save folder under `slot_name`.

    The folder is assembled under a temporary name and renamed into place at the end, so
    the game never sees a partly written save. The caller is responsible for having
    checked that `slot_name` is free, or for having backed up what is there.
    """
    if SAV not in files:
        raise SaveError(f"an incoming save must contain {SAV}")

    save_dir.mkdir(parents=True, exist_ok=True)
    staging = save_dir / (slot_name + _PARTIAL_SUFFIX)
    final = save_dir / slot_name

    if final.exists():
        raise SaveError(f"{final} already exists, and Engram does not overwrite saves")
    if staging.exists():
        shutil.rmtree(staging)

    payload = dict(files)
    if rename_in_metadata:
        payload = _retitle(payload, slot_name)

    try:
        staging.mkdir(parents=True)
        for name, data in payload.items():
            if name == ENABLED_MODS:
                continue
            target = staging / name
            if target.parent != staging:
                raise SaveError(f"{name!r} is not a plain file name")
            target.write_bytes(data)
        staging.rename(final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final


def _retitle(files: dict[str, bytes], slot_name: str) -> dict[str, bytes]:
    """Set the displayed name to match the folder it is going into.

    The load menu shows the metadata's own `name`, not the folder, so leaving it alone
    would list the sender's slot name on the receiver's machine.
    """
    out = dict(files)
    for name, data in files.items():
        if not re.fullmatch(r"metadata.*\.json", name):
            continue
        try:
            raw = json.loads(data.decode("utf-8"))
            block = _metadata_block(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, SaveError):
            continue
        block["name"] = slot_name
        out[name] = json.dumps(raw, indent=4).encode("utf-8")
    return out
