"""Building OCR results by hand, so the logic can be tested with no pictures."""

import pytest

from shot.model import Line


def line(text, *, conf=0.9, x=0.1, y=0.5, w=0.3, h=0.02):
    return Line(text=text, confidence=conf, x=x, y=y, width=w, height=h)


def lines(*texts, **kwargs):
    return [line(t, **kwargs) for t in texts]


def grey(*values, width=9, height=8):
    """A 9x8 greyscale buffer, padded with the last value given."""
    data = list(values)
    data += [data[-1] if data else 0] * (width * height - len(data))
    return bytes(data[: width * height])


@pytest.fixture
def index():
    from shot.index import Index

    with Index(":memory:") as db:
        yield db
