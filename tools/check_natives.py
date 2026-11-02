"""Check that every native the redscript declares is one the plugin registers.

`scc.exe` compiles redscript happily whether or not a native actually exists. The check
happens later, inside the game, when RED4ext validates the scripts against RTTI. If it
fails there the game refuses to start at all, with a dialog and nothing else, which is a
very expensive way to find out about a spelling mistake.

So this compares the two sides directly:

  - the native class and functions declared in mod/r6/scripts/Engram/*.reds
  - the class and functions registered in native/src/Main.cpp

It also checks the thing that actually broke once: a native class declared inside a module
is namespaced by it, so `module Engram` above a native class declares `Engram.EngramNative`
and RED4ext looks for an RTTI class that does not exist. Native declarations belong in a
file with no module line, which is how Codeware and ArchiveXL do it.

    python tools/check_natives.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "mod" / "r6" / "scripts" / "Engram"
MAIN = ROOT / "native" / "src" / "Main.cpp"

_NATIVE_CLASS = re.compile(
    r"^\s*(?:public\s+|abstract\s+)*native\s+class\s+(?P<name>\w+)", re.MULTILINE
)
_NATIVE_FUNC = re.compile(
    r"^\s*public\s+static\s+native\s+func\s+(?P<name>\w+)\s*\((?P<args>[^)]*)\)"
    r"\s*(?:->\s*(?P<returns>[\w<>]+))?",
    re.MULTILINE,
)
_MODULE = re.compile(r"^\s*module\s+", re.MULTILINE)

_REGISTERED_CLASS = re.compile(r'TTypedClass<\w+>\s+g_class\("(?P<name>\w+)"\)')
_REGISTERED_SIMPLE = re.compile(
    r'CClassStaticFunction::Create\(\s*&g_class,\s*"(?P<name>\w+)"'
)
_REGISTERED_TABLE = re.compile(
    r'\{\s*"(?P<name>\w+)",\s*&\w+,\s*(?P<returns>nullptr|"[^"]*"),\s*\{(?P<takes>[^}]*)\}\s*\}'
)

#: redscript type name for each type the table registers.
_TYPES = {
    "String": "String",
    "Int32": "Int32",
    "Bool": "Bool",
    "Float": "Float",
    "array:String": "array<String>",
    None: "Void",
}


def declared() -> tuple[dict[str, dict], list[str]]:
    """What the redscript says exists, and anything structurally wrong with how."""
    problems: list[str] = []
    functions: dict[str, dict] = {}
    classes: dict[str, Path] = {}

    for path in sorted(SCRIPTS.glob("*.reds")):
        text = path.read_text(encoding="utf-8")
        found = _NATIVE_CLASS.findall(text)
        if not found:
            continue

        # The bug that stopped the game starting: a module line above a native class.
        if _MODULE.search(text):
            problems.append(
                f"{path.name} declares a native class but has a module line. A native class "
                "inside a module is namespaced by it, so RED4ext looks for an RTTI class "
                "that does not exist and refuses to start the game. Move the declaration "
                "to a file with no module line."
            )

        for name in found:
            classes[name] = path

        for match in _NATIVE_FUNC.finditer(text):
            args = [a.strip() for a in match.group("args").split(",") if a.strip()]
            types = [a.split(":", 1)[1].strip() for a in args if ":" in a]
            functions[match.group("name")] = {
                "takes": types,
                "returns": (match.group("returns") or "Void").strip(),
                "file": path.name,
            }

    return {"classes": classes, "functions": functions}, problems


def registered() -> dict:
    """What the plugin actually puts into RTTI."""
    text = MAIN.read_text(encoding="utf-8")

    class_match = _REGISTERED_CLASS.search(text)
    classes = {class_match.group("name")} if class_match else set()

    functions: dict[str, dict] = {}
    for match in _REGISTERED_SIMPLE.finditer(text):
        functions.setdefault(match.group("name"), {"takes": [], "returns": None})

    for match in _REGISTERED_TABLE.finditer(text):
        returns = match.group("returns")
        takes = [t.strip().strip('"') for t in match.group("takes").split(",") if t.strip()]
        functions[match.group("name")] = {
            "takes": takes,
            "returns": None if returns == "nullptr" else returns.strip('"'),
        }

    # The simple registrations set their return type on a following line.
    for name in list(functions):
        if functions[name]["returns"] is None and not functions[name]["takes"]:
            pattern = re.compile(
                rf'Create\(\s*&g_class,\s*"{name}".*?SetReturnType\("([^"]+)"\)', re.DOTALL
            )
            found = pattern.search(text)
            if found:
                functions[name]["returns"] = found.group(1)

    return {"classes": classes, "functions": functions}


def main() -> int:
    mine, problems = declared()
    theirs = registered()

    for name in sorted(mine["classes"]):
        if name not in theirs["classes"]:
            problems.append(
                f"the scripts declare native class {name}, which the plugin does not "
                f"register. RED4ext will refuse to start the game."
            )

    missing = sorted(set(mine["functions"]) - set(theirs["functions"]))
    for name in missing:
        problems.append(
            f"{name} is declared native in {mine['functions'][name]['file']} but the plugin "
            "does not register it"
        )

    unused = sorted(set(theirs["functions"]) - set(mine["functions"]))

    for name in sorted(set(mine["functions"]) & set(theirs["functions"])):
        ours = mine["functions"][name]
        plugin = theirs["functions"][name]

        expected_return = _TYPES.get(plugin["returns"], plugin["returns"] or "Void")
        if ours["returns"] != expected_return:
            problems.append(
                f"{name} returns {ours['returns']} in the scripts but "
                f"{expected_return} in the plugin"
            )

        expected_takes = [_TYPES.get(t, t) for t in plugin["takes"]]
        if ours["takes"] != expected_takes:
            problems.append(
                f"{name} takes ({', '.join(ours['takes'])}) in the scripts but "
                f"({', '.join(expected_takes)}) in the plugin"
            )

    print(f"scripts    {len(mine['functions'])} native function(s), "
          f"{len(mine['classes'])} native class(es)")
    print(f"plugin     {len(theirs['functions'])} registered, "
          f"{len(theirs['classes'])} class(es)")
    if unused:
        print(f"registered but unused by the scripts: {', '.join(unused)}")

    if problems:
        print(f"\n{len(problems)} problem(s):\n")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print("\nevery native the scripts declare is registered, with matching signatures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
