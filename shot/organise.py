"""Filing screenshots away: into a folder per period, named after their contents.

The point is that you never think about it. You press the shortcut, the file
lands on the Desktop, and a moment later it is in `Screenshots/2026-09/` under
a name that says what it is.

Two rules hold throughout, because this moves a person's files:

**Nothing is overwritten, ever.** A target that exists gets `-2`, and if the
file already sitting there is byte-for-byte the same picture, the move is
dropped instead — re-filing something twice should be a no-op, not a
duplicate.

**A plan is built before anything moves.** The plan is printable, the moves
are checked against each other for collisions, and `--apply` is a separate
decision. A rename you cannot preview is a rename you cannot trust.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .hashing import digest
from .naming import suggest

#: How the folders are cut. Days give you three hundred folders a year; years
#: give you one with everything in it. Months are the readable middle.
PERIODS = {
    "day": "%Y-%m-%d",
    "month": "%Y-%m",
    "year": "%Y",
    "flat": "",
}


@dataclass(slots=True)
class Move:
    source: Path
    target: Path
    #: Why this one is not moving, when it is not.
    skip: str = ""

    @property
    def moving(self) -> bool:
        return not self.skip and self.source != self.target


@dataclass(slots=True)
class Plan:
    moves: list[Move]

    @property
    def doing(self) -> list[Move]:
        return [m for m in self.moves if m.moving]

    @property
    def folders(self) -> dict[str, int]:
        counted: dict[str, int] = {}
        for move in self.doing:
            counted[move.target.parent.name] = counted.get(move.target.parent.name, 0) + 1
        return dict(sorted(counted.items()))

    def __len__(self) -> int:
        return len(self.doing)


def folder_for(when: float, *, period: str = "month") -> str:
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")
    pattern = PERIODS[period]
    return datetime.fromtimestamp(when).strftime(pattern) if pattern else ""


def under(rows: Iterable, folder: Path, *, recursive: bool = False) -> list:
    """Only the screenshots in a given folder.

    Not recursive by default, and that default matters. A scan picks up every
    file named like a screenshot anywhere it walked, including the ones filed
    years ago inside an archive of school notes. Those are already organised;
    sweeping them into a folder-per-month would destroy the structure someone
    built by hand. Loose files in one folder are the thing worth tidying.
    """
    folder = folder.expanduser().resolve()
    kept = []
    for row in rows:
        parent = Path(row["path"]).parent
        try:
            parent = parent.resolve()
        except OSError:
            continue
        if parent == folder or (recursive and folder in parent.parents):
            kept.append(row)
    return kept


def build(
    rows: Iterable,
    *,
    root: Path,
    period: str = "month",
    rename: bool = True,
    taken: set[Path] | None = None,
) -> Plan:
    """Work out where every screenshot should go. Touches nothing.

    ``taken`` seeds the set of names already spoken for, so that two files in
    one plan cannot both be promised the same target — the second gets `-2`
    even though nothing has been written yet.
    """
    claimed: set[Path] = set(taken or ())
    moves: list[Move] = []

    for row in rows:
        source = Path(row["path"])
        if not source.exists():
            moves.append(Move(source, source, skip="gone"))
            continue
        if row["error"]:
            moves.append(Move(source, source, skip="could not be read"))
            continue

        folder = root / folder_for(row["mtime"], period=period)
        name = (
            suggest(source, title=row["title"], kind=row["kind"], when=row["mtime"])
            if rename
            else source.name
        )
        ideal = folder / name

        # These two checks must come before collision avoidance, or a file
        # that is already correctly filed gets invented a "-2" name and moved
        # next to itself.
        if ideal == source:
            moves.append(Move(source, source, skip="already filed"))
            continue
        if ideal.exists() and _same(source, ideal):
            moves.append(Move(source, ideal, skip="already there, identical"))
            continue

        target = _free(ideal, claimed, source)
        if target == source:
            moves.append(Move(source, source, skip="already filed"))
            continue
        claimed.add(target)
        moves.append(Move(source, target))

    return Plan(moves)


def _free(target: Path, claimed: set[Path], source: Path | None = None) -> Path:
    """The first name not already taken on disk or elsewhere in this plan.

    A file's own current name counts as free. Without that, the second of two
    screenshots sharing a title sits at `-2`, sees `-2` occupied on the next
    run — by itself — and moves to `-3`, then `-4`. Running the organiser
    twice has to be the same as running it once.
    """

    def available(candidate: Path) -> bool:
        return candidate not in claimed and (candidate == source or not candidate.exists())

    if available(target):
        return target
    stem, suffix = target.stem, target.suffix
    for n in range(2, 1000):
        candidate = target.with_name(f"{stem}-{n}{suffix}")
        if available(candidate):
            return candidate
    raise FileExistsError(f"a thousand files named like {target.name}")


def apply(plan: Plan, *, on_move=None) -> tuple[int, list[tuple[Path, str]]]:
    """Carry out a plan. Returns how many moved, and what went wrong.

    A target that already holds the identical picture means this file has been
    filed before under another name — the copy on the Desktop is redundant, so
    the move is skipped rather than creating a second one.
    """
    done = 0
    failures: list[tuple[Path, str]] = []

    for move in plan.doing:
        try:
            move.target.parent.mkdir(parents=True, exist_ok=True)
            if move.target.exists() and _same(move.source, move.target):
                move.skip = "already there, identical"
                continue
            move.source.rename(move.target)
        except OSError as error:
            failures.append((move.source, str(error)))
            continue
        done += 1
        if on_move:
            on_move(move)
    return done, failures


def _same(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
        return digest(left) == digest(right)
    except OSError:
        return False


def summarise(plan: Plan, *, limit: int = 12) -> list[str]:
    """A few example moves and a count per folder, for printing."""
    lines = []
    for move in plan.doing[:limit]:
        lines.append(f"  {move.source.name}")
        lines.append(f"  → {move.target.parent.name}/{move.target.name}")
    if len(plan) > limit:
        lines.append(f"  … and {len(plan) - limit} more")
    return lines
