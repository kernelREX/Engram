"""The block and warn rules, which are the part of Engram that has to be right.

Each test here is one of the ways a travelling save goes wrong on the receiving machine.
"""

from __future__ import annotations

from engram import compare
from engram.compare import BLOCK, NOTE, WARN, Report, build_report
from engram.mods import ModEntry, ModSet
from engram.running import Running

from conftest import build_game, metadata_document, write_save


def codes_of(report: Report, severity: str) -> set[str]:
    return {f.code for f in report.of(severity)}


def save_meta(**overrides) -> dict:
    return metadata_document(**overrides)["Data"]["metadata"]


def mod_set(*entries: ModEntry, phantom_liberty: bool = True) -> ModSet:
    return ModSet(entries=list(entries), phantom_liberty=phantom_liberty)


def redscript(name, version=None, persistent=False):
    return ModEntry(
        name=name, kind="redscript", version=version, writes_persistent_state=persistent
    )


def archive(name, records=False):
    return ModEntry(
        name=name, kind="archive", extends_records=records, writes_persistent_state=False
    )


def plugin(name, version=None):
    return ModEntry(name=name, kind="red4ext", version=version)


def report_for(sender: ModSet, receiver: ModSet, **meta) -> Report:
    return build_report(
        slot_meta=save_meta(**meta),
        sender_mods=sender,
        receiver_mods=receiver,
        receiver_game_version=meta.get("gameVersion", 2310),
    )


# --------------------------------------------------------------- the three failure modes


def test_a_missing_record_mod_blocks():
    """Records that no longer resolve are the failure most likely to refuse to load."""
    sender = mod_set(archive("Atlas", records=True), plugin("ArchiveXL", "1.28.6"))
    receiver = mod_set(plugin("ArchiveXL", "1.28.6"))
    report = report_for(sender, receiver)
    assert "missing-records" in codes_of(report, BLOCK)
    assert report.blocked


def test_a_missing_plain_archive_only_notes():
    sender = mod_set(archive("HD Reworked Project", records=False))
    report = report_for(sender, mod_set())
    assert not report.blocked
    assert "missing-other" in codes_of(report, NOTE)


def test_a_missing_redscript_mod_warns_rather_than_blocks():
    """Orphaned state sits unread, which is usually harmless."""
    sender = mod_set(redscript("Cyberbane", "1.4.5", persistent=True))
    report = report_for(sender, mod_set())
    assert not report.blocked
    assert "missing-redscript" in codes_of(report, WARN)


def test_a_version_difference_in_a_persistent_mod_warns_loudly():
    """The silent failure: the save opens and the mod's progress is gone."""
    sender = mod_set(redscript("Cyberbane", "1.4.5", persistent=True))
    receiver = mod_set(redscript("Cyberbane", "1.5.0", persistent=True))
    report = report_for(sender, receiver)
    warning = next(f for f in report.warnings if f.code == "persistent-version")
    assert "1.4.5" in warning.items[0] and "1.5.0" in warning.items[0]
    assert not report.blocked


def test_a_version_difference_in_a_stateless_mod_is_only_a_note():
    sender = mod_set(redscript("Byakko", "1.0.0", persistent=False))
    receiver = mod_set(redscript("Byakko", "1.1.0", persistent=False))
    report = report_for(sender, receiver)
    assert "version-differs" in codes_of(report, NOTE)
    assert not report.warnings


def test_a_persistent_mod_with_no_version_on_either_side_is_flagged():
    sender = mod_set(redscript("Cyberbane", None, persistent=True))
    receiver = mod_set(redscript("Cyberbane", None, persistent=True))
    report = report_for(sender, receiver)
    assert "version-unknown" in codes_of(report, NOTE)


# ------------------------------------------------------------------------- frameworks


def test_a_missing_framework_blocks_when_the_sender_has_it():
    sender = mod_set(plugin("ArchiveXL", "1.28.6"), plugin("TweakXL", "1.12.0"))
    report = report_for(sender, mod_set())
    assert {"missing-archivexl", "missing-tweakxl"} <= codes_of(report, BLOCK)


def test_no_framework_complaint_when_neither_side_has_it():
    report = report_for(mod_set(), mod_set())
    assert not report.blocked


# ------------------------------------------------------------------- the save itself


def test_a_newer_save_blocks_on_an_older_game():
    report = build_report(
        slot_meta=save_meta(gameVersion=2500, buildPatch="2.5"),
        sender_mods=mod_set(),
        receiver_mods=mod_set(),
        receiver_game_version=2310,
    )
    assert "downgrade" in codes_of(report, BLOCK)


def test_an_older_save_on_a_newer_game_is_fine():
    report = build_report(
        slot_meta=save_meta(gameVersion=2310, buildPatch="2.31"),
        sender_mods=mod_set(),
        receiver_mods=mod_set(),
        receiver_game_version=2500,
    )
    assert not report.blocked
    assert "older-save" in codes_of(report, NOTE)


def test_no_saves_here_yet_means_no_version_comparison():
    report = build_report(
        slot_meta=save_meta(gameVersion=2310),
        sender_mods=mod_set(),
        receiver_mods=mod_set(),
        receiver_game_version=None,
    )
    assert "no-local-version" in codes_of(report, NOTE)
    assert not report.blocked


def test_phantom_liberty_is_required_by_the_games_own_test():
    report = build_report(
        slot_meta=save_meta(additionalContentIds=["EP1"]),
        sender_mods=mod_set(phantom_liberty=True),
        receiver_mods=mod_set(phantom_liberty=False),
        receiver_game_version=2310,
    )
    assert "missing-phantom-liberty" in codes_of(report, BLOCK)


def test_a_base_game_save_does_not_need_phantom_liberty():
    report = build_report(
        slot_meta=save_meta(additionalContentIds=[]),
        sender_mods=mod_set(phantom_liberty=True),
        receiver_mods=mod_set(phantom_liberty=False),
        receiver_game_version=2310,
    )
    assert not report.blocked


def test_the_modded_flag_is_reported_but_never_changed():
    report = report_for(mod_set(), mod_set(), isModded=True)
    note = next(f for f in report.notes if f.code == "modded-flag")
    assert "Achievements" in note.detail


# --------------------------------------------------------------------- the environment


def test_the_game_being_open_blocks():
    report = Report()
    compare.check_environment(Running(game=("Cyberpunk2077.exe",)), report)
    assert "game-running" in codes_of(report, BLOCK)


def test_steam_being_open_warns_about_the_cloud():
    report = Report()
    compare.check_environment(Running(steam=("steam.exe",)), report)
    warning = next(f for f in report.warnings if f.code == "steam-running")
    assert "Cloud" in warning.summary or "cloud" in warning.detail


def test_an_unavailable_process_list_is_a_note_not_a_failure():
    report = Report()
    compare.check_environment(Running(checked=False), report)
    assert "no-process-check" in codes_of(report, NOTE)


# --------------------------------------------------------------------------- the rest


def test_extra_mods_here_are_only_noted():
    report = report_for(mod_set(), mod_set(redscript("Byakko", "1.0.0")))
    assert "extra-here" in codes_of(report, NOTE)
    assert not report.blocked


def test_a_version_in_the_folder_name_is_not_a_different_mod():
    """Vortex leaves the version in the folder name, which must not read as two mods."""
    sender = mod_set(redscript("Native Interactions Framework 1.05b", "1.05b"))
    receiver = mod_set(redscript("Native Interactions Framework 1.06", "1.06"))
    report = report_for(sender, receiver)
    assert "missing-redscript" not in codes_of(report, WARN)
    assert "extra-here" not in codes_of(report, NOTE)
    assert "version-differs" in codes_of(report, NOTE)


def test_an_identical_machine_reports_nothing_that_matters(tmp_path):
    from engram import mods as modscan

    game = build_game(
        tmp_path / "game",
        redscript={"Cyberbane": {"persistent": True, "version": "1.4.5"}},
        plugins={"ArchiveXL": "1.28.6"},
    )
    found = modscan.scan(game)
    report = report_for(found, found)
    assert not report.blocked
    assert not report.warnings


def test_the_summary_leads_with_the_worst_thing():
    blocked = report_for(mod_set(archive("Atlas", records=True)), mod_set())
    assert "stop this save loading" in compare.summarise(blocked)

    warned = report_for(mod_set(redscript("Cyberbane", "1.4.5")), mod_set())
    assert "warning" in compare.summarise(warned)

    assert compare.summarise(Report()) == "this save should load cleanly"


def test_local_game_version_comes_from_the_newest_save(save_dir):
    write_save(save_dir, "ManualSave-1", gameVersion=2310)
    write_save(
        save_dir,
        "ManualSave-2",
        gameVersion=2500,
        timestampString="10:00:00, 3.08.2026",
    )
    assert compare.local_game_version(save_dir) == 2500


def test_local_game_version_is_unknown_with_no_saves(save_dir):
    assert compare.local_game_version(save_dir) is None
