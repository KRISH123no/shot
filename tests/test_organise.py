"""Planning and carrying out the filing. Nothing here may lose a file."""

from datetime import datetime
from pathlib import Path

import pytest

from shot.index import Index
from shot.model import Shot
from shot.organise import apply, build, folder_for, summarise

WHEN = datetime(2026, 9, 8, 18, 58).timestamp()


def picture(tmp_path, name="Screenshot 2026-09-08 at 6.58.31 PM.png", body=b"x" * 50):
    path = tmp_path / name
    path.write_bytes(body)
    return path


def row(path, *, title="Session limit reached", kind="error", when=WHEN, error=""):
    return {"path": str(path), "title": title, "kind": kind, "mtime": when, "error": error}


@pytest.mark.parametrize(
    "period,expected",
    [("day", "2026-09-08"), ("month", "2026-09"), ("year", "2026"), ("flat", "")],
)
def test_the_folder_is_cut_by_period(period, expected):
    assert folder_for(WHEN, period=period) == expected


def test_an_unknown_period_is_refused():
    with pytest.raises(ValueError, match="period must be"):
        folder_for(WHEN, period="fortnight")


# -------------------------------------------------------------- planning


def test_a_screenshot_is_filed_by_month_and_named_by_content(tmp_path):
    source = picture(tmp_path)
    plan = build([row(source)], root=tmp_path / "Shots")
    target = plan.doing[0].target
    assert target.parent.name == "2026-09"
    assert "session limit reached" in target.name
    assert target.name.startswith("2026-09-08")


def test_keeping_the_names_still_files_them(tmp_path):
    source = picture(tmp_path)
    plan = build([row(source)], root=tmp_path / "Shots", rename=False)
    assert plan.doing[0].target.name == source.name
    assert plan.doing[0].target.parent.name == "2026-09"


def test_two_screenshots_of_the_same_thing_do_not_claim_one_name(tmp_path):
    """Both would be named from the same title; the second must not win."""
    a = picture(tmp_path, "a.png")
    b = picture(tmp_path, "b.png", body=b"y" * 50)
    plan = build([row(a), row(b)], root=tmp_path / "Shots")
    targets = [m.target for m in plan.doing]
    assert len(set(targets)) == 2
    assert targets[1].stem.endswith("-2")


def test_a_name_already_on_disk_is_not_reused(tmp_path):
    source = picture(tmp_path)
    folder = tmp_path / "Shots" / "2026-09"
    folder.mkdir(parents=True)
    first = build([row(source)], root=tmp_path / "Shots").doing[0].target
    first.write_bytes(b"occupied")
    plan = build([row(source)], root=tmp_path / "Shots")
    assert plan.doing[0].target != first


def test_a_file_already_where_it_belongs_is_left_alone(tmp_path):
    folder = tmp_path / "Shots" / "2026-09"
    folder.mkdir(parents=True)
    source = folder / "2026-09-08 error — session limit reached.png"
    source.write_bytes(b"x" * 50)
    plan = build([row(source)], root=tmp_path / "Shots")
    assert plan.doing == []
    assert plan.moves[0].skip == "already filed"


def test_a_file_that_has_gone_is_skipped_not_planned(tmp_path):
    plan = build([row(tmp_path / "vanished.png")], root=tmp_path / "Shots")
    assert plan.doing == [] and plan.moves[0].skip == "gone"


def test_a_picture_that_could_not_be_read_is_not_renamed_blind(tmp_path):
    source = picture(tmp_path)
    plan = build([row(source, error="could not decode")], root=tmp_path / "Shots")
    assert plan.doing == []


def test_the_plan_counts_per_folder(tmp_path):
    rows = [
        row(picture(tmp_path, "a.png"), when=datetime(2026, 9, 1).timestamp()),
        row(picture(tmp_path, "b.png", b"y" * 50), when=datetime(2026, 8, 1).timestamp()),
    ]
    assert build(rows, root=tmp_path / "S").folders == {"2026-08": 1, "2026-09": 1}


def test_a_plan_can_be_summarised_for_printing(tmp_path):
    plan = build([row(picture(tmp_path))], root=tmp_path / "S")
    assert any("→" in line for line in summarise(plan))


# --------------------------------------------------------------- applying


def test_applying_moves_the_file_and_makes_the_folder(tmp_path):
    source = picture(tmp_path)
    plan = build([row(source)], root=tmp_path / "Shots")
    target = plan.doing[0].target
    moved, failures = apply(plan)
    assert moved == 1 and failures == []
    assert target.exists() and not source.exists()


def test_the_bytes_survive_the_move(tmp_path):
    source = picture(tmp_path, body=b"exactly these bytes")
    plan = build([row(source)], root=tmp_path / "Shots")
    target = plan.doing[0].target
    apply(plan)
    assert target.read_bytes() == b"exactly these bytes"


def test_filing_the_same_picture_twice_does_not_make_a_copy(tmp_path):
    """Re-filing should be a no-op, not a second file."""
    folder = tmp_path / "Shots" / "2026-09"
    folder.mkdir(parents=True)
    existing = folder / "2026-09-08 error — session limit reached.png"
    existing.write_bytes(b"x" * 50)

    source = picture(tmp_path, "Screenshot copy.png", body=b"x" * 50)
    plan = build([row(source)], root=tmp_path / "Shots")
    moved, _ = apply(plan)
    assert moved == 0
    assert len(list(folder.iterdir())) == 1


def test_a_different_picture_with_the_same_name_is_kept_not_clobbered(tmp_path):
    folder = tmp_path / "Shots" / "2026-09"
    folder.mkdir(parents=True)
    existing = folder / "2026-09-08 error — session limit reached.png"
    existing.write_bytes(b"the original")

    source = picture(tmp_path, "other.png", body=b"something else entirely")
    plan = build([row(source)], root=tmp_path / "Shots")
    apply(plan)
    assert existing.read_bytes() == b"the original"
    assert len(list(folder.iterdir())) == 2


def test_a_failure_is_reported_and_does_not_stop_the_rest(tmp_path, monkeypatch):
    a = picture(tmp_path, "a.png")
    b = picture(tmp_path, "b.png", body=b"y" * 50)
    plan = build([row(a), row(b)], root=tmp_path / "Shots")

    real = Path.rename

    def flaky(self, target):
        if self.name == "a.png":
            raise OSError("permission denied")
        return real(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    moved, failures = apply(plan)
    assert moved == 1 and len(failures) == 1


def test_the_index_can_follow_the_move(tmp_path):
    source = picture(tmp_path)
    with Index(":memory:") as index:
        index.upsert(Shot(path=str(source), size=50, mtime=WHEN, digest="d",
                          kind="error", title="Session limit reached", text="findable"))
        plan = build(index.rows(), root=tmp_path / "Shots")
        target = plan.doing[0].target
        apply(plan)
        index.move(str(source), str(target))
        assert index.search("findable")[0].path == str(target)


# --------------------------------------------------------------- scoping


def test_only_files_loose_in_the_folder_are_taken(tmp_path):
    """An archive of school notes is already organised; leave it alone."""
    from shot.organise import under

    loose = picture(tmp_path, "a.png")
    (tmp_path / "old notes" / "class IX").mkdir(parents=True)
    filed = tmp_path / "old notes" / "class IX" / "b.png"
    filed.write_bytes(b"y" * 50)

    kept = under([row(loose), row(filed)], tmp_path)
    assert [Path(r["path"]).name for r in kept] == ["a.png"]


def test_subfolders_can_be_asked_for_explicitly(tmp_path):
    from shot.organise import under

    loose = picture(tmp_path, "a.png")
    (tmp_path / "deep").mkdir()
    nested = tmp_path / "deep" / "b.png"
    nested.write_bytes(b"y" * 50)

    kept = under([row(loose), row(nested)], tmp_path, recursive=True)
    assert len(kept) == 2


def test_a_folder_with_nothing_loose_in_it_yields_nothing(tmp_path):
    from shot.organise import under

    (tmp_path / "deep").mkdir()
    nested = tmp_path / "deep" / "b.png"
    nested.write_bytes(b"y" * 50)
    assert under([row(nested)], tmp_path) == []
