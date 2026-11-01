"""Fingerprinting an install, which is where the comparison gets its facts."""

from __future__ import annotations

from engram import mods
from engram.mods import ModSet, normalise_name, split_version

from conftest import build_game


def names_of(found: ModSet, kind: str) -> list[str]:
    return [entry.name for entry in found.of_kind(kind)]


def entry(found: ModSet, kind: str, name: str):
    return next(e for e in found.of_kind(kind) if e.name == name)


def test_every_kind_of_mod_is_found(game):
    found = mods.scan(game)
    assert names_of(found, "redscript") == ["Byakko", "Cyberbane"]
    assert names_of(found, "red4ext") == ["ArchiveXL", "TweakXL"]
    assert names_of(found, "tweak") == ["VegaCPMods"]
    assert names_of(found, "cet") == ["nativeSettings"]
    assert found.phantom_liberty


def test_a_mod_declaring_persistent_fields_is_spotted(game):
    """This is the mod whose state vanishes on a version change."""
    found = mods.scan(game)
    assert entry(found, "redscript", "Cyberbane").writes_persistent_state is True
    assert entry(found, "redscript", "Byakko").writes_persistent_state is False


def test_a_plugin_version_is_read(game):
    found = mods.scan(game)
    assert entry(found, "red4ext", "ArchiveXL").version == "1.28.6"


def test_the_frameworks_are_recognised(game):
    found = mods.scan(game)
    assert found.has_framework("archivexl")
    assert found.has_framework("tweakxl")
    assert not found.has_framework("codeware")


def test_an_archive_and_its_xl_file_are_one_mod(game):
    found = mods.scan(game)
    names = names_of(found, "archive")
    assert names == ["Atlas", "HD Reworked Project"]
    assert entry(found, "archive", "Atlas").extends_records is True
    assert entry(found, "archive", "Atlas").file_count == 2
    assert entry(found, "archive", "HD Reworked Project").extends_records is False


def test_tweaks_always_count_as_records(game):
    assert entry(mods.scan(game), "tweak", "VegaCPMods").extends_records is True


def test_a_cet_mod_version_comes_out_of_its_lua(game):
    assert entry(mods.scan(game), "cet", "nativeSettings").version == "1.96"


def test_a_redmod_version_comes_out_of_its_info_file(tmp_path):
    game = build_game(tmp_path / "game", redmods={"ArasakaTower": "2.1.0"})
    found = mods.scan(game)
    assert entry(found, "redmod", "ArasakaTower").version == "2.1.0"


def test_bookkeeping_folders_are_not_mods(tmp_path):
    game = build_game(tmp_path / "game", redscript={"Real": {}})
    (game.path / "r6" / "scripts" / "__folder_managed_by_vortex").write_text("x")
    (game.path / "r6" / "scripts" / ".gitkeep").write_text("x")
    assert names_of(mods.scan(game), "redscript") == ["Real"]


def test_an_author_declaration_wins_over_every_guess(tmp_path):
    game = build_game(
        tmp_path / "game",
        redscript={
            "SomeMod": {
                "persistent": False,
                "version": "0.1.0",
                "declare": {
                    "name": "Some Mod",
                    "version": "2.0.0",
                    "writesPersistentState": True,
                },
            }
        },
    )
    found = entry(mods.scan(game), "redscript", "Some Mod")
    assert found.version == "2.0.0"
    assert found.writes_persistent_state is True
    assert found.declared is True


def test_an_empty_install_is_an_empty_set(tmp_path):
    game = build_game(tmp_path / "game", phantom_liberty=False)
    found = mods.scan(game)
    assert len(found) == 0
    assert not found.phantom_liberty


def test_a_game_folder_with_nothing_in_it_does_not_raise(tmp_path):
    from engram.paths import GameInstall

    found = mods.scan(GameInstall(path=tmp_path / "missing", source="test"))
    assert len(found) == 0


def test_a_version_at_the_end_of_a_folder_name_is_separated():
    assert split_version("Native Interactions Framework 1.05b") == (
        "Native Interactions Framework",
        "1.05b",
    )
    assert split_version("EquipmentEx") == ("EquipmentEx", None)
    assert split_version("HD Reworked Project v1.2") == ("HD Reworked Project", "1.2")


def test_names_fold_so_two_machines_agree():
    assert normalise_name("Native Interactions Framework 1.05b") == normalise_name(
        "native-interactions-framework 1.06"
    )
    assert normalise_name("Cyberbane") != normalise_name("Cyberware")


def test_entries_survive_a_trip_through_the_manifest(game):
    found = mods.scan(game)
    restored = ModSet.from_json(found.to_json())
    assert len(restored) == len(found)
    assert restored.phantom_liberty == found.phantom_liberty
    assert {e.key for e in restored} == {e.key for e in found}
    assert entry(restored, "redscript", "Cyberbane").writes_persistent_state is True
    assert entry(restored, "archive", "Atlas").extends_records is True


def test_scanning_is_quick_enough_to_run_before_every_share(game):
    import time

    start = time.perf_counter()
    mods.scan(game)
    assert time.perf_counter() - start < 5.0
