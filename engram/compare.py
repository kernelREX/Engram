"""Deciding what the receiver is told before a single byte is written.

Three ways a travelling save goes wrong, worst last:

1. The receiver is missing a mod the sender had. The orphaned state sits unread, which is
   usually harmless, so this is a warning.
2. The receiver has the same mod at a different version. If the mod changed its persistent
   field layout between those versions, the game silently drops that class's data on load.
   The save opens, and everything that mod was tracking is gone. That presents to the
   player as a brand new playthrough, so a version difference in a mod that declares
   persistent state is the loudest warning here.
3. The receiver is missing ArchiveXL or TweakXL content whose records are in V's inventory.
   Those records no longer resolve, and this is the one most likely to refuse to load at
   all, so it blocks.

Plus the three that have nothing to do with mods and refuse outright: a save from a newer
game than the receiver runs, a Phantom Liberty save without Phantom Liberty, and the game
being open over the folder we are about to write into.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .mods import ModEntry, ModSet, normalise_name
from .running import Running
from .saves import SaveSlot, list_saves

BLOCK = "block"
WARN = "warn"
NOTE = "note"

_RANK = {BLOCK: 2, WARN: 1, NOTE: 0}


@dataclass(frozen=True)
class Finding:
    """One thing the receiver should know, and how strongly."""

    severity: str
    code: str
    summary: str
    detail: str = ""
    items: tuple[str, ...] = ()

    @property
    def rank(self) -> int:
        return _RANK[self.severity]


@dataclass
class Report:
    """Everything worth saying about installing this save here."""

    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        severity: str,
        code: str,
        summary: str,
        detail: str = "",
        items: list[str] | tuple[str, ...] = (),
    ) -> None:
        self.findings.append(
            Finding(
                severity=severity,
                code=code,
                summary=summary,
                detail=detail,
                items=tuple(items),
            )
        )

    def of(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def blocks(self) -> list[Finding]:
        return self.of(BLOCK)

    @property
    def warnings(self) -> list[Finding]:
        return self.of(WARN)

    @property
    def notes(self) -> list[Finding]:
        return self.of(NOTE)

    @property
    def blocked(self) -> bool:
        return bool(self.blocks)

    def sorted(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: -f.rank)


def local_game_version(save_dir: Path) -> int | None:
    """What the receiver's game writes, taken from their own newest save.

    The executable's version resource does not track the patch number people talk about,
    and the receiver may be mid update, so their own saves are the honest answer. A
    machine with no saves yet gets no comparison rather than a wrong one.
    """
    versions = [slot.game_version for slot in list_saves(save_dir) if slot.game_version]
    return max(versions) if versions else None


def _label(entry: ModEntry) -> str:
    return f"{entry.name} ({entry.kind}{', ' + entry.version if entry.version else ''})"


def _versions_differ(a: ModEntry, b: ModEntry) -> bool:
    if not a.version or not b.version:
        return False
    return a.version.strip().lower() != b.version.strip().lower()


def compare_mods(sender: ModSet, receiver: ModSet, report: Report) -> None:
    """Classify the two mod lists into missing here, extra here, and version differs."""
    mine = receiver.by_key
    theirs = sender.by_key

    missing_records: list[str] = []
    missing_redscript: list[str] = []
    missing_other: list[str] = []
    persistent_mismatch: list[str] = []
    version_mismatch: list[str] = []
    unknown_versions: list[str] = []

    for key, entry in theirs.items():
        here = mine.get(key)
        if here is None:
            if entry.extends_records:
                missing_records.append(_label(entry))
            elif entry.kind == "redscript":
                missing_redscript.append(_label(entry))
            else:
                missing_other.append(_label(entry))
            continue

        if _versions_differ(entry, here):
            line = f"{entry.name}: they have {entry.version}, you have {here.version}"
            if entry.writes_persistent_state or here.writes_persistent_state:
                persistent_mismatch.append(line)
            else:
                version_mismatch.append(line)
        elif (entry.writes_persistent_state or here.writes_persistent_state) and not (
            entry.version and here.version
        ):
            unknown_versions.append(entry.name)

    extra = [_label(e) for key, e in mine.items() if key not in theirs]

    if missing_records:
        report.add(
            BLOCK,
            "missing-records",
            f"{len(missing_records)} mod(s) that add records are not installed here",
            "The save can refer to items, vehicles and clothing from these by record "
            "name. Those names will not resolve on this machine, which is the failure "
            "most likely to stop the save loading at all. Install them, or share with "
            "--force if you know the save does not use them.",
            missing_records,
        )

    for framework in ("archivexl", "tweakxl"):
        sender_has = sender.has_framework(framework)
        if sender_has and not receiver.has_framework(framework):
            proper = "ArchiveXL" if framework == "archivexl" else "TweakXL"
            report.add(
                BLOCK,
                f"missing-{framework}",
                f"{proper} is not installed here, and the sender has it",
                f"{proper} is what resolves the extra records a modded save refers to. "
                "Without it, anything those mods added is a dangling reference.",
            )

    if persistent_mismatch:
        report.add(
            WARN,
            "persistent-version",
            f"{len(persistent_mismatch)} mod(s) that keep state in the save are a "
            "different version here",
            "Read this one. If the mod changed its persistent fields between these two "
            "versions, the game drops that mod's data when the save loads. Nothing "
            "fails, nothing is reported, and everything the mod was tracking is gone. "
            "Match the sender's version before loading if you care about that progress.",
            persistent_mismatch,
        )

    if missing_redscript:
        report.add(
            WARN,
            "missing-redscript",
            f"{len(missing_redscript)} redscript mod(s) the sender has are missing here",
            "Their state is in the save and nothing will read it. Usually harmless, and "
            "it does come back if you install the mod later.",
            missing_redscript,
        )

    if version_mismatch:
        report.add(
            NOTE,
            "version-differs",
            f"{len(version_mismatch)} mod(s) are a different version here",
            "None of these declare state in the save, so the difference is cosmetic as "
            "far as the save is concerned.",
            version_mismatch,
        )

    if unknown_versions:
        report.add(
            NOTE,
            "version-unknown",
            f"{len(unknown_versions)} mod(s) keep state in the save but publish no version",
            "Engram cannot tell whether these match. If the save behaves oddly, these "
            "are the first thing to check.",
            unknown_versions,
        )

    if missing_other:
        report.add(
            NOTE,
            "missing-other",
            f"{len(missing_other)} other mod(s) the sender has are missing here",
            "",
            missing_other,
        )

    if extra:
        report.add(
            NOTE,
            "extra-here",
            f"you have {len(extra)} mod(s) the sender does not",
            "These were not active when the save was made. They apply from now on.",
            extra,
        )


def mods_on_this_save(mods: ModSet) -> Finding:
    """The alert both sides get: this save was made with mods, and here they are.

    The sender sees it before they read the code out and the receiver sees it before
    anything is written, so neither of them is surprised by what travelled.
    """
    if not len(mods):
        return Finding(
            severity=NOTE,
            code="save-has-mods",
            summary="this save was made with no mods installed",
            detail="Nothing from a mod is inside it, so it will load on any machine "
            "running the same patch.",
        )

    items = []
    for entry in mods:
        line = _label(entry)
        if entry.writes_persistent_state:
            line += "  [keeps state in the save]"
        elif entry.extends_records:
            line += "  [adds records]"
        items.append(line)

    return Finding(
        severity=WARN,
        code="save-has-mods",
        summary=f"this save was made with {len(mods)} mod(s) installed",
        detail="A modded save carries those mods' state inside sav.dat. Anyone loading it "
        "without them gets a save that may behave differently, and the game disables "
        "achievements for it. The full list is below.",
        items=tuple(items),
    )


def check_save(
    slot_meta: dict,
    sender_mods: ModSet,
    receiver_mods: ModSet,
    receiver_game_version: int | None,
    report: Report,
) -> None:
    """The checks that come from the save itself rather than the mod lists."""
    sender_version = int(slot_meta.get("gameVersion") or 0)
    build = str(slot_meta.get("buildPatch") or "unknown")

    if sender_version and receiver_game_version:
        if sender_version > receiver_game_version:
            report.add(
                BLOCK,
                "downgrade",
                f"this save is from game {build} and yours is older",
                f"The save reports game version {sender_version} and the newest save on "
                f"this machine reports {receiver_game_version}. Cyberpunk does not read "
                "a save from a newer patch. Update the game and try again.",
            )
        elif sender_version < receiver_game_version:
            report.add(
                NOTE,
                "older-save",
                f"this save is from game {build}, which is older than yours",
                "Loading an older save on a newer patch is normal and the game upgrades "
                "it in place.",
            )
    elif sender_version and receiver_game_version is None:
        report.add(
            NOTE,
            "no-local-version",
            "cannot compare game versions, because there are no saves here yet",
            f"The save is from game {build}. If your game is older than that, it will "
            "not load.",
        )

    # What the save was made with, every time, whether or not it differs from here.
    report.findings.append(mods_on_this_save(sender_mods))

    needs_pl = "EP1" in [str(i) for i in (slot_meta.get("additionalContentIds") or [])]
    if needs_pl and not receiver_mods.phantom_liberty:
        report.add(
            BLOCK,
            "missing-phantom-liberty",
            "this save needs Phantom Liberty and it is not installed",
            "The save was made with the expansion active. Without it the game has "
            "nothing to load the expansion's content from.",
        )

    if slot_meta.get("isModded"):
        report.add(
            NOTE,
            "modded-flag",
            "the game has flagged this save as modded",
            "Achievements stay disabled while playing it, and the load menu marks it. "
            "That flag is the game's own and Engram does not set or clear it.",
        )

    sender_pt = sender_mods.phantom_liberty
    if sender_pt and not receiver_mods.phantom_liberty and not needs_pl:
        report.add(
            NOTE,
            "sender-has-pl",
            "the sender has Phantom Liberty and you do not",
            "This particular save does not use it, so it should still load.",
        )


def check_environment(running: Running, report: Report) -> None:
    """What is holding the save folder open right now."""
    if not running.checked:
        report.add(
            NOTE,
            "no-process-check",
            "could not check what is running",
            "Close Cyberpunk and Steam before writing a save, in case either is holding "
            "the folder.",
        )
        return

    if running.game_is_up:
        report.add(
            BLOCK,
            "game-running",
            "Cyberpunk is open",
            "The game writes its own saves over this folder and will not see a new one "
            "that appears while it is running. Close it, including the launcher: "
            + ", ".join(running.game),
        )

    if running.steam_is_up:
        report.add(
            WARN,
            "steam-running",
            "Steam is running, and Steam Cloud syncs this folder",
            "Steam can replace an imported save with its cloud copy within seconds of "
            "the import working, which looks exactly like the import having failed. "
            "Close Steam, import, then start Steam again.",
        )

    if running.launchers:
        report.add(
            NOTE,
            "launcher-running",
            "a game launcher is running: " + ", ".join(running.launchers),
            "Worth closing before importing.",
        )


def build_report(
    slot_meta: dict,
    sender_mods: ModSet,
    receiver_mods: ModSet,
    receiver_game_version: int | None,
    running: Running | None = None,
) -> Report:
    """Everything, in one pass, before anything is written."""
    report = Report()
    check_save(slot_meta, sender_mods, receiver_mods, receiver_game_version, report)
    compare_mods(sender_mods, receiver_mods, report)
    if running is not None:
        check_environment(running, report)
    return report


def summarise(report: Report) -> str:
    """One line, for the top of the output."""
    blocks, warnings, notes = len(report.blocks), len(report.warnings), len(report.notes)
    if blocks:
        return f"{blocks} thing(s) stop this save loading here"
    if warnings:
        return f"this save should load, with {warnings} warning(s) worth reading"
    if notes:
        return f"this save should load cleanly, {notes} note(s)"
    return "this save should load cleanly"
