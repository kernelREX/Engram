"""Which of the things that fight over the save folder are running right now.

Steam Cloud syncs this directory. If Steam is running when a save is written into it, the
cloud copy can win and the import disappears a few seconds after it worked, which is a
very confusing way to lose a save. The game itself holds the folder open and writes its own
saves over the top.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

GAME_PROCESSES = ("Cyberpunk2077.exe", "REDprelauncher.exe", "REDlauncher.exe")
STEAM_PROCESSES = ("steam.exe",)
OTHER_LAUNCHERS = ("GalaxyClient.exe", "EpicGamesLauncher.exe")

_TIMEOUT = 10


@dataclass(frozen=True)
class Running:
    """What was found running, by the name of the process."""

    game: tuple[str, ...] = ()
    steam: tuple[str, ...] = ()
    launchers: tuple[str, ...] = ()
    checked: bool = True

    @property
    def game_is_up(self) -> bool:
        return bool(self.game)

    @property
    def steam_is_up(self) -> bool:
        return bool(self.steam)


def process_names() -> set[str] | None:
    """Every running process name, lowercased, or None if we could not look."""
    if sys.platform != "win32":
        return None
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    names = set()
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        names.add(line.split('","', 1)[0].lstrip('"').lower())
    return names or None


def check() -> Running:
    """Look once, and report what is up."""
    names = process_names()
    if names is None:
        return Running(checked=False)
    found = {}
    for label, wanted in (
        ("game", GAME_PROCESSES),
        ("steam", STEAM_PROCESSES),
        ("launchers", OTHER_LAUNCHERS),
    ):
        found[label] = tuple(p for p in wanted if p.lower() in names)
    return Running(
        game=found["game"],
        steam=found["steam"],
        launchers=found["launchers"],
        checked=True,
    )
