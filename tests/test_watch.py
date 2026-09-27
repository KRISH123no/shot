"""Catching a screenshot the moment it lands, and not a moment before."""

from pathlib import Path

from shot.index import Index
from shot.watch import LABEL, build_plist, candidates, settled, watch


class Clock:
    """Time that moves only when something sleeps."""

    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class Growing:
    """A file being written: it gains bytes on each check, then stops."""

    def __init__(self, path, chunks):
        self.path = path
        self.chunks = list(chunks)
        path.write_bytes(b"")

    def sleep(self, _seconds):
        if self.chunks:
            with open(self.path, "ab") as handle:
                handle.write(b"x" * self.chunks.pop(0))


# --------------------------------------------------------------- settling


def test_a_file_that_stops_growing_is_ready(tmp_path):
    path = tmp_path / "a.png"
    grower = Growing(path, [100, 100, 0, 0])
    assert settled(path, sleep=grower.sleep) is True


def test_a_file_still_being_written_is_not(tmp_path):
    """macOS writes the PNG after creating it; reading early gets a stub."""
    path = tmp_path / "a.png"
    grower = Growing(path, [10] * 200)
    assert settled(path, timeout=2.0, sleep=grower.sleep) is False


def test_an_empty_file_never_settles(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"")
    clock = Clock()
    assert settled(path, timeout=2.0, sleep=clock.sleep) is False


def test_a_file_that_vanishes_mid_wait_is_not_an_error(tmp_path):
    path = tmp_path / "a.png"
    path.write_bytes(b"x" * 50)

    def remove(_seconds):
        path.unlink(missing_ok=True)

    assert settled(path, sleep=remove) is False


def test_a_file_that_was_never_there(tmp_path):
    assert settled(tmp_path / "nope.png") is False


# ------------------------------------------------------------- candidates


def make(folder, name, size=9000):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"x" * size)
    return path


def test_only_screenshots_are_picked_up_by_default(tmp_path):
    make(tmp_path, "Screenshot 2026-09-08 at 1.00.00 PM.png")
    make(tmp_path, "holiday.jpg")
    assert {p.name for p in candidates(tmp_path)} == {
        "Screenshot 2026-09-08 at 1.00.00 PM.png"
    }


def test_every_image_can_be_picked_up_instead(tmp_path):
    make(tmp_path, "Screenshot 2026-09-08 at 1.00.00 PM.png")
    make(tmp_path, "holiday.jpg")
    assert len(candidates(tmp_path, screenshots_only=False)) == 2


def test_it_does_not_descend_into_the_folder_it_files_into(tmp_path):
    """Otherwise it would re-file everything already tidied away."""
    make(tmp_path, "Screenshot 2026-09-08 at 1.00.00 PM.png")
    make(tmp_path / "Screenshots" / "2026-09", "Screenshot old.png")
    assert len(candidates(tmp_path)) == 1


def test_hidden_files_and_non_images_are_ignored(tmp_path):
    make(tmp_path, ".Screenshot hidden.png")
    make(tmp_path, "Screenshot notes.txt")
    assert candidates(tmp_path) == set()


def test_a_folder_that_does_not_exist_is_empty_not_an_error(tmp_path):
    assert candidates(tmp_path / "nope") == set()


# ----------------------------------------------------------------- watching


def test_what_is_already_there_is_left_alone(tmp_path):
    """Starting the watcher must not silently reorganise your Desktop."""
    make(tmp_path, "Screenshot 2026-09-08 at 1.00.00 PM.png")
    seen = []
    with Index(":memory:") as index:
        handled = watch(index, tmp_path, root=tmp_path / "S", once=True,
                        engine=object(), on_file=lambda s, t: seen.append(s),
                        sleep=lambda _s: None)
    assert handled == 0 and seen == []


def test_the_plist_files_into_the_right_place():
    plist = build_plist(python="/usr/bin/python3", folder=Path("/Users/x/Desktop"),
                        root=Path("/Users/x/Desktop/Screenshots"), period="day")
    assert LABEL in plist
    assert "/Users/x/Desktop/Screenshots" in plist
    assert "<string>day</string>" in plist
    assert "--apply" in plist, "the agent is pointless if it only looks"


def test_the_agent_is_told_where_the_package_lives():
    """launchd starts from /, so a source checkout is on no import path."""
    assert "<key>PYTHONPATH</key>" in build_plist(folder=Path("/a"), root=Path("/b"))


def test_the_agent_stays_out_of_the_way():
    plist = build_plist(folder=Path("/a"), root=Path("/b"))
    assert "Background" in plist and "LowPriorityIO" in plist


def test_a_polling_caller_keeps_its_own_baseline(tmp_path):
    """Re-baselining on every call is a watcher that never sees anything."""
    make(tmp_path, "Screenshot old.png")
    seen = []
    with Index(":memory:") as index:
        known = candidates(tmp_path)
        watch(index, tmp_path, root=tmp_path / "S", once=True, known=known,
              engine=object(), on_file=lambda s, t: seen.append(s), sleep=lambda _s: None)
        assert seen == [], "what was already there is not news"

        make(tmp_path, "Screenshot new.png")
        watch(index, tmp_path, root=tmp_path / "S", once=True, known=known,
              engine=_StubEngine(), on_file=lambda s, t: seen.append(s), sleep=lambda _s: None)
    assert [p.name for p in seen] == ["Screenshot new.png"]


class _StubEngine:
    """Enough of an Engine for the watcher to get through a file."""

    def read(self, path):
        from shot.model import Line

        return 100, 100, [Line(text="a new screenshot", confidence=0.9, y=0.9, height=0.05)]

    def greyscale(self, path):
        return bytes(72)
