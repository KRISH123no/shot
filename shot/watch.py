"""Filing screenshots as they are taken.

A screenshot appears on the Desktop the instant you release the shortcut, but
it is not finished — macOS is still writing it, and a file read at that moment
is a truncated PNG that Vision refuses. So a new file is left alone until its
size stops changing.

Polling rather than FSEvents, deliberately. FSEvents delivers through a run
loop, and a background agent with no run loop never hears it — which is the
exact failure that made a sister project report the same application for
nineteen days. A directory listing every couple of seconds costs nothing and
cannot go quietly stale.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .index import Index
from .organise import apply as apply_plan
from .organise import build
from .scanner import scan
from .walk import EXTENSIONS, looks_like_a_screenshot

LABEL = "com.shot.watcher"

#: How long a file's size must hold still before it is considered written.
SETTLE = 0.6
#: Give up on a file that never settles — something else is still appending.
SETTLE_TIMEOUT = 20.0


def settled(path: Path, *, settle: float = SETTLE, timeout: float = SETTLE_TIMEOUT,
            sleep: Callable[[float], None] = time.sleep) -> bool:
    """Wait until the file stops growing. False if it never does."""
    waited = 0.0
    try:
        last = path.stat().st_size
    except OSError:
        return False
    while waited < timeout:
        sleep(settle)
        waited += settle
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == last and size > 0:
            return True
        last = size
    return False


def candidates(folder: Path, *, screenshots_only: bool = True) -> set[Path]:
    """Images sitting directly in a folder — not recursive, on purpose.

    The watched folder is the one screenshots land in. Descending into it
    would re-file everything already tidied away underneath.
    """
    found = set()
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return found
    for entry in entries:
        if not entry.is_file() or entry.name.startswith("."):
            continue
        path = Path(entry.path)
        if path.suffix.lower() not in EXTENSIONS:
            continue
        if screenshots_only and not looks_like_a_screenshot(path):
            continue
        found.add(path)
    return found


def watch(
    index: Index,
    folder: Path,
    *,
    root: Path,
    period: str = "month",
    interval: float = 3.0,
    apply: bool = False,
    engine=None,
    once: bool = False,
    known: set[Path] | None = None,
    on_file: Callable[[Path, Path | None], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> int:
    """Read and file every screenshot that appears. Returns how many.

    Everything already in the folder at startup is taken as the baseline and
    left alone — starting the watcher should not silently reorganise a Desktop
    you have not looked at yet.

    ``known`` is that baseline, and it is mutated in place. A caller polling
    with ``once=True`` must pass its own set and keep it between calls;
    otherwise every call re-baselines and nothing is ever new, which is a
    watcher that silently does nothing.
    """
    from .ocr import Engine

    engine = engine or Engine()
    if known is None:
        known = candidates(folder)
    handled = 0

    while True:
        current = candidates(folder)
        for path in sorted(current - known):
            known.add(path)
            if not settled(path, sleep=sleep):
                continue

            scan(index, [path], engine=engine, jobs=1)
            row = index.db.execute(
                "SELECT * FROM shots WHERE path = ?", (str(path),)
            ).fetchone()
            if row is None:
                continue

            plan = build([row], root=root, period=period)
            target = plan.moves[0].target if plan.doing else None
            if apply and plan.doing:
                moved, _ = apply_plan(plan)
                if moved:
                    index.move(str(path), str(target))
            if on_file:
                on_file(path, target)
            handled += 1

        # Forget files that have gone, so a name reused later counts as new.
        known &= current | {p for p in known if p.exists()}
        if once:
            return handled
        sleep(interval)


# ------------------------------------------------------------------ launchd


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_agent_can_start(python: str) -> None:
    """Run what launchd will run, from where launchd will run it."""
    try:
        done = subprocess.run(
            [python, "-c", "import shot"], capture_output=True, text=True, cwd="/",
            env={**os.environ, "PYTHONPATH": str(package_root())}, timeout=30,
        )
    except OSError as error:
        raise RuntimeError(f"cannot run {python}: {error}") from error
    if done.returncode != 0:
        raise RuntimeError(
            f"{python} cannot import shot when started outside the repository.\n"
            f"  install it there first:  {python} -m pip install -e ."
        )


def build_plist(*, python: str | None = None, folder: Path, root: Path,
                period: str = "month") -> str:
    python = python or sys.executable
    log = Path.home() / ".shot" / "watcher.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string><string>shot</string><string>watch</string>
        <string>--folder</string><string>{folder}</string>
        <string>--root</string><string>{root}</string>
        <string>--by</string><string>{period}</string>
        <string>--apply</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict><key>PYTHONPATH</key><string>{package_root()}</string></dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ProcessType</key><string>Background</string>
    <key>LowPriorityIO</key><true/>
    <key>StandardErrorPath</key><string>{log}</string>
    <key>StandardOutPath</key><string>{log}</string>
</dict>
</plist>
"""


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["launchctl", *args], capture_output=True, text=True)
    except OSError:
        return subprocess.CompletedProcess(args, 127, "", "launchctl not found")


def install(*, folder: Path, root: Path, period: str = "month",
            python: str | None = None) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("the watcher runs at login through launchd, which is macOS only")
    check_agent_can_start(python or sys.executable)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    (Path.home() / ".shot").mkdir(parents=True, exist_ok=True)
    path.write_text(build_plist(python=python, folder=folder, root=root, period=period),
                    encoding="utf-8")
    target = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{target}/{LABEL}")
    if _launchctl("bootstrap", target, str(path)).returncode != 0:
        _launchctl("load", "-w", str(path))
    return path


def uninstall() -> bool:
    path = plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    _launchctl("unload", str(path))
    if path.exists():
        path.unlink()
        return True
    return False


def is_running() -> bool:
    return any(LABEL in line for line in _launchctl("list").stdout.splitlines())
