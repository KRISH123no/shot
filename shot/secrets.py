"""Which of your screenshots have credentials in them.

You screenshot a terminal to send someone an error and the export line above
it goes too. Once the picture is indexed, the key is searchable text sitting
in a database — so the tool that made that true owes you a way to find them.

This reports. It never edits or deletes a picture: a false positive that
quietly damages a screenshot you needed is a far worse failure than one you
have to glance at and dismiss.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

#: Order matters. The first pattern to claim a string owns it, so anything
#: whose prefix is a longer version of another's must come first — otherwise
#: `sk-ant-...` is reported as an OpenAI key and the specific rule never runs.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_-]{16,}")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("google api key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("private key", re.compile(r"-{2,}BEGIN [A-Z ]*PRIVATE KEY")),
    ("assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|passwd|password|token|bearer)\b\s*[:=]\s*\S{6,}")),
]

_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def luhn(number: str) -> bool:
    """The checksum every card number satisfies.

    Without it, any thirteen-to-nineteen digit run is a card — order numbers,
    tracking numbers, the timestamps in a log — and a check that cries wolf on
    every screenshot of a terminal is a check nobody reads.
    """
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def mask(text: str) -> str:
    """Show enough to recognise it, never enough to use it."""
    text = text.strip()
    if len(text) <= 10:
        return text[:2] + "…"
    return f"{text[:6]}…{text[-3:]}"


def find(text: str) -> list[tuple[str, str]]:
    """Every apparent credential in some text, as (what, masked)."""
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()

    for label, pattern in PATTERNS:
        for found in pattern.findall(text):
            value = found if isinstance(found, str) else found[0]
            if value not in seen:
                seen.add(value)
                hits.append((label, mask(value)))

    for candidate in _CARD.findall(text):
        if luhn(candidate) and candidate not in seen:
            seen.add(candidate)
            hits.append(("card number", mask(candidate)))

    return hits


def scan(rows: Iterable[tuple[str, str]]) -> Iterator[tuple[str, list[tuple[str, str]]]]:
    """Run :func:`find` over (path, text) pairs, yielding only the hits."""
    for path, text in rows:
        found = find(text or "")
        if found:
            yield path, found
