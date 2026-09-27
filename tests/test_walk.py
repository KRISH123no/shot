"""Finding the pictures without wandering into places that waste an hour."""

import pytest

from shot.walk import (
    EXTENSIONS,
    MIN_BYTES,
    images,
    looks_like_a_screenshot,
    skip_dir,
)


def make(root, path, size=MIN_BYTES + 1):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x" * size)
    return target


def found(root, **kwargs):
    return sorted(p.name for p in images([root], **kwargs))


def test_images_are_found(tmp_path):
    make(tmp_path, "a.png")
    make(tmp_path, "deep/b.jpg")
    assert found(tmp_path) == ["a.png", "b.jpg"]


def test_things_that_are_not_images_are_not(tmp_path):
    make(tmp_path, "a.png")
    make(tmp_path, "notes.txt")
    make(tmp_path, "archive.zip")
    assert found(tmp_path) == ["a.png"]


@pytest.mark.parametrize("suffix", sorted(EXTENSIONS))
def test_every_format_core_graphics_reads_is_collected(tmp_path, suffix):
    make(tmp_path, f"a{suffix}")
    assert found(tmp_path) == [f"a{suffix}"]


def test_icons_are_too_small_to_be_screenshots(tmp_path):
    make(tmp_path, "icon.png", size=200)
    make(tmp_path, "real.png")
    assert found(tmp_path) == ["real.png"]


def test_app_bundles_are_not_descended_into(tmp_path):
    """A .app is a directory full of icons nobody wants to search."""
    make(tmp_path, "Thing.app/Contents/Resources/icon.png")
    make(tmp_path, "real.png")
    assert found(tmp_path) == ["real.png"]


def test_the_photo_library_is_left_alone(tmp_path):
    make(tmp_path, "Photos.photoslibrary/originals/x.jpg")
    assert found(tmp_path) == []


@pytest.mark.parametrize("name", ["node_modules", ".git", "__pycache__", ".venv", "Library"])
def test_the_usual_time_sinks_are_skipped(tmp_path, name):
    make(tmp_path, f"{name}/a.png")
    make(tmp_path, "real.png")
    assert found(tmp_path) == ["real.png"]


def test_hidden_files_and_folders_are_skipped(tmp_path):
    make(tmp_path, ".hidden.png")
    make(tmp_path, ".config/a.png")
    make(tmp_path, "real.png")
    assert found(tmp_path) == ["real.png"]


def test_a_file_reached_twice_is_still_one_file(tmp_path):
    """A hard link, or two roots that overlap."""
    original = make(tmp_path, "a.png")
    (tmp_path / "also").mkdir()
    (tmp_path / "also" / "b.png").hardlink_to(original)
    assert len(list(images([tmp_path]))) == 1


def test_symlinks_are_not_followed_by_default(tmp_path):
    """One link back to your home directory walks the whole disk twice."""
    make(tmp_path, "real/a.png")
    (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    assert len(list(images([tmp_path]))) == 1


def test_a_missing_root_is_ignored_not_an_error(tmp_path):
    assert list(images([tmp_path / "nope"])) == []


def test_a_single_file_can_be_given_as_a_root(tmp_path):
    path = make(tmp_path, "a.png")
    assert [p.name for p in images([path])] == ["a.png"]


# ------------------------------------------------------------ screenshots


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Screenshot 2026-09-08 at 6.58.31 PM.png", True),
        ("Screen Shot 2020-01-01 at 10.00.00.png", True),
        ("CleanShot 2026-01-01 at 10.00.png", True),
        ("holiday-photo.jpg", False),
        ("Figure_1_Convergence.png", False),
    ],
)
def test_screenshot_names_are_recognised(name, expected):
    assert looks_like_a_screenshot(name) is expected


def test_the_screenshot_filter_leaves_photographs_out(tmp_path):
    make(tmp_path, "Screenshot 2026-01-01 at 1.00.00 PM.png")
    make(tmp_path, "birthday.jpg")
    assert found(tmp_path, screenshots_only=True) == [
        "Screenshot 2026-01-01 at 1.00.00 PM.png"
    ]


def test_skip_dir_says_no_to_dotfolders():
    assert skip_dir(".git") and skip_dir("node_modules") and not skip_dir("Desktop")


def test_a_small_screenshot_is_not_mistaken_for_an_icon(tmp_path):
    """A screenshot of a small dialog is a few kilobytes and still wanted."""
    make(tmp_path, "Screenshot 2026-07-16 at 9.10.56 PM.png", size=4587)
    assert found(tmp_path) == ["Screenshot 2026-07-16 at 9.10.56 PM.png"]


def test_but_a_small_unnamed_image_is_still_an_icon(tmp_path):
    make(tmp_path, "toolbar-icon.png", size=300)
    assert found(tmp_path) == []
