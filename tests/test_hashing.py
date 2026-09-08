"""Digests, perceptual hashes, and grouping the pictures that are the same."""

import pytest
from conftest import grey

from shot.hashing import (
    MASK,
    NEAR,
    cluster,
    dhash,
    digest,
    distance,
    to_signed,
    to_unsigned,
)


def test_the_same_bytes_give_the_same_digest(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"\x89PNG" + b"x" * 4096)
    b.write_bytes(b"\x89PNG" + b"x" * 4096)
    assert digest(a) == digest(b)


def test_one_changed_byte_changes_the_digest(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    a.write_bytes(b"x" * 4096)
    b.write_bytes(b"x" * 4095 + b"y")
    assert digest(a) != digest(b)


def test_a_large_file_is_read_in_pieces(tmp_path):
    """Digesting must not load the whole picture into memory."""
    big = tmp_path / "big.png"
    big.write_bytes(b"z" * (5 << 20))
    assert len(digest(big, chunk=4096)) == 32


# ------------------------------------------------------------------ dhash


def test_a_flat_image_hashes_to_zero():
    """Nothing is brighter than anything else, so no bit is set."""
    assert dhash(grey(*([128] * 72))) == 0


def test_the_hash_is_sixty_four_bits():
    steps = bytes(range(72))
    assert 0 <= dhash(steps) <= MASK


def test_a_short_buffer_is_refused_not_padded():
    with pytest.raises(ValueError, match="need 72"):
        dhash(b"\x00" * 40)


def test_identical_pictures_are_zero_apart():
    a = bytes(range(72))
    assert distance(dhash(a), dhash(a)) == 0


def test_a_small_change_stays_close():
    a = bytearray(range(72))
    b = bytearray(range(72))
    b[10] = 0
    assert 0 < distance(dhash(bytes(a)), dhash(bytes(b))) <= NEAR


def test_an_inverted_picture_is_far_away():
    a = bytes(range(72))
    b = bytes(255 - v for v in range(72))
    assert distance(dhash(a), dhash(b)) > NEAR * 4


# ----------------------------------------------------------------- signed


@pytest.mark.parametrize("value", [0, 1, (1 << 62), (1 << 63), MASK, (1 << 63) + 7])
def test_a_hash_survives_the_trip_through_sqlites_signed_integer(value):
    assert to_unsigned(to_signed(value)) == value


def test_the_top_half_of_the_range_becomes_negative():
    """Which is the whole point — SQLite would overflow on it otherwise."""
    assert to_signed(1 << 63) < 0
    assert to_signed((1 << 63) - 1) > 0


def test_distance_works_on_values_that_came_back_signed():
    value = MASK
    assert distance(to_signed(value), value) == 0


# ---------------------------------------------------------------- grouping


def test_pictures_that_match_are_grouped():
    assert cluster([("a", 0b1010), ("b", 0b1010), ("c", MASK)]) == [["a", "b"]]


def test_a_lone_picture_is_not_a_group():
    assert cluster([("a", 1), ("b", MASK)]) == []


def test_a_chain_of_near_matches_is_one_pile():
    """A is close to B, B to C, A not quite to C — still one set of three."""
    a = 0
    b = 0b111
    c = 0b111_111
    groups = cluster([("a", a), ("b", b), ("c", c)], near=4)
    assert groups == [["a", "b", "c"]]


def test_nothing_in_nothing_out():
    assert cluster([]) == []
