"""Choosing a name from the geometry of the text."""

import pytest
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


# --------------------------------------------- buttons read as words


@pytest.mark.parametrize(
    "raw,clean",
    [
        ("My Dashboard - IIT Madras B x", "My Dashboard - IIT Madras B"),
        # "Go" is a word, so nothing is stripped here — this one is caught by
        # the truncation rule instead, which is the right mechanism for it.
        ("Explain Astrology Ch: × | G tarot reading - Go",
         "Explain Astrology Ch: × | G tarot reading - Go"),
        ("*= Activity Assignment-3", "Activity Assignment-3"),
        ("→ Ask Gemini •", "Ask Gemini"),
        ("• Session limit reached", "Session limit reached"),
        ("x / +", ""),
        ("Finalized-LaTeX-Project-V3.zip \"", "Finalized-LaTeX-Project-V3.zip"),
    ],
)
def test_furniture_is_stripped_from_both_ends(raw, clean):
    from shot.naming import strip_glyphs

    assert strip_glyphs(raw) == clean


def test_an_ordinary_title_is_untouched():
    from shot.naming import strip_glyphs

    assert strip_glyphs("Course Announcements") == "Course Announcements"


def test_a_hyphenated_word_is_not_furniture():
    from shot.naming import strip_glyphs

    assert strip_glyphs("Assignment-3") == "Assignment-3"


# ------------------------------------------------------- truncation


@pytest.mark.parametrize(
    "text,cut",
    [
        ("My Dashboard - IIT Madras B", True),   # "BS Degree", cut by the tab
        ("Explain Astrology Ch", True),          # "Ch" is "Chart", cut by the tab
        ("SNU Links - Ar", True),
        ("Course Announcements", False),
        ("Week 1 Assignment", False),
        ("a picture of a dog", False),           # "dog" is a whole word
        ("this is up to me", False),             # short real words are allowed
        ("Due Aug 17, 2026", False),             # a number is not a stub
    ],
)
def test_a_cut_off_title_is_recognised(text, cut):
    from shot.naming import looks_truncated

    assert looks_truncated(text) is cut


# ----------------------------------------------------------- domains


def test_the_address_bar_gives_the_domain():
    from shot.naming import domain_of

    assert domain_of([
        line("seek.study.iitm.ac.in/courses/ns_26t2_cs2002?s", y=0.90),
    ]) == "seek.study.iitm.ac.in"


def test_www_is_dropped():
    from shot.naming import domain_of

    assert domain_of([line("https://www.internshala.com/student", y=0.9)]) == "internshala.com"


def test_the_address_bar_wins_over_a_url_printed_in_the_page():
    """A link in the body is not the page's own address."""
    from shot.naming import domain_of

    lines = [
        line("see also example.org/help", y=0.40),
        line("photos.google.com/albums", y=0.93),
    ]
    assert domain_of(lines) == "photos.google.com"


@pytest.mark.parametrize(
    "text",
    ["Screenshot at 6.58.31 PM", "version v1.2.3 released", "Mr. Goswami", "1.00 of 2.00"],
)
def test_things_that_look_like_domains_and_are_not(text):
    from shot.naming import domain_of

    assert domain_of([line(text, y=0.9)]) is None


def test_a_picture_with_no_url_has_no_domain():
    from shot.naming import domain_of

    assert domain_of([line("Session limit reached", y=0.7)]) is None


# --------------------------------------------------------- describe


def test_a_browser_is_named_from_its_domain_not_its_tab():
    """The tab is the biggest text at the top and is the damaged one."""
    from shot.naming import describe

    lines = [
        line("My Dashboard - IIT Madras B x", y=0.96, h=0.019),
        line("seek.study.iitm.ac.in/courses/ns_26t2", y=0.90, h=0.026),
        line("Activity Assignment-3", y=0.84, h=0.023),
    ]
    got = describe(lines, "web")
    assert got.startswith("seek.study.iitm.ac.in")
    assert "iit madras b" not in got.lower()


def test_the_heading_is_kept_when_it_says_something_extra():
    from shot.naming import describe

    lines = [
        line("blackboard.snu.edu.in/courses", y=0.92),
        line("Course Announcements", y=0.80, h=0.03, w=0.4),
    ]
    assert describe(lines, "web") == "blackboard.snu.edu.in — Course Announcements"


def test_a_domain_that_needs_no_help_stands_alone():
    from shot.naming import describe

    lines = [line("photos.google.com/albums", y=0.93), line("Photos", y=0.8)]
    assert describe(lines, "web") == "photos.google.com"


def test_a_heading_that_is_just_the_address_again_is_dropped():
    from shot.naming import describe

    lines = [
        line("sih.gov.in/collegeRegistration", y=0.93),
        line("sih.gov.in/collegeRegistration", y=0.85, h=0.03, w=0.5),
    ]
    assert describe(lines, "web") == "sih.gov.in"


def test_a_truncated_heading_is_not_glued_onto_the_domain():
    from shot.naming import describe

    lines = [
        line("blackboard.snu.edu.in/x", y=0.92),
        line("SNU Links - Ar", y=0.80, h=0.03, w=0.4),
    ]
    assert describe(lines, "web") == "blackboard.snu.edu.in"


def test_a_screenshot_with_no_browser_in_it_is_named_the_old_way():
    from shot.naming import describe

    lines = [line("Session limit reached", y=0.9, h=0.05, w=0.4), line("Try again", y=0.5)]
    assert describe(lines, "error") == "Session limit reached"


def test_a_chat_is_never_named_after_a_link_someone_sent():
    """Only browser-ish kinds look for a domain."""
    from shot.naming import describe

    lines = [
        line("Dr Sumit Goswami", y=0.92, h=0.04, w=0.3),
        line("have a look at example.com/paper", y=0.6),
    ]
    assert describe(lines, "chat") == "Dr Sumit Goswami"


# ----------------------------------------------------- chrome band


def test_the_tab_strip_loses_to_the_page_beneath_it():
    from shot.naming import CHROME_BAND, best_title

    lines = [
        line("My Dashboard - IIT Madras", y=0.96, h=0.019, w=0.35),
        line("Activity Assignment-3", y=0.84, h=0.023, w=0.30),
    ]
    assert best_title(lines, chrome_band=CHROME_BAND) == "Activity Assignment-3"


def test_without_a_browser_the_top_of_the_image_still_wins():
    from shot.naming import best_title

    lines = [
        line("Quarterly Revenue Report", y=0.96, h=0.05, w=0.5),
        line("some body text", y=0.3, h=0.01, w=0.2),
    ]
    assert best_title(lines) == "Quarterly Revenue Report"


def test_the_em_dash_separator_survives_tidying():
    """Without it `site.com the page` reads as one run-on phrase."""
    assert "—" in tidy("seek.study.iitm.ac.in — Activity Assignment-3")


# ----------------------------------------------- fragments are not names


@pytest.mark.parametrize("fragment", ["MeDI", "V3cm", "60cm2", "x2", "AB", "5"])
def test_an_ocr_fragment_is_no_name_at_all(fragment):
    """Scanned maths notes yield labels off a diagram. A date alone beats them."""
    from shot.naming import describe

    assert describe([line(fragment, y=0.9, h=0.04, w=0.3)], "app") == ""


@pytest.mark.parametrize("real", ["Spotify", "Session limit reached", "Course Grades"])
def test_a_short_but_real_title_survives(real):
    from shot.naming import describe

    assert describe([line(real, y=0.9, h=0.04, w=0.3)], "error") == real


def test_a_nameless_picture_is_named_by_its_date_alone(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"x")
    assert suggest(path, title="", kind="app", when=1_757_000_000).endswith("app.png")
