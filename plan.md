# Engram - carry a Cyberpunk 2077 save to another PC with a code

*Working name. An engram is the game's own word for a stored personality you move between
bodies, which is exactly what this does to a save.*

## The flow, and it is the whole product

**Sender.** Saves the game. Opens Engram, picks the save, presses Share. Gets a code:

```
K7P2-9XMR-4TBQ
```

Reads it to their friend over voice chat. That is their entire involvement.

**Receiver.** Opens Engram, pastes the code, presses Get. Engram downloads the save, compares
the sender's mod list against their own, shows anything that differs, and writes the save once
they accept. They start Cyberpunk and it is in the load list.

No files, no uploads to find, no accounts, no logins. One code said out loud.

---

## Is it possible? Yes, and it needs no server at all

A save is about 6 MB (measured below). Several file hosts accept an anonymous upload over
plain HTTP, with no account and no key, and hand back a short URL. That is the entire backend.

**Litterbox** (run by catbox.moe) is the best fit. Anonymous upload, up to 1 GB, and the file
expires on a timer you choose between one hour and three days. Expiry is a feature here rather
than a limitation: a code that stops working after three days is exactly what you want a code
to do. **0x0.st** is the second: anonymous, 512 MiB, retention scaled by file size, and it
supports secret URLs and delete tokens. Both numbers are from third-party documentation, so
check each service's own page before writing against it.

These are volunteer-run, so the client should know how to talk to more than one and fall back.

**Google Drive, honestly.** There are two ways to do it and both fail, for different reasons.

*Shared credentials in the mod.* Whatever you embed, a refresh token or a service account
file, anybody who downloads the mod can extract. The Drive gets abused, Google suspends the
account, every outstanding code dies at once. Any design that hides a secret inside a program
you hand to strangers ends this way.

*Each sender signs in with their own Drive.* This one genuinely works: the sender uploads to
their own Drive with the `drive.file` scope, makes the file link-shareable, and the receiver
needs no account at all. The problem is the sender. They now have to sign in to Google to send
a save to a friend, which is precisely the work you asked to remove, and on top of that an
unverified OAuth app is capped at a hundred users until you take it through Google's
verification process. You would be adding a login and a bureaucracy to buy something the free
hosts give you for nothing.

**If it ever outgrows the free hosts**, Cloudflare R2 behind a Worker is the upgrade: reported
free tier of 10 GB storage with 1 million class A and 10 million class B operations a month,
Workers free at 100,000 requests a day, and no egress charge, which is the only thing this
does in volume. That is a decision for the day it is needed, not for day one.

---

## The design that makes the whole thing free: the code is the address

These hosts hand back a short URL. A Litterbox one looks like
`https://litter.catbox.moe/8kq2mz.bin`, where only `8kq2mz` is actually unique.

So do not store a mapping anywhere. **Put the file id in the code**, with a one-character tag
for which host it is on and a random secret that never leaves either machine:

```
  L  -  8KQ2MZ  -  7FPR4TQX
  |      |           |
  |      |           the secret: encrypts the save, never uploaded
  |      the host's own file id
  the host: L litterbox, Z 0x0.st
```

Said aloud as "L, eight-kay-cue-two-em-zed, seven-eff-pee-arr-four-tee-cue-ex". Fifteen
characters, and it needs no database, no server, no account and nothing to pay for, because
there is nothing to look anything up in. The code **is** the lookup.

**Encrypt before uploading**, with a key derived from the secret half:

```
content key = SHA-256("engram-v1" + secret)   -> AES-256-GCM
```

The host receives an opaque blob and a filename it generated itself. It cannot read a save,
and neither can you, and neither can anyone who stumbles on the URL without the secret. That
matters more here than it would with your own server: you are putting other people's data on
somebody else's free service, and the honest way to do that is to make it unreadable first.

The cost is that losing the code loses the save, which is correct for a thing whose whole
purpose is a code.

**Alphabet**: Crockford base32 without `I`, `L`, `O` and `U`, so nothing is ambiguous read
aloud. Accept input case-insensitively, with or without the dashes, and accept a pasted URL
too since somebody will try it.

**Expiry** comes from the host: ask Litterbox for 72 hours. Nothing to clean up, nothing to
bill, and a code that has stopped working is self-explanatory.

**The secret must be generated locally and never sent.** It is the only part of this that has
to be got right.

---

## The thing that is already in the game

Cyberpunk has a save transfer feature built in, with a complete UI, and it is switched off on
PC. From the game's own source in `<GameDir>/tools/redmod/scripts`:

```
core/ui/systemRequestsHandler.script:47
    public import function ExportSavedGame( saveId : Int32 );
    public import function ImportSavedGame();
```

Behind them is a finished 337-line flow in
`cyberpunk/UI/fullscreen/notification/transferSaveGameNotification.script`: an export
confirmation showing the save's own screenshot, a spinner, success and failure states, an
import checking pass. The status enum (`loadGameMenu.script:27`) has nine members including
`ImportNoSave` and `ImportNotEnoughSpace`, so the import side already looks for a file in a
place it knows and checks there is room.

It is reached from two script call sites, each behind a native gate:

| Where | Line | Gate |
|---|---|---|
| Save menu, export | `saveGameMenu.script:225` | `IsTransferSavedExportSupported()` |
| Load menu, import | `loadGameMenu.script:309` | `IsTransferSavedImportSupported()` |

The gates are native and cannot be replaced from redscript, but the checks live in script, so
a mod can wrap `SaveGameMenuGameController.OnSaveFile` (`saveGameMenu.script:190`) and the
matching load-menu handler, build the same `TransferSaveData` the console build does and call
`TransferSavedGame(data)` without asking.

**This does not replace the code system**, because whatever that native does it almost
certainly writes to local or console storage rather than to a URL. It matters for two other
reasons: if it produces a clean single-file export, that is your container format already
designed and tested by CDPR, and the import side may give you a supported way to install a
save that the game itself blesses. Spike it before writing your own container.

---

## What a save actually is

Measured on this machine, not remembered.

```
%USERPROFILE%\Saved Games\CD Projekt Red\Cyberpunk 2077\
    ManualSave-1\
        sav.dat            5.7 MB    the save itself
        metadata.9.json    9 KB      everything the load menu shows
        screenshot.png     130 KB    the thumbnail
    EnabledMods.json                 REDmod's enabled list, shared by all saves
```

Three files, about 6 MB, no hardware lock, no account lock. Steam, GOG and Epic all read the
same folder, so the store does not matter. People publish saves on Nexus and other people load
them, so the premise is proven.

`metadata.9.json` is plain JSON and already carries the whole compatibility check without
touching the binary:

| Field | Example | Use |
|---|---|---|
| `buildPatch` / `gameVersion` | `2.31` / `2310` | refuse an import into an older game |
| `saveVersion` | `269` | save format revision |
| `isModded` | `false` | the game's own verdict, shown in its load menu |
| `playthroughID` | `6a36b2a1202a4ff2` | spot a re-import of the same run |
| `level`, `lifePath`, `playTime`, `timestampString` | | show the receiver what they are about to take |
| `finishedQuests`, `activeQuests`, `trackedQuest` | | and where in the story it sits |

---

## The real work: warning about mods

The code and the upload are an afternoon each. This is the part that decides whether the mod is
trusted.

A save made with mods carries their state **inside `sav.dat`**. Three failure modes, worst last:

1. **Receiver is missing a mod the sender had.** The orphaned state sits unread. Usually
   harmless.
2. **Receiver has the same mod at a different version.** If the mod changed its persistent
   field layout between those two versions, the game silently drops that class's data on load.
   The save opens fine and everything that mod was tracking is gone. This is not theoretical:
   it is exactly what happens in Cyberbane whenever a `persistent let` is added or removed, and
   it presents to the player as a brand new playthrough.
3. **Receiver is missing an ArchiveXL or TweakXL mod whose items are in V's inventory.**
   Records that no longer resolve. The most likely of the three to refuse to load at all.

So the manifest, written by us and encrypted with everything else:

```json
{
  "engramVersion": 1,
  "exportedAt": "2026-11-01T14:02:00Z",
  "save": { "name": "ManualSave-1", "buildPatch": "2.31", "gameVersion": 2310,
            "saveVersion": 269, "playthroughID": "...", "isModded": false,
            "level": 60, "lifePath": "StreetKid", "playTime": 378900 },
  "requires": { "phantomLiberty": true },
  "mods": [ { "name": "Cyberbane", "version": "1.4.5", "kind": "redscript",
              "writesPersistentState": true } ],
  "sha256": { "sav.dat": "...", "metadata.9.json": "..." }
}
```

Fingerprint the sender's machine by scanning `r6/scripts/*`, `red4ext/plugins/*`,
`archive/pc/mod/*`, `mods/*` and `bin/x64/plugins/cyber_engine_tweaks/mods/*`: folder names, and
versions where a mod publishes one. On the receiving side, compare and classify into missing
here, extra here, and version differs. **Block on missing ArchiveXL or TweakXL content. Warn on
a missing redscript mod. Warn loudly on a version difference in a mod that writes persistent
state.** Never copy `EnabledMods.json` silently.

Worth adding later: a one-file convention, say `engram.json` beside a mod, where its author
declares the name, the version and whether a version change wipes its state. Cyberbane ships the
first one.

---

## Where the code runs

| Layer | Can read and write files | Can talk to the network |
|---|---|---|
| redscript | no | no |
| CET Lua | yes, mods use `io` for configs | not exposed |
| RED4ext plugin (C++) | yes | yes |
| External tool | yes | yes |

So the download has to happen outside redscript. Three options, in the order worth building
them:

1. **External tool first.** Works today, nothing to spike, and the receiver has to come out of
   the game anyway. This is the product.
2. **A CET panel for the sender.** Pick a save and get a code without leaving the game. CET
   has `io` but no networking, so it would shell out to the same tool through `os.execute`.
   Needs a spike to confirm CET has not sandboxed that.
3. **A RED4ext plugin**, only if somebody really wants zero alt-tabbing. C++, HTTP and file
   access in one place, and considerably more work than it saves.

---

## Phases

**Phase 0 - Spikes.** Does the native `ExportSavedGame` do anything on PC, and where does it
put it? Can CET Lua shell out? Half a day each, and both change what you build.

**Phase 1 - Move a save with no service.** `engram pack` and `engram unpack` on a local file,
with backups and never overwriting an existing slot. Prove a save moves between two PCs and
loads. Keep this forever as a first-class feature.

**Phase 2 - The code.** Anonymous upload to Litterbox, the code format, encryption with the
secret half, download and decrypt, and a second host behind the same interface. No server is
written in this phase because none is needed.

**Phase 3 - The manifest and the warning.** Mod fingerprinting, the comparison, the
block and warn rules, shown before a single byte is written.

**Phase 4 - Make it look like the game.** A window listing saves with their own screenshots and
metadata, a Share button, a code box. All the material for that is already in the save folder.

---

## The risk that is not technical

Putting the file id in the code removes the worst version of this: there is no server to pay
for, no account to lapse and no database to lose. What is left is that **you depend on free
services run by other people**. Litterbox can rate-limit, block a user agent, or close.

Four things make that survivable, and all four are cheap if done from the start:

- **Know more than one host.** Litterbox first, 0x0.st second, and the host tag in the code
  means an old code keeps working after you change the default.
- **Keep the local file route from Phase 1 as a real feature**, not a fallback. The code is a
  convenience layered on something that works with no network at all.
- **Put the host list in a config file**, so a broken default can be fixed without a new
  release.
- **Be a good guest.** A 6 MB upload with a 72 hour expiry and a sane user agent is a
  reasonable thing to ask of a free host. Do not retry in a loop, and do not use permanent
  storage when expiring storage will do.

## Other risks

- **Steam Cloud.** It syncs this directory and will happily overwrite an imported save within
  seconds. Import must happen with the game and the launcher closed; check whether Steam is
  running and say so.
- **Phantom Liberty.** A PL save will not load without PL. Catch it in the manifest rather than
  letting the game fail.
- **Downgrade.** A 2.31 save will not load on 2.2. Compare `gameVersion` and refuse.
- **Achievements.** A save flagged `isModded` has them disabled, and the game's own load menu
  shows an icon for it (`loadGameMenu.script:1097`). Put it in the readme so nobody is
  surprised.
- **Trust.** `sav.dat` from a stranger is a binary going into the game's deserializer. Verify
  the manifest hashes, and say plainly that a code should come from someone you know.

## Open questions

1. Does `ExportSavedGame` do anything on a PC build, and where does the file land?
2. Does `ImportSavedGame` scan a fixed path, and can that path be pointed somewhere?
3. What does native `LoadModdedSave(saveId)` (`singleplayerMenu.script:51`) relax compared to
   `LoadSaveInGame`? If it tolerates a mismatched mod set, it is useful for exactly this.
4. Can CET Lua still call `os.execute` or `io.popen`?
5. Litterbox and 0x0.st current limits, expiry options and any stated policy on automated
   use, from the services themselves rather than from third-party docs.
6. Do either of them rate-limit by IP in a way that would bite two friends on the same
   connection?

## Sources

Third-party, all of it. Check the services' own pages before writing code against any number
here.

- [Litterbox, temporary anonymous upload, 1 GB, 1h to 72h](https://docs.rs/catbox/latest/catbox/litter/index.html)
- [Catbox and Litterbox limits and anonymous upload](https://getclawkit.com/skills/official-microck-catbox-upload)
- [0x0.st, anonymous hosting, secret URLs and delete tokens](https://engineered.at/articles/til-public-file-hosting-with-0x0-st)
- [Collected upload services and their limits](https://rentry.co/file-upload-scripts)
- [Cloudflare R2 free tier, zero egress](https://dev.to/0012303/cloudflare-r2-has-a-free-tier-s3-compatible-object-storage-with-zero-egress-fees-54a2)
- [Cloudflare free limits, 2026](https://eastondev.com/blog/en/posts/dev/20260526-cloudflare-free-limits/)
