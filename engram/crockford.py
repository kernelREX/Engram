"""Crockford base32, the alphabet used for everything a person has to read aloud.

I, L, O and U are absent. On input, I and L fold to 1, O folds to 0, and case is
irrelevant, so a receiver who mishears or mistypes in the usual ways still lands on the
right code.
"""

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_DECODE = {c: i for i, c in enumerate(ALPHABET)}
_DECODE.update({c.lower(): i for i, c in enumerate(ALPHABET)})
_DECODE.update({"I": 1, "i": 1, "L": 1, "l": 1, "O": 0, "o": 0})


class CrockfordError(ValueError):
    """Input that is not a Crockford base32 string."""


def normalise(text: str) -> str:
    """Strip separators and fold ambiguous characters to canonical ones."""
    out = []
    for ch in text:
        if ch in "- \t_":
            continue
        try:
            out.append(ALPHABET[_DECODE[ch]])
        except KeyError:
            raise CrockfordError(f"{ch!r} is not a character a code can contain") from None
    return "".join(out)


def encode_int(value: int, width: int) -> str:
    """Encode a non negative integer into exactly `width` characters."""
    if value < 0:
        raise ValueError("value must not be negative")
    if value >= 32 ** width:
        raise ValueError(f"{value} does not fit in {width} characters")
    out = []
    for _ in range(width):
        out.append(ALPHABET[value % 32])
        value //= 32
    return "".join(reversed(out))


def decode_int(text: str) -> int:
    """Decode a Crockford string into an integer. Input is normalised first."""
    text = normalise(text)
    if not text:
        raise CrockfordError("nothing to decode")
    value = 0
    for ch in text:
        value = value * 32 + _DECODE[ch]
    return value


def width_for(bit_count: int) -> int:
    """How many characters it takes to hold `bit_count` bits."""
    return max(1, -(-bit_count // 5))
