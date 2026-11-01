"""The container, the manifest, and everything that must not open."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from engram import container, manifest as manifestmod, mods
from engram.container import ContainerError
from engram.crypto import DecryptionError, KeyParams, derive_key


def test_a_plain_container_round_trips_byte_for_byte(slot, game):
    found = mods.scan(game.path and game)
    blob, built = container.pack(slot, found)
    assert not container.is_encrypted(blob)

    bundle = container.unpack(blob)
    assert bundle.files == container.collect(slot)
    assert bundle.manifest.source_folder == slot.folder_name
    assert len(bundle.manifest.mods) == len(built.mods)


def test_a_sealed_container_needs_the_secret(slot, game):
    found = mods.scan(game)
    blob, _ = container.pack(slot, found, secret="7FPR4TQX", context="litterbox")
    assert container.is_encrypted(blob)

    assert container.unpack(blob, secret="7FPR4TQX").files == container.collect(slot)

    with pytest.raises(ContainerError, match="no code was given"):
        container.unpack(blob)
    with pytest.raises(DecryptionError):
        container.unpack(blob, secret="7FPR4TQY")


def test_the_context_is_part_of_the_key(slot, game):
    found = mods.scan(game)
    blob, _ = container.pack(slot, found, secret="7FPR4TQX", context="litterbox")
    edited = blob.replace(b'"context":"litterbox"', b'"context":"litterboy"')
    assert edited != blob
    with pytest.raises(DecryptionError):
        container.unpack(edited, secret="7FPR4TQX")


def test_a_flipped_bit_in_the_body_is_caught(slot, game):
    blob, _ = container.pack(slot, mods.scan(game), secret="7FPR4TQX", context="x")
    broken = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(DecryptionError):
        container.unpack(broken, secret="7FPR4TQX")


def test_an_altered_save_inside_a_plain_container_fails_its_hash(slot, game):
    blob, _ = container.pack(slot, mods.scan(game))
    _, offset = container.read_header(blob)

    source = zipfile.ZipFile(io.BytesIO(blob[offset:]))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith("sav.dat"):
                data = data[:-1] + bytes([data[-1] ^ 0xFF])
            out.writestr(name, data)

    with pytest.raises(ContainerError, match="does not match its hash"):
        container.unpack(blob[:offset] + buffer.getvalue())


def test_a_save_that_is_not_a_save_is_refused(slot, game):
    blob, _ = container.pack(slot, mods.scan(game))
    _, offset = container.read_header(blob)

    source = zipfile.ZipFile(io.BytesIO(blob[offset:]))
    files = {n: source.read(n) for n in source.namelist()}
    files["save/sav.dat"] = b"not a save at all"
    document = json.loads(files["manifest.json"])
    document["sha256"]["sav.dat"] = manifestmod.sha256(files["save/sav.dat"])
    files["manifest.json"] = json.dumps(document).encode("utf-8")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in files.items():
            out.writestr(name, data)

    with pytest.raises(ContainerError, match="does not start like a Cyberpunk save"):
        container.unpack(blob[:offset] + buffer.getvalue())


@pytest.mark.parametrize(
    "blob",
    [b"", b"hello", b"ENGRAM", b"ENGRAM\x00\x01", b"ENGRAM\x00\x01\xff\xff\xff\xff"],
)
def test_files_that_are_not_containers_are_refused(blob):
    with pytest.raises(ContainerError):
        container.unpack(blob)


def test_a_newer_format_version_says_so():
    with pytest.raises(ContainerError, match="Update Engram"):
        container.unpack(b"ENGRAM\x00\x09" + b"\x02\x00\x00\x00" + b"{}")


def test_an_unknown_cipher_says_so():
    header = json.dumps({"enc": "something-else"}).encode("utf-8")
    blob = (
        container.MAGIC + len(header).to_bytes(4, "little") + header + b"body"
    )
    with pytest.raises(ContainerError, match="does not know"):
        container.unpack(blob, secret="7FPR4TQX")


def test_a_path_outside_the_save_folder_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as out:
        out.writestr("manifest.json", json.dumps({"engramVersion": 1, "sha256": {}}))
        out.writestr("save/../../evil.dat", b"nope")
    header = json.dumps({"enc": "none"}).encode("utf-8")
    blob = container.MAGIC + len(header).to_bytes(4, "little") + header + buffer.getvalue()
    with pytest.raises(ContainerError):
        container.unpack(blob)


def test_a_manifest_from_a_newer_engram_says_so():
    with pytest.raises(manifestmod.ManifestError, match="Update Engram"):
        manifestmod.Manifest.from_json({"engramVersion": 99, "sha256": {}})


def test_a_manifest_with_no_hashes_is_refused():
    built = manifestmod.Manifest(save={}, mods=mods.ModSet(), hashes={})
    with pytest.raises(manifestmod.ManifestError, match="no hashes"):
        built.verify({"sav.dat": b"VASC"})


def test_the_key_depends_on_both_halves():
    assert derive_key("7FPR4TQX", "a") != derive_key("7FPR4TQX", "b")
    assert derive_key("7FPR4TQX", "a") != derive_key("7FPR4TQY", "a")
    assert derive_key("7FPR4TQX", "a") == derive_key("7FPR4TQX", "a")


def test_key_parameters_travel_with_the_file():
    params = KeyParams(n=1 << 14)
    assert KeyParams.from_json(params.to_json()) == params
    with pytest.raises(DecryptionError, match="does not know"):
        KeyParams.from_json({"kdf": "pbkdf2", "n": 1, "r": 1, "p": 1})
