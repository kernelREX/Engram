# Engram

Move a Cyberpunk 2077 save to another PC by reading a code out loud.

```
C0FE-GGYV-7FPR-4TQX
```

That is the whole thing. No accounts, no logins, no file to find and attach. One person
picks a save and gets a code. The other person types it in and the save turns up in their
load list.

An engram is the game's own word for a stored personality you move between bodies, which
is close enough to what this does to a save.

---

## Where to find it

Install the mod and **Engram** appears in the main menu and the pause menu, just after the
Mods entry. Everything happens from there: pick a save, get a code, or type in a code
somebody read out to you.

Engram has no account of any kind. No mod.io, no logins, nothing to sign up for.

There is also a standalone tool for moving a save with no mod installed, no game running,
or no network at all. It is described further down.

---

## Installing the mod

You need [RED4ext](https://www.nexusmods.com/cyberpunk2077/mods/2380) and
[Codeware](https://www.nexusmods.com/cyberpunk2077/mods/7780). Most modded installs already
have both.

Extract `Engram-1.0.0.zip` into your Cyberpunk 2077 folder, the one with `bin`, `r6` and
`archive` in it. Vortex and Mod Organizer handle the archive as it is.

To remove it, delete these two folders:

```
red4ext/plugins/Engram
r6/scripts/Engram
```

---

## You are always told what the save was made with

Every save carries the list of mods that were installed when it was made, and both people
see that list.

**The sender** sees it before the code exists, so they can stop if they did not mean to
share a modded save. **The receiver** sees it before anything is written, so they know what
is inside the save they are about to load. Mods that keep state in the save and mods that
add records are called out in the list, because those are the two that actually change what
the save does on another machine.

A save made with no mods says that plainly rather than saying nothing.

---

## What Engram checks before it writes anything

This is the part that matters. A save made with mods carries their state inside `sav.dat`,
and the game will not tell you when something is wrong with that. Engram records the
sender's mod list, compares it against yours, and sorts the differences into three groups.

**It stops** when the save almost certainly will not load:

- You are missing a mod that adds records through ArchiveXL or TweakXL. Items, vehicles
  and clothing from those mods are referred to by name inside the save, and those names
  will not resolve on your machine.
- You are missing ArchiveXL or TweakXL themselves.
- The save is from a newer patch than your game. Cyberpunk does not read those.
- The save needs Phantom Liberty and you do not have it.
- Cyberpunk is open, when you are using the standalone tool. It writes over this folder
  and will not notice a save that appears while it is running. This does not apply in the
  mod, which is already inside the game: there it just reminds you that the load list is
  built when the menu opens, so step back out to the main menu to see the new save.

**It warns** when the save will load but something may be quietly wrong:

- You have a mod the sender has, at a different version, and that mod keeps state in the
  save. This is the one to read. If the mod changed its persistent fields between those
  two versions, the game drops that mod's data when the save loads. Nothing fails, nothing
  is reported, and everything the mod was tracking is gone. It looks like a brand new
  playthrough. Match the sender's version first if you care about that progress.
- You are missing a redscript mod the sender has. Its state sits in the save unread. This
  is usually harmless, and the state comes back if you install the mod later.
- Steam is running. Steam Cloud syncs the save folder and can replace an imported save
  with its cloud copy within seconds, which looks exactly like the import having failed.
  Close Steam, import, then start it again.

**It notes** everything else: mods you have that the sender does not, version differences
in mods that keep no state, an older save on a newer patch, and the game's own modded
flag, which disables achievements while you play that save.

Nothing is written until you have seen all of that and agreed to it.

---

## Where the save goes

Into a new folder next to your own saves, named `EngramSave-1`, then `EngramSave-2`, and
so on. Engram never writes over a save that is already there.

`EnabledMods.json` is shared by every save and is never copied, so an import cannot change
which mods you have enabled.

---

## Your save, and who can read it

The save is encrypted on your machine before it is uploaded, with AES-256-GCM. The key
comes from the last eight characters of the code, which are generated locally and never
sent anywhere. The file host receives a blob and a filename it made up itself. It cannot
read your save, and neither can anybody who stumbles across the link without the code.

The trade is that the code is the only copy of the key. Lose the code and the save is
gone. That is the correct behaviour for a thing whose whole purpose is a code.

**There is a route that needs no host at all.** When you share, the last option is
**Save to a file instead**. It writes a `.engram` file into an Engram folder beside your
Cyberpunk saves. Move that file to the other PC however you like, drop it in the same
folder there, and pick **Open a file someone sent**. Same checks, same mod list, no
network and nobody else's server involved. The hosts are free services run by volunteers
and they do go down, so this is worth knowing about before you need it.

**You choose how long the code lasts.** After picking a save you pick a lifetime: 1 hour,
12 hours, 1 day, or 3 days. The file is removed from the host when it runs out and the code
stops working. Shorter is safer, and 3 days is the longest the host allows. From the
standalone tool it is `--expiry`, in hours.

A code that has stopped working has usually just run out.

One thing worth saying plainly: `sav.dat` is a binary going into the game's own loader.
Engram checks that the file matches the hashes the sender recorded and that it starts like
a Cyberpunk save, which catches damage and tampering in transit. It cannot tell you
whether a stranger meant well. Take codes from people you know.

---

## The standalone tool

The mod is the way most people will use Engram. The tool is for the times it cannot help:
no mod installed, the game will not start, a friend who does not mod, or no network at all.

Download `engram.exe` and run it from a terminal. It needs nothing installed.

**Sending:**

```
engram share ManualSave-1
```

```
sharing ManualSave-1
  save             level 60 StreetKid, 105h 15m played, saved 19:09:31, 2.08.2026
  mods recorded    32
  sealed           4.6 MB, AES-256-GCM
  uploading to Litterbox, which keeps it for 72h

  Read this out. It is the whole thing the other person needs.

    C0FE-GGYV-7FPR-4TQX

  C zero F E,  G G Y V,  7 F P R,  4 T Q X
```

**Receiving:**

```
engram get C0FE-GGYV-7FPR-4TQX
```

Same checks, same report, same refusal to overwrite anything.

**With no internet at all**, which also works when every free file host is down:

```
engram pack ManualSave-1 -o myrun.engram
```

Put the file on a USB stick, or in a chat window, then on the other machine:

```
engram unpack myrun.engram
```

`--seal` encrypts that file and prints a passphrase for it.

There is a window too, if you would rather click than type:

```
engram gui
```

### Commands

| Command | What it does |
|---|---|
| `engram share [save]` | Upload a save and print a code. Uses the newest save if you name none. `--expiry HOURS` sets how long it lasts. |
| `engram get <code>` | Fetch a save from a code, check it, and write it. |
| `engram pack [save]` | Write a save to a `.engram` file. |
| `engram unpack <file>` | Write a save back out of a `.engram` file. |
| `engram inspect <code or file>` | Show what it holds and what would differ. Writes nothing. |
| `engram saves` | List the saves on this machine. |
| `engram mods` | List the mods Engram can see, and which ones keep state in saves. |
| `engram doctor` | Show everything Engram found: folders, versions, hosts, what is running. |
| `engram config` | Show settings, or write a settings file with `--init`. |
| `engram gui` | Open the window. |

Useful flags: `--dry-run` to check without writing, `--force` to go ahead past a stop,
`--yes` to skip the question, `--into <slot>` to choose where it lands, `--save-dir` and
`--game-dir` when Engram guesses wrong.

---

## When something is not right

**It asked me to sign in to mod.io.** That is not Engram. Engram uses no account at all.
If you see it, something has moved the main menu's entries around, because the game
hardcodes the position of its own mod.io button. Report it with your mod list.

**Engram is not in the menu.** Check that `red4ext/plugins/Engram/Engram.dll` and
`r6/scripts/Engram/` both exist, and that RED4ext and Codeware are installed. If the game
starts with every mod disabled, look in `r6/logs/redscript_rCURRENT.log`.

**Engram cannot find my game.** Run `engram doctor` to see where it looked. It reads the
Steam library list, the GOG registry entries and the Epic manifests, and it only accepts a
folder with `bin/x64/Cyberpunk2077.exe` in it, so a leftover mod folder is not mistaken for
an install. Point it at the right place with `--game-dir`.

**The code does not work.** If it says the file is gone, it has probably expired, since
codes last 72 hours. If it downloads and then says the secret did not open it, the last
eight characters are wrong.

**A host refuses to take the file.** Engram knows three and tries each in turn, and tells
you what every one of them said rather than only the last. If both refuse, use
**Save to a file instead**, which needs no host. Which host a code is on is baked into its first character, so old codes keep
working when the default changes. If both are down, `engram pack` still works and needs
nothing but a USB stick.

**I want to change which hosts it uses.** `engram config --init` writes a settings file you
can edit. The host addresses live in there, so a broken one can be fixed without waiting
for a new release.

**The imported save vanished.** Steam Cloud. Close Steam, import again, then start Steam.

---

## For mod authors

If your mod keeps state in the save, say so, and Engram will tell people when their version
does not match the sender's. Drop an `engram.json` beside your mod:

```json
{
  "name": "Cyberbane",
  "version": "1.4.5",
  "writesPersistentState": true
}
```

Without it, Engram reads versions out of DLL resources, REDmod `info.json` files, Lua
sources and folder names, and guesses at persistent state by looking for `persistent let`
in your redscript sources. The guess is usually right. Your declaration is always right.

---

## Building it yourself

The mod needs Visual Studio Build Tools with the C++ workload and the Windows SDK.

```
git clone --recurse-submodules https://github.com/tfthushaar/Engram
cd Engram/native
cmake -B build -S . -A x64
cmake --build build --config Release
cd ..
python tools/build_mod_zip.py
```

That writes `dist/Engram-1.0.0.zip`. `tools/check_redscript.py` compiles the mod's
redscript with the game's own compiler without launching Cyberpunk, which is worth running
before any install, because a redscript mistake disables every mod on the next launch.

The standalone tool needs Python 3.10 or newer and one package:

```
pip install -e .
python -m pytest
pyinstaller engram.spec
```

---

## Licence

MIT. See [LICENSE](LICENSE).
