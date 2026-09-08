"""What kind of screenshot is this?

Not machine learning. A screenshot of a chat and a screenshot of a terminal
differ in ways you can state in a sentence — one has clock times down one
side and short lines, the other has brackets and prompts — and a rule you can
state is a rule you can debug at two in the morning. A model that says
"terminal, 0.83" and cannot say why is worse here, not better.

Every classifier scores from zero to one and the highest wins. Scores rather
than a chain of ifs, because screenshots are genuinely mixed: an error message
inside a terminal is both, and the ranking should say which is more.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .model import Line

KINDS = ("chat", "terminal", "error", "web", "settings", "document", "receipt",
         "app", "unknown")

_TIME = re.compile(r"\b\d{1,2}:\d{2}\s*(?:[APap]\.?[Mm]\.?)?\b")
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+\.(?:com|org|net|io|dev|ac\.in|gov|edu)\b")
_CODE_PUNCT = re.compile(r"[{}()\[\];=<>|/\\$#*&^~`]")
#: A shell prompt, not merely a dollar sign. The loose version of this matched
#: `% S` in a percentage, `$ 9` in a price and `> 0` in a breadcrumb, which put
#: three-fifths of a real screenshot collection in the terminal pile. So: the
#: prompt character must open a line, and what follows must look like a command
#: rather than a digit. The second half wants a command *with an argument*, for
#: the same reason — "git" is also a word in a sentence.
_PROMPT = re.compile(
    r"(?m)^\s*[$%>\u276f\u279c]\s+[a-z][\w.-]+"
    r"|(?<![\w-])(?:sudo|npm|pnpm|yarn|pip3?|git|brew|pytest|cargo|docker|ssh"
    r"|curl|chmod|mkdir|source|export|venv|conda)\s+[\w./=-]"
)
_ERROR = re.compile(
    r"\b(?:error|errno|exception|traceback|failed|failure|denied|refused|not found"
    r"|cannot|could not|invalid|unable to|fatal|panic|limit reached|rate limit"
    r"|quota|too many|timed out|expired|unavailable|try again)\b",
    re.I,
)
_MONEY = re.compile(r"(?:[₹$€£]\s?\d|\b(?:INR|USD|EUR|GBP)\b)")
_TOTAL = re.compile(r"\b(?:total|subtotal|amount|paid|invoice|receipt|payment|order)\b", re.I)
#: The settings app names itself. Anything less than that is a word like
#: "general" or "security", which appear in half the emails ever written.
_SETTINGS_APP = re.compile(r"\b(?:system settings|system preferences|control cent(?:re|er))\b", re.I)
#: Pane names. Two of them together is a settings window; one is a coincidence.
_SETTINGS_PANE = re.compile(
    r"\b(?:accessibility|bluetooth|wi-?fi|software update|screen time|touch id"
    r"|login items|full disk access|screen recording|sound|displays)\b",
    re.I,
)
_CHROME = re.compile(r"\b(?:bookmarks|new tab|incognito|address bar|reload|back|forward)\b", re.I)


def _ratio(lines: Sequence[str], test) -> float:
    return sum(1 for line in lines if test(line)) / len(lines) if lines else 0.0


def score(lines: Sequence[Line]) -> dict[str, float]:
    """How much each kind explains this picture."""
    texts = [line.text.strip() for line in lines if line.text.strip()]
    if not texts:
        return dict.fromkeys(KINDS, 0.0) | {"unknown": 1.0}

    joined = "\n".join(texts)
    count = len(texts)
    short = _ratio(texts, lambda t: len(t) <= 40)
    long_prose = _ratio(texts, lambda t: len(t) >= 60 and " " in t)
    times = len(_TIME.findall(joined))
    punct = sum(len(_CODE_PUNCT.findall(t)) for t in texts) / max(len(joined), 1)

    scores = {
        # Clock times running down the side, and most lines short. One stray
        # timestamp is a clock in the menu bar, so this needs several.
        # The first clock is the one in the menu bar; it proves nothing. Real
        # chats stamp every few messages, so only the extras count — and short
        # lines only corroborate, never carry it alone, or a picture with the
        # single word "meow" in it becomes a conversation.
        "chat": min(max(times - 1, 0) / 4, 1.0) * 0.75 + (short * 0.25 if times >= 2 else 0.0),
        # A prompt or a shell word carries this; punctuation only corroborates.
        # Interface chrome OCRs as arrows and chevrons — <, >, •, — — and on
        # density alone a screenshot of Word outscores an actual terminal.
        "terminal": (0.5 if _PROMPT.search(joined) else 0.0) + min(punct * 8, 1.0) * 0.3,
        "error": min(len(_ERROR.findall(joined)) / 2, 1.0) * 0.9,
        "web": (0.55 if _URL.search(joined) else 0.0)
        + (0.35 if _CHROME.search(joined) else 0.0),
        "settings": 0.85
        if _SETTINGS_APP.search(joined)
        else (0.55 if len(set(_SETTINGS_PANE.findall(joined))) >= 2 else 0.0),
        "receipt": (0.5 if _MONEY.search(joined) else 0.0)
        + (0.45 if _TOTAL.search(joined) else 0.0),
        # Real sentences, and enough of them. A bonus for merely having many
        # lines made a document of every busy interface: fifty-eight lines of
        # buttons and menu items, not one of them a sentence.
        "document": long_prose * 0.85 if long_prose >= 0.25 else 0.0,
        # Most screenshots are of an interface: many short runs of text, menu
        # items and labels, and barely a sentence between them. Without this,
        # more than half a real collection lands in "unknown", which is honest
        # and useless. It scores below every specific signal, so it only ever
        # catches what nothing else explains.
        "app": 0.35 if count >= 12 and long_prose < 0.15 and short > 0.7 else 0.0,
        # The floor. Anything that clears nothing else is honestly unknown,
        # which is a more useful answer than a confident wrong one.
        "unknown": 0.15,
    }
    return {kind: round(min(value, 1.0), 3) for kind, value in scores.items()}


def classify(lines: Sequence[Line]) -> str:
    ranked = score(lines)
    return max(ranked.items(), key=lambda kv: (kv[1], kv[0] != "unknown"))[0]
