"""Working out what is installed, so the receiver can be told what differs.

A save made with mods carries their state inside `sav.dat`. The game will not tell you
that, and neither will the save, so the sender's mod list has to travel alongside it.

Nothing here reads `sav.dat`. It looks at the five places mods live, takes folder names and
whatever version each mod publishes about itself, and notes which mods declare persistent
fields, because those are the ones whose state disappears when the version changes.

A mod author can settle all of this by dropping an `engram.json` beside their mod:

    {"name": "Cyberbane", "version": "1.4.5", "writesPersistentState": true}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .paths import GameInstall
from .peversion import read_version

#: Files and folders that are bookkeeping rather than mods.
IGNORED_NAMES = {
    "__folder_managed_by_vortex",
    "__folder_managed_by_vortex.txt",
    "desktop.ini",
    "thumbs.db",
    ".git",
    ".gitkeep",
    "engram.json",
}

#: The convention a mod author can use to declare all of this properly.
DECLARATION = "engram.json"

#: Anything matching this in a redscript source means the mod keeps state in the save.
PERSISTENT = re.compile(r"\bpersistent\s+(?:let|func)\b")

#: A version at the end of a folder name, the way Vortex and Nexus tend to leave it.
NAME_VERSION = re.compile(r"^(?P<base>.*?)[ _\-]+v?(?P<version>\d+(?:\.\d+)*[a-z]?)$")

#: A version a Lua mod assigns to itself.
LUA_VERSION = re.compile(
    r"""(?:^|[^A-Za-z])(?:mod)?version\s*=\s*['"](?P<version>[0-9][^'"]{0,19})['"]""",
    re.IGNORECASE,
)

_VERSION_FILES = (".version", "version.txt", "VERSION")

_REDSCRIPT_SUFFIXES = (".reds", ".script")
_TWEAK_SUFFIXES = (".yaml", ".yml", ".json")

#: Kinds whose content is resolved by record name at load time, so a missing one can
#: leave an item in V's inventory pointing at nothing.
RECORD_KINDS = frozenset({"archive", "tweak"})

#: The frameworks that resolve those records.
FRAMEWORKS = {"archivexl": "ArchiveXL", "tweakxl": "TweakXL"}


@dataclass(frozen=True)
class ModEntry:
    """One mod, as much as can be known about it from the outside."""

    name: str
    kind: str
    version: str | None = None
    writes_persistent_state: bool | None = None
    declared: bool = False
    extends_records: bool = False
    file_count: int = 0

    @property
    def key(self) -> str:
        """What makes two installs' entries the same mod."""
        return f"{self.kind}:{normalise_name(self.name)}"

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}" if self.version else self.name

    def to_json(self) -> dict:
        data: dict = {"name": self.name, "kind": self.kind}
        if self.version:
            data["version"] = self.version
        if self.writes_persistent_state is not None:
            data["writesPersistentState"] = self.writes_persistent_state
        if self.declared:
            data["declared"] = True
        if self.extends_records:
            data["extendsRecords"] = True
        if self.file_count:
            data["files"] = self.file_count
        return data

    @classmethod
    def from_json(cls, data: dict) -> "ModEntry":
        return cls(
            name=str(data.get("name") or "unnamed"),
            kind=str(data.get("kind") or "unknown"),
            version=(str(data["version"]) if data.get("version") else None),
            writes_persistent_state=data.get("writesPersistentState"),
            declared=bool(data.get("declared")),
            extends_records=bool(data.get("extendsRecords")),
            file_count=int(data.get("files") or 0),
        )


@dataclass
class ModSet:
    """Everything installed on one machine, plus what the game itself provides."""

    entries: list[ModEntry] = field(default_factory=list)
    phantom_liberty: bool = False

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def by_key(self) -> dict[str, ModEntry]:
        return {entry.key: entry for entry in self.entries}

    def of_kind(self, kind: str) -> list[ModEntry]:
        return [entry for entry in self.entries if entry.kind == kind]

    def has_framework(self, which: str) -> bool:
        """Whether ArchiveXL or TweakXL is installed, by either of its two shapes."""
        wanted = which.lower()
        for entry in self.entries:
            if normalise_name(entry.name) == wanted:
                return True
        return False

    def to_json(self) -> dict:
        return {
            "phantomLiberty": self.phantom_liberty,
            "mods": [entry.to_json() for entry in self.entries],
        }

    @classmethod
    def from_json(cls, data: dict) -> "ModSet":
        return cls(
            entries=[ModEntry.from_json(m) for m in data.get("mods") or []],
            phantom_liberty=bool(data.get("phantomLiberty")),
        )


def normalise_name(name: str) -> str:
    """Fold a mod name so two installs agree on it.

    Folder names arrive with the version baked in often enough that ignoring it would
    report one mod as both missing and extra on a version bump.
    """
    base, _ = split_version(name)
    return re.sub(r"[^a-z0-9]", "", base.lower())


def split_version(name: str) -> tuple[str, str | None]:
    """Separate a trailing version from a folder name."""
    match = NAME_VERSION.match(name.strip())
    if not match:
        return name.strip(), None
    base = match.group("base").strip()
    return (base or name.strip()), match.group("version")


def _interesting(path: Path) -> bool:
    return path.name not in IGNORED_NAMES and not path.name.startswith(".")


def _children(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    try:
        return sorted(p for p in root.iterdir() if _interesting(p))
    except OSError:
        return []


def _declaration(folder: Path) -> dict | None:
    """An `engram.json` a mod author left for us."""
    item = folder / DECLARATION
    if not item.is_file():
        return None
    try:
        data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _version_file(folder: Path) -> str | None:
    for name in _VERSION_FILES:
        item = folder / name
        if not item.is_file():
            continue
        try:
            text = item.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        first = text.splitlines()[0].strip() if text else ""
        if first and len(first) <= 40:
            return first
    return None


def _count_files(folder: Path) -> int:
    try:
        return sum(1 for p in folder.rglob("*") if p.is_file())
    except OSError:
        return 0


def _text_of(paths: list[Path], budget: int = 2_000_000) -> str:
    """Read a bounded amount of source, enough to spot a declaration."""
    chunks = []
    remaining = budget
    for path in paths:
        if remaining <= 0:
            break
        try:
            data = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunks.append(data[:remaining])
        remaining -= len(data)
    return "\n".join(chunks)


def _sources(folder: Path, suffixes: tuple[str, ...], cap: int = 400) -> list[Path]:
    out = []
    try:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes:
                out.append(path)
                if len(out) >= cap:
                    break
    except OSError:
        pass
    return out


def _apply_declaration(entry: ModEntry, declared: dict | None) -> ModEntry:
    if not declared:
        return entry
    name = str(declared.get("name") or entry.name)
    version = declared.get("version")
    persistent = declared.get("writesPersistentState")
    return ModEntry(
        name=name,
        kind=entry.kind,
        version=str(version) if version else entry.version,
        writes_persistent_state=(
            bool(persistent) if persistent is not None else entry.writes_persistent_state
        ),
        declared=True,
        extends_records=entry.extends_records,
        file_count=entry.file_count,
    )


def _scan_redscript(root: Path) -> list[ModEntry]:
    """`r6/scripts`: redscript mods, which are the ones that can hold save state."""
    out = []
    loose: list[Path] = []
    for child in _children(root):
        if child.is_file():
            if child.suffix.lower() in _REDSCRIPT_SUFFIXES:
                loose.append(child)
            continue
        sources = _sources(child, _REDSCRIPT_SUFFIXES)
        base, name_version = split_version(child.name)
        entry = ModEntry(
            name=child.name,
            kind="redscript",
            version=_version_file(child) or name_version,
            writes_persistent_state=bool(PERSISTENT.search(_text_of(sources))),
            file_count=len(sources) or _count_files(child),
        )
        out.append(_apply_declaration(entry, _declaration(child)))

    for item in loose:
        out.append(
            ModEntry(
                name=item.name,
                kind="redscript",
                writes_persistent_state=bool(PERSISTENT.search(_text_of([item]))),
                file_count=1,
            )
        )
    return out


def _scan_red4ext(root: Path) -> list[ModEntry]:
    """`red4ext/plugins`: native plugins, versioned by their own DLL resource."""
    out = []
    for child in _children(root):
        if child.is_file():
            if child.suffix.lower() != ".dll":
                continue
            info = read_version(child)
            out.append(
                ModEntry(
                    name=child.stem,
                    kind="red4ext",
                    version=info.best if info else None,
                    file_count=1,
                )
            )
            continue

        dlls = sorted(child.rglob("*.dll"))
        if not dlls:
            continue
        preferred = next(
            (d for d in dlls if normalise_name(d.stem) == normalise_name(child.name)),
            dlls[0],
        )
        info = read_version(preferred)
        base, name_version = split_version(child.name)
        has_records = any(
            True for _ in child.rglob("*.xl")
        ) or any(True for _ in child.rglob("*.archive"))
        entry = ModEntry(
            name=child.name,
            kind="red4ext",
            version=(info.best if info else None) or _version_file(child) or name_version,
            extends_records=has_records,
            file_count=_count_files(child),
        )
        out.append(_apply_declaration(entry, _declaration(child)))
    return out


def _archive_base(name: str) -> str:
    """The shared stem of `Thing.archive` and `Thing.archive.xl`."""
    lowered = name.lower()
    for suffix in (".archive.xl", ".archive", ".xl"):
        if lowered.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _scan_archive(root: Path) -> list[ModEntry]:
    """`archive/pc/mod`: resource archives, and the ArchiveXL files that extend records."""
    groups: dict[str, dict] = {}
    for child in _children(root):
        if child.is_dir():
            continue
        lowered = child.name.lower()
        if not (lowered.endswith(".archive") or lowered.endswith(".xl")):
            continue
        base = _archive_base(child.name)
        group = groups.setdefault(base, {"files": 0, "xl": False})
        group["files"] += 1
        if lowered.endswith(".xl"):
            group["xl"] = True

    out = []
    for base in sorted(groups):
        group = groups[base]
        out.append(
            ModEntry(
                name=base,
                kind="archive",
                writes_persistent_state=False,
                extends_records=bool(group["xl"]),
                file_count=int(group["files"]),
            )
        )
    return out


def _scan_tweaks(root: Path) -> list[ModEntry]:
    """`r6/tweaks`: TweakXL records, which inventory items can point at."""
    out = []
    for child in _children(root):
        if child.is_file():
            if child.suffix.lower() not in _TWEAK_SUFFIXES:
                continue
            out.append(
                ModEntry(
                    name=child.stem,
                    kind="tweak",
                    writes_persistent_state=False,
                    extends_records=True,
                    file_count=1,
                )
            )
            continue
        base, name_version = split_version(child.name)
        entry = ModEntry(
            name=child.name,
            kind="tweak",
            version=_version_file(child) or name_version,
            writes_persistent_state=False,
            extends_records=True,
            file_count=_count_files(child),
        )
        out.append(_apply_declaration(entry, _declaration(child)))
    return out


def _scan_redmod(root: Path) -> list[ModEntry]:
    """`mods`: REDmod packages, which publish a name and a version in `info.json`."""
    out = []
    for child in _children(root):
        if not child.is_dir():
            continue
        info_path = child / "info.json"
        name, version = child.name, None
        if info_path.is_file():
            try:
                info = json.loads(info_path.read_text(encoding="utf-8", errors="replace"))
                name = str(info.get("name") or child.name)
                version = info.get("version")
            except (OSError, json.JSONDecodeError):
                pass
        if version is None:
            _, version = split_version(child.name)
        entry = ModEntry(
            name=name,
            kind="redmod",
            version=str(version) if version else None,
            extends_records=any(True for _ in child.rglob("*.archive")),
            file_count=_count_files(child),
        )
        out.append(_apply_declaration(entry, _declaration(child)))
    return out


def _scan_cet(root: Path) -> list[ModEntry]:
    """CET mods, which keep their own state in their own folder rather than the save."""
    out = []
    for child in _children(root):
        if not child.is_dir():
            continue
        version = _version_file(child)
        if not version:
            match = LUA_VERSION.search(_text_of(_sources(child, (".lua",), cap=40)))
            version = match.group("version") if match else None
        if not version:
            _, version = split_version(child.name)
        entry = ModEntry(
            name=child.name,
            kind="cet",
            version=version,
            writes_persistent_state=False,
            file_count=_count_files(child),
        )
        out.append(_apply_declaration(entry, _declaration(child)))
    return out


_SCANNERS = {
    "redscript": _scan_redscript,
    "red4ext": _scan_red4ext,
    "archive": _scan_archive,
    "redmod": _scan_redmod,
    "cet": _scan_cet,
}


def scan(game: GameInstall) -> ModSet:
    """Fingerprint one install."""
    entries: list[ModEntry] = []
    roots = game.mod_roots
    for kind, scanner in _SCANNERS.items():
        root = roots.get(kind)
        if root is None:
            continue
        entries.extend(scanner(root))
    entries.extend(_scan_tweaks(game.path / "r6" / "tweaks"))

    entries.sort(key=lambda e: (e.kind, e.name.lower()))
    return ModSet(entries=entries, phantom_liberty=game.has_phantom_liberty)
