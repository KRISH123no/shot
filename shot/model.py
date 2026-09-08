"""What shot deals in: a picture, the text found in it, and a search hit.

Nothing here imports a Mac framework, which is why the interesting parts —
ranking, classification, naming, near-duplicate detection — can be tested on
a Linux runner with no images at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Line:
    """One run of text Vision found, and where on the picture it sat.

    ``area`` is the fraction of the image the text block covers. It is the
    single most useful signal in the whole tool: the biggest text on a
    screenshot is almost always its heading, which is what you would have
    named the file if you had bothered.
    """

    text: str
    confidence: float
    #: Normalised, origin bottom-left, the way Vision reports it.
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(slots=True)
class Shot:
    """One indexed image."""

    path: str
    size: int
    mtime: float
    #: Digest of the bytes. Identifies a file that was merely renamed, so it
    #: is not put through OCR a second time.
    digest: str = ""
    #: 64-bit perceptual hash. Survives recompression and a changed cursor,
    #: which a byte digest does not.
    phash: int = 0
    width: int = 0
    height: int = 0
    text: str = ""
    lines: list[Line] = field(default_factory=list)
    kind: str = "unknown"
    title: str = ""
    scanned: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass(slots=True)
class Match:
    """A search result."""

    path: str
    score: float
    snippet: str
    kind: str
    mtime: float
    title: str = ""
