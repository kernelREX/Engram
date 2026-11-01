"""The command line. Everything Engram does, it does from here.

Two commands matter and the rest are there to explain them:

    engram share ManualSave-1     the sender reads out the code it prints
    engram get C8KQ-2MZ7-FPR4-TQX the receiver types it in

`pack` and `unpack` do the same job through a file instead of a host, and they keep
working when every free service on the internet is down.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, code as codes, compare, config as configmod, container
from . import manifest as manifestmod, mods, paths, running, saves, ui
from .code import CodeError
from .compare import Report
from .config import ConfigError
from .container import ContainerError
from .crypto import DecryptionError
from .hosts import spec
from .hosts.provider import HostError, download, upload
from .manifest import Manifest, ManifestError
from .mods import ModSet
from .paths import LocationError
from .saves import SaveError

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BLOCKED = 2
EXIT_CANCELLED = 3


class Abort(Exception):
    """Something the user should be told plainly, with no traceback."""

    def __init__(self, message: str, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code


# --------------------------------------------------------------------------- context


class Context:
    """The directories and settings every command needs, resolved once and lazily."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        try:
            self.config = configmod.load(getattr(args, "config", None))
        except ConfigError as exc:
            raise Abort(str(exc)) from None
        self._save_dir: Path | None = None
        self._game: paths.GameInstall | None = None
        self._mods: ModSet | None = None

    @property
    def save_dir(self) -> Path:
        if self._save_dir is None:
            override = getattr(self.args, "save_dir", None) or self.config.save_dir
            try:
                self._save_dir = paths.find_save_dir(override)
            except LocationError as exc:
                raise Abort(str(exc)) from None
        return self._save_dir

    @property
    def game(self) -> paths.GameInstall:
        if self._game is None:
            override = getattr(self.args, "game_dir", None) or self.config.game_dir
            try:
                self._game = paths.find_game_dir(override)
            except LocationError as exc:
                raise Abort(str(exc)) from None
        return self._game

    @property
    def mods(self) -> ModSet:
        if self._mods is None:
            self._mods = mods.scan(self.game)
        return self._mods


# --------------------------------------------------------------------------- helpers


def _resolve_slot(ctx: Context, wanted: str | None) -> saves.SaveSlot:
    try:
        if wanted:
            return saves.find_save(ctx.save_dir, wanted)
        found = saves.list_saves(ctx.save_dir)
        if not found:
            raise Abort(f"no saves in {ctx.save_dir}")
        return found[0]
    except SaveError as exc:
        raise Abort(str(exc)) from None


def _print_save(slot: saves.SaveSlot, marker: str = "") -> None:
    flags = []
    if slot.needs_phantom_liberty:
        flags.append("Phantom Liberty")
    if slot.is_modded:
        flags.append("modded")
    tail = "  " + ui.paint("(" + ", ".join(flags) + ")", "dim") if flags else ""
    print(f"  {marker}{slot.folder_name.ljust(24)} {slot.describe()}{tail}")


def _build_report(
    manifest: Manifest, ctx: Context, check_processes: bool = True
) -> Report:
    return compare.build_report(
        slot_meta=manifest.save,
        sender_mods=manifest.mods,
        receiver_mods=ctx.mods,
        receiver_game_version=compare.local_game_version(ctx.save_dir),
        running=running.check() if check_processes else None,
    )


def _show_incoming(manifest: Manifest, report: Report, size: int) -> None:
    ui.heading(f"{manifest.display_name}, from the sender's {manifest.source_folder}")
    ui.field("save", manifest.describe())
    ui.field("game", manifest.save.get("buildPatch") or "unknown")
    ui.field("needs", "Phantom Liberty" if manifest.needs_phantom_liberty else "base game")
    ui.field("sender's mods", str(len(manifest.mods)))
    ui.field("size", ui.megabytes(size))
    if manifest.exported_at:
        ui.field("packed", manifest.exported_at)

    ui.heading(compare.summarise(report))
    ui.report(report)


def _write_bundle(
    ctx: Context, bundle: container.Bundle, into: str | None, keep_name: bool
) -> Path:
    slot_name = into or saves.free_slot_name(ctx.save_dir, ctx.config.slot_prefix)
    target = ctx.save_dir / slot_name

    if target.exists():
        if not saves.is_save_folder(target):
            raise Abort(f"{target} exists and is not a save folder, so it is left alone")
        backup = saves.back_up(target, ctx.config.backups)
        ui.say(f"  backed up the save already in {slot_name} to {backup}")
        import shutil

        shutil.rmtree(target)

    try:
        written = saves.install_save(
            ctx.save_dir,
            slot_name,
            bundle.files,
            rename_in_metadata=not keep_name,
        )
    except (SaveError, OSError) as exc:
        raise Abort(f"could not write the save: {exc}") from None
    return written


def _accept(report: Report, force: bool, assume_yes: bool) -> None:
    """Stop here unless the receiver has actually agreed to what they just read."""
    if report.blocked and not force:
        ui.say()
        ui.warn(
            "Engram has not written anything. Install what is missing and run this "
            "again, or add --force if you are sure the save does not use it."
        )
        raise Abort("blocked by the checks above", EXIT_BLOCKED)

    if report.blocked:
        ui.say()
        ui.warn("--force given, so the blocks above are being ignored.")

    if assume_yes:
        return
    ui.say()
    if not ui.confirm("Write this save into your save folder?", default=not report.blocked):
        raise Abort("nothing was written", EXIT_CANCELLED)


# --------------------------------------------------------------------------- commands


def cmd_saves(ctx: Context) -> int:
    found = saves.list_saves(ctx.save_dir)
    ui.heading(f"{len(found)} save(s) in {ctx.save_dir}")
    if not found:
        ui.say("  nothing here yet")
        return EXIT_OK
    for index, slot in enumerate(found):
        _print_save(slot, marker="* " if index == 0 else "  ")
    ui.say()
    ui.say(ui.paint("  * the newest, which is what share uses when you name no save", "dim"))
    return EXIT_OK


def cmd_mods(ctx: Context) -> int:
    found = ctx.mods
    ui.heading(f"{len(found)} mod(s) in {ctx.game.path}")
    ui.field("Phantom Liberty", "installed" if found.phantom_liberty else "not installed")
    ui.field("ArchiveXL", "yes" if found.has_framework("archivexl") else "no")
    ui.field("TweakXL", "yes" if found.has_framework("tweakxl") else "no")

    for kind in ("redscript", "red4ext", "redmod", "tweak", "archive", "cet"):
        entries = found.of_kind(kind)
        if not entries:
            continue
        ui.heading(f"{kind} ({len(entries)})")
        for entry in entries:
            notes = []
            if entry.writes_persistent_state:
                notes.append("keeps state in the save")
            if entry.extends_records:
                notes.append("adds records")
            if entry.declared:
                notes.append("declared")
            suffix = "  " + ui.paint("- " + ", ".join(notes), "dim") if notes else ""
            version = entry.version or "no version"
            print(f"  {entry.name[:44].ljust(44)} {version.ljust(12)}{suffix}")
    return EXIT_OK


def cmd_pack(ctx: Context) -> int:
    slot = _resolve_slot(ctx, ctx.args.save)
    target = Path(ctx.args.output) if ctx.args.output else Path(f"{slot.folder_name}.engram")
    if target.exists() and not ctx.args.force:
        raise Abort(f"{target} already exists. Pass --force to replace it.")

    secret = codes.new_secret() if ctx.args.seal else None
    try:
        blob, manifest = container.pack(slot, ctx.mods, secret=secret, context="")
        written = container.write(target, blob)
    except (ContainerError, OSError) as exc:
        raise Abort(str(exc)) from None

    ui.heading(f"packed {slot.folder_name}")
    ui.field("save", manifest.describe())
    ui.field("mods recorded", str(len(manifest.mods)))
    ui.say()
    ui.finding(compare.mods_on_this_save(manifest.mods), limit=40)
    ui.field("file", str(written))
    ui.field("size", ui.megabytes(len(blob)))
    if secret:
        ui.say()
        ui.say("  This file is sealed. It cannot be opened without the passphrase below,")
        ui.say("  and there is no copy of it anywhere else.")
        ui.code_block(codes.group(secret))
        ui.say(f"  Open it with:  engram unpack {target.name} --secret {secret}")
    else:
        ui.say()
        ui.say(f"  Open it on the other machine with:  engram unpack {target.name}")
    return EXIT_OK


def cmd_unpack(ctx: Context) -> int:
    try:
        blob = container.read(ctx.args.file)
        bundle = container.unpack(blob, secret=_clean_secret(ctx.args.secret))
    except (ContainerError, DecryptionError) as exc:
        raise Abort(str(exc)) from None

    report = _build_report(bundle.manifest, ctx)
    _show_incoming(bundle.manifest, report, len(blob))

    if ctx.args.dry_run:
        ui.say()
        ui.say("  --dry-run, so nothing was written.")
        return EXIT_BLOCKED if report.blocked else EXIT_OK

    _accept(report, force=ctx.args.force, assume_yes=ctx.args.yes)
    written = _write_bundle(ctx, bundle, ctx.args.into, ctx.args.keep_name)
    _report_written(written, bundle)
    return EXIT_OK


def cmd_share(ctx: Context) -> int:
    slot = _resolve_slot(ctx, ctx.args.save)
    hosts = _hosts_to_try(ctx)

    secret = codes.new_secret()
    ui.heading(f"sharing {slot.folder_name}")
    ui.field("save", slot.describe())
    ui.field("mods recorded", str(len(ctx.mods)))

    # Say what is travelling before the code exists, so the sender can stop here.
    ui.say()
    ui.finding(compare.mods_on_this_save(ctx.mods), limit=40)

    last_error: str | None = None
    for host in hosts:
        try:
            blob, manifest = container.pack(slot, ctx.mods, secret=secret, context=host.key)
        except ContainerError as exc:
            raise Abort(str(exc)) from None

        ui.field("sealed", f"{ui.megabytes(len(blob))}, AES-256-GCM")
        ui.say(f"  uploading to {host.label}, which keeps it for {host.expiry or 'a while'}")
        try:
            result = upload(host, blob)
        except HostError as exc:
            last_error = str(exc)
            ui.warn(f"  {host.label}: {exc}")
            continue

        code = codes.format_code(host, result.file_id, secret)
        ui.say()
        ui.say("  Read this out. It is the whole thing the other person needs.")
        ui.code_block(code)
        ui.say("  " + ui.paint(ui.spoken(code), "dim"))
        ui.say()
        ui.field("host", host.label)
        ui.field("expires", host.expiry or "per the host's policy")
        ui.field("they run", f"engram get {code}")
        if result.delete_token:
            ui.field("delete token", result.delete_token)
        ui.say()
        ui.say(
            ui.paint(
                "  The save is encrypted before it leaves this machine, and the key is "
                "the last\n  eight characters of that code, which were never uploaded. "
                "Lose the code and\n  the save is gone.",
                "dim",
            )
        )
        return EXIT_OK

    raise Abort(
        "no host would take the file. "
        + (last_error or "")
        + "\nThe local route still works: engram pack "
        + slot.folder_name
    )


def cmd_get(ctx: Context) -> int:
    code = _parse(ctx.args.code)
    host = ctx.config.host_by_key(code.host.key) or code.host

    ui.heading(f"fetching from {host.label}")
    ui.field("code", code.text())
    ui.field("address", host.url_for(code.file_id))
    try:
        blob = download(host, code.file_id)
    except HostError as exc:
        raise Abort(str(exc)) from None
    ui.field("downloaded", ui.megabytes(len(blob)))

    try:
        bundle = container.unpack(blob, secret=code.secret)
    except (ContainerError, DecryptionError) as exc:
        raise Abort(str(exc)) from None

    report = _build_report(bundle.manifest, ctx)
    _show_incoming(bundle.manifest, report, len(blob))

    if ctx.args.dry_run:
        ui.say()
        ui.say("  --dry-run, so nothing was written.")
        return EXIT_BLOCKED if report.blocked else EXIT_OK

    _accept(report, force=ctx.args.force, assume_yes=ctx.args.yes)
    written = _write_bundle(ctx, bundle, ctx.args.into, ctx.args.keep_name)
    _report_written(written, bundle)
    return EXIT_OK


def cmd_inspect(ctx: Context) -> int:
    target = ctx.args.target
    path = Path(target)
    if path.is_file():
        try:
            blob = container.read(path)
            bundle = container.unpack(blob, secret=_clean_secret(ctx.args.secret))
        except (ContainerError, DecryptionError) as exc:
            raise Abort(str(exc)) from None
    else:
        code = _parse(target)
        host = ctx.config.host_by_key(code.host.key) or code.host
        ui.heading(f"fetching from {host.label}")
        ui.field("address", host.url_for(code.file_id))
        try:
            blob = download(host, code.file_id)
            bundle = container.unpack(blob, secret=code.secret)
        except (HostError, ContainerError, DecryptionError) as exc:
            raise Abort(str(exc)) from None

    report = _build_report(bundle.manifest, ctx)
    _show_incoming(bundle.manifest, report, len(blob))
    ui.say()
    ui.say("  inspect never writes anything.")
    return EXIT_BLOCKED if report.blocked else EXIT_OK


def cmd_doctor(ctx: Context) -> int:
    ui.heading("Engram")
    ui.field("version", __version__)
    ui.field("python", sys.version.split()[0])
    ui.field("config", str(ctx.config.path or configmod.default_config_path()))
    ui.field("backups", str(ctx.config.backups))

    ui.heading("save folder")
    try:
        save_dir = ctx.save_dir
        found = saves.list_saves(save_dir)
        ui.field("path", str(save_dir))
        ui.field("saves", str(len(found)))
        local_version = compare.local_game_version(save_dir)
        ui.field("game version", str(local_version) if local_version else "unknown")
        if found:
            ui.field("newest", f"{found[0].folder_name}, {found[0].describe()}")
    except Abort as exc:
        ui.field("path", ui.paint(str(exc), "red"))

    ui.heading("game folder")
    try:
        game = ctx.game
        ui.field("path", str(game.path))
        ui.field("found via", game.source)
        ui.field("Phantom Liberty", "yes" if game.has_phantom_liberty else "no")
        found_mods = ctx.mods
        ui.field("mods", str(len(found_mods)))
        ui.field("ArchiveXL", "yes" if found_mods.has_framework("archivexl") else "no")
        ui.field("TweakXL", "yes" if found_mods.has_framework("tweakxl") else "no")
        persistent = [m.name for m in found_mods if m.writes_persistent_state]
        if persistent:
            ui.field("keep save state", ", ".join(persistent[:6]))
    except Abort as exc:
        ui.field("path", ui.paint(str(exc), "red"))

    ui.heading("running now")
    state = running.check()
    if not state.checked:
        ui.field("processes", "could not check")
    else:
        ui.field("Cyberpunk", ", ".join(state.game) if state.game else "not running")
        ui.field("Steam", ", ".join(state.steam) if state.steam else "not running")
        ui.field("launchers", ", ".join(state.launchers) if state.launchers else "none")

    ui.heading("hosts, in the order they are tried")
    for host in ctx.config.hosts():
        ui.field(host.label, f"tag {host.tag}, {host.upload_url}")
        if host.note:
            ui.say(ui.paint(f"                   {host.note}", "dim"))
    return EXIT_OK


def cmd_config(ctx: Context) -> int:
    target = ctx.config.path or configmod.default_config_path()
    if ctx.args.init:
        if target.exists() and not ctx.args.force:
            raise Abort(f"{target} already exists. Pass --force to overwrite it.")
        written = configmod.save(ctx.config, target)
        ui.heading("wrote a config file with the current defaults")
        ui.field("path", str(written))
        return EXIT_OK

    ui.heading("config")
    ui.field("path", str(target))
    ui.field("exists", "yes" if target.exists() else "no, defaults in use")
    ui.field("host order", ", ".join(h.key for h in ctx.config.hosts()))
    ui.field("slot prefix", ctx.config.slot_prefix)
    ui.field("backups", str(ctx.config.backups))
    if not target.exists():
        ui.say()
        ui.say("  Write one with:  engram config --init")
    return EXIT_OK


def cmd_gui(ctx: Context) -> int:
    from . import gui

    return gui.run(ctx.config)


# --------------------------------------------------------------------------- plumbing


def _clean_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    from .crockford import CrockfordError, normalise

    try:
        return normalise(secret)
    except CrockfordError as exc:
        raise Abort(f"that passphrase is not one Engram produced: {exc}") from None


def _parse(text: str):
    try:
        return codes.parse_code(text)
    except CodeError as exc:
        raise Abort(str(exc)) from None


def _hosts_to_try(ctx: Context):
    wanted = getattr(ctx.args, "host", None)
    if wanted:
        host = ctx.config.host_by_key(wanted)
        if host is None:
            raise Abort(
                f"no host called {wanted!r}. Engram knows: " + ", ".join(spec.known_keys())
            )
        return [host]
    return ctx.config.hosts()


def _report_written(written: Path, bundle: container.Bundle) -> None:
    ui.say()
    ui.say("  " + ui.paint("written", "green") + f": {written}")
    ui.field("as", written.name)
    ui.field("files", ", ".join(sorted(bundle.files)))
    ui.say()
    ui.say("  Start Cyberpunk and it is in the load list.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engram",
        description="Carry a Cyberpunk 2077 save to another PC with a code.",
    )
    parser.add_argument("--version", action="version", version=f"Engram {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--save-dir", help="where Cyberpunk keeps its saves")
    common.add_argument("--game-dir", help="where Cyberpunk is installed")
    common.add_argument("--config", help="use this settings file")

    writing = argparse.ArgumentParser(add_help=False)
    writing.add_argument("--into", help="write into this slot name instead of a new one")
    writing.add_argument(
        "--keep-name",
        action="store_true",
        help="leave the sender's save name in the metadata",
    )
    writing.add_argument("--dry-run", action="store_true", help="check but write nothing")
    writing.add_argument("--force", action="store_true", help="write despite the blocks")
    writing.add_argument("-y", "--yes", action="store_true", help="do not ask first")

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    listing = subparsers.add_parser(
        "saves", parents=[common], help="list the saves on this machine"
    )
    listing.set_defaults(run=cmd_saves)

    modlist = subparsers.add_parser(
        "mods", parents=[common], help="list the mods Engram can see"
    )
    modlist.set_defaults(run=cmd_mods)

    share = subparsers.add_parser(
        "share", parents=[common], help="upload a save and print a code for it"
    )
    share.add_argument("save", nargs="?", help="a save name, or the newest one by default")
    share.add_argument("--host", help="upload to this host rather than the first that works")
    share.set_defaults(run=cmd_share)

    get = subparsers.add_parser(
        "get", parents=[common, writing], help="fetch a save from a code and write it"
    )
    get.add_argument("code", help="the code the sender read out")
    get.set_defaults(run=cmd_get)

    pack = subparsers.add_parser(
        "pack", parents=[common], help="write a save to a file, with no network at all"
    )
    pack.add_argument("save", nargs="?", help="a save name, or the newest one by default")
    pack.add_argument("-o", "--output", help="where to write the file")
    pack.add_argument("--seal", action="store_true", help="encrypt it and print a passphrase")
    pack.add_argument("--force", action="store_true", help="replace the file if it exists")
    pack.set_defaults(run=cmd_pack)

    unpack = subparsers.add_parser(
        "unpack", parents=[common, writing], help="write a save back out of a file"
    )
    unpack.add_argument("file", help="the .engram file")
    unpack.add_argument("--secret", help="the passphrase, if the file was sealed")
    unpack.set_defaults(run=cmd_unpack)

    inspect = subparsers.add_parser(
        "inspect", parents=[common], help="show what a code or file holds, writing nothing"
    )
    inspect.add_argument("target", help="a code or a .engram file")
    inspect.add_argument("--secret", help="the passphrase, if a file was sealed")
    inspect.set_defaults(run=cmd_inspect)

    doctor = subparsers.add_parser(
        "doctor", parents=[common], help="show what Engram found on this machine"
    )
    doctor.set_defaults(run=cmd_doctor)

    conf = subparsers.add_parser("config", parents=[common], help="show or write settings")
    conf.add_argument("--init", action="store_true", help="write a settings file")
    conf.add_argument("--force", action="store_true", help="overwrite an existing one")
    conf.set_defaults(run=cmd_config)

    window = subparsers.add_parser("gui", parents=[common], help="open the window")
    window.set_defaults(run=cmd_gui)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "run", None):
        parser.print_help()
        return EXIT_OK

    try:
        return args.run(Context(args))
    except Abort as exc:
        ui.fail(str(exc))
        return exc.exit_code
    except KeyboardInterrupt:
        ui.say()
        ui.fail("stopped")
        return EXIT_CANCELLED
    except (ManifestError, SaveError, ContainerError, CodeError) as exc:
        ui.fail(str(exc))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
