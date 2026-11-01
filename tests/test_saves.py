"""Reading the save folder, and the rules about writing into it."""

from __future__ import annotations

import json

import pytest

from engram import saves
from engram.saves import SaveError

from conftest import write_save


def test_a_save_is_read_off_disk(slot):
    assert slot.folder_name == "ManualSave-1"
    assert slot.level == 60
    assert slot.life_path == "StreetKid"
    assert slot.game_version == 2310
    assert slot.build_patch == "2.31"
    assert slot.needs_phantom_liberty
    assert slot.saved_at is not None and slot.saved_at.year == 2026
    assert [f.name for f in slot.files()] == [
        "metadata.9.json",
        "sav.dat",
        "screenshot.png",
    ]


def test_saves_are_listed_newest_first(save_dir):
    write_save(save_dir, "Older", timestampString="08:00:00, 1.08.2026")
    write_save(save_dir, "Newest", timestampString="20:00:00, 5.08.2026")
    write_save(save_dir, "Middle", timestampString="12:00:00, 3.08.2026")
    assert [s.folder_name for s in saves.list_saves(save_dir)] == [
        "Newest",
        "Middle",
        "Older",
    ]


def test_things_that_are_not_saves_are_skipped(save_dir, slot):
    (save_dir / "NotASave").mkdir()
    (save_dir / "NotASave" / "readme.txt").write_text("hello", encoding="utf-8")
    (save_dir / "HalfASave").mkdir()
    (save_dir / "HalfASave" / "sav.dat").write_bytes(b"VASC")
    assert [s.folder_name for s in saves.list_saves(save_dir)] == ["ManualSave-1"]


def test_a_save_with_unreadable_metadata_is_skipped_not_fatal(save_dir, slot):
    broken = save_dir / "Broken"
    broken.mkdir()
    (broken / "sav.dat").write_bytes(b"VASC")
    (broken / "metadata.9.json").write_text("{ this is not json", encoding="utf-8")
    assert [s.folder_name for s in saves.list_saves(save_dir)] == ["ManualSave-1"]


def test_a_save_is_found_by_folder_name_or_part_of_it(save_dir, slot):
    assert saves.find_save(save_dir, "ManualSave-1").folder_name == "ManualSave-1"
    assert saves.find_save(save_dir, "manualsave-1").folder_name == "ManualSave-1"
    assert saves.find_save(save_dir, "Manual").folder_name == "ManualSave-1"


def test_an_unknown_name_lists_what_is_there(save_dir, slot):
    with pytest.raises(SaveError, match="ManualSave-1"):
        saves.find_save(save_dir, "Nonexistent")


def test_a_free_slot_name_skips_what_exists(save_dir):
    assert saves.free_slot_name(save_dir) == "EngramSave-1"
    write_save(save_dir, "EngramSave-1")
    write_save(save_dir, "EngramSave-2")
    assert saves.free_slot_name(save_dir) == "EngramSave-3"


def test_installing_a_save_writes_every_file(save_dir, slot):
    files = {name: path.read_bytes() for name, path in
             ((p.name, p) for p in slot.files())}
    written = saves.install_save(save_dir, "EngramSave-1", files)
    assert written.name == "EngramSave-1"
    assert (written / "sav.dat").read_bytes() == files["sav.dat"]
    assert (written / "screenshot.png").is_file()


def test_installing_renames_the_save_so_the_load_menu_matches(save_dir, slot):
    files = {p.name: p.read_bytes() for p in slot.files()}
    written = saves.install_save(save_dir, "EngramSave-7", files)
    document = json.loads((written / "metadata.9.json").read_text(encoding="utf-8"))
    assert document["Data"]["metadata"]["name"] == "EngramSave-7"
    assert document["Data"]["metadata"]["level"] == 60.0


def test_keeping_the_senders_name_is_possible(save_dir, slot):
    files = {p.name: p.read_bytes() for p in slot.files()}
    written = saves.install_save(
        save_dir, "EngramSave-7", files, rename_in_metadata=False
    )
    document = json.loads((written / "metadata.9.json").read_text(encoding="utf-8"))
    assert document["Data"]["metadata"]["name"] == "ManualSave-1"


def test_an_existing_slot_is_never_overwritten(save_dir, slot):
    files = {p.name: p.read_bytes() for p in slot.files()}
    with pytest.raises(SaveError, match="does not overwrite"):
        saves.install_save(save_dir, "ManualSave-1", files)
    assert json.loads(
        (save_dir / "ManualSave-1" / "metadata.9.json").read_text(encoding="utf-8")
    )["Data"]["metadata"]["name"] == "ManualSave-1"


def test_a_save_with_no_sav_file_is_refused(save_dir):
    with pytest.raises(SaveError, match="sav.dat"):
        saves.install_save(save_dir, "EngramSave-1", {"metadata.9.json": b"{}"})


def test_nothing_is_left_behind_when_a_write_fails(save_dir, slot):
    files = {p.name: p.read_bytes() for p in slot.files()}
    files["sub/dir.dat"] = b"nope"
    with pytest.raises(SaveError):
        saves.install_save(save_dir, "EngramSave-1", files)
    assert not (save_dir / "EngramSave-1").exists()
    assert not list(save_dir.glob("*.engram-incoming"))


def test_the_shared_mod_list_is_never_written(save_dir, slot):
    files = {p.name: p.read_bytes() for p in slot.files()}
    files[saves.ENABLED_MODS] = b'{"enabled_mods": ["something"]}'
    written = saves.install_save(save_dir, "EngramSave-1", files)
    assert not (written / saves.ENABLED_MODS).exists()


def test_backing_up_copies_the_whole_folder(save_dir, slot, tmp_path):
    backup = saves.back_up(slot.path, tmp_path / "backups")
    assert (backup / "sav.dat").read_bytes() == (slot.path / "sav.dat").read_bytes()
    assert (backup / "metadata.9.json").is_file()
    assert slot.path.is_dir()


def test_a_save_with_no_timestamp_still_sorts(save_dir):
    write_save(save_dir, "NoStamp", timestampString="")
    found = saves.list_saves(save_dir)
    assert found[0].folder_name == "NoStamp"
    assert found[0].sort_key > 0
