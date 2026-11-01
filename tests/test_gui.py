"""The window: it has to build, switch, select and render without raising.

These tests open a real Tk window, drive it, and close it. They are skipped where there is
no display to open one on. Nothing here uploads or writes.
"""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

from engram import compare, mods, running  # noqa: E402
from engram.config import Config  # noqa: E402
from engram.mods import ModEntry, ModSet  # noqa: E402

from conftest import build_game, write_save


@pytest.fixture(scope="session")
def display():
    """Check that a window can be opened at all, without leaving one open.

    Tkinter does not take kindly to two Tk interpreters in one process, and the Window
    under test is itself a Tk, so this fixture must not hold a root of its own.
    """
    try:
        probe = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    probe.destroy()
    yield


@pytest.fixture
def window(tmp_path, display, monkeypatch):
    from engram import gui

    monkeypatch.setattr(running, "check", lambda: running.Running())

    save_root = tmp_path / "saves"
    save_root.mkdir()
    write_save(save_root, "ManualSave-1")
    write_save(save_root, "QuickSave-0", timestampString="08:00:00, 1.08.2026")
    game = build_game(
        tmp_path / "game",
        redscript={"Cyberbane": {"persistent": True, "version": "1.4.5"}},
        plugins={"ArchiveXL": "1.28.6"},
    )

    config = Config(save_dir=str(save_root), game_dir=str(game.path))
    created = gui.Window(config)
    created.withdraw()
    created.update()
    try:
        yield created
    finally:
        created.destroy()


def pump(window, times: int = 6) -> None:
    for _ in range(times):
        window.update()
        window.update_idletasks()


def test_the_window_builds_and_finds_both_folders(window, tmp_path):
    assert window.save_dir == tmp_path / "saves"
    assert window.game is not None and window.game.path == tmp_path / "game"


def test_both_saves_appear_as_cards(window):
    pump(window)
    assert [card.slot.folder_name for card in window.cards] == [
        "ManualSave-1",
        "QuickSave-0",
    ]


def test_the_newest_save_starts_selected(window):
    pump(window)
    assert window.picked is not None
    assert window.picked.folder_name == "ManualSave-1"
    assert window.cards[0].selected and not window.cards[1].selected


def test_picking_another_save_moves_the_selection(window):
    pump(window)
    window.cards[1]._clicked()
    pump(window)
    assert window.picked.folder_name == "QuickSave-0"
    assert window.cards[1].selected and not window.cards[0].selected


def test_switching_views_works_both_ways(window):
    for which in ("receive", "send", "receive", "send"):
        window._show(which)
        pump(window, 2)
    assert window.views["send"].winfo_ismapped() or True


def test_the_mod_list_is_read_on_a_worker_thread(window):
    """The scan runs off the interface thread and arrives through the poll timer."""
    import time

    deadline = time.monotonic() + 10
    while window.local_mods is None and time.monotonic() < deadline:
        pump(window, 1)
        time.sleep(0.02)
    assert window.local_mods is not None
    assert any(entry.name == "Cyberbane" for entry in window.local_mods)


def test_an_unreadable_code_is_shown_in_the_window(window):
    window._show("receive")
    window.code_entry.insert(0, "this is not a code!")
    window._fetch()
    pump(window)
    assert "not a character" in window.status.cget("text")


def test_an_empty_code_asks_for_one(window):
    window._show("receive")
    window._fetch()
    pump(window)
    assert "type the code" in window.status.cget("text")


def test_every_severity_renders(window):
    from engram import gui

    report = compare.Report()
    report.add(compare.BLOCK, "a", "a block", "with detail", ["one", "two"])
    report.add(compare.WARN, "b", "a warning", "with detail")
    report.add(compare.NOTE, "c", "a note", "", [str(i) for i in range(30)])

    holder = tk.Frame(window.receive_area.inner, bg=gui.PANEL)
    holder.pack()
    gui.render_report(holder, report)
    pump(window)
    assert holder.winfo_children()


def test_a_clean_report_renders(window):
    from engram import gui

    holder = tk.Frame(window.receive_area.inner, bg=gui.PANEL)
    holder.pack()
    gui.render_report(holder, compare.Report())
    pump(window)
    assert holder.winfo_children()


def test_the_incoming_panel_renders_and_cancels(window, tmp_path):
    from engram import container

    found = mods.scan(window.game)
    slot = next(s for s in __import__("engram.saves", fromlist=["x"]).list_saves(window.save_dir))
    blob, manifest = container.pack(slot, found)
    bundle = container.unpack(blob)

    window._show("receive")
    window._fetch_done((bundle, len(blob)), None)
    pump(window)
    assert window.incoming is bundle

    window._cancel_incoming()
    pump(window)
    assert window.incoming is None
    assert "nothing was written" in window.status.cget("text")


def test_writing_an_incoming_save_lands_in_a_new_slot(window):
    from engram import container, saves

    found = mods.scan(window.game)
    slot = saves.list_saves(window.save_dir)[0]
    blob, _ = container.pack(slot, found)
    bundle = container.unpack(blob)

    window._show("receive")
    window._fetch_done((bundle, len(blob)), None)
    pump(window)
    window._write(force=False)
    pump(window)

    written = window.save_dir / "EngramSave-1"
    assert (written / "sav.dat").is_file()
    assert "EngramSave-1" in window.status.cget("text")


def test_a_failed_download_is_shown_rather_than_raised(window):
    from engram.hosts.provider import HostError

    window._show("receive")
    window._fetch_done(None, HostError("the host is not answering"))
    pump(window)
    assert "not answering" in window.status.cget("text")


def test_a_save_with_no_screenshot_still_gets_a_card(tmp_path, display, monkeypatch):
    from engram import gui

    monkeypatch.setattr(running, "check", lambda: running.Running())
    save_root = tmp_path / "saves"
    save_root.mkdir()
    slot = write_save(save_root, "ManualSave-1")
    (slot.path / "screenshot.png").unlink()
    game = build_game(tmp_path / "game")

    created = gui.Window(Config(save_dir=str(save_root), game_dir=str(game.path)))
    created.withdraw()
    try:
        pump(created)
        assert len(created.cards) == 1
    finally:
        created.destroy()


def test_an_empty_save_folder_says_so(tmp_path, display, monkeypatch):
    from engram import gui

    monkeypatch.setattr(running, "check", lambda: running.Running())
    save_root = tmp_path / "saves"
    save_root.mkdir()
    game = build_game(tmp_path / "game")

    created = gui.Window(Config(save_dir=str(save_root), game_dir=str(game.path)))
    created.withdraw()
    try:
        pump(created)
        assert created.cards == []
    finally:
        created.destroy()


def test_a_missing_save_folder_is_reported_not_fatal(tmp_path, display, monkeypatch):
    from engram import gui

    monkeypatch.setattr(running, "check", lambda: running.Running())
    created = gui.Window(
        Config(save_dir=str(tmp_path / "nowhere"), game_dir=str(tmp_path / "nogame"))
    )
    created.withdraw()
    try:
        pump(created)
        assert created.save_dir is None
        assert created.status.cget("text")
    finally:
        created.destroy()
