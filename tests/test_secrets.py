"""Finding credentials that ended up in a picture."""

import pytest

from shot.secrets import find, luhn, mask, scan


@pytest.mark.parametrize(
    "text,label",
    [
        ("export OPENAI_API_KEY=sk-proj-abcdefghij1234567890", "openai key"),
        ("ANTHROPIC=sk-ant-api03-aaaaaaaaaaaaaaaaaaaa", "anthropic key"),
        ("ghp_AAAABBBBCCCCDDDDEEEEFFFFGGGG1234", "github token"),
        ("AKIAIOSFODNN7EXAMPLE", "aws key id"),
        ("xoxb-1234567890-abcdefghij", "slack token"),
        ("eyJhbGciOiJI.eyJzdWIiOiIx.SflKxwRJSM", "jwt"),
        ("-----BEGIN RSA PRIVATE KEY-----", "private key"),
        ("password = hunter2hunter2", "assignment"),
    ],
)
def test_the_usual_shapes_are_caught(text, label):
    assert label in [kind for kind, _ in find(text)]


def test_a_credential_is_never_shown_in_full():
    hits = find("sk-proj-abcdefghij1234567890")
    assert "abcdefghij1234567890" not in hits[0][1]


def test_ordinary_text_is_left_alone():
    assert find("Session limit reached. Try again at 7:11 PM.") == []


def test_the_same_secret_twice_is_reported_once():
    assert len(find("key sk-abcdefghijklmnop1 and again sk-abcdefghijklmnop1")) == 1


# -------------------------------------------------------------------- luhn


def test_a_real_card_number_passes():
    assert luhn("4539578763621486")


def test_a_random_run_of_digits_does_not():
    """Without this, every order number in every screenshot is a card."""
    assert not luhn("1234567812345678")


def test_a_card_is_only_reported_when_the_checksum_agrees():
    assert find("order 1234567812345678") == []
    assert find("card 4539578763621486")


@pytest.mark.parametrize("bad", ["", "123", "abcd", "1" * 25])
def test_things_that_are_not_card_numbers(bad):
    assert not luhn(bad)


def test_a_spaced_card_number_is_still_one():
    assert luhn("4539 5787 6362 1486")


# -------------------------------------------------------------------- scan


def test_scanning_yields_only_the_pictures_with_something_in_them():
    rows = [("/a.png", "nothing here"), ("/b.png", "token: ghp_AAAABBBBCCCCDDDDEEEE1234")]
    assert [path for path, _ in scan(rows)] == ["/b.png"]


def test_a_picture_with_no_text_is_not_an_error():
    assert list(scan([("/a.png", "")])) == []


def test_mask_keeps_it_recognisable():
    assert mask("sk-proj-abcdefghijkl").startswith("sk-")


def test_a_more_specific_pattern_is_not_swallowed_by_a_general_one():
    """`sk-ant-...` also matches `sk-...`; the specific rule must win."""
    labels = [kind for kind, _ in find("sk-ant-api03-aaaaaaaaaaaaaaaaaaaa")]
    assert labels == ["anthropic key"]
