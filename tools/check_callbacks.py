"""Check that every callback the mod registers has a handler the engine will actually call.

redscript matches callbacks by signature at runtime. A handler whose parameter type is
wrong is simply never called: the compiler is happy, the game starts, the button renders,
and pressing it does nothing at all. There is no log line and nothing to search for.

That is exactly how Engram shipped a popup whose buttons did nothing. The handler took a
`wref<inkButtonController>` where Codeware's `CallCustomCallback` hands over the button's
own root widget, so it never matched.

This reads the mod's redscript, finds every registration, and checks the handler exists and
takes what that event actually delivers.

    python tools/check_callbacks.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "mod" / "r6" / "scripts" / "Engram"

#: What each kind of event hands its handler.
#:
#: Custom callbacks raised through inkWidget.CallCustomCallback deliver the widget. That
#: covers Codeware's buttons, whose CustomButton.OnRelease ends in
#: CallCustomCallback(n"OnBtnClick"), and matches how Codeware's own OnConfirmClick and
#: OnCancelClick are declared.
CUSTOM_WIDGET_CALLBACKS = {"OnBtnClick"}

#: Pointer events the engine raises on a widget.
POINTER_CALLBACKS = {
    "OnPress", "OnRelease", "OnEnter", "OnLeave", "OnHoverOver", "OnHoverOut", "OnClick",
}

EXPECTED = {
    "custom": "wref<inkWidget>",
    "pointer": "ref<inkPointerEvent>",
    "anim": "ref<inkAnimProxy>",
    "notification": "ref<inkGameNotificationData>",
}

_REGISTER_WIDGET = re.compile(
    r"RegisterToCallback\(\s*n\"(?P<event>\w+)\"\s*,\s*this\s*,\s*n\"(?P<handler>\w+)\"\s*\)"
)
_REGISTER_ANIM = re.compile(
    r"RegisterToCallback\(\s*inkanimEventType\.\w+\s*,\s*this\s*,\s*n\"(?P<handler>\w+)\"\s*\)"
)
_REGISTER_LISTENER = re.compile(
    r"RegisterListener\(\s*this\s*,\s*n\"(?P<handler>\w+)\"\s*\)"
)
_HANDLER = re.compile(
    r"(?:protected|public|private)?\s*cb\s+func\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)",
)


def handlers_in(text: str) -> dict[str, str]:
    """Every callback handler and the type of its first parameter."""
    found = {}
    for match in _HANDLER.finditer(text):
        args = match.group("args").strip()
        first = args.split(",")[0].strip() if args else ""
        found[match.group("name")] = first.split(":", 1)[1].strip() if ":" in first else ""
    return found


def kind_of(event: str) -> str:
    if event in CUSTOM_WIDGET_CALLBACKS:
        return "custom"
    if event in POINTER_CALLBACKS:
        return "pointer"
    return ""


def main() -> int:
    problems: list[str] = []
    checked = 0

    for path in sorted(SCRIPTS.glob("*.reds")):
        text = path.read_text(encoding="utf-8")
        handlers = handlers_in(text)

        wanted: list[tuple[str, str, str]] = []
        for match in _REGISTER_WIDGET.finditer(text):
            event, handler = match.group("event"), match.group("handler")
            kind = kind_of(event)
            if not kind:
                problems.append(
                    f"{path.name}: {event} is registered but this checker does not know "
                    "what it delivers. Add it to CUSTOM_WIDGET_CALLBACKS or "
                    "POINTER_CALLBACKS once you have checked the source."
                )
                continue
            wanted.append((handler, kind, event))

        for match in _REGISTER_ANIM.finditer(text):
            wanted.append((match.group("handler"), "anim", "an animation event"))

        for match in _REGISTER_LISTENER.finditer(text):
            wanted.append((match.group("handler"), "notification", "a notification token"))

        for handler, kind, event in wanted:
            checked += 1
            if handler not in handlers:
                problems.append(
                    f"{path.name}: {event} is registered to {handler}, which is not a "
                    "cb func in this file. It will never be called."
                )
                continue

            expected = EXPECTED[kind]
            actual = handlers[handler]
            if actual != expected:
                problems.append(
                    f"{path.name}: {handler} takes {actual or 'nothing'} but {event} "
                    f"delivers {expected}. redscript matches callbacks by signature, so "
                    "this handler is never called and the control silently does nothing."
                )

    print(f"checked {checked} callback registration(s)")
    if problems:
        print(f"\n{len(problems)} problem(s):\n")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("every registered callback has a handler with the right signature")
    return 0


if __name__ == "__main__":
    sys.exit(main())
