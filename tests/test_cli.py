"""The commands, end to end, including a save going out and coming back.

The share and get pair runs against a local server standing in for a file host, so the
whole path is exercised: pack, seal, upload, code, parse, download, open, compare, write.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from engram import cli, running
from engram.cli import EXIT_BLOCKED, EXIT_CANCELLED, EXIT_ERROR, EXIT_OK

from conftest import build_game, write_save


@pytest.fixture(autouse=True)
def quiet_machine(monkeypatch):
    """Whatever is running on the machine running the tests must not change the result."""
    monkeypatch.setattr(running, "check", lambda: running.Running())


@pytest.fixture
def fake_host():
    """A host that keeps one file, the way Litterbox does for 72 hours."""
    store: dict[str, bytes] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            match = re.search(
                rb'name="fileToUpload"[^\r]*\r\nContent-Type:[^\r]*\r\n\r\n(.*)\r\n--',
                raw,
                re.DOTALL,
            )
            store["8kq2mz"] = match.group(1) if match else b""
            body = f"http://127.0.0.1:{self.server.server_port}/8kq2mz.bin".encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            name = self.path.lstrip("/").removesuffix(".bin")
            data = store.get(name)
            if data is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", store
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def config_file(tmp_path, fake_host) -> Path:
    base, _ = fake_host
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps(
            {
                "hostOrder": ["litterbox"],
                "hosts": {
                    "litterbox": {
                        "uploadUrl": f"{base}/api.php",
                        "urlTemplate": base + "/{id}.bin",
                        "expiry": "72h",
                    }
                },
                "backupRoot": str(tmp_path / "backups"),
            }
        ),
        encoding="utf-8",
    )
    return target


@pytest.fixture
def sender(tmp_path):
    """A machine with a save and a modest mod list."""
    save_root = tmp_path / "sender-saves"
    save_root.mkdir()
    write_save(save_root, "ManualSave-1")
    game = build_game(
        tmp_path / "sender-game",
        redscript={"Cyberbane": {"persistent": True, "version": "1.4.5"}},
        plugins={"ArchiveXL": "1.28.6"},
        archives=["Atlas.archive", "Atlas.archive.xl"],
    )
    return save_root, game.path


@pytest.fixture
def receiver(tmp_path):
    """A matching machine, so the default comparison is clean."""
    save_root = tmp_path / "receiver-saves"
    save_root.mkdir()
    write_save(save_root, "ManualSave-9", display_name="ManualSave-9")
    game = build_game(
        tmp_path / "receiver-game",
        redscript={"Cyberbane": {"persistent": True, "version": "1.4.5"}},
        plugins={"ArchiveXL": "1.28.6"},
        archives=["Atlas.archive", "Atlas.archive.xl"],
    )
    return save_root, game.path


def run(*argv: str) -> int:
    return cli.main(list(argv))


def where(save_root: Path, game_root: Path, config: Path) -> list[str]:
    return [
        "--save-dir",
        str(save_root),
        "--game-dir",
        str(game_root),
        "--config",
        str(config),
    ]


# ------------------------------------------------------------------------- the basics


def test_no_arguments_prints_help(capsys):
    assert run() == EXIT_OK
    assert "carry a cyberpunk" in capsys.readouterr().out.lower()


def test_saves_lists_what_is_there(sender, config_file, capsys):
    save_root, game_root = sender
    assert run("saves", *where(save_root, game_root, config_file)) == EXIT_OK
    assert "ManualSave-1" in capsys.readouterr().out


def test_mods_lists_what_is_installed(sender, config_file, capsys):
    save_root, game_root = sender
    assert run("mods", *where(save_root, game_root, config_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert "Cyberbane" in out
    assert "keeps state in the save" in out


def test_doctor_reports_both_folders(sender, config_file, capsys):
    save_root, game_root = sender
    assert run("doctor", *where(save_root, game_root, config_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert str(save_root) in out and str(game_root) in out
    assert "Litterbox" in out


def test_config_can_be_written_and_read_back(tmp_path, capsys):
    target = tmp_path / "new-config.json"
    assert run("config", "--init", "--config", str(target)) == EXIT_OK
    assert target.is_file()
    assert run("config", "--config", str(target)) == EXIT_OK
    assert "litterbox" in capsys.readouterr().out


# -------------------------------------------------------------------- the local route


def test_a_save_moves_between_two_machines_through_a_file(
    sender, receiver, config_file, tmp_path, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    bundle = tmp_path / "moved.engram"

    assert (
        run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
        == EXIT_OK
    )
    assert bundle.is_file()
    capsys.readouterr()

    assert (
        run("unpack", str(bundle), "--yes", *where(get_saves, get_game, config_file))
        == EXIT_OK
    )
    out = capsys.readouterr().out
    assert "written" in out

    written = get_saves / "EngramSave-1"
    assert (written / "sav.dat").read_bytes() == (
        send_saves / "ManualSave-1" / "sav.dat"
    ).read_bytes()
    document = json.loads((written / "metadata.9.json").read_text(encoding="utf-8"))
    assert document["Data"]["metadata"]["name"] == "EngramSave-1"


def test_packing_twice_needs_force(sender, config_file, tmp_path):
    save_root, game_root = sender
    bundle = tmp_path / "once.engram"
    args = where(save_root, game_root, config_file)
    assert run("pack", "ManualSave-1", "-o", str(bundle), *args) == EXIT_OK
    assert run("pack", "ManualSave-1", "-o", str(bundle), *args) == EXIT_ERROR
    assert run("pack", "ManualSave-1", "-o", str(bundle), "--force", *args) == EXIT_OK


def test_a_sealed_file_needs_its_passphrase(
    sender, receiver, config_file, tmp_path, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    bundle = tmp_path / "sealed.engram"

    assert (
        run("pack", "ManualSave-1", "--seal", "-o", str(bundle),
            *where(send_saves, send_game, config_file))
        == EXIT_OK
    )
    printed = capsys.readouterr().out
    passphrase = re.search(r"\n    ([0-9A-Z]{4}-[0-9A-Z]{4})\n", printed).group(1)

    get_args = where(get_saves, get_game, config_file)
    assert run("unpack", str(bundle), "--yes", *get_args) == EXIT_ERROR
    capsys.readouterr()
    assert run("unpack", str(bundle), "--secret", "0000-0000", "--yes", *get_args) == EXIT_ERROR
    capsys.readouterr()
    assert run("unpack", str(bundle), "--secret", passphrase, "--yes", *get_args) == EXIT_OK
    assert (get_saves / "EngramSave-1" / "sav.dat").is_file()


def test_a_dry_run_writes_nothing(sender, receiver, config_file, tmp_path, capsys):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    bundle = tmp_path / "dry.engram"
    run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
    capsys.readouterr()

    assert (
        run("unpack", str(bundle), "--dry-run", *where(get_saves, get_game, config_file))
        == EXIT_OK
    )
    assert "nothing was written" in capsys.readouterr().out
    assert not (get_saves / "EngramSave-1").exists()


def test_declining_the_prompt_writes_nothing(
    sender, receiver, config_file, tmp_path, monkeypatch, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    bundle = tmp_path / "declined.engram"
    run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
    capsys.readouterr()

    monkeypatch.setattr("engram.ui.confirm", lambda *a, **k: False)
    assert (
        run("unpack", str(bundle), *where(get_saves, get_game, config_file))
        == EXIT_CANCELLED
    )
    assert not (get_saves / "EngramSave-1").exists()


def test_a_blocked_save_is_not_written(sender, config_file, tmp_path, capsys):
    """The receiver is missing the record mod, so this must stop before writing."""
    send_saves, send_game = sender
    bundle = tmp_path / "blocked.engram"
    run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
    capsys.readouterr()

    bare_saves = tmp_path / "bare-saves"
    bare_saves.mkdir()
    write_save(bare_saves, "ManualSave-9")
    bare_game = build_game(tmp_path / "bare-game").path

    assert (
        run("unpack", str(bundle), "--yes", *where(bare_saves, bare_game, config_file))
        == EXIT_BLOCKED
    )
    captured = capsys.readouterr()
    assert "[stop]" in captured.out
    assert "has not written anything" in captured.err
    assert not (bare_saves / "EngramSave-1").exists()

    assert (
        run("unpack", str(bundle), "--yes", "--force",
            *where(bare_saves, bare_game, config_file))
        == EXIT_OK
    )
    assert (bare_saves / "EngramSave-1" / "sav.dat").is_file()


def test_phantom_liberty_missing_blocks(sender, config_file, tmp_path, capsys):
    send_saves, send_game = sender
    bundle = tmp_path / "pl.engram"
    run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
    capsys.readouterr()

    no_pl_saves = tmp_path / "nopl-saves"
    no_pl_saves.mkdir()
    write_save(no_pl_saves, "ManualSave-9")
    no_pl_game = build_game(
        tmp_path / "nopl-game",
        redscript={"Cyberbane": {"persistent": True, "version": "1.4.5"}},
        plugins={"ArchiveXL": "1.28.6"},
        archives=["Atlas.archive", "Atlas.archive.xl"],
        phantom_liberty=False,
    ).path

    assert (
        run("unpack", str(bundle), "--yes", *where(no_pl_saves, no_pl_game, config_file))
        == EXIT_BLOCKED
    )
    assert "Phantom Liberty" in capsys.readouterr().out


def test_a_version_change_in_a_persistent_mod_warns_but_still_writes(
    sender, config_file, tmp_path, capsys
):
    send_saves, send_game = sender
    bundle = tmp_path / "warn.engram"
    run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
    capsys.readouterr()

    other_saves = tmp_path / "other-saves"
    other_saves.mkdir()
    write_save(other_saves, "ManualSave-9")
    other_game = build_game(
        tmp_path / "other-game",
        redscript={"Cyberbane": {"persistent": True, "version": "1.9.9"}},
        plugins={"ArchiveXL": "1.28.6"},
        archives=["Atlas.archive", "Atlas.archive.xl"],
    ).path

    assert (
        run("unpack", str(bundle), "--yes", *where(other_saves, other_game, config_file))
        == EXIT_OK
    )
    out = capsys.readouterr().out
    assert "[warn]" in out
    assert "1.4.5" in out and "1.9.9" in out
    assert (other_saves / "EngramSave-1" / "sav.dat").is_file()


def test_an_existing_slot_is_backed_up_before_being_replaced(
    sender, receiver, config_file, tmp_path, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    bundle = tmp_path / "into.engram"
    run("pack", "ManualSave-1", "-o", str(bundle), *where(send_saves, send_game, config_file))
    capsys.readouterr()

    original = (get_saves / "ManualSave-9" / "sav.dat").read_bytes()
    assert (
        run("unpack", str(bundle), "--into", "ManualSave-9", "--yes",
            *where(get_saves, get_game, config_file))
        == EXIT_OK
    )
    assert "backed up" in capsys.readouterr().out
    backups = list((tmp_path / "backups").glob("*-ManualSave-9"))
    assert len(backups) == 1
    assert (backups[0] / "sav.dat").read_bytes() == original


# --------------------------------------------------------------------- the code route


def test_a_save_moves_between_two_machines_with_a_code(
    sender, receiver, config_file, fake_host, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    _, store = fake_host

    assert (
        run("share", "ManualSave-1", *where(send_saves, send_game, config_file)) == EXIT_OK
    )
    printed = capsys.readouterr().out
    code = re.search(r"\n    ([0-9A-Z]{4}(?:-[0-9A-Z]{4}){3})\n", printed).group(1)
    assert code.startswith("C")
    assert store, "the container never reached the host"

    assert (
        run("get", code, "--yes", *where(get_saves, get_game, config_file)) == EXIT_OK
    )
    out = capsys.readouterr().out
    assert "written" in out

    written = get_saves / "EngramSave-1"
    assert (written / "sav.dat").read_bytes() == (
        send_saves / "ManualSave-1" / "sav.dat"
    ).read_bytes()


def test_what_the_host_holds_is_unreadable_without_the_code(
    sender, config_file, fake_host, capsys
):
    """The host gets a blob. The key is the part of the code that was never uploaded."""
    send_saves, send_game = sender
    _, store = fake_host
    run("share", "ManualSave-1", *where(send_saves, send_game, config_file))
    capsys.readouterr()

    uploaded = next(iter(store.values()))
    original = (send_saves / "ManualSave-1" / "sav.dat").read_bytes()
    assert original not in uploaded
    assert b"ManualSave-1" not in uploaded
    assert b"Cyberbane" not in uploaded

    from engram import container
    from engram.container import ContainerError

    with pytest.raises(ContainerError):
        container.unpack(uploaded)


def test_a_mistyped_code_is_explained_rather_than_crashing(
    sender, receiver, config_file, fake_host, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    run("share", "ManualSave-1", *where(send_saves, send_game, config_file))
    printed = capsys.readouterr().out
    code = re.search(r"\n    ([0-9A-Z]{4}(?:-[0-9A-Z]{4}){3})\n", printed).group(1)

    args = where(get_saves, get_game, config_file)
    wrong_secret = code[:-1] + ("Y" if code[-1] != "Y" else "Z")
    assert run("get", wrong_secret, "--yes", *args) == EXIT_ERROR
    assert "did not open it" in capsys.readouterr().err

    assert run("get", "C000-0000-0000-0000", "--yes", *args) == EXIT_ERROR
    assert "expire" in capsys.readouterr().err

    assert run("get", "nonsense!", *args) == EXIT_ERROR
    assert "not a character" in capsys.readouterr().err

    assert run("get", f"http://127.0.0.1/x.bin", *args) == EXIT_ERROR
    assert "not the code" in capsys.readouterr().err


def test_inspect_shows_a_code_without_writing_anything(
    sender, receiver, config_file, fake_host, capsys
):
    send_saves, send_game = sender
    get_saves, get_game = receiver
    run("share", "ManualSave-1", *where(send_saves, send_game, config_file))
    printed = capsys.readouterr().out
    code = re.search(r"\n    ([0-9A-Z]{4}(?:-[0-9A-Z]{4}){3})\n", printed).group(1)

    assert run("inspect", code, *where(get_saves, get_game, config_file)) == EXIT_OK
    out = capsys.readouterr().out
    assert "never writes anything" in out
    assert "level 60 StreetKid" in out
    assert not (get_saves / "EngramSave-1").exists()


def test_an_unknown_host_name_is_refused(sender, config_file, capsys):
    save_root, game_root = sender
    assert (
        run("share", "ManualSave-1", "--host", "dropbox",
            *where(save_root, game_root, config_file))
        == EXIT_ERROR
    )
    assert "litterbox" in capsys.readouterr().err


def test_a_missing_save_folder_is_explained(tmp_path, config_file, capsys):
    assert (
        run("saves", "--save-dir", str(tmp_path / "nowhere"), "--config", str(config_file))
        == EXIT_ERROR
    )
    assert "not a directory" in capsys.readouterr().err


def test_a_game_folder_without_the_game_in_it_is_refused(sender, config_file, tmp_path, capsys):
    save_root, _ = sender
    empty = tmp_path / "not-the-game"
    empty.mkdir()
    assert (
        run("mods", "--save-dir", str(save_root), "--game-dir", str(empty),
            "--config", str(config_file))
        == EXIT_ERROR
    )
    assert "Cyberpunk2077.exe" in capsys.readouterr().err
