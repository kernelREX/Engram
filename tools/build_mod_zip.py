"""Build the mod archive people download from Nexus.

A Nexus archive for a Cyberpunk mod mirrors the game folder. There is no wrapper
directory: the paths inside start at `r6` and `red4ext`, so Vortex and a plain extract into
the game directory both put every file where it belongs. Getting that wrong is the single
most common reason a mod does nothing after it is installed.

    python tools/build_mod_zip.py
    python tools/build_mod_zip.py --skip-check     # when there is no game to compile against

It refuses to build an archive with a stale or missing DLL, and by default it refuses to
build one whose redscript does not compile, because an archive that disables every mod on
the player's machine is worse than no archive.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engram import __version__  # noqa: E402

PLUGIN_DLL = ROOT / "native" / "build" / "Release" / "Engram.dll"
SCRIPTS = ROOT / "mod" / "r6" / "scripts" / "Engram"
LICENSE = ROOT / "LICENSE"

#: Where each file lands inside the archive, which is where it lands in the game folder.
PLUGIN_DIR = "red4ext/plugins/Engram"
SCRIPT_DIR = "r6/scripts/Engram"

README = """# Engram

Move a Cyberpunk 2077 save to another PC by reading a code out loud.

Open the main menu or the pause menu and pick Engram, next to Load Game.

## Using it

Open the main menu or the pause menu and pick Engram, next to Load Game.

Share a save and you get a code to read out. Receive with a code and you type in
the one somebody read to you. Both sides are shown the list of mods the save was
made with before anything happens.

## Installing

Extract into your Cyberpunk 2077 folder, the one with bin, r6 and archive in it.
Vortex and Mod Organizer handle this archive as it is.

You need RED4ext and Codeware installed. Both are on Nexus, and most modded
installs already have them.

## Removing

Delete these two folders:

    red4ext/plugins/Engram
    r6/scripts/Engram

## What it does with your save

Your save is encrypted on your machine before it goes anywhere. The key comes
from the last part of the code, which is generated on your PC and never
uploaded. Lose the code and the save cannot be recovered, which is the point of
a code. Shared files stop working after 72 hours.

A save from a stranger is a binary going into the game's own loader. Engram
checks it against the hashes the sender recorded, but it cannot tell you whether
somebody meant well. Take codes from people you know.

## Source

https://github.com/tfthushaar/Engram
"""


def staleness(dll: Path, sources: list[Path]) -> list[Path]:
    """Source files newer than the built DLL."""
    if not dll.is_file():
        return sources
    built = dll.stat().st_mtime
    return [s for s in sources if s.stat().st_mtime > built]


def installed_in_game() -> bool:
    """Whether the mod's scripts are in the game folder for the compile check to see.

    The compiler is pointed at the game's own r6/scripts. If the mod is not deployed there,
    `--only Engram` finds no Engram errors and reports success without having checked
    anything, which is a false pass worth refusing.
    """
    sys.path.insert(0, str(ROOT))
    from engram.paths import LocationError, find_game_dir

    try:
        game = find_game_dir()
    except LocationError:
        return False
    return any((game.path / "r6" / "scripts" / "Engram").glob("*.reds"))


def check_redscript() -> bool:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_redscript.py"), "--only", "Engram"],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(completed.stdout)
    if completed.returncode != 0:
        sys.stdout.write(completed.stderr)
    return completed.returncode == 0


def build(out_dir: Path, skip_check: bool) -> Path:
    scripts = sorted(SCRIPTS.glob("*.reds"))
    if not scripts:
        raise SystemExit(f"no redscript in {SCRIPTS}")
    if not PLUGIN_DLL.is_file():
        raise SystemExit(
            f"no plugin at {PLUGIN_DLL}\n"
            "Build it first:\n"
            "  cmake --build native/build --config Release"
        )

    native_sources = sorted((ROOT / "native" / "src").rglob("*"))
    stale = staleness(PLUGIN_DLL, [p for p in native_sources if p.is_file()])
    if stale:
        names = ", ".join(p.name for p in stale[:4])
        raise SystemExit(
            f"the plugin is older than its sources ({names}). Rebuild before packaging."
        )

    if skip_check:
        print("skipping the redscript check")
    elif not installed_in_game():
        raise SystemExit(
            "the mod is not deployed in the game folder, so compiling against it would "
            "check nothing and pass anyway. Deploy it first:\n"
            "  cmake --install native/build --config Release\n"
            "or pass --skip-check if you know there is nothing to check against."
        )
    elif not check_redscript():
        raise SystemExit(
            "the redscript does not compile, so this archive would disable every mod on "
            "the player's machine. Fix it, or pass --skip-check if there is no game here."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"Engram-{__version__}.zip"

    # No directory entries, forward slashes, deflate: the same shape as every other mod
    # archive, so the tools people already use handle it without surprises.
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for script in scripts:
            archive.write(script, f"{SCRIPT_DIR}/{script.name}")
        archive.write(PLUGIN_DLL, f"{PLUGIN_DIR}/Engram.dll")
        archive.write(LICENSE, f"{PLUGIN_DIR}/LICENSE")
        archive.writestr(f"{PLUGIN_DIR}/readme.md", README)

    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "dist"), help="where to write it")
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="do not compile the redscript first, for machines with no game installed",
    )
    args = parser.parse_args(argv)

    target = build(Path(args.out), args.skip_check)

    with zipfile.ZipFile(target) as archive:
        entries = archive.infolist()

    print(f"\n{target}")
    print(f"{target.stat().st_size / 1024:.0f} KB, {len(entries)} file(s)\n")
    for entry in entries:
        print(f"{entry.file_size:>9}  {entry.filename}")

    roots = sorted({e.filename.split("/")[0] for e in entries})
    print(f"\nextracts into the game folder as: {', '.join(roots)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
