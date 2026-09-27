"""Finding the pictures, and not wandering into places that will waste an hour.

The naive version — walk everything under the home directory — spends most of
its time inside application bundles, caches and node_modules, reading icons
nobody wants to search. The exclusions below are most of what makes a scan
take a minute instead of forty.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

#: Formats Core Graphics decodes without help.
EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp",
                        ".tiff", ".tif", ".gif", ".bmp"})

#: Directory names never worth descending into. Anything ending in one of the
#: bundle suffixes goes too — a .app is a directory full of icons, and a
#: .photoslibrary is a directory full of somebody else's index.
SKIP_NAMES = frozenset({
    "node_modules", ".git", ".svn", "__pycache__", ".venv", "venv", "env",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".Trash", "Library", ".cache", ".npm", ".cargo", "site-packages",
})
SKIP_SUFFIXES = (".app", ".photoslibrary", ".fcpbundle", ".framework",
                 ".xcodeproj", ".bundle", ".sparsebundle", ".lproj")

#: Under this, it is an icon or a UI asset, not something you screenshotted.
MIN_BYTES = 8 * 1024


#: Names macOS and the common capture tools give a screenshot.
SCREENSHOT = re.compile(
    r"^(?:screen[ _-]?shot|screenshot|cleanshot|shottr|capture|snip)", re.I
)


def default_roots() -> list[Path]:
    """Where screenshots land — not the whole picture library.

    ``~/Pictures`` holds six thousand photographs on this machine and no text
    worth searching. Reading them would cost two hours and would quietly build
    a searchable index of somebody's birthday party, which is not what anyone
    asked this tool to do. Pass a path explicitly to scan one.
    """
    home = Path.home()
    wanted = [home / "Desktop", home / "Downloads", home / "Pictures" / "Screenshots"]
    return [p for p in wanted if p.is_dir()]


def looks_like_a_screenshot(path: Path | str) -> bool:
    return bool(SCREENSHOT.match(Path(path).name))


def skip_dir(name: str) -> bool:
    return (
        name in SKIP_NAMES
        or (name.startswith(".") and name not in {".", ".."})
        or name.endswith(SKIP_SUFFIXES)
    )


def images(
    roots: Iterable[Path | str],
    *,
    min_bytes: int = MIN_BYTES,
    follow_symlinks: bool = False,
    screenshots_only: bool = False,
) -> Iterator[Path]:
    """Every image worth reading, deepest-first order not guaranteed.

    Symlinks are not followed by default: one link pointing at your home
    directory is all it takes to walk the disk twice.
    """
    seen: set[tuple[int, int]] = set()

    for root in roots:
        root = Path(root).expanduser()
        if not root.exists():
            continue
        if root.is_file():
            if root.suffix.lower() in EXTENSIONS:
                yield root
            continue

        for folder, subdirs, files in os.walk(root, followlinks=follow_symlinks):
            subdirs[:] = [d for d in subdirs if not skip_dir(d)]
            for name in files:
                if name.startswith("."):
                    continue
                if Path(name).suffix.lower() not in EXTENSIONS:
                    continue
                if screenshots_only and not SCREENSHOT.match(name):
                    continue
                path = Path(folder) / name
                try:
                    stat = path.stat()
                except OSError:
                    continue  # vanished, or not ours to read
                # The size floor is there to skip interface assets. A file
                # named like a screenshot is never one, and a screenshot of a
                # small dialog is genuinely only a few kilobytes — four real
                # ones were silently skipped before this exception existed.
                if stat.st_size < min_bytes and not SCREENSHOT.match(name):
                    continue
                # The same file reached down two paths is still one file.
                key = (stat.st_dev, stat.st_ino)
                if key in seen:
                    continue
                seen.add(key)
                yield path
