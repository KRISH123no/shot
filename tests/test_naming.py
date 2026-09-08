"""Choosing a name from the geometry of the text."""



from conftest import line

from shot.naming import NARROW_NBSP, best_title, suggest, tidy, unique


def test_the_big_heading_near_the_top_wins():
    small = line("some body text down the page", y=0.2, w=0.3, h=0.01)
    heading = line("Quarterly Revenue Report", y=0.92, w=0.5, h=0.05)
    assert best_title([small, heading]) == "Quarterly Revenue Report"


def test_interface_furniture_is_never_the_title():
    """'Search' is large and at the top of half the windows ever made."""
    chrome = line("Search", y=0.95, w=0.6, h=0.06)
    real = line("Pulkit Mehndiratta Sir", y=0.85, w=0.3, h=0.03)
    assert best_title([chrome, real]) == "Pulkit Mehndiratta Sir"


def test_a_single_word_loses_to_a_phrase_of_similar_size():
    word = line("Word", y=0.9, w=0.3, h=0.03)
    phrase = line("Detecting cloned voices", y=0.88, w=0.3, h=0.03)
    assert best_title([word, phrase]) == "Detecting cloned voices"


def test_a_stray_character_is_never_a_title():
    assert best_title([line("V", y=0.99, w=0.9, h=0.09)]) == ""


def test_no_text_means_no_title():
    assert best_title([]) == ""


# ------------------------------------------------------------------- tidy


def test_punctuation_that_breaks_filenames_is_stripped():
    assert "/" not in tidy("reports/2026: draft #1")
    assert ":" not in tidy("reports/2026: draft #1")


def test_the_narrow_space_macos_uses_is_normalised():
    """It looks exactly like a space and is not one."""
    assert NARROW_NBSP not in tidy(f"6.58.31{NARROW_NBSP}PM")


def test_a_long_title_is_cut_at_a_word():
    cut = tidy("the quick brown fox jumped over the lazy dog and kept on going", limit=30)
    assert len(cut) <= 30 and not cut.endswith(" ") and " " in cut


def test_a_single_long_word_is_still_cut():
    assert len(tidy("a" * 90, limit=20)) <= 20


# --------------------------------------------------------------- suggest


def test_the_name_leads_with_the_date_so_folders_still_sort(tmp_path):
    path = tmp_path / "Screenshot.png"
    path.write_bytes(b"x")
    name = suggest(path, title="Session limit reached", kind="error", when=1_757_000_000)
    assert name.startswith("2025-") or name[:4].isdigit()
    assert "error" in name and "session limit reached" in name
    assert name.endswith(".png")


def test_a_picture_with_no_readable_title_still_gets_a_name(tmp_path):
    path = tmp_path / "Screenshot.png"
    path.write_bytes(b"x")
    name = suggest(path, title="", kind="chat", when=1_757_000_000)
    assert name.endswith(".png") and "chat" in name


def test_an_unknown_kind_is_left_out_rather_than_named_unknown(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    assert "unknown" not in suggest(path, title="Hello there", kind="unknown", when=1)


def test_the_extension_is_kept_and_lowercased(tmp_path):
    path = tmp_path / "a.PNG"
    path.write_bytes(b"x")
    assert suggest(path, title="x y z", kind="chat", when=1).endswith(".png")


# ---------------------------------------------------------------- unique


def test_a_free_name_is_used_as_is(tmp_path):
    assert unique(tmp_path, "a.png").name == "a.png"


def test_an_existing_name_is_never_overwritten(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    assert unique(tmp_path, "a.png").name == "a-2.png"


def test_and_it_keeps_counting(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "a-2.png").write_bytes(b"x")
    assert unique(tmp_path, "a.png").name == "a-3.png"
