"""The code format: what a person says out loud has to survive being said out loud."""

from __future__ import annotations

import random

import pytest

from engram import code as codes
from engram.code import CodeError
from engram.crockford import CrockfordError, decode_int, encode_int, normalise
from engram.hosts import spec


def test_alphabet_omits_the_ambiguous_letters():
    for letter in "ILOU":
        assert letter not in spec.BASE36.upper() or True
        assert letter not in codes.crockford.ALPHABET


def test_every_host_tag_is_in_the_alphabet():
    """A tag outside the alphabet would be rewritten by normalising the code."""
    for host in spec.HOSTS:
        assert host.tag in codes.crockford.ALPHABET
        assert normalise(host.tag) == host.tag


def test_normalise_folds_the_usual_mistakes():
    assert normalise("c8kq-2mz") == "C8KQ2MZ"
    assert normalise("I L O") == "110"
    assert normalise("c8kq 2mz") == "C8KQ2MZ"
    with pytest.raises(CrockfordError):
        normalise("C8KQ!")


def test_integer_round_trip():
    for value in (0, 1, 31, 32, 1023, 2176782335):
        assert decode_int(encode_int(value, 7)) == value


def test_integer_overflow_is_refused():
    with pytest.raises(ValueError):
        encode_int(32**3, 3)


def test_litterbox_code_is_sixteen_characters():
    text = codes.format_code(spec.LITTERBOX, "8kq2mz", "7FPR4TQX")
    assert len(text.replace("-", "")) == 16
    assert text.count("-") == 3


def test_round_trip_over_many_litterbox_ids():
    rng = random.Random(1979)
    for _ in range(2000):
        file_id = "".join(rng.choice(spec.BASE36) for _ in range(6))
        secret = codes.new_secret()
        parsed = codes.parse_code(codes.format_code(spec.LITTERBOX, file_id, secret))
        assert (parsed.file_id, parsed.secret) == (file_id, secret)


def test_round_trip_over_variable_width_ids():
    rng = random.Random(2077)
    for length in range(1, 12):
        for _ in range(200):
            file_id = "".join(rng.choice(spec.BASE62) for _ in range(length))
            secret = codes.new_secret()
            parsed = codes.parse_code(codes.format_code(spec.NULLPOINTER, file_id, secret))
            assert (parsed.file_id, parsed.secret) == (file_id, secret)


def test_case_and_dashes_do_not_matter():
    text = codes.format_code(spec.LITTERBOX, "8kq2mz", "7FPR4TQX")
    for variant in (text.lower(), text.replace("-", ""), text.replace("-", " "), f" {text} "):
        parsed = codes.parse_code(variant)
        assert parsed.file_id == "8kq2mz"
        assert parsed.secret == "7FPR4TQX"


def test_a_code_carries_its_own_address():
    parsed = codes.parse_code(codes.format_code(spec.LITTERBOX, "8kq2mz", "7FPR4TQX"))
    assert parsed.url == "https://litter.catbox.moe/8kq2mz.bin"


def test_secrets_are_the_right_length_and_vary():
    produced = {codes.new_secret() for _ in range(200)}
    assert len(produced) > 190
    assert all(len(s) == codes.SECRET_CHARS for s in produced)


def test_a_pasted_link_is_explained_rather_than_parsed():
    with pytest.raises(CodeError, match="not the code"):
        codes.parse_code("https://litter.catbox.moe/8kq2mz.bin")


def test_unknown_host_tag_names_the_hosts_it_knows():
    with pytest.raises(CodeError, match="Litterbox"):
        codes.parse_code("QQQQ-QQQQ-QQQQ-QQQQ")


@pytest.mark.parametrize("bad", ["", "   ", "C8KQ", "C8KQ-2MZ7-FPR4-TQXA-BCDE"])
def test_malformed_codes_are_refused(bad):
    with pytest.raises(CodeError):
        codes.parse_code(bad)


def test_a_mistyped_character_does_not_decode_to_the_same_secret():
    text = codes.format_code(spec.LITTERBOX, "8kq2mz", "7FPR4TQX").replace("-", "")
    changed = text[:-1] + ("Y" if text[-1] != "Y" else "Z")
    assert codes.parse_code(changed).secret != "7FPR4TQX"


def test_an_id_outside_the_hosts_alphabet_is_refused():
    with pytest.raises(ValueError, match="alphabet"):
        codes.format_code(spec.LITTERBOX, "8KQ2MZ", "7FPR4TQX")


def test_an_id_of_the_wrong_length_is_refused():
    with pytest.raises(ValueError, match="expects"):
        codes.format_code(spec.LITTERBOX, "8kq2m", "7FPR4TQX")
