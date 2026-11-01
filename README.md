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

## What it looks like

**Sending.** Save the game, quit, run one command:

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

**Receiving.** The other person runs:

```
engram get C0FE-GGYV-7FPR-4TQX
```

Engram downloads the save, compares your mods against theirs, shows you anything that
differs, and writes the save once you say yes. Start the game and it is in the load list.

There is a window too, if you would rather click than type:

```
engram gui
```

---

## Installing

You need Python 3.10 or newer.

```
pip install git+https://github.com/tfthushaar/Engram
```

If you would rather have a single file to hand around, build one:

```
pip install pyinstaller
pyinstaller engram.spec
```

That leaves `engram.exe` in `dist`, and it needs nothing else installed.

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
- Cyberpunk is open. It writes over this folder and will not notice a save that appears
  while it is running.

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

Nothing is written until you have seen all of that and said yes. If you disagree with a
stop, `--force` goes ahead anyway.

To look without committing to anything:

```
engram inspect C0FE-GGYV-7FPR-4TQX
engram get C0FE-GGYV-7FPR-4TQX --dry-run
```

---

## Where the save goes

Into a new folder next to your own saves, named `EngramSave-1`, then `EngramSave-2`, and
so on. Engram never writes over a save that is already there. If you point it at an
existing slot with `--into`, it copies that slot somewhere safe first and tells you where.

`EnabledMods.json` is shared by every save and is never copied, so an import cannot change
which mods you have enabled.

---

## Without the internet

The code route is a convenience on top of something simpler that always works:

```
engram pack ManualSave-1 -o myrun.engram
```

Put the file on a USB stick, or in a chat window, or anywhere else, then on the other
machine:

```
engram unpack myrun.engram
```

Same checks, same report, same refusal to overwrite anything. `--seal` encrypts the file
and prints a passphrase for it, if it is going somewhere you would rather it was not
readable.

---

## Your save, and who can read it

The save is encrypted on your machine before it is uploaded, with AES-256-GCM. The key
comes from the last eight characters of the code, which are generated locally and never
sent anywhere. The file host receives a blob and a filename it made up itself. It cannot
read your save, and neither can anybody who stumbles across the link without the code.

The trade is that the code is the only copy of the key. Lose the code and the save is
gone. That is the correct behaviour for a thing whose whole purpose is a code.

Files expire from the host after 72 hours. A code that has stopped working has usually
just run out.

One thing worth saying plainly: `sav.dat` is a binary going into the game's own loader.
Engram checks that the file matches the hashes the sender recorded and that it starts like
a Cyberpunk save, which catches damage and tampering in transit. It cannot tell you
whether a stranger meant well. Take codes from people you know.

---

## Commands

| Command | What it does |
|---|---|
| `engram share [save]` | Upload a save and print a code. Uses the newest save if you name none. |
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

**Engram cannot find my game.** Run `engram doctor` to see where it looked. It reads the
Steam library list, the GOG registry entries and the Epic manifests, and it only accepts a
folder with `bin/x64/Cyberpunk2077.exe` in it, so a leftover mod folder is not mistaken for
an install. Point it at the right place with `--game-dir`.

**The code does not work.** If it says the file is gone, it has probably expired, since
codes last 72 hours. If it downloads and then says the secret did not open it, the last
four characters are wrong.

**A host refuses to take the file.** Engram knows more than one, and tries the next one by
itself. Which host a code is on is baked into its first character, so old codes keep
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

## Licence

MIT. See [LICENSE](LICENSE).
