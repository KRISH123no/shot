"""The commands, and the scanner's bookkeeping."""

import sys

import pytest

from shot.cli import main
from shot.index import Index
from shot.model import Shot
from shot.scanner import Report, scan


def run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "i.db"
    with Index(path) as index:
        index.upsert(Shot(path=str(tmp_path / "a.png"), size=100, mtime=1.0, digest="d1",
                          phash=0x0F0F_0F0F_0F0F_0F0F, kind="chat",
                          title="Pulkit Mehndiratta Sir",
                          text="gentle reminder for the Turnitin check"))
        index.upsert(Shot(path=str(tmp_path / "b.png"), size=200, mtime=2.0, digest="d2",
                          phash=0xF0F0_F0F0_F0F0_F0F0, kind="error",
                          title="Session limit reached",
                          text="Session limit reached\nexport KEY=sk-abcdefghijklmnop12"))
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(b"x" * 100)
    return str(path)


def test_no_command_prints_help(capsys):
    code, out = run(capsys)
    assert code == 1 and "usage: shot" in out


def test_find_shows_the_matching_words(capsys, db):
    code, out = run(capsys, "--db", db, "find", "turnitin")
    assert code == 0 and "a.png" in out and "Turnitin" in out


def test_a_multi_word_query_does_not_need_quoting(capsys, db):
    code, out = run(capsys, "--db", db, "find", "session", "limit")
    assert code == 0 and "b.png" in out


def test_no_match_says_so_and_fails(capsys, db):
    code, out = run(capsys, "--db", db, "find", "kangaroo")
    assert code == 1 and "nothing matches" in out


def test_results_can_be_narrowed_by_kind(capsys, db):
    code, _ = run(capsys, "--db", db, "find", "reminder", "--kind", "error")
    assert code == 1, "the only reminder is a chat, not an error"


def test_show_prints_everything_read_from_one_picture(capsys, db, tmp_path):
    code, out = run(capsys, "--db", db, "show", str(tmp_path / "a.png"))
    assert code == 0 and "Turnitin" in out


def test_show_on_something_unindexed_says_what_to_do(capsys, db):
    code, out = run(capsys, "--db", db, "show", "/not/indexed.png")
    assert code == 1 and "shot scan" in out


def test_stats_breaks_down_by_kind(capsys, db):
    code, out = run(capsys, "--db", db, "stats")
    assert code == 0 and "chat" in out and "error" in out


def test_secrets_finds_the_key_in_the_screenshot(capsys, db):
    code, out = run(capsys, "--db", db, "secrets")
    assert code == 0 and "openai key" in out


def test_secrets_never_prints_the_key(capsys, db):
    _, out = run(capsys, "--db", db, "secrets")
    assert "sk-abcdefghijklmnop12" not in out


def test_dupes_reports_nothing_when_there_is_nothing(capsys, db):
    code, out = run(capsys, "--db", db, "dupes")
    assert code == 0 and "no duplicates" in out


def test_dupes_finds_identical_files(capsys, tmp_path):
    path = tmp_path / "i.db"
    with Index(path) as index:
        for name in ("a.png", "b.png"):
            index.upsert(Shot(path=str(tmp_path / name), size=1, mtime=1.0,
                              digest="same", phash=1))
    code, out = run(capsys, "--db", str(path), "dupes")
    assert code == 0 and "identical" in out and "nothing was deleted" in out


def test_rename_shows_the_plan_and_changes_nothing(capsys, db, tmp_path):
    code, out = run(capsys, "--db", db, "rename")
    assert code == 0 and "nothing changed" in out
    assert (tmp_path / "a.png").exists(), "the file was not touched"


def test_rename_apply_moves_the_file_and_follows_it(capsys, db, tmp_path):
    code, out = run(capsys, "--db", db, "rename", "--apply")
    assert code == 0 and "renamed 2" in out
    assert not (tmp_path / "a.png").exists()
    with Index(db) as index:
        hit = index.search("turnitin")[0]
        assert hit.path != str(tmp_path / "a.png"), "the index followed the rename"
        # Named from its title, not from a phrase buried in the body.
        assert "pulkit mehndiratta sir" in hit.path.lower()


def test_prune_drops_rows_for_files_that_are_gone(capsys, db, tmp_path):
    (tmp_path / "a.png").unlink()
    code, out = run(capsys, "--db", db, "prune")
    assert code == 0 and "dropped 1" in out


# ------------------------------------------------------------- bookkeeping


def test_the_report_reads_as_a_sentence():
    report = Report(read=10, skipped=2, reused=1, failed=0, seconds=4.0)
    assert "10 read" in str(report) and report.total == 13


def test_an_unchanged_file_is_skipped_without_being_read(tmp_path):
    """No Engine is passed, so touching the picture at all would explode."""
    picture = tmp_path / "a.png"
    picture.write_bytes(b"x" * 100)
    stat = picture.stat()
    with Index(":memory:") as index:
        index.upsert(Shot(path=str(picture), size=stat.st_size, mtime=stat.st_mtime,
                          digest="d", text="already read"))
        report = scan(index, [picture], engine=object(), jobs=1)
    assert report.skipped == 1 and report.read == 0


def test_a_vanished_file_is_ignored_rather_than_crashing(tmp_path):
    with Index(":memory:") as index:
        report = scan(index, [tmp_path / "gone.png"], engine=object(), jobs=1)
    assert report.total == 0


darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


@darwin
def test_vision_is_there_and_reads_something():
    from shot.ocr import Engine

    engine = Engine()
    assert engine.level == "accurate"


@darwin
def test_doctor_reports_what_this_mac_can_do(capsys):
    code, out = run(capsys, "doctor")
    assert code == 0 and "Vision" in out


def test_duplicates_are_shown_by_what_differs_not_by_what_matches():
    """Truncating from the left made two distinct files render identically."""
    from shot.cli import show_group

    out = "\n".join(show_group([
        "/Users/a/very/deep/one/Screen Shot 2016-03-07 at 9.11.15 AM.png",
        "/Users/a/very/deep/two/Screen Shot 2016-03-07 at 9.11.15 AM.png",
    ]))
    assert "one/" in out and "two/" in out


def test_a_group_spanning_the_root_is_printed_whole():
    from shot.cli import show_group

    out = show_group(["/a/x.png", "/b/x.png"])
    assert out == ["    /a/x.png", "    /b/x.png"]


def test_a_snippet_is_cut_to_the_visible_width_not_the_stored_one():
    """Highlight markers become colour codes and take up no room on screen."""
    from shot.cli import HL_OFF, HL_ON, clip

    text = f"aaaa{HL_ON}bbbb{HL_OFF}cccccccccc"
    out = clip(text, 10)
    assert len(out.replace(HL_ON, "").replace(HL_OFF, "").rstrip("…")) == 10


def test_clipping_never_leaves_a_highlight_open():
    """An unclosed marker would paint the rest of the terminal yellow."""
    from shot.cli import HL_OFF, HL_ON, clip

    out = clip(f"aaaa{HL_ON}bbbbbbbbbb{HL_OFF}", 6)
    assert out.count(HL_ON) == out.count(HL_OFF)


def test_a_short_snippet_is_left_alone():
    from shot.cli import clip

    assert clip("short", 40) == "short"


def test_clipping_does_not_leave_an_empty_highlight():
    """A cut landing exactly on a marker rendered as a bare `[]`."""
    from shot.cli import HL_OFF, HL_ON, clip

    out = clip(f"abcdef{HL_ON}g{HL_OFF}", 6)
    assert HL_ON not in out
