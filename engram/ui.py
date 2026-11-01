"""Printing. Plain text that happens to use colour when the terminal supports it.

Everything here degrades to readable output with no escape codes, because people run this
in whatever shell they already had open, and a save transfer tool that prints garbage
characters does not inspire confidence in the part that writes to disk.
"""

from __future__ import annotations

import ctypes
import os
import sys

from .compare import BLOCK, NOTE, WARN, Finding, Report

_CODES = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "yellow": "\x1b[33m",
    "green": "\x1b[32m",
    "cyan": "\x1b[36m",
}

_MARKERS = {BLOCK: ("stop", "red"), WARN: ("warn", "yellow"), NOTE: ("note", "dim")}


def _enable_windows_colour() -> bool:
    if sys.platform != "win32":
        return True
    try:
        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (OSError, AttributeError):
        return False


def _colour_wanted() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    return _enable_windows_colour()


_COLOUR = _colour_wanted()


def paint(text: str, *styles: str) -> str:
    if not _COLOUR or not styles:
        return text
    prefix = "".join(_CODES.get(s, "") for s in styles)
    return f"{prefix}{text}{_CODES['reset']}" if prefix else text


def say(text: str = "") -> None:
    print(text)


def warn(text: str) -> None:
    print(paint(text, "yellow"), file=sys.stderr)


def fail(text: str) -> None:
    print(paint("Engram: " + text, "red"), file=sys.stderr)


def heading(text: str) -> None:
    print()
    print(paint(text, "bold"))


def field(label: str, value: str, width: int = 16) -> None:
    print(f"  {label.ljust(width)} {value}")


def code_block(code: str) -> None:
    """The code, given room, because this is the thing being read out loud."""
    print()
    print("    " + paint(code, "bold", "cyan"))
    print()


def spoken(code: str) -> str:
    """How to say a code, for the sender who is about to read it over voice chat."""
    names = {"0": "zero", "1": "one"}
    parts = []
    for group in code.split("-"):
        parts.append(" ".join(names.get(ch, ch) for ch in group))
    return ",  ".join(parts)


def finding(item: Finding, show_items: bool = True, limit: int = 12) -> None:
    marker, colour = _MARKERS[item.severity]
    print(f"  {paint('[' + marker + ']', colour)} {item.summary}")
    if item.detail:
        for line in _wrap(item.detail, 76):
            print(f"        {paint(line, 'dim')}")
    if show_items and item.items:
        for entry in item.items[:limit]:
            print(f"        - {entry}")
        if len(item.items) > limit:
            print(f"        - and {len(item.items) - limit} more")


def report(result: Report, show_items: bool = True) -> None:
    if not result.findings:
        say("  " + paint("[ ok ]", "green") + " nothing differs between the two machines")
        return
    for item in result.sorted():
        finding(item, show_items=show_items)


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def confirm(question: str, default: bool = False) -> bool:
    """Ask, and treat a shell with no input attached as a no."""
    suffix = " [Y/n] " if default else " [y/N] "
    if not sys.stdin or not sys.stdin.isatty():
        return default
    try:
        answer = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    return answer in ("y", "yes")


def megabytes(size: int) -> str:
    return f"{size / 1048576:.1f} MB"
