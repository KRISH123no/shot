"""Two kinds of sameness.

A **digest** answers "are these the same bytes". It catches the file you
copied, and it is what lets a rename skip re-reading the picture.

A **perceptual hash** answers "are these the same picture", which is the
question you actually have when you screenshot the same window twice and one
of them has the cursor in it. Byte digests say those are unrelated. This says
they are one pixel apart.

The construction is dHash: shrink to nine pixels by eight, in grey, then set
one bit per horizontal pair for whether the left pixel is brighter than the
right. Sixty-four comparisons, sixty-four bits. It survives rescaling and
recompression because it records *relationships* between regions rather than
any absolute value.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Two images within this Hamming distance are the same picture.
#: Chosen low: at 64 bits, unrelated screenshots of similar UIs sit around 25
#: to 30 bits apart, and genuine variants land under 8.
NEAR = 8


def digest(path: Path | str, *, chunk: int = 1 << 20) -> str:
    """A content digest, read in chunks so a large image is not held in memory."""
    hasher = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as handle:
        while block := handle.read(chunk):
            hasher.update(block)
    return hasher.hexdigest()


def dhash(grey: bytes, width: int = 9, height: int = 8) -> int:
    """Pack a 9x8 greyscale buffer into 64 bits of brightness comparisons."""
    if len(grey) < width * height:
        raise ValueError(f"need {width * height} bytes, got {len(grey)}")
    bits = 0
    for row in range(height):
        base = row * width
        for column in range(width - 1):
            bits <<= 1
            if grey[base + column] > grey[base + column + 1]:
                bits |= 1
    return bits


MASK = 0xFFFF_FFFF_FFFF_FFFF


def to_signed(value: int) -> int:
    """SQLite's INTEGER is signed 64-bit; a dHash is unsigned 64-bit.

    Half of all possible hashes do not fit, and the failure is an overflow at
    insert time rather than a wrong answer, which at least is loud.
    """
    value &= MASK
    return value - (1 << 64) if value >= (1 << 63) else value


def to_unsigned(value: int) -> int:
    return value & MASK


def distance(left: int, right: int) -> int:
    """How many of the sixty-four comparisons disagree."""
    return ((left ^ right) & MASK).bit_count()


def cluster(items: list[tuple[str, int]], *, near: int = NEAR) -> list[list[str]]:
    """Group paths whose pictures are the same, allowing for small differences.

    Union-find rather than a single pass: if A is close to B and B is close to
    C but A is not quite close to C, the three are still one pile. Comparing
    every pair is fine at this size — a life's worth of screenshots is tens of
    thousands, and the whole thing is a bit-count.
    """
    parent = list(range(len(items)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if distance(items[i][1], items[j][1]) <= near:
                a, b = find(i), find(j)
                if a != b:
                    parent[a] = b

    groups: dict[int, list[str]] = {}
    for index, (path, _) in enumerate(items):
        groups.setdefault(find(index), []).append(path)
    return [sorted(g) for g in groups.values() if len(g) > 1]
