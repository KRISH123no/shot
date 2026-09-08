"""Reading a picture, using the text engine already sitting on the Mac.

Vision is on-device, ships with macOS, needs no download and no key, and is
fast on Apple silicon — under a second for a full-screen screenshot. That is
the whole reason this tool is practical: a hundred screenshots is a minute,
not an afternoon and a five-gigabyte model on a disk with seven gigabytes
left.

This is the only file that imports an Apple framework. Everything else works
on the dataclasses it returns.
"""

from __future__ import annotations

import time
from pathlib import Path

from .model import Line

#: Vision's own two settings. "fast" is roughly four times quicker and makes a
#: mess of small text, which is most of what a screenshot contains.
ACCURATE = "accurate"
FAST = "fast"

_DHASH_W, _DHASH_H = 9, 8


class Engine:
    """Vision, resolved once, so the import cost is paid a single time."""

    def __init__(self, *, level: str = ACCURATE, languages: list[str] | None = None) -> None:
        try:
            import Quartz
            import Vision
            from Foundation import NSURL
        except ImportError as error:  # pragma: no cover - only off a Mac
            raise RuntimeError(
                "shot reads text with Apple's Vision framework: pip install 'shot[mac]'"
            ) from error

        self._vision = Vision
        self._quartz = Quartz
        self._nsurl = NSURL
        self.level = level
        self.languages = languages or ["en-US"]

    # ------------------------------------------------------------------ text

    def read(self, path: Path | str) -> tuple[int, int, list[Line]]:
        """Return the image's size and every run of text found in it."""
        Vision = self._vision
        url = self._nsurl.fileURLWithPath_(str(path))

        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(
            Vision.VNRequestTextRecognitionLevelAccurate
            if self.level == ACCURATE
            else Vision.VNRequestTextRecognitionLevelFast
        )
        request.setUsesLanguageCorrection_(self.level == ACCURATE)
        request.setRecognitionLanguages_(self.languages)

        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise OSError(f"could not read {path}: {error}")

        lines: list[Line] = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates or not len(candidates):
                continue
            best = candidates[0]
            box = observation.boundingBox()
            lines.append(
                Line(
                    text=best.string(),
                    confidence=float(best.confidence()),
                    x=float(box.origin.x),
                    y=float(box.origin.y),
                    width=float(box.size.width),
                    height=float(box.size.height),
                )
            )

        width, height = self.dimensions(path)
        return width, height, lines

    # ----------------------------------------------------------------- pixels

    def _cgimage(self, path: Path | str):
        Quartz = self._quartz
        source = Quartz.CGImageSourceCreateWithURL(
            self._nsurl.fileURLWithPath_(str(path)), None
        )
        if source is None:
            raise OSError(f"not an image this Mac can decode: {path}")
        image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        if image is None:
            raise OSError(f"could not decode {path}")
        return image

    def dimensions(self, path: Path | str) -> tuple[int, int]:
        image = self._cgimage(path)
        return (
            int(self._quartz.CGImageGetWidth(image)),
            int(self._quartz.CGImageGetHeight(image)),
        )

    def greyscale(self, path: Path | str) -> bytes:
        """Shrink to nine by eight, in grey, for the perceptual hash.

        Core Graphics does the resampling, so this costs nothing extra and
        avoids pulling in an imaging library to shrink a picture to 72 pixels.
        """
        Quartz = self._quartz
        image = self._cgimage(path)
        space = Quartz.CGColorSpaceCreateDeviceGray()
        context = Quartz.CGBitmapContextCreate(
            None, _DHASH_W, _DHASH_H, 8, _DHASH_W, space, Quartz.kCGImageAlphaNone
        )
        if context is None:
            raise OSError(f"could not make a bitmap for {path}")
        Quartz.CGContextSetInterpolationQuality(context, Quartz.kCGInterpolationHigh)
        Quartz.CGContextDrawImage(
            context, Quartz.CGRectMake(0, 0, _DHASH_W, _DHASH_H), image
        )
        raw = Quartz.CGBitmapContextGetData(context)
        count = _DHASH_W * _DHASH_H
        # pyobjc hands back an objc.varlist, which slices into a tuple of
        # one-byte objects rather than into bytes. as_buffer gives the real
        # memory; the join is the fallback for older bridge versions.
        try:
            return bytes(raw.as_buffer(count))
        except AttributeError:  # pragma: no cover
            return b"".join(raw[:count])


def timed(function, *args, **kwargs):
    """Run something and say how long it took, for the progress line."""
    started = time.perf_counter()
    return function(*args, **kwargs), time.perf_counter() - started
