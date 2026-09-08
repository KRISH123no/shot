"""A small pretend collection, so the tool can be seen before you scan anything.

Reading pictures is the one part that needs a Mac and a minute; everything
after it is rules over text. These are the results those rules would receive,
written out by hand — which means the README's output is real output, and
anyone can reproduce it on any machine without owning the screenshots.
"""

from __future__ import annotations

import time

from .classify import classify
from .index import Index
from .model import Line, Shot
from .naming import best_title

#: (filename, days ago, [(text, y, height)]) — y is Vision's, origin bottom-left.
COLLECTION = [
    ("Screenshot 2026-09-08 at 6.58.31 PM.png", 1, [
        ("Chats", 0.97, 0.02), ("Search", 0.94, 0.02),
        ("Dr Sumit Goswami", 0.90, 0.035),
        ("6:52 PM", 0.80, 0.012),
        ("Respected Sir, gentle reminder for the clearance whenever convenient", 0.74, 0.015),
        ("7:04 PM", 0.62, 0.012), ("Will look at it tonight", 0.56, 0.015),
        ("7:11 PM", 0.44, 0.012), ("Thank you sir", 0.38, 0.015),
    ]),
    ("Screenshot 2026-09-05 at 3.32.49 PM.png", 4, [
        ("Session limit reached", 0.72, 0.05),
        ("Auto-resuming at 7:11 PM", 0.62, 0.02),
        ("Auto-continue when limits reset", 0.54, 0.018),
        ("View details", 0.44, 0.016), ("Try again", 0.38, 0.016),
    ]),
    ("Screenshot 2026-09-05 at 4.40.48 PM.png", 4, [
        ("ds.study.iitm.ac.in/student_dashboard/current_courses", 0.96, 0.014),
        ("My Dashboard - IIT Madras BS Degree", 0.90, 0.03),
        ("Database Management Systems", 0.78, 0.022),
        ("Week 6 - Normalisation", 0.70, 0.018),
        ("Graded assignment due 14 September", 0.62, 0.016),
    ]),
    ("Screenshot 2026-08-27 at 1.14.02 AM.png", 13, [
        ("apple@mac tally %", 0.95, 0.014),
        ("$ pytest -q", 0.90, 0.014),
        ("172 passed in 1.04s", 0.84, 0.014),
        ("$ ruff check .", 0.78, 0.014),
        ("All checks passed!", 0.72, 0.014),
    ]),
    ("Screenshot 2026-08-19 at 11.02.10 AM.png", 21, [
        ("Order #KB-4821", 0.94, 0.03), ("Domain registration", 0.84, 0.018),
        ("Subtotal", 0.70, 0.016), ("Rs 799.00", 0.70, 0.016),
        ("Total", 0.60, 0.02), ("Rs 942.82", 0.60, 0.02),
    ]),
    ("Screenshot 2026-08-14 at 9.20.44 PM.png", 26, [
        ("System Settings", 0.96, 0.035),
        ("Privacy & Security", 0.88, 0.022),
        ("Accessibility", 0.78, 0.018), ("Screen Recording", 0.70, 0.018),
        ("Full Disk Access", 0.62, 0.018),
    ]),
    ("Screenshot 2026-08-02 at 5.05.19 PM.png", 38, [
        ("export ANTHROPIC_API_KEY=sk-ant-api03-notarealkeyatallxxxx", 0.90, 0.014),
        ("apple@mac ~ %", 0.95, 0.014),
        ("$ python -m airlock serve", 0.84, 0.014),
        ("listening on 8080", 0.78, 0.014),
    ]),
]


def build(index: Index) -> int:
    """Fill an index with the pretend collection. Returns how many."""
    now = time.time()
    for order, (name, days, raw) in enumerate(COLLECTION):
        lines = [
            Line(text=text, confidence=0.93, x=0.08, y=y, width=min(len(text) * 0.011, 0.8),
                 height=height)
            for text, y, height in raw
        ]
        text = "\n".join(line.text for line in lines)
        index.upsert(
            Shot(
                path=f"/Users/you/Desktop/{name}",
                size=1_400_000 - order * 90_000,
                mtime=now - days * 86400,
                digest=f"demo{order:02d}",
                phash=(0x0F0F_0F0F_0F0F_0F0F * (order + 1)) & 0xFFFF_FFFF_FFFF_FFFF,
                width=2560, height=1600,
                kind=classify(lines), title=best_title(lines),
                text=text, lines=lines, scanned=now,
            )
        )
    return len(COLLECTION)
