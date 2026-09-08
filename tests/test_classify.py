"""Deciding what a screenshot is, from the words in it."""

import pytest
from conftest import lines

from shot.classify import KINDS, classify, score


def test_a_chat_is_recognised_by_its_clock_times():
    assert classify(lines(
        "Pulkit Mehndiratta Sir", "6:52 PM", "thank you sir", "7:04 PM",
        "I am very sorry for the repeated requests", "7:11 PM",
    )) == "chat"


def test_one_clock_is_the_menu_bar_and_proves_nothing():
    """Every full-screen screenshot has the time in the corner."""
    assert classify(lines(
        "9:41 AM", "The quick brown fox jumped over the lazy dog and kept going",
        "and this is a second long sentence of ordinary prose about nothing",
        "and a third, because a document is mostly sentences",
    )) != "chat"


def test_a_terminal_is_recognised_by_its_punctuation():
    assert classify(lines(
        "$ pytest -q", "tests/test_index.py::test_search PASSED",
        "def scan(index, paths, *, jobs=4):", "  return Report(read=12)",
    )) == "terminal"


def test_a_date_alone_is_not_a_terminal():
    """One slash is 09/09/2026, not a path."""
    assert classify(lines("Invoice date 09/09/2026", "Dear Krish")) != "terminal"


def test_an_error_dialog_is_an_error():
    assert classify(lines("Session limit reached", "Auto-resuming at 7:11 PM",
                          "Try again")) == "error"


def test_a_browser_is_recognised_by_its_address_bar():
    assert classify(lines("ds.study.iitm.ac.in/student_dashboard",
                          "My Dashboard - IIT Madras", "New tab")) == "web"


def test_settings_needs_the_app_not_just_the_word_general():
    """'General' and 'security' appear in half the emails ever written."""
    assert classify(lines("Dear Sir", "In general, the security of the scheme",
                          "is our main concern")) != "settings"


def test_the_settings_window_is_recognised():
    assert classify(lines("System Settings", "Privacy & Security",
                          "Accessibility")) == "settings"


def test_two_pane_names_are_enough_without_the_app_title():
    assert classify(lines("Accessibility", "Screen Recording", "Full Disk Access")) == "settings"


def test_a_receipt_needs_money_and_a_total():
    assert classify(lines("Order #4821", "Subtotal ₹1,240", "Total ₹1,463")) == "receipt"


def test_a_picture_with_no_text_is_unknown():
    assert classify([]) == "unknown"


def test_a_picture_of_a_cat_is_not_a_document():
    assert classify(lines("meow")) == "unknown"


def test_every_kind_gets_a_score():
    assert set(score(lines("hello"))) == set(KINDS)


@pytest.mark.parametrize("kind", KINDS)
def test_no_score_escapes_zero_to_one(kind):
    values = score(lines("$ ls -la", "3:15 PM", "https://x.io", "Total ₹9"))
    assert 0.0 <= values[kind] <= 1.0


def test_an_error_inside_a_terminal_ranks_both():
    """Screenshots are genuinely mixed; the ranking should say so."""
    values = score(lines("$ python main.py", "Traceback (most recent call last):",
                         "ValueError: invalid literal"))
    assert values["error"] > 0 and values["terminal"] > 0


def test_a_percent_sign_in_a_dashboard_is_not_a_shell_prompt():
    """The loose version of this rule swallowed three fifths of a real collection."""
    assert classify(lines("Convergence Score", "82 %", "Share", "Export")) != "terminal"


def test_a_price_is_not_a_shell_prompt():
    assert classify(lines("Subtotal", "$ 940", "Checkout")) != "terminal"


def test_a_breadcrumb_chevron_is_not_a_shell_prompt():
    assert classify(lines("Home > Courses > Week 6", "My Dashboard")) != "terminal"


def test_a_real_prompt_still_reads_as_a_terminal():
    assert classify(lines("apple@mac ~ %", "$ git status", "On branch main")) == "terminal"


def test_a_command_with_an_argument_is_enough():
    assert classify(lines("npm install --save-dev vitest", "added 214 packages")) == "terminal"


def test_the_word_git_in_a_sentence_is_not():
    assert classify(lines(
        "I pushed the change to git and then went home for the evening",
        "and the build was still red the following morning, unfortunately",
    )) != "terminal"


def test_a_busy_interface_with_no_sentences_is_not_a_document():
    """Fifty-eight lines of buttons is not prose, however many there are."""
    assert classify(lines(*[f"Button {n}" for n in range(58)])) == "app"


def test_actual_prose_is():
    assert classify(lines(
        "The convergence of these two directorates has produced a measurable",
        "improvement in throughput across the reporting period, as shown below",
        "and the remaining variance is accounted for by the seasonal effect",
    )) == "document"


def test_an_interface_full_of_labels_is_an_app():
    assert classify(lines(*[f"Menu item {n}" for n in range(20)])) == "app"


def test_but_a_specific_signal_still_wins_over_app():
    """A dashboard is a web page first, whatever its interface looks like."""
    assert classify(
        lines("ds.study.iitm.ac.in/dashboard", *[f"Course {n}" for n in range(20)])
    ) == "web"


def test_too_little_text_is_still_unknown():
    assert classify(lines("Open", "Cancel")) == "unknown"
