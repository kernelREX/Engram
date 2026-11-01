"""Compile the mod's redscript without starting Cyberpunk.

A redscript file that does not compile does not fail quietly. The game refuses to build
any script, starts with every mod disabled, and says so in a log the player has to go
looking for. On a heavily modded install that is an alarming way to find out about a typo,
so this runs the game's own compiler, `engine/tools/scc.exe`, over the same inputs the game
would use and reports what it says.

The inputs matter. The game compiles `r6/scripts` and also the redscript that RED4ext
plugins ship beside their DLLs, which is where ArchiveXL, Codeware and TweakXL define the
things half the mods on a machine depend on. Compiling `r6/scripts` alone reports those
mods as broken when they are fine.

Nothing here writes into the game. The compiled output goes to a temporary directory and
is thrown away.

    python tools/check_redscript.py
    python tools/check_redscript.py --game-dir "D:/SteamLibrary/steamapps/common/Cyberpunk 2077"
    python tools/check_redscript.py --only Engram
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engram.paths import LocationError, find_game_dir  # noqa: E402

SCC = Path("engine") / "tools" / "scc.exe"
SCRIPTS = Path("r6") / "scripts"
CACHE = Path("r6") / "cache" / "final.redscripts"

#: Where RED4ext plugins keep the redscript they ship, relative to a plugin's folder.
PLUGIN_SCRIPT_DIRS = ("Scripts", "redscript", "scripts", "")

_ERROR = re.compile(r"^\[ERROR[^\]]*\]\s*(?:\[(?P<kind>[A-Z_]+)\]\s*)?(?P<rest>.*)$")


def plugin_scripts(game_dir: Path) -> list[Path]:
    """Every .reds a RED4ext plugin ships, the way the game collects them."""
    root = game_dir / "red4ext" / "plugins"
    if not root.is_dir():
        return []

    found: list[Path] = []
    for plugin in sorted(p for p in root.iterdir() if p.is_dir()):
        for name in PLUGIN_SCRIPT_DIRS:
            folder = plugin / name if name else plugin
            if not folder.is_dir():
                continue
            found.extend(sorted(folder.rglob("*.reds")))
            if name:
                break
    # A plugin with both a Scripts folder and loose files can list one twice.
    seen: set[Path] = set()
    unique = []
    for path in found:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def run(game_dir: Path, extra_scripts: list[Path]) -> tuple[int, str]:
    scc = game_dir / SCC
    if not scc.is_file():
        raise LocationError(f"no redscript compiler at {scc}")

    with tempfile.TemporaryDirectory(prefix="engram-scc-") as temporary:
        workspace = Path(temporary)
        paths_file = workspace / "paths.txt"
        paths_file.write_text(
            "\n".join(str(p) for p in extra_scripts) + "\n", encoding="utf-8"
        )

        command = [
            str(scc),
            "-compile",
            str(game_dir / SCRIPTS),
            str(game_dir / CACHE),
            "-customCacheDir",
            str(workspace),
            "-outputCacheFile",
            str(workspace / "final.redscripts"),
            "-compilePathsFile",
            str(paths_file),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
        return completed.returncode, completed.stdout + completed.stderr


def errors_in(output: str) -> list[str]:
    """The compiler reports failures in its log rather than in its exit code."""
    found = []
    lines = output.splitlines()
    for index, line in enumerate(lines):
        match = _ERROR.match(line.strip())
        if not match:
            continue
        block = [match.group("rest").strip()]
        for follow in lines[index + 1 : index + 4]:
            if follow.strip().startswith("["):
                break
            if follow.strip():
                block.append(follow.rstrip())
        found.append("\n".join(block))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game-dir", help="where Cyberpunk is installed")
    parser.add_argument(
        "--only",
        help="only fail on errors whose path contains this, so another mod's breakage "
        "does not mask ours",
    )
    args = parser.parse_args(argv)

    try:
        game = find_game_dir(args.game_dir)
    except LocationError as exc:
        print(f"check_redscript: {exc}")
        return 1

    extra = plugin_scripts(game.path)
    print(f"game        {game.path}")
    print(f"scripts     {game.path / SCRIPTS}")
    print(f"plugin reds {len(extra)} file(s) from red4ext/plugins")

    code, output = run(game.path, extra)
    failures = errors_in(output)

    if args.only:
        wanted = args.only.lower()
        failures = [f for f in failures if wanted in f.lower()]

    if not failures:
        print("\nredscript compiles cleanly")
        return 0

    print(f"\n{len(failures)} error(s):\n")
    for failure in failures:
        print(failure)
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
