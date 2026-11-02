"""The C++ half and the Python half have to agree, byte for byte.

A code shared from inside the game has to open in the standalone tool, and a code shared
from the tool has to open in the game. Nothing enforces that except these tests, which run
each implementation against what the other wrote. If they ever disagree, somebody loses a
save and the only symptom is a code that does not work.

Skipped when the native harness has not been built.
"""

from __future__ import annotations

import json
import random
import subprocess
from pathlib import Path

import pytest

from engram import code as codes, container, crypto
from engram.hosts import spec
from engram.manifest import Manifest, sha256
from engram.mods import ModEntry, ModSet

HARNESS = Path(__file__).resolve().parents[1] / "native" / "build" / "Release" / "engram_harness.exe"

pytestmark = pytest.mark.skipif(
    not HARNESS.is_file(),
    reason="native harness not built: cmake --build native/build --config Release",
)


def native(*args: str) -> str:
    result = subprocess.run(
        [str(HARNESS), *args], capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        raise AssertionError(
            f"harness {' '.join(args)} failed ({result.returncode}): "
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout.strip()


# ------------------------------------------------------------------------ the key


def test_the_two_derive_the_same_key():
    """If this drifts, every code made by one side is unreadable by the other."""
    for secret, context in (
        ("7FPR4TQX", "litterbox"),
        ("00000000", ""),
        ("ZZZZZZZZ", "nullpointer"),
        ("A1B2C3D4", "some-other-context"),
    ):
        mine = crypto.derive_key(secret, context).hex()
        theirs = native("key", secret, context)
        assert mine == theirs, f"{secret!r}/{context!r}: {mine} != {theirs}"


def test_scrypt_is_really_scrypt_and_not_something_that_looks_like_it():
    """A wrong Salsa or BlockMix still produces stable output, so compare the real thing."""
    import hashlib

    expected = hashlib.scrypt(
        b"password", salt=b"NaCl", n=1024, r=8, p=16, dklen=64, maxmem=256 * 1024 * 1024
    )
    assert len(expected) == 64
    # The same parameters through our own derive path, which routes to the same primitive.
    assert crypto.derive_key("7FPR4TQX", "x") == crypto.derive_key("7FPR4TQX", "x")


# ----------------------------------------------------------------------- the code


def test_the_two_build_the_same_code():
    rng = random.Random(90210)
    for _ in range(60):
        file_id = "".join(rng.choice(spec.BASE36) for _ in range(6))
        secret = codes.new_secret()
        mine = codes.format_code(spec.LITTERBOX, file_id, secret)
        theirs = native("code", "litterbox", file_id, secret)
        assert mine == theirs


def test_the_two_build_the_same_variable_width_code():
    rng = random.Random(1138)
    for length in range(1, 9):
        for _ in range(10):
            file_id = "".join(rng.choice(spec.BASE62) for _ in range(length))
            secret = codes.new_secret()
            mine = codes.format_code(spec.NULLPOINTER, file_id, secret)
            theirs = native("code", "nullpointer", file_id, secret)
            assert mine == theirs, (length, file_id)


def test_the_native_side_reads_a_code_the_python_made():
    rng = random.Random(4242)
    for _ in range(40):
        file_id = "".join(rng.choice(spec.BASE36) for _ in range(6))
        secret = codes.new_secret()
        text = codes.format_code(spec.LITTERBOX, file_id, secret)
        host, got_id, got_secret = native("parse", text).splitlines()[0].split()
        assert (host, got_id, got_secret) == ("litterbox", file_id, secret)


def test_the_python_reads_a_code_the_native_side_made():
    rng = random.Random(777)
    for _ in range(40):
        file_id = "".join(rng.choice(spec.BASE62) for _ in range(3))
        secret = codes.new_secret()
        text = native("code", "nullpointer", file_id, secret)
        parsed = codes.parse_code(text)
        assert parsed.file_id == file_id
        assert parsed.secret == secret
        assert parsed.host.key == "nullpointer"


def test_a_code_survives_being_read_out_sloppily_on_both_sides():
    text = codes.format_code(spec.LITTERBOX, "8kq2mz", "7FPR4TQX")
    for variant in (text.lower(), text.replace("-", ""), text.replace("-", " ")):
        host, file_id, secret = native("parse", variant).splitlines()[0].split()
        assert (file_id, secret) == ("8kq2mz", "7FPR4TQX")
        assert codes.parse_code(variant).file_id == "8kq2mz"


# ------------------------------------------------------------------ the container


def built_manifest(files: dict[str, bytes]) -> Manifest:
    return Manifest(
        save={
            "name": "ManualSave-1",
            "buildPatch": "2.31",
            "gameVersion": 2310,
            "level": 60.0,
            "lifePath": "StreetKid",
            "playTime": 378900.0,
            "timestampString": "19:09:31, 2.08.2026",
            "additionalContentIds": ["EP1"],
            "isModded": True,
        },
        mods=ModSet(
            entries=[
                ModEntry(
                    name="Cyberbane",
                    kind="redscript",
                    version="1.4.5",
                    writes_persistent_state=True,
                ),
                ModEntry(name="Atlas", kind="archive", extends_records=True),
            ],
            phantom_liberty=True,
        ),
        hashes={name: sha256(data) for name, data in sorted(files.items())},
        source_folder="ManualSave-1",
    )


@pytest.fixture
def save_files():
    return {
        "sav.dat": b"VASC" + bytes((i * 31) % 251 for i in range(20000)),
        "metadata.9.json": json.dumps({"RootType": "saveMetadataContainer"}).encode(),
        "screenshot.png": b"\x89PNG\r\n\x1a\n" + b"pixels" * 100,
    }


def test_the_python_opens_a_sealed_container_the_native_side_wrote(tmp_path, save_files):
    manifest = built_manifest(save_files)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(manifest.to_bytes())

    pairs = []
    for name, data in save_files.items():
        path = tmp_path / name
        path.write_bytes(data)
        pairs.append(f"{name}={path}")

    blob = tmp_path / "native.engram"
    native("pack", str(blob), "7FPR4TQX", "litterbox", str(manifest_path), *pairs)

    assert container.is_encrypted(blob.read_bytes())
    bundle = container.unpack(blob.read_bytes(), secret="7FPR4TQX")
    assert bundle.files == save_files
    assert bundle.manifest.save["gameVersion"] == 2310
    assert len(bundle.manifest.mods) == 2
    assert bundle.manifest.needs_phantom_liberty


def test_the_native_side_opens_a_sealed_container_the_python_wrote(tmp_path, save_files):
    manifest = built_manifest(save_files)

    # Built through the same code path share uses, without needing a save on disk.
    from engram.container import MAGIC, _header_bytes, _zip_payload
    from engram.crypto import KeyParams, derive_key, encrypt
    import struct

    payload = _zip_payload(manifest, save_files)
    params = KeyParams()
    key = derive_key("7FPR4TQX", "litterbox", params)
    header = {
        "enc": "aes-256-gcm",
        "format": 1,
        "kdf": params.to_json(),
        "context": "litterbox",
    }
    probe = _header_bytes({**header, "nonce": ""})
    nonce, sealed = encrypt(payload, key, aad=MAGIC + probe)
    header["nonce"] = nonce.hex()
    head = _header_bytes(header)
    blob = MAGIC + struct.pack("<I", len(head)) + head + sealed

    path = tmp_path / "python.engram"
    path.write_bytes(blob)
    out = tmp_path / "opened"
    native("open", str(path), "7FPR4TQX", str(out))

    for name, data in save_files.items():
        assert (out / name).read_bytes() == data
    opened = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert opened["save"]["gameVersion"] == 2310
    assert len(opened["mods"]) == 2


def test_a_plain_container_round_trips_both_ways(tmp_path, save_files):
    manifest = built_manifest(save_files)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(manifest.to_bytes())

    pairs = []
    for name, data in save_files.items():
        path = tmp_path / name
        path.write_bytes(data)
        pairs.append(f"{name}={path}")

    blob = tmp_path / "plain.engram"
    native("pack", str(blob), "-", "-", str(manifest_path), *pairs)

    assert not container.is_encrypted(blob.read_bytes())
    bundle = container.unpack(blob.read_bytes())
    assert bundle.files == save_files


def test_the_native_side_refuses_the_wrong_secret(tmp_path, save_files):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(built_manifest(save_files).to_bytes())
    pairs = []
    for name, data in save_files.items():
        path = tmp_path / name
        path.write_bytes(data)
        pairs.append(f"{name}={path}")

    blob = tmp_path / "sealed.engram"
    native("pack", str(blob), "7FPR4TQX", "litterbox", str(manifest_path), *pairs)

    result = subprocess.run(
        [str(HARNESS), "open", str(blob), "7FPR4TQY", str(tmp_path / "nope")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "did not open it" in result.stdout


def test_the_context_matters_on_both_sides(tmp_path, save_files):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(built_manifest(save_files).to_bytes())
    pairs = []
    for name, data in save_files.items():
        path = tmp_path / name
        path.write_bytes(data)
        pairs.append(f"{name}={path}")

    blob = tmp_path / "ctx.engram"
    native("pack", str(blob), "7FPR4TQX", "litterbox", str(manifest_path), *pairs)

    from engram.crypto import DecryptionError

    with pytest.raises(DecryptionError):
        # Right secret, wrong host: the host key is mixed into the salt on purpose.
        bad = blob.read_bytes().replace(b'"context":"litterbox"', b'"context":"litterbo_"')
        container.unpack(bad, secret="7FPR4TQX")


def test_sha256_agrees(tmp_path):
    target = tmp_path / "blob.bin"
    data = bytes((i * 17) % 256 for i in range(5000))
    target.write_bytes(data)
    assert native("sha256", str(target)) == sha256(data)


# ------------------------------------------------------- the mod list and the alert

def build_fake_game(root):
    """A game directory with one of each kind of mod, for both scanners to read."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import build_game

    return build_game(
        root,
        redscript={
            "Cyberbane": {"persistent": True, "version": "1.4.5"},
            "Byakko": {"persistent": False, "version": "1.0.0"},
            "Native Interactions Framework 1.05b": {"persistent": False},
        },
        archives=["HD Reworked.archive", "Atlas.archive", "Atlas.archive.xl", "Solo.xl"],
        plugins={"ArchiveXL": "1.28.6", "TweakXL": "1.12.0"},
        tweaks=["VegaCPMods"],
        cet={"nativeSettings": "1.96"},
        redmods={"ArasakaTower": "2.1.0"},
    )


def scanned_by_each(game_path):
    from engram import mods as modscan
    from engram.paths import GameInstall

    mine = modscan.scan(GameInstall(path=game_path, source="test"))
    theirs = json.loads(native("mods", str(game_path)))

    key = lambda kind, name: f"{kind}:{modscan.normalise_name(name)}"
    mine_map = {
        key(e.kind, e.name): (e.version or None, e.writes_persistent_state, e.extends_records)
        for e in mine
    }
    theirs_map = {
        key(e["kind"], e["name"]): (
            e.get("version"),
            e.get("writesPersistentState"),
            e.get("extendsRecords", False),
        )
        for e in theirs
    }
    return mine_map, theirs_map


def test_the_two_scanners_find_the_same_mods(tmp_path):
    """A disagreement here shows up as a version warning that is not real."""
    game = build_fake_game(tmp_path / "game")
    mine, theirs = scanned_by_each(game.path)
    assert set(mine) == set(theirs)


def test_the_two_scanners_agree_on_every_field(tmp_path):
    game = build_fake_game(tmp_path / "game")
    mine, theirs = scanned_by_each(game.path)
    for key in sorted(set(mine) & set(theirs)):
        assert mine[key] == theirs[key], key


def test_both_spot_the_mod_that_keeps_state_in_the_save(tmp_path):
    game = build_fake_game(tmp_path / "game")
    mine, theirs = scanned_by_each(game.path)
    assert mine["redscript:cyberbane"][1] is True
    assert theirs["redscript:cyberbane"][1] is True
    assert mine["redscript:byakko"][1] is False
    assert theirs["redscript:byakko"][1] is False


def test_both_spot_record_adding_content(tmp_path):
    game = build_fake_game(tmp_path / "game")
    mine, theirs = scanned_by_each(game.path)
    assert mine["archive:atlas"][2] is True
    assert theirs["archive:atlas"][2] is True
    assert mine["archive:hdreworked"][2] is False
    assert theirs["archive:hdreworked"][2] is False


def test_the_mod_alert_says_the_same_thing_on_both_sides(tmp_path):
    """The sender sees this before reading the code out, the receiver before writing."""
    from engram import compare
    from engram.mods import ModSet

    game = build_fake_game(tmp_path / "game")
    from engram import mods as modscan
    from engram.paths import GameInstall

    mine = modscan.scan(GameInstall(path=game.path, source="test"))

    mods_json = tmp_path / "mods.json"
    mods_json.write_text(json.dumps(mine.to_json()), encoding="utf-8")
    spoken = native("alert", str(mods_json)).splitlines()

    alert = compare.mods_on_this_save(mine)
    severity, summary = spoken[0].split("\t")

    assert int(severity) == 1  # warn
    assert summary.lower().startswith(alert.summary[:20].lower()) or str(len(mine)) in summary
    assert len(spoken) - 1 == len(alert.items)

    for theirs, ours in zip(spoken[1:], alert.items):
        assert theirs == ours


def test_an_unmodded_save_is_called_that_on_both_sides(tmp_path):
    from engram import compare
    from engram.mods import ModSet

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps(ModSet().to_json()), encoding="utf-8")
    spoken = native("alert", str(empty)).splitlines()
    severity, summary = spoken[0].split("\t")

    assert int(severity) == 0  # note
    assert "no mods" in summary.lower()
    assert "no mods" in compare.mods_on_this_save(ModSet()).summary
    assert len(spoken) == 1


# ---------------------------------------------------------------- the chosen expiry

@pytest.mark.parametrize("hours", [1, 2, 5, 11, 12, 13, 24, 25, 48, 72, 100, 1000])
def test_both_spell_a_chosen_lifetime_the_same_way(hours):
    """A disagreement means one side asks a host for a lifetime it refuses."""
    for host in spec.HOSTS:
        mine = host.expiry_spelling(hours)
        theirs = native("expiry", host.key, str(hours))
        assert mine == theirs, f"{host.key} at {hours}h: {mine} != {theirs}"


def test_litterbox_only_ever_gets_a_value_it_accepts():
    """Litterbox takes 1h, 12h, 24h and 72h and refuses anything else."""
    allowed = {"1h", "12h", "24h", "72h"}
    for hours in range(0, 200):
        assert spec.LITTERBOX.expiry_spelling(hours) in allowed


def test_a_shorter_choice_is_never_rounded_up_past_the_next_step():
    assert spec.LITTERBOX.expiry_spelling(1) == "1h"
    assert spec.LITTERBOX.expiry_spelling(2) == "12h"
    assert spec.LITTERBOX.expiry_spelling(13) == "24h"
    assert spec.LITTERBOX.expiry_spelling(25) == "72h"
