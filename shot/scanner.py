"""Walk, read, classify, store — and do as little of it as possible.

Reading a picture is the expensive step, roughly seven-tenths of a second
each, so nearly all the engineering here is about not doing it:

**Unchanged files are skipped** on size and mtime, so the second scan of a
folder costs a directory walk.

**A moved or copied file is recognised by its bytes.** Renaming a screenshot
is not a reason to read it again — the digest finds the old row and the text
is carried across.

**The rest run in parallel.** Vision spends its time inside Apple's framework
rather than in Python, so threads genuinely overlap; the database stays
single-threaded, taking finished work as it lands.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .classify import classify
from .hashing import dhash, digest, to_unsigned
from .index import Index
from .model import Shot
from .naming import best_title
from .ocr import Engine


def _safe_digest(path: Path) -> str:
    try:
        return digest(path)
    except OSError:
        return ""


@dataclass(slots=True)
class Report:
    read: int = 0
    skipped: int = 0
    reused: int = 0
    failed: int = 0
    seconds: float = 0.0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.read + self.skipped + self.reused + self.failed

    def __str__(self) -> str:
        rate = f"{self.read / self.seconds:.1f}/s" if self.seconds and self.read else "—"
        return (
            f"{self.read} read ({rate}), {self.reused} recognised by content, "
            f"{self.skipped} unchanged, {self.failed} failed, in {self.seconds:.1f}s"
        )


def _examine(path: Path, engine: Engine, known_digest: str = "") -> Shot:
    """Everything that touches the picture itself. Runs off the main thread."""
    stat = path.stat()
    shot = Shot(path=str(path), size=stat.st_size, mtime=stat.st_mtime,
                digest=known_digest or digest(path), scanned=time.time())
    try:
        shot.width, shot.height, shot.lines = engine.read(path)
        shot.text = "\n".join(line.text for line in shot.lines)
        shot.kind = classify(shot.lines)
        shot.title = best_title(shot.lines)
        try:
            shot.phash = dhash(engine.greyscale(path))
        except (OSError, ValueError):
            shot.phash = 0  # a picture worth reading is still worth indexing
    except (OSError, RuntimeError) as error:
        shot.error = str(error)[:300]
    return shot


def scan(
    index: Index,
    paths: Iterable[Path],
    *,
    engine: Engine | None = None,
    jobs: int = 4,
    force: bool = False,
    progress: Callable[[int, int, Path], None] | None = None,
) -> Report:
    engine = engine or Engine()
    report = Report()
    started = time.perf_counter()

    todo: list[Path] = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        if not force and index.is_current(str(path), stat.st_size, stat.st_mtime):
            report.skipped += 1
            continue
        todo.append(path)

    def finish(shot: Shot) -> None:
        index.upsert(shot)
        if shot.error:
            report.failed += 1
            report.errors.append((shot.path, shot.error))

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        # Digest everything first, in parallel. This is file reading, which
        # genuinely overlaps, and doing it inline in the loop below would put
        # a serial disk read between every parallel OCR.
        digests = dict(zip(todo, pool.map(_safe_digest, todo), strict=True))

        futures = {}
        for path in todo:
            # The bytes settle whether this is a file already read under
            # another name. The lookup itself stays on this thread; SQLite
            # connections are not shared.
            found = digests[path]
            known = index.by_digest(found) if found else None
            if known is not None and not force and known["path"] != str(path):
                stat = path.stat()
                carried = Shot(
                    path=str(path), size=stat.st_size, mtime=stat.st_mtime,
                    digest=known["digest"], phash=to_unsigned(known["phash"]),
                    width=known["width"], height=known["height"],
                    kind=known["kind"], title=known["title"], text=known["text"],
                    scanned=time.time(),
                )
                index.upsert(carried)
                report.reused += 1
                done += 1
                if progress:
                    progress(done, len(todo), path)
                continue
            futures[pool.submit(_examine, path, engine, digests[path])] = path

        for future in as_completed(futures):
            shot = future.result()
            finish(shot)
            if not shot.error:
                report.read += 1
            done += 1
            if progress:
                progress(done, len(todo), Path(shot.path))

    report.seconds = time.perf_counter() - started
    return report
