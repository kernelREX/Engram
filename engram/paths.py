"""Finding the two directories everything else depends on.

Neither can be assumed. The save directory is a Windows known folder and people relocate
it. The game directory depends on the store, and a machine can carry a stale partial copy
alongside the real install, so a candidate only counts once the executable is in it.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

#: Cyberpunk 2077 on Steam.
STEAM_APP_ID = "1091500"

#: Cyberpunk 2077 in GOG's registry, including the Ultimate Edition entry.
GOG_PRODUCT_IDS = ("1423049311", "2093619782", "1844897427")

SAVE_SUBPATH = Path("CD Projekt Red") / "Cyberpunk 2077"

#: What proves a directory is a real install rather than a leftover mod folder.
GAME_MARKER = Path("bin") / "x64" / "Cyberpunk2077.exe"

_FOLDERID_SAVED_GAMES = "{4C5C32FF-BB9D-43b0-B5B4-2D72E54EAAA4}"


class LocationError(Exception):
    """A directory Engram needs could not be found."""


@dataclass(frozen=True)
class GameInstall:
    """A located game directory and what it tells us about itself."""

    path: Path
    source: str

    @property
    def has_phantom_liberty(self) -> bool:
        return (self.path / "archive" / "pc" / "ep1").is_dir()

    @property
    def mod_roots(self) -> dict[str, Path]:
        cet = self.path / "bin" / "x64" / "plugins" / "cyber_engine_tweaks" / "mods"
        return {
            "redscript": self.path / "r6" / "scripts",
            "red4ext": self.path / "red4ext" / "plugins",
            "archive": self.path / "archive" / "pc" / "mod",
            "redmod": self.path / "mods",
            "cet": cet,
        }


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


def _known_folder(folder_id: str) -> Path | None:
    """Ask Windows where a known folder actually is."""
    if sys.platform != "win32":
        return None
    try:
        guid_text = ctypes.create_unicode_buffer(folder_id)
        iid = _GUID()
        if ctypes.windll.ole32.IIDFromString(guid_text, ctypes.byref(iid)) != 0:
            return None
        out = ctypes.c_wchar_p()
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(iid), 0, None, ctypes.byref(out)
        )
        if result != 0 or not out.value:
            return None
        path = Path(out.value)
        ctypes.windll.ole32.CoTaskMemFree(out)
        return path
    except (OSError, AttributeError):
        return None


def saved_games_root() -> Path:
    """The Saved Games folder, asking Windows before falling back to the usual place."""
    known = _known_folder(_FOLDERID_SAVED_GAMES)
    if known and known.is_dir():
        return known
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    return Path(profile) / "Saved Games"


def find_save_dir(override: str | os.PathLike | None = None) -> Path:
    """Where Cyberpunk keeps its saves."""
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise LocationError(f"{path} is not a directory")
        return path
    path = saved_games_root() / SAVE_SUBPATH
    if not path.is_dir():
        raise LocationError(
            f"no save folder at {path}. Run Cyberpunk once and save, or point Engram at "
            "the folder with --save-dir."
        )
    return path


def _reg_value(root_name: str, subkey: str, name: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg
    except ImportError:
        return None
    roots = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    root = roots[root_name]
    for flag in (winreg.KEY_READ, winreg.KEY_READ | winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(root, subkey, 0, flag) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return str(value)
        except OSError:
            continue
    return None


def _steam_root() -> Path | None:
    registry_spots = (
        ("HKCU", "Software" + os.sep + "Valve" + os.sep + "Steam", "SteamPath"),
        ("HKLM", "SOFTWARE" + os.sep + "Valve" + os.sep + "Steam", "InstallPath"),
    )
    for root, sub, name in registry_spots:
        value = _reg_value(root, sub, name)
        if value and Path(value).is_dir():
            return Path(value)
    guesses = (
        Path(os.environ.get("ProgramFiles(x86)", "C:" + os.sep + "Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", "C:" + os.sep + "Program Files")),
    )
    for base in guesses:
        if (base / "Steam").is_dir():
            return base / "Steam"
    return None


def _steam_libraries(steam_root: Path) -> list[Path]:
    """Library paths from libraryfolders.vdf, the one holding the game first."""
    libraries = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return libraries
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return libraries
    blocks = re.split(r'"\d+"\s*\{', text)[1:]
    preferred: list[Path] = []
    others: list[Path] = []
    for block in blocks:
        match = re.search(r'"path"\s*"([^"]+)"', block)
        if not match:
            continue
        path = Path(match.group(1).replace("\\\\", "\\"))
        if '"' + STEAM_APP_ID + '"' in block:
            preferred.append(path)
        else:
            others.append(path)
    for path in preferred + others:
        if path not in libraries:
            libraries.append(path)
    return libraries


def _steam_candidates() -> list[tuple[Path, str]]:
    root = _steam_root()
    if root is None:
        return []
    found = []
    for library in _steam_libraries(root):
        found.append((library / "steamapps" / "common" / "Cyberpunk 2077", "Steam"))
    return found


def _gog_candidates() -> list[tuple[Path, str]]:
    found = []
    for product in GOG_PRODUCT_IDS:
        subkey = os.sep.join(["SOFTWARE", "GOG.com", "Games", product])
        value = _reg_value("HKLM", subkey, "path")
        if value:
            found.append((Path(value), "GOG"))
    return found


def _epic_candidates() -> list[tuple[Path, str]]:
    program_data = Path(os.environ.get("PROGRAMDATA", "C:" + os.sep + "ProgramData"))
    base = program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    if not base.is_dir():
        return []
    found = []
    for item in base.glob("*.item"):
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if "cyberpunk" not in str(data.get("DisplayName", "")).lower():
            continue
        location = data.get("InstallLocation")
        if location:
            found.append((Path(location), "Epic"))
    return found


def _fallback_candidates() -> list[tuple[Path, str]]:
    found = []
    for letter in "CDEFGH":
        drive = Path(letter + ":" + os.sep)
        if not drive.exists():
            continue
        found.append((drive / "GOG Games" / "Cyberpunk 2077", "guess"))
        found.append((drive / "Games" / "Cyberpunk 2077", "guess"))
        found.append(
            (drive / "SteamLibrary" / "steamapps" / "common" / "Cyberpunk 2077", "guess")
        )
    return found


def game_candidates() -> list[tuple[Path, str]]:
    """Every place worth looking, in the order worth looking."""
    seen: set[Path] = set()
    out: list[tuple[Path, str]] = []
    everywhere = (
        _steam_candidates()
        + _gog_candidates()
        + _epic_candidates()
        + _fallback_candidates()
    )
    for path, source in everywhere:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        out.append((path, source))
    return out


def find_game_dir(override: str | os.PathLike | None = None) -> GameInstall:
    """Locate the game, refusing anything without the executable in it."""
    if override:
        path = Path(override).expanduser()
        if not (path / GAME_MARKER).is_file():
            raise LocationError(
                str(path) + " does not contain " + GAME_MARKER.as_posix()
                + ", so it is not a Cyberpunk 2077 install"
            )
        return GameInstall(path=path, source="given")

    leftovers: list[Path] = []
    for path, source in game_candidates():
        if (path / GAME_MARKER).is_file():
            return GameInstall(path=path, source=source)
        if path.is_dir():
            leftovers.append(path)

    message = "could not find Cyberpunk 2077. Point Engram at it with --game-dir."
    if leftovers:
        listed = "\n  ".join(str(p) for p in leftovers[:4])
        message += (
            "\nThese folders exist but hold no game executable, so they are leftovers "
            "rather than installs:\n  " + listed
        )
    raise LocationError(message)
