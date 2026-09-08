"""Turning `Screenshot 2026-09-08 at 6.58.31 PM.png` into something you can read.

The heading of a screenshot is usually the largest text near the top, and
Vision hands back a bounding box for every line, so the geometry is free. That
is the whole idea: rank the lines by how title-shaped they are — big, high up,
confidently read, and of a sensible length — and take the winner.

Then get out of the way. A rename that loses the date, or collides with a file
already there, is worse than the ugly name it replaced.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from .model import Line

#: Interface furniture that is large, high, and says nothing.
CHROME = {
    "search", "q search", "chats", "menu", "file", "edit", "view", "help", "home",
    "settings", "back", "cancel", "done", "ok", "new tab", "untitled", "close",
}
_TIDY = re.compile(r"[^\w\s.,'()-]+", re.UNICODE)
_SPACE = re.compile(r"\s+")
#: macOS puts U+202F, a narrow no-break space, before AM/PM in screenshot
#: names. Written as an escape because as a literal it is indistinguishable
#: from a space in every editor, which is exactly the trap.
#: It looks exactly like a space and is not one, which is how a path copied out
#: of `ls` stops matching the file it came from.
NARROW_NBSP = "\u202f"

MAX_TITLE = 58


def title_score(line: Line, *, index: int) -> float:
    """How much this line looks like the name of the picture."""
    text = line.text.strip()
    if not text or text.lower() in CHROME or len(text) < 4:
        return 0.0

    size = min(line.area * 60, 1.0)          # big
    height = min(line.height * 25, 1.0)      # tall glyphs beat a long thin run
    top = line.y                             # Vision's origin is bottom-left
    order = max(0.0, 1.0 - index / 12)       # read early
    length = 1.0 if 12 <= len(text) <= MAX_TITLE else 0.45
    words = 1.0 if " " in text else 0.5      # a single token is rarely a title

    return round(
        (size * 0.2 + height * 0.2 + top * 0.25 + order * 0.15) * length * words
        + line.confidence * 0.2,
        4,
    )


def best_title(lines: Sequence[Line]) -> str:
    ranked = sorted(
        ((title_score(line, index=i), i, line.text.strip()) for i, line in enumerate(lines)),
        key=lambda item: (-item[0], item[1]),
    )
    return ranked[0][2] if ranked and ranked[0][0] > 0 else ""


def tidy(text: str, *, limit: int = MAX_TITLE) -> str:
    text = _SPACE.sub(" ", _TIDY.sub(" ", text.replace(NARROW_NBSP, " "))).strip(" .,-")
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]).rstrip(" .,-")


def suggest(path: Path | str, *, title: str, kind: str, when: float | None = None) -> str:
    """`2026-09-08 chat — gentle reminder for the turnitin check.png`

    The date leads, so a directory sorts chronologically the way the old names
    did. Losing that would be a downgrade dressed as an improvement.
    """
    path = Path(path)
    stamp = datetime.fromtimestamp(when if when is not None else path.stat().st_mtime)
    clean = tidy(title).lower()
    parts = [stamp.strftime("%Y-%m-%d")]
    if kind and kind != "unknown":
        parts.append(kind)
    name = " ".join(parts) + (f" — {clean}" if clean else "")
    return name + path.suffix.lower()


def unique(directory: Path, name: str) -> Path:
    """Never overwrite. Two screenshots of the same screen get -2, -3, ..."""
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for n in range(2, 1000):
        alternative = directory / f"{stem}-{n}{suffix}"
        if not alternative.exists():
            return alternative
    raise FileExistsError(f"a thousand files named like {name}")
