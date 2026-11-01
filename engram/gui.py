"""The window, for people who would rather not use a terminal.

It does what the two commands do and nothing more: pick a save and get a code, or type a
code and read what it would change before accepting it. Every long job runs on a worker
thread and comes back to the interface through `after`, because a window that stops
redrawing during a six megabyte upload looks broken.

The save folder already contains everything needed to make this look like the game: each
save carries its own screenshot at 456 by 256, and its own metadata.
"""

from __future__ import annotations

import gc
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from . import code as codes, compare, container, mods, paths, running, saves
from .code import CodeError
from .compare import BLOCK, NOTE, WARN, Report
from .config import Config
from .container import ContainerError
from .crypto import DecryptionError
from .hosts.provider import HostError, download, upload
from .manifest import Manifest

BACKGROUND = "#0b0e11"
PANEL = "#14191f"
PANEL_HIGH = "#1c232b"
LINE = "#2a333d"
TEXT = "#d7e0e8"
MUTED = "#7d8c9a"
ACCENT = "#fcee0a"
CYAN = "#00e5ff"
RED = "#ff4d5e"
AMBER = "#ffb01f"

TITLE_FONT = ("Segoe UI Semibold", 20)
HEAD_FONT = ("Segoe UI Semibold", 11)
BODY_FONT = ("Segoe UI", 9)
SMALL_FONT = ("Segoe UI", 8)
CODE_FONT = ("Consolas", 26, "bold")
MONO_FONT = ("Consolas", 10)

SEVERITY_COLOUR = {BLOCK: RED, WARN: AMBER, NOTE: MUTED}
SEVERITY_LABEL = {BLOCK: "STOP", WARN: "WARN", NOTE: "NOTE"}


def _button(parent, text, command, primary=False, **kwargs):
    """A flat button, because ttk themes do not take kindly to dark backgrounds."""
    colours = (
        {"bg": ACCENT, "fg": "#0b0e11", "activebackground": "#fff85c"}
        if primary
        else {"bg": PANEL_HIGH, "fg": TEXT, "activebackground": LINE}
    )
    return tk.Button(
        parent,
        text=text,
        command=command,
        font=HEAD_FONT if primary else BODY_FONT,
        relief="flat",
        borderwidth=0,
        padx=18,
        pady=8,
        cursor="hand2",
        activeforeground=colours["fg"],
        highlightthickness=0,
        **colours,
        **kwargs,
    )


class Worker:
    """Runs one job off the interface thread and hands the result back on it.

    The poll is cancelled when the window closes, and a result that arrives after that is
    dropped rather than delivered to widgets that no longer exist.
    """

    POLL_MS = 80

    #: How long closing the window waits for a job that is still running.
    SHUTDOWN_WAIT = 10.0

    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.results: queue.Queue = queue.Queue()
        self.stopped = False
        self._threads: list[threading.Thread] = []
        self._timer: str | None = self.root.after(self.POLL_MS, self._drain)

    def start(self, job: Callable[[], object], done: Callable[[object, Exception | None], None]):
        def run():
            try:
                self.results.put((done, job(), None))
            except Exception as exc:  # surfaced in the window rather than a traceback
                self.results.put((done, None, exc))

        thread = threading.Thread(target=run, daemon=True)
        self._threads = [t for t in self._threads if t.is_alive()]
        self._threads.append(thread)
        thread.start()

    def stop(self) -> None:
        """Cancel the poll, then wait for any job still reading files off disk.

        A job left running past teardown keeps walking directories that are about to go
        away, so closing the window waits for it rather than abandoning it.
        """
        self.stopped = True
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except tk.TclError:
                pass
            self._timer = None
        for thread in self._threads:
            thread.join(timeout=self.SHUTDOWN_WAIT)
        self._threads = []

    def _drain(self) -> None:
        if self.stopped:
            return
        try:
            while True:
                done, value, error = self.results.get_nowait()
                try:
                    done(value, error)
                except tk.TclError:
                    return
        except queue.Empty:
            pass
        if not self.stopped:
            self._timer = self.root.after(self.POLL_MS, self._drain)


class SaveCard(tk.Frame):
    """One save in the list, with its own screenshot."""

    def __init__(self, parent, slot: saves.SaveSlot, on_pick: Callable[[saves.SaveSlot], None]):
        super().__init__(parent, bg=PANEL, highlightthickness=1, highlightbackground=PANEL)
        self.slot = slot
        self.on_pick = on_pick
        self.selected = False
        self._thumbnail: tk.PhotoImage | None = None

        shot = slot.screenshot
        if shot is not None:
            try:
                image = tk.PhotoImage(file=str(shot))
                self._thumbnail = image.subsample(3)
            except tk.TclError:
                self._thumbnail = None

        if self._thumbnail is not None:
            tk.Label(self, image=self._thumbnail, bg=PANEL, borderwidth=0).pack(
                side="left", padx=(0, 10)
            )
        else:
            tk.Label(
                self, text="no\nimage", bg=PANEL_HIGH, fg=MUTED, font=SMALL_FONT,
                width=19, height=5,
            ).pack(side="left", padx=(0, 10))

        body = tk.Frame(self, bg=PANEL)
        body.pack(side="left", fill="both", expand=True, pady=6)
        tk.Label(
            body, text=slot.folder_name, bg=PANEL, fg=TEXT, font=HEAD_FONT, anchor="w"
        ).pack(fill="x")
        tk.Label(
            body, text=slot.describe(), bg=PANEL, fg=MUTED, font=SMALL_FONT, anchor="w"
        ).pack(fill="x")

        marks = []
        if slot.needs_phantom_liberty:
            marks.append("Phantom Liberty")
        if slot.is_modded:
            marks.append("modded")
        if marks:
            tk.Label(
                body, text=" / ".join(marks), bg=PANEL, fg=CYAN, font=SMALL_FONT, anchor="w"
            ).pack(fill="x", pady=(4, 0))

        for widget in self._every_widget():
            widget.bind("<Button-1>", self._clicked)

    def destroy(self) -> None:
        """Let go of the screenshot here, on the thread that made it.

        A PhotoImage finalised by the garbage collector calls back into Tcl, and if that
        collection happens on a worker thread the interpreter is being touched from the
        wrong thread. Dropping the reference during destroy keeps that on the main thread.
        """
        self._thumbnail = None
        super().destroy()

    def _every_widget(self):
        yield self
        stack = list(self.winfo_children())
        while stack:
            widget = stack.pop()
            yield widget
            stack.extend(widget.winfo_children())

    def _clicked(self, _event=None) -> None:
        self.on_pick(self.slot)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        self.configure(highlightbackground=ACCENT if selected else PANEL)


class ScrollArea(tk.Frame):
    """A scrollable column, which Tk does not provide on its own."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BACKGROUND, **kwargs)
        self.canvas = tk.Canvas(self, bg=BACKGROUND, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=BACKGROUND)

        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_inner(self, _event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _wheel(self, event) -> None:
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def clear(self) -> None:
        for child in self.inner.winfo_children():
            child.destroy()


def render_report(parent: tk.Misc, report: Report) -> None:
    """The findings, laid out the way the command line lays them out."""
    if not report.findings:
        tk.Label(
            parent,
            text="Nothing differs between the two machines.",
            bg=PANEL,
            fg="#5ddc8c",
            font=BODY_FONT,
            anchor="w",
        ).pack(fill="x", pady=2)
        return

    for item in report.sorted():
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=(6, 0))
        colour = SEVERITY_COLOUR[item.severity]
        tk.Label(
            row,
            text=SEVERITY_LABEL[item.severity],
            bg=PANEL,
            fg=colour,
            font=("Consolas", 8, "bold"),
            width=5,
            anchor="w",
        ).pack(side="left", anchor="n")
        body = tk.Frame(row, bg=PANEL)
        body.pack(side="left", fill="x", expand=True)
        tk.Label(
            body, text=item.summary, bg=PANEL, fg=TEXT, font=BODY_FONT,
            anchor="w", justify="left", wraplength=620,
        ).pack(fill="x")
        if item.detail:
            tk.Label(
                body, text=item.detail, bg=PANEL, fg=MUTED, font=SMALL_FONT,
                anchor="w", justify="left", wraplength=620,
            ).pack(fill="x")
        for entry in item.items[:10]:
            tk.Label(
                body, text="- " + entry, bg=PANEL, fg=MUTED, font=SMALL_FONT, anchor="w"
            ).pack(fill="x")
        if len(item.items) > 10:
            tk.Label(
                body, text=f"- and {len(item.items) - 10} more", bg=PANEL, fg=MUTED,
                font=SMALL_FONT, anchor="w",
            ).pack(fill="x")


class Window(tk.Tk):
    """The whole interface."""

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config_data = config
        self.worker = Worker(self)

        self.title("Engram")
        self.geometry("1000x680")
        self.minsize(860, 560)
        self.configure(bg=BACKGROUND)

        self.save_dir: Path | None = None
        self.game: paths.GameInstall | None = None
        self.local_mods: mods.ModSet | None = None
        self.cards: list[SaveCard] = []
        self.picked: saves.SaveSlot | None = None
        self.incoming: container.Bundle | None = None

        self._style()
        self._build()
        self._locate()

    def destroy(self) -> None:
        """Shut down in order: the poll, then the jobs, then the images, then the widgets."""
        self.worker.stop()
        for card in self.cards:
            card._thumbnail = None
        self.cards = []
        gc.collect()
        super().destroy()

    # ------------------------------------------------------------------ construction

    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Vertical.TScrollbar",
            background=PANEL_HIGH,
            troughcolor=BACKGROUND,
            bordercolor=BACKGROUND,
            arrowcolor=MUTED,
            relief="flat",
        )

    def _build(self) -> None:
        header = tk.Frame(self, bg=BACKGROUND)
        header.pack(fill="x", padx=24, pady=(18, 10))
        tk.Label(header, text="ENGRAM", bg=BACKGROUND, fg=ACCENT, font=TITLE_FONT).pack(
            side="left"
        )
        tk.Label(
            header,
            text="carry a save to another PC with a code",
            bg=BACKGROUND,
            fg=MUTED,
            font=BODY_FONT,
        ).pack(side="left", padx=(12, 0), pady=(8, 0))

        nav = tk.Frame(header, bg=BACKGROUND)
        nav.pack(side="right")
        self.send_tab = _button(nav, "Send a save", lambda: self._show("send"))
        self.send_tab.pack(side="left", padx=4)
        self.receive_tab = _button(nav, "Receive a save", lambda: self._show("receive"))
        self.receive_tab.pack(side="left", padx=4)

        self.body = tk.Frame(self, bg=BACKGROUND)
        self.body.pack(fill="both", expand=True, padx=24)

        self.views = {"send": self._build_send(), "receive": self._build_receive()}

        self.status = tk.Label(
            self, text="", bg=BACKGROUND, fg=MUTED, font=SMALL_FONT, anchor="w"
        )
        self.status.pack(fill="x", padx=26, pady=(6, 12))
        self._show("send")

    def _build_send(self) -> tk.Frame:
        view = tk.Frame(self.body, bg=BACKGROUND)

        left = tk.Frame(view, bg=BACKGROUND)
        left.pack(side="left", fill="both", expand=True)
        tk.Label(
            left, text="Your saves", bg=BACKGROUND, fg=TEXT, font=HEAD_FONT, anchor="w"
        ).pack(fill="x", pady=(0, 8))
        self.save_list = ScrollArea(left)
        self.save_list.pack(fill="both", expand=True)

        right = tk.Frame(view, bg=PANEL, width=380)
        right.pack(side="right", fill="both", padx=(18, 0))
        right.pack_propagate(False)

        self.send_panel = tk.Frame(right, bg=PANEL)
        self.send_panel.pack(fill="both", expand=True, padx=18, pady=18)
        self._send_placeholder()
        return view

    def _build_receive(self) -> tk.Frame:
        view = tk.Frame(self.body, bg=BACKGROUND)

        top = tk.Frame(view, bg=PANEL)
        top.pack(fill="x")
        inner = tk.Frame(top, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=18)

        tk.Label(
            inner,
            text="Type the code they read out",
            bg=PANEL,
            fg=TEXT,
            font=HEAD_FONT,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            text="Case and dashes do not matter.",
            bg=PANEL,
            fg=MUTED,
            font=SMALL_FONT,
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        row = tk.Frame(inner, bg=PANEL)
        row.pack(fill="x")
        self.code_entry = tk.Entry(
            row,
            font=("Consolas", 18),
            bg=PANEL_HIGH,
            fg=ACCENT,
            insertbackground=ACCENT,
            relief="flat",
            borderwidth=0,
        )
        self.code_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 12))
        self.code_entry.bind("<Return>", lambda _e: self._fetch())
        self.fetch_button = _button(row, "Get", self._fetch, primary=True)
        self.fetch_button.pack(side="left")

        self.receive_area = ScrollArea(view)
        self.receive_area.pack(fill="both", expand=True, pady=(14, 0))
        return view

    def _send_placeholder(self) -> None:
        for child in self.send_panel.winfo_children():
            child.destroy()
        tk.Label(
            self.send_panel,
            text="Pick a save on the left,\nthen press Share.",
            bg=PANEL,
            fg=MUTED,
            font=BODY_FONT,
            justify="left",
            anchor="w",
        ).pack(fill="x")

    # ------------------------------------------------------------------------ plumbing

    def _show(self, which: str) -> None:
        for view in self.views.values():
            view.pack_forget()
        self.views[which].pack(fill="both", expand=True)
        for name, button in (("send", self.send_tab), ("receive", self.receive_tab)):
            button.configure(
                fg=ACCENT if name == which else TEXT,
                bg=PANEL_HIGH if name == which else PANEL,
            )

    def _say(self, text: str, colour: str = MUTED) -> None:
        self.status.configure(text=text, fg=colour)

    def _locate(self) -> None:
        try:
            self.save_dir = paths.find_save_dir(self.config_data.save_dir)
        except paths.LocationError as exc:
            self._say(str(exc), RED)
            return
        try:
            self.game = paths.find_game_dir(self.config_data.game_dir)
        except paths.LocationError as exc:
            self._say(str(exc), AMBER)

        self._load_saves()
        if self.game is not None:
            self._say("reading the mod list", MUTED)
            self.worker.start(lambda: mods.scan(self.game), self._mods_ready)

    def _mods_ready(self, found, error) -> None:
        if error is not None:
            self._say(f"could not read the mod list: {error}", AMBER)
            self.local_mods = mods.ModSet()
            return
        self.local_mods = found
        where = self.game.path if self.game else "unknown"
        self._say(f"{len(found)} mod(s) found in {where}")

    def _load_saves(self) -> None:
        self.save_list.clear()
        self.cards = []
        if self.save_dir is None:
            return
        found = saves.list_saves(self.save_dir)
        if not found:
            tk.Label(
                self.save_list.inner,
                text="No saves in this folder yet.",
                bg=BACKGROUND,
                fg=MUTED,
                font=BODY_FONT,
            ).pack(anchor="w", pady=12)
            return
        for slot in found:
            card = SaveCard(self.save_list.inner, slot, self._pick)
            card.pack(fill="x", pady=4, ipadx=6)
            self.cards.append(card)
        self._pick(found[0])

    def _pick(self, slot: saves.SaveSlot) -> None:
        self.picked = slot
        for card in self.cards:
            card.set_selected(card.slot.folder_name == slot.folder_name)
        self._show_picked(slot)

    # -------------------------------------------------------------------------- send

    def _show_picked(self, slot: saves.SaveSlot) -> None:
        for child in self.send_panel.winfo_children():
            child.destroy()

        tk.Label(
            self.send_panel, text=slot.folder_name, bg=PANEL, fg=TEXT, font=HEAD_FONT,
            anchor="w",
        ).pack(fill="x")
        for label, value in (
            ("Level", f"{slot.level}, street cred {slot.street_cred}"),
            ("Life path", slot.life_path),
            ("Difficulty", slot.difficulty),
            ("Saved", slot.timestamp_string or "unknown"),
            ("Game", slot.build_patch or "unknown"),
            ("Needs", "Phantom Liberty" if slot.needs_phantom_liberty else "base game"),
            ("Size", f"{slot.size_bytes / 1048576:.1f} MB"),
        ):
            row = tk.Frame(self.send_panel, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=label, bg=PANEL, fg=MUTED, font=SMALL_FONT, width=11, anchor="w"
            ).pack(side="left")
            tk.Label(
                row, text=value, bg=PANEL, fg=TEXT, font=SMALL_FONT, anchor="w"
            ).pack(side="left", fill="x", expand=True)

        self.share_button = _button(
            self.send_panel, "Share this save", self._share, primary=True
        )
        self.share_button.pack(fill="x", pady=(16, 0))
        tk.Label(
            self.send_panel,
            text=(
                "The save is encrypted on this machine before it is uploaded. The key is "
                "the last part of the code, which is never sent anywhere."
            ),
            bg=PANEL,
            fg=MUTED,
            font=SMALL_FONT,
            wraplength=320,
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(12, 0))

    def _share(self) -> None:
        if self.picked is None or self.game is None:
            return
        slot = self.picked
        found = self.local_mods if self.local_mods is not None else mods.ModSet()
        secret = codes.new_secret()
        self.share_button.configure(state="disabled", text="Sharing...")
        self._say("packing and uploading, which takes a moment", CYAN)

        hosts = self.config_data.hosts()

        def job():
            last: Exception | None = None
            for host in hosts:
                blob, manifest = container.pack(slot, found, secret=secret, context=host.key)
                try:
                    result = upload(host, blob)
                except HostError as exc:
                    last = exc
                    continue
                return host, codes.format_code(host, result.file_id, secret), len(blob)
            raise last or HostError("no host would take the file")

        self.worker.start(job, self._share_done)

    def _share_done(self, value, error) -> None:
        if hasattr(self, "share_button") and self.share_button.winfo_exists():
            self.share_button.configure(state="normal", text="Share this save")
        if error is not None:
            self._say(str(error), RED)
            messagebox.showerror("Engram", str(error))
            return

        host, code, size = value
        self._say(f"uploaded {size / 1048576:.1f} MB to {host.label}", CYAN)

        for child in self.send_panel.winfo_children():
            child.destroy()
        tk.Label(
            self.send_panel, text="Read this out", bg=PANEL, fg=TEXT, font=HEAD_FONT,
            anchor="w",
        ).pack(fill="x")

        box = tk.Frame(self.send_panel, bg=PANEL_HIGH)
        box.pack(fill="x", pady=12)
        tk.Label(box, text=code, bg=PANEL_HIGH, fg=ACCENT, font=CODE_FONT).pack(
            padx=10, pady=14
        )

        from .ui import spoken

        tk.Label(
            self.send_panel, text=spoken(code), bg=PANEL, fg=MUTED, font=SMALL_FONT,
            wraplength=320, justify="left", anchor="w",
        ).pack(fill="x")

        _button(self.send_panel, "Copy the code", lambda: self._copy(code)).pack(
            fill="x", pady=(14, 0)
        )
        for label, value in (
            ("Host", host.label),
            ("Expires", host.expiry or "per the host"),
            ("They run", f"engram get {code}"),
        ):
            row = tk.Frame(self.send_panel, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=label, bg=PANEL, fg=MUTED, font=SMALL_FONT, width=11, anchor="w"
            ).pack(side="left")
            tk.Label(
                row, text=value, bg=PANEL, fg=TEXT, font=SMALL_FONT, anchor="w"
            ).pack(side="left", fill="x", expand=True)

        _button(
            self.send_panel, "Back to the save list", lambda: self._pick(self.picked)
        ).pack(fill="x", pady=(16, 0))

    def _copy(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self._say("code copied to the clipboard", CYAN)

    # ----------------------------------------------------------------------- receive

    def _fetch(self) -> None:
        raw = self.code_entry.get().strip()
        if not raw:
            self._say("type the code first", AMBER)
            return
        try:
            parsed = codes.parse_code(raw)
        except CodeError as exc:
            self._say(str(exc), RED)
            self.receive_area.clear()
            tk.Label(
                self.receive_area.inner, text=str(exc), bg=BACKGROUND, fg=RED,
                font=BODY_FONT, wraplength=820, justify="left", anchor="w",
            ).pack(fill="x", pady=8)
            return

        host = self.config_data.host_by_key(parsed.host.key) or parsed.host
        self.fetch_button.configure(state="disabled", text="...")
        self._say(f"downloading from {host.label}", CYAN)

        def job():
            blob = download(host, parsed.file_id)
            bundle = container.unpack(blob, secret=parsed.secret)
            return bundle, len(blob)

        self.worker.start(job, self._fetch_done)

    def _fetch_done(self, value, error) -> None:
        self.fetch_button.configure(state="normal", text="Get")
        self.receive_area.clear()
        if error is not None:
            self._say(str(error), RED)
            tk.Label(
                self.receive_area.inner, text=str(error), bg=BACKGROUND, fg=RED,
                font=BODY_FONT, wraplength=820, justify="left", anchor="w",
            ).pack(fill="x", pady=8)
            return

        bundle, size = value
        self.incoming = bundle
        report = compare.build_report(
            slot_meta=bundle.manifest.save,
            sender_mods=bundle.manifest.mods,
            receiver_mods=self.local_mods if self.local_mods is not None else mods.ModSet(),
            receiver_game_version=(
                compare.local_game_version(self.save_dir) if self.save_dir else None
            ),
            running=running.check(),
        )
        self._say(compare.summarise(report), RED if report.blocked else CYAN)
        self._render_incoming(bundle.manifest, report, size)

    def _render_incoming(self, manifest: Manifest, report: Report, size: int) -> None:
        panel = tk.Frame(self.receive_area.inner, bg=PANEL)
        panel.pack(fill="x")
        inner = tk.Frame(panel, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=18)

        tk.Label(
            inner, text=manifest.display_name, bg=PANEL, fg=TEXT, font=HEAD_FONT, anchor="w"
        ).pack(fill="x")
        tk.Label(
            inner, text=manifest.describe(), bg=PANEL, fg=MUTED, font=BODY_FONT, anchor="w"
        ).pack(fill="x")
        tk.Label(
            inner,
            text=(
                f"game {manifest.save.get('buildPatch') or 'unknown'}  /  "
                f"{len(manifest.mods)} mod(s) on the sender's machine  /  "
                f"{size / 1048576:.1f} MB"
            ),
            bg=PANEL,
            fg=MUTED,
            font=SMALL_FONT,
            anchor="w",
        ).pack(fill="x", pady=(2, 10))

        tk.Label(
            inner, text=compare.summarise(report), bg=PANEL,
            fg=RED if report.blocked else TEXT, font=HEAD_FONT, anchor="w",
        ).pack(fill="x", pady=(8, 2))
        render_report(inner, report)

        buttons = tk.Frame(inner, bg=PANEL)
        buttons.pack(fill="x", pady=(18, 0))
        if report.blocked:
            tk.Label(
                buttons,
                text=(
                    "Engram will not write this save while the items above stand. "
                    "Install what is missing and press Get again."
                ),
                bg=PANEL,
                fg=AMBER,
                font=SMALL_FONT,
                wraplength=620,
                justify="left",
                anchor="w",
            ).pack(fill="x", pady=(0, 10))
            _button(
                buttons, "Write it anyway", lambda: self._write(force=True)
            ).pack(side="left")
        else:
            _button(
                buttons, "Write this save", lambda: self._write(force=False), primary=True
            ).pack(side="left")
        _button(buttons, "Cancel", self._cancel_incoming).pack(side="left", padx=8)

    def _cancel_incoming(self) -> None:
        self.incoming = None
        self.receive_area.clear()
        self._say("nothing was written")

    def _write(self, force: bool) -> None:
        if self.incoming is None or self.save_dir is None:
            return
        if force and not messagebox.askyesno(
            "Engram",
            "The checks said this save may not load on this machine.\n\n"
            "Write it anyway?",
        ):
            return

        bundle = self.incoming
        slot_name = saves.free_slot_name(self.save_dir, self.config_data.slot_prefix)
        try:
            written = saves.install_save(self.save_dir, slot_name, bundle.files)
        except (saves.SaveError, OSError) as exc:
            self._say(str(exc), RED)
            messagebox.showerror("Engram", str(exc))
            return

        self.incoming = None
        self._say(f"written to {written}", "#5ddc8c")
        self.receive_area.clear()
        done = tk.Frame(self.receive_area.inner, bg=PANEL)
        done.pack(fill="x")
        inner = tk.Frame(done, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=18)
        tk.Label(
            inner, text=f"Written as {slot_name}", bg=PANEL, fg="#5ddc8c", font=HEAD_FONT,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            text="Start Cyberpunk and it is in the load list.",
            bg=PANEL,
            fg=TEXT,
            font=BODY_FONT,
            anchor="w",
        ).pack(fill="x", pady=(4, 0))
        tk.Label(
            inner, text=str(written), bg=PANEL, fg=MUTED, font=MONO_FONT, anchor="w"
        ).pack(fill="x", pady=(8, 0))
        self._load_saves()


def run(config: Config) -> int:
    """Open the window. Returns a shell exit code."""
    try:
        window = Window(config)
    except tk.TclError as exc:
        print(f"Engram: could not open a window: {exc}")
        return 1
    window.mainloop()
    return 0


def main() -> int:
    """Entry point for the windowed launcher, which gets no command line."""
    from .config import ConfigError, load

    try:
        return run(load())
    except ConfigError as exc:
        print(f"Engram: {exc}")
        return 1
