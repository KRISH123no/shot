"""Turning `Screenshot 2026-09-08 at 6.58.31 PM.png` into something you can read.

The heading of a screenshot is usually the largest text near the top, and
Vision hands back a bounding box for every line, so the geometry is free. That
is the whole idea: rank the lines by how title-shaped they are — big, high up,
confidently read, and of a sensible length — and take the winner.

It is the wrong idea for a browser, and browsers are most of what anyone
screenshots. The largest text near the top of a browser window is the tab
strip, which is the one piece of text on screen guaranteed to be damaged: cut
to whatever fits the tab, with the close button read as a trailing word. That
is how a dashboard became `my dashboard - iit m x`.

So a browser is named from its **domain** instead. It is the only string in
the window that is never truncated and never ambiguous — a tab title is cut to
fit, and a page heading may be a logo with no text in it at all.

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
#: The em dash is kept: it is the separator between a domain and a heading,
#: and without it `site.com — the page` reads as one run-on phrase.
_TIDY = re.compile(r"[^\w\s.,'()—-]+", re.UNICODE)
_SPACE = re.compile(r"\s+")

#: Buttons that Vision reads as words and hands back inside the line. A tab's
#: close button becomes a trailing "x", which is most of why the browser names
#: were wrong.
#: These are the characters Vision actually returns, ambiguous ones included:
#: a close button reads as × as often as x. Matching the lookalike is the job.
GLYPHS = {"x", "×", "+", "⋮", "⋯", "|", "•", "▾", "▼", "‹", "›", "<", ">", "-", "—", "/"}

#: A host, with or without a path. Anchored on a known suffix on purpose:
#: "at 6.58.31 PM" and "v1.2.3" are not domains, and a pattern loose enough to
#: catch every real one catches those too.
URL = re.compile(
    r"\b((?:[a-z0-9][a-z0-9-]*\.)+(?:com|org|net|io|dev|ai|app|me|xyz|edu|gov"
    r"|ac\.in|co\.in|co\.uk|gov\.in|co|in))(?:[/?#]\S*)?",
    re.I,
)

#: Where a browser keeps its chrome: tab strip at the very top, address bar
#: just under it. Measured — on a full-screen browser screenshot the tabs sit
#: at y≈0.96, the address bar at y≈0.90, and the page starts around y≈0.85.
CHROME_BAND = 0.88

#: macOS puts U+202F, a narrow no-break space, before AM/PM in screenshot
#: names. Written as an escape because as a literal it is indistinguishable
#: from a space in every editor, which is exactly the trap.
NARROW_NBSP = " "

MAX_TITLE = 58


def _is_furniture(token: str) -> bool:
    """A token that is a button, a bullet, or an icon read as text.

    Two cases: things made only of punctuation, such as `*=` or an arrow,
    which carry
    no information anywhere, and the handful of single letters that are
    actually buttons, of which `x` on a browser tab is the one that matters.
    """
    bare = token.strip(".,")
    return not bare or not any(c.isalnum() for c in bare) or bare.lower() in GLYPHS


def strip_glyphs(text: str) -> str:
    """Drop buttons and icons that Vision read as words at either end."""
    tokens = text.split()
    while tokens and _is_furniture(tokens[0]):
        tokens.pop(0)
    while tokens and _is_furniture(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def looks_truncated(text: str) -> bool:
    """Does this end mid-word?

    A tab cut to fit leaves a stub: "My Dashboard - IIT Madras B" is "BS
    Degree" with the rest of it gone. A trailing one- or two-letter word is
    almost never how a real title ends, and is exactly how a cut one does.
    """
    tokens = text.split()
    if len(tokens) < 2:
        return False
    last = tokens[-1].strip(".,)")
    return len(last) <= 2 and last.isalpha() and last.lower() not in {"a", "i", "to", "of", "in", "on", "at", "is", "it", "me", "my", "we", "us", "up", "go", "no", "ok", "hi", "ai", "pm", "am"}


def domain_of(lines: Sequence[Line]) -> str | None:
    """The site a browser screenshot is showing, or None if it is not one.

    Searched top-down through the image rather than in reading order: the
    address bar is above the page, and a URL printed in the body of a page is
    not the page's own address.
    """
    for line in sorted(lines, key=lambda item: -item.y):
        found = URL.search(line.text)
        if not found:
            continue
        host = found.group(1).lower().rstrip(".")
        return host[4:] if host.startswith("www.") else host
    return None


def title_score(line: Line, *, index: int, chrome_band: float | None = None) -> float:
    """How much this line looks like the name of the picture."""
    text = strip_glyphs(line.text.strip())
    if not text or text.lower() in CHROME or len(text) < 4:
        return 0.0

    size = min(line.area * 60, 1.0)          # big
    height = min(line.height * 25, 1.0)      # tall glyphs beat a long thin run
    top = line.y                             # Vision's origin is bottom-left
    order = max(0.0, 1.0 - index / 12)       # read early
    length = 1.0 if 12 <= len(text) <= MAX_TITLE else 0.45
    words = 1.0 if " " in text else 0.5      # a single token is rarely a title

    score = (
        (size * 0.2 + height * 0.2 + top * 0.25 + order * 0.15) * length * words
        + line.confidence * 0.2
    )
    if looks_truncated(text):
        score *= 0.35
    # In a browser, everything above this line is chrome, and chrome is the
    # tallest, highest text there is — which is what the geometry rewards.
    if chrome_band is not None and line.y >= chrome_band:
        score *= 0.25
    return round(score, 4)


def best_title(lines: Sequence[Line], *, chrome_band: float | None = None) -> str:
    ranked = sorted(
        (
            (title_score(line, index=i, chrome_band=chrome_band), i,
             strip_glyphs(line.text.strip()))
            for i, line in enumerate(lines)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return ranked[0][2] if ranked and ranked[0][0] > 0 else ""


def describe(lines: Sequence[Line], kind: str = "") -> str:
    """The name for this picture: a domain for a browser, a heading otherwise.

    The heading is kept alongside the domain when it says something the domain
    does not — `photos.google.com` needs no help, but
    `seek.study.iitm.ac.in — activity assignment-3` is worth the extra words.
    """
    domain = domain_of(lines) if kind in ("web", "app", "unknown", "") else None
    if domain is None:
        return _worth_saying(best_title(lines))

    heading = best_title(lines, chrome_band=CHROME_BAND)
    if _adds_to(heading, domain):
        return f"{domain} — {heading}"
    return domain


#: Below this a "title" is an OCR fragment, not a name. Scanned maths notes
#: produce things like "60cm2" and "MeDI" — a label off a diagram, picked
#: because nothing better was on the page. `2026-03-15 app.png` is a more
#: honest name than `2026-03-15 app — 60cm2.png`.
MIN_TITLE = 6


def _worth_saying(title: str) -> str:
    flat = tidy(title)
    return title if len(flat) >= MIN_TITLE and any(c.isalpha() for c in flat) else ""


def _adds_to(heading: str, domain: str) -> bool:
    """Is this heading worth printing next to the domain?"""
    if len(heading) < 8 or looks_truncated(heading):
        return False
    flat = tidy(heading).lower()
    if not flat or flat in domain or domain.startswith(flat.replace(" ", "")):
        return False
    # A heading that is itself a URL is the address bar read twice.
    return not URL.search(heading)


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
