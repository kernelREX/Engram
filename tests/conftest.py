"""Fixtures that build a save folder and a mod tree on disk.

Nothing in the test suite touches the real game or the network. The fixtures write the
same file shapes Cyberpunk and the mod loaders use, which is what the scanners read, so
the tests exercise the real code paths against synthetic input.
"""

from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engram.manifest import SAV_MAGIC  # noqa: E402
from engram.paths import GameInstall  # noqa: E402
from engram.saves import read_slot  # noqa: E402


def metadata_document(**overrides) -> dict:
    """A metadata file shaped like the real thing, with the fields Engram reads."""
    metadata = {
        "name": "ManualSave-1",
        "buildPatch": "2.31",
        "gameVersion": 2310,
        "saveVersion": 269,
        "playthroughID": "6a36b2a1202a4ff2",
        "isModded": False,
        "level": 60.0,
        "streetCred": 50.0,
        "lifePath": "StreetKid",
        "difficulty": "Easy",
        "playTime": 378900.22,
        "playthroughTime": 389069.37,
        "timestampString": "19:09:31, 2.08.2026",
        "locationName": "LocKey#94156",
        "trackedQuest": "LocKey#9860",
        "additionalContentIds": ["EP1"],
        "platform": "pc",
        "isEndGameSave": False,
        "isPointOfNoReturn": False,
        "fileSize": 4096,
    }
    metadata.update(overrides)
    return {"RootType": "saveMetadataContainer", "Data": {"metadata": metadata}}


def write_save(root: Path, name: str = "ManualSave-1", size: int = 4096, **overrides):
    """Create one save folder, and return the SaveSlot for it."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    body = SAV_MAGIC + struct.pack("<I", size) + bytes((i * 7) % 251 for i in range(size))
    (folder / "sav.dat").write_bytes(body)
    (folder / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"thumbnail" * 16)
    document = metadata_document(name=overrides.pop("display_name", name), **overrides)
    (folder / "metadata.9.json").write_text(json.dumps(document, indent=4), encoding="utf-8")
    return read_slot(folder)


@pytest.fixture
def save_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "saves"
    folder.mkdir()
    (folder / "EnabledMods.json").write_text('{"enabled_mods": []}', encoding="utf-8")
    return folder


@pytest.fixture
def slot(save_dir: Path):
    return write_save(save_dir)


def build_game(
    root: Path,
    redscript: dict[str, dict] | None = None,
    archives: list[str] | None = None,
    plugins: dict[str, str] | None = None,
    tweaks: list[str] | None = None,
    cet: dict[str, str] | None = None,
    redmods: dict[str, str] | None = None,
    phantom_liberty: bool = True,
) -> GameInstall:
    """Lay out a game directory with the mod shapes the scanners look for."""
    (root / "bin" / "x64").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "x64" / "Cyberpunk2077.exe").write_bytes(b"MZ" + b"\0" * 64)
    if phantom_liberty:
        (root / "archive" / "pc" / "ep1").mkdir(parents=True, exist_ok=True)

    scripts = root / "r6" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name, options in (redscript or {}).items():
        folder = scripts / name
        folder.mkdir(parents=True, exist_ok=True)
        source = "module Test\n"
        if options.get("persistent"):
            source += "public class State {\n  persistent let counter: Int32;\n}\n"
        else:
            source += "public func Hello() {}\n"
        (folder / "main.reds").write_text(source, encoding="utf-8")
        if options.get("version"):
            (folder / ".version").write_text(str(options["version"]), encoding="utf-8")
        if options.get("declare"):
            (folder / "engram.json").write_text(
                json.dumps(options["declare"]), encoding="utf-8"
            )

    mod_archive = root / "archive" / "pc" / "mod"
    mod_archive.mkdir(parents=True, exist_ok=True)
    for name in archives or []:
        (mod_archive / name).write_bytes(b"archive")

    plugin_root = root / "red4ext" / "plugins"
    plugin_root.mkdir(parents=True, exist_ok=True)
    for name, version in (plugins or {}).items():
        folder = plugin_root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.dll").write_bytes(b"MZ" + b"\0" * 64)
        (folder / ".version").write_text(version, encoding="utf-8")

    tweak_root = root / "r6" / "tweaks"
    tweak_root.mkdir(parents=True, exist_ok=True)
    for name in tweaks or []:
        folder = tweak_root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "records.yaml").write_text("Items.Thing: {}\n", encoding="utf-8")

    cet_root = root / "bin" / "x64" / "plugins" / "cyber_engine_tweaks" / "mods"
    cet_root.mkdir(parents=True, exist_ok=True)
    for name, version in (cet or {}).items():
        folder = cet_root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "init.lua").write_text(
            f'local mod = {{}}\nmod.version = "{version}"\nreturn mod\n', encoding="utf-8"
        )

    redmod_root = root / "mods"
    redmod_root.mkdir(parents=True, exist_ok=True)
    for name, version in (redmods or {}).items():
        folder = redmod_root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "info.json").write_text(
            json.dumps({"name": name, "version": version}), encoding="utf-8"
        )

    return GameInstall(path=root, source="test")


@pytest.fixture
def game(tmp_path: Path) -> GameInstall:
    return build_game(
        tmp_path / "game",
        redscript={
            "Cyberbane": {"persistent": True, "version": "1.4.5"},
            "Byakko": {"persistent": False, "version": "1.0.0"},
        },
        archives=["HD Reworked Project.archive", "Atlas.archive", "Atlas.archive.xl"],
        plugins={"ArchiveXL": "1.28.6", "TweakXL": "1.12.0"},
        tweaks=["VegaCPMods"],
        cet={"nativeSettings": "1.96"},
    )
