"""`shot scan`, `find`, `dupes`, `secrets`, `rename`."""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from . import __version__
from .hashing import NEAR, cluster
from .index import Index, default_path
from .naming import suggest, unique
from .secrets import scan as scan_secrets
from .walk import default_roots, images

HL_ON, HL_OFF = "\x02", "\x03"
BOLD, DIM, GREEN, YELLOW, RED, RESET = (
    "\033[1m", "\033[2m", "\033[38;5;35m", "\033[38;5;214m", "\033[38;5;203m", "\033[0m",
)


def colour() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("SHOT_COLOR") == "always":
        return True  # for capturing output into a document
    return sys.stdout.isatty()


def paint(text: str, style: str) -> str:
    return f"{style}{text}{RESET}" if colour() else text


def terminal_width(default: int = 96) -> int:
    import shutil

    return max(60, min(shutil.get_terminal_size((default, 24)).columns, 120))


def clip(text: str, width: int) -> str:
    """Cut to width, counting what will be shown rather than what is stored.

    The highlight markers are zero-width once they become colour codes, so a
    naive slice cuts the visible line short by however many matches it found.
    """
    shown = 0
    out = []
    for chunk in re.split(f"([{HL_ON}{HL_OFF}])", text):
        if chunk in (HL_ON, HL_OFF):
            if chunk == HL_ON and shown >= width:
                break  # opening a highlight with no room left renders as "[]"
            out.append(chunk)
            continue
        room = width - shown
        if room <= 0:
            break
        out.append(chunk[:room])
        shown += len(chunk[:room])
    result = "".join(out)
    if result.count(HL_ON) > result.count(HL_OFF):
        result += HL_OFF
    return result + ("…" if shown >= width else "")


def short(path: str, *, width: int = 52) -> str:
    text = str(path).replace(str(Path.home()), "~")
    return text if len(text) <= width else "…" + text[-(width - 1):]


def human(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(count) < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} GB"


def show_group(paths: list[str], indent: str = "    ") -> list[str]:
    """Print a set of duplicates so that what differs is what you can see.

    Truncating from the left made two files in the same deep folder render as
    the same line — which, in a list whose whole purpose is telling near
    identical things apart, is the one mistake that matters.
    """
    import os.path

    if len(paths) < 2:
        return [f"{indent}{short(p)}" for p in paths]
    common = os.path.commonpath(paths)
    if common in ("/", ""):
        return [f"{indent}{p}" for p in paths]
    lines = [f"{indent}{short(common, width=60)}/"]
    lines += [f"{indent}  {os.path.relpath(p, common)}" for p in paths]
    return lines


def _open(path: str) -> None:
    subprocess.run(["open", path], check=False)


# ---------------------------------------------------------------- commands


def cmd_scan(args) -> int:
    from .ocr import Engine
    from .scanner import scan

    index = Index(args.db)
    roots = [Path(p).expanduser() for p in args.paths] if args.paths else default_roots()
    if not roots:
        print("nothing to scan — pass a folder")
        return 1

    found = list(images(roots, screenshots_only=args.screenshots))
    print(f"{len(found)} images under {', '.join(short(str(r), width=30) for r in roots)}")
    if not found:
        return 0

    try:
        engine = Engine(level="fast" if args.fast else "accurate")
    except RuntimeError as error:
        print(error)
        return 1

    def progress(done: int, total: int, path: Path) -> None:
        if sys.stdout.isatty():
            print(f"\r  {done}/{total}  {short(path.name, width=48):<50}", end="", flush=True)

    report = scan(index, found, engine=engine, jobs=args.jobs,
                  force=args.force, progress=progress)
    if sys.stdout.isatty():
        print("\r" + " " * 62, end="\r")
    print(f"  {report}")
    for path, error in report.errors[:5]:
        print(paint(f"  ! {short(path)}: {error[:70]}", RED))
    return 0


def cmd_find(args) -> int:
    index = Index(args.db)
    try:
        hits = index.search(args.query, limit=args.limit, kind=args.kind)
    except ValueError as error:
        print(error)
        return 1

    if not hits:
        print(f"nothing matches {args.query!r}")
        return 1

    for position, hit in enumerate(hits, start=1):
        when = datetime.fromtimestamp(hit.mtime).strftime("%Y-%m-%d")
        # A fixed-width prefix, so the snippets line up and the clip below can
        # know how much room is actually left.
        prefix = f"     {when}  {hit.kind:<8}  "
        snippet = clip(hit.snippet.replace("\n", " "), terminal_width() - len(prefix) - 2)
        snippet = (
            snippet.replace(HL_ON, BOLD + YELLOW).replace(HL_OFF, RESET)
            if colour()
            else snippet.replace(HL_ON, "[").replace(HL_OFF, "]")
        )
        print(f"{position:>3}. {paint(short(hit.path), BOLD)}")
        print(f"     {paint(f'{when}  {hit.kind:<8}', DIM)}  {snippet}")

    if args.open:
        _open(hits[0].path)
        print(paint(f"\nopened {short(hits[0].path)}", DIM))
    return 0


def cmd_show(args) -> int:
    index = Index(args.db)
    text = index.text_of(str(Path(args.path).expanduser().resolve()))
    if text is None:
        text = index.text_of(args.path)
    if text is None:
        print("not indexed — run `shot scan` on its folder first")
        return 1
    print(text)
    return 0


def cmd_dupes(args) -> int:
    index = Index(args.db)

    exact = index.digests()
    if exact:
        print(paint(f"{len(exact)} sets of identical files", BOLD))
        for paths in list(exact.values())[: args.limit]:
            print(f"  {len(paths)} copies")
            print("\n".join(show_group(paths)))

    groups = cluster(index.phashes(), near=args.near)
    # Anything already reported as byte-identical is not news again.
    identical = {tuple(sorted(paths)) for paths in exact.values()}
    near = [g for g in groups if tuple(sorted(g)) not in identical]
    if near:
        print(paint(f"\n{len(near)} sets of near-identical pictures "
                    f"(within {args.near} of 64 bits)", BOLD))
        for paths in near[: args.limit]:
            print(f"  {len(paths)} similar")
            print("\n".join(show_group(paths)))

    if not exact and not near:
        print("no duplicates")
    else:
        print(paint("\nnothing was deleted. these are yours to judge.", DIM))
    return 0


def cmd_secrets(args) -> int:
    index = Index(args.db)
    found = list(scan_secrets(index.texts()))
    if not found:
        print("no credentials found in any indexed screenshot")
        return 0

    print(paint(
        f"{len(found)} screenshot{'s' if len(found) != 1 else ''} "
        f"appear{'' if len(found) != 1 else 's'} to contain credentials", YELLOW))
    for path, hits in found[: args.limit]:
        print(f"\n  {paint(short(path), BOLD)}")
        for label, masked in hits:
            print(f"    {label:<16} {masked}")
    print(paint("\nnothing was changed. delete or crop them yourself.", DIM))
    return 0


def cmd_rename(args) -> int:
    index = Index(args.db)
    rows = [r for r in index.rows(kind=args.kind) if not r["error"]]
    planned: list[tuple[Path, Path]] = []

    for row in rows:
        source = Path(row["path"])
        if not source.exists():
            continue
        name = suggest(source, title=row["title"], kind=row["kind"], when=row["mtime"])
        if name == source.name:
            continue
        planned.append((source, unique(source.parent, name)))
        if len(planned) >= args.limit:
            break

    if not planned:
        print("nothing to rename")
        return 0

    for source, target in planned:
        print(f"  {paint(source.name, DIM)}\n  → {paint(target.name, GREEN)}")

    if not args.apply:
        print(paint(f"\n{len(planned)} files. nothing changed — pass --apply to do it.", DIM))
        return 0

    done = 0
    for source, target in planned:
        try:
            source.rename(target)
        except OSError as error:
            print(paint(f"  ! {source.name}: {error}", RED))
            continue
        index.move(str(source), str(target))
        done += 1
    print(f"\nrenamed {done} files")
    return 0


def cmd_demo(args) -> int:
    """Show what the tool does, against a pretend collection, no pictures needed."""
    import tempfile

    from .demo import build

    # A file, not ":memory:" — every connection to an in-memory database gets
    # its own empty one, so the commands below would each open a fresh void.
    args.demo = True
    holder = tempfile.TemporaryDirectory()
    args.db = str(pathlib.Path(holder.name) / "demo.db")
    index = Index(args.db)
    count = build(index)
    print(paint(f"a pretend collection of {count} screenshots\n", DIM))

    for query in (args.query or "session limit"), "normalisation", "pytest":
        print(paint(f"$ shot find {query}", BOLD))
        args.query, args.kind, args.limit, args.open = query, None, 2, False
        cmd_find(args)
        print()

    print(paint("$ shot stats", BOLD))
    cmd_stats(args)
    print()
    print(paint("$ shot secrets", BOLD))
    cmd_secrets(args)
    return 0


def default_root() -> pathlib.Path:
    return pathlib.Path.home() / "Desktop" / "Screenshots"


def cmd_organise(args) -> int:
    """File screenshots into a folder per period, named after their contents."""
    from .organise import apply as apply_plan
    from .organise import build, summarise, under

    index = Index(args.db)
    root = pathlib.Path(args.root).expanduser() if args.root else default_root()
    rows = index.rows(kind=args.kind)
    if not rows:
        print("nothing indexed — run `shot scan` first")
        return 1

    if args.source:
        folder = pathlib.Path(args.source).expanduser()
        before = len(rows)
        rows = under(rows, folder, recursive=args.recursive)
        scope = "and below" if args.recursive else "only, not subfolders"
        print(paint(f"{len(rows)} of {before} are in {short(str(folder))} {scope}", DIM))
        if not rows:
            print("nothing to file there")
            return 0

    plan = build(rows, root=root, period=args.by, rename=not args.keep_names)
    if not plan.doing:
        print("everything is already filed")
        return 0

    print(f"{len(plan)} screenshots -> {short(str(root))}/")
    print()
    print("\n".join(summarise(plan)))
    print()
    for folder, count in plan.folders.items():
        print(f"  {folder}   {count}")

    if not args.apply:
        print(paint("\nnothing moved — pass --apply to do it.", DIM))
        return 0

    moved, failures = apply_plan(plan)
    for move in plan.moves:
        if move.target != move.source and not move.skip:
            index.move(str(move.source), str(move.target))
    print(f"\nmoved {moved}")
    for path, error in failures[:5]:
        print(paint(f"  ! {short(str(path))}: {error}", RED))
    return 0


def cmd_watch(args) -> int:
    """File every screenshot as it appears."""
    from .ocr import Engine
    from .watch import watch

    index = Index(args.db)
    folder = pathlib.Path(args.folder).expanduser() if args.folder else pathlib.Path.home() / "Desktop"
    root = pathlib.Path(args.root).expanduser() if args.root else default_root()
    try:
        engine = Engine()
    except RuntimeError as error:
        print(error)
        return 1

    mode = "filing" if args.apply else paint("watching only (pass --apply to move files)", DIM)
    print(f"watching {short(str(folder))} → {short(str(root))}/  {mode}")

    def report(source, target):
        when = datetime.now().strftime("%H:%M:%S")
        if target is None:
            print(f"  {when}  {source.name}")
        else:
            print(f"  {when}  {source.name}\n            → {target.parent.name}/{target.name}")

    watch(index, folder, root=root, period=args.by, interval=args.interval,
          apply=args.apply, engine=engine, on_file=report)
    return 0


def cmd_watch_install(args) -> int:
    from .watch import install, is_running

    folder = pathlib.Path(args.folder).expanduser() if args.folder else pathlib.Path.home() / "Desktop"
    root = pathlib.Path(args.root).expanduser() if args.root else default_root()
    try:
        path = install(folder=folder, root=root, period=args.by)
    except RuntimeError as error:
        print(error)
        return 1
    print(f"installed {path}")
    print(f"new screenshots in {short(str(folder))} will be filed into {short(str(root))}/")
    print("running" if is_running() else "installed but not running — see ~/.shot/watcher.log")
    return 0


def cmd_watch_uninstall(args) -> int:
    from .watch import uninstall

    print("removed" if uninstall() else "nothing installed")
    return 0


def cmd_reclassify(args) -> int:
    """Apply improved rules to everything already read, without reading again."""
    from .classify import classify
    from .naming import best_title

    index = Index(args.db)
    changed = index.reclassify(classify, best_title)
    print(f"reclassified {changed:,} of {index.stats()['count']:,} screenshots")
    return 0


def cmd_stats(args) -> int:
    index = Index(args.db)
    facts = index.stats()
    if not getattr(args, "demo", False):
        print(f"index       {index.path}")
    print(f"screenshots {facts['count']:,}  ({human(float(facts['bytes']))} of pictures)")
    print(f"text        {int(facts['chars']):,} characters read out of them")
    if facts["failed"]:
        print(f"failed      {facts['failed']}")
    kinds = facts["kinds"]
    if kinds:
        widest = max(kinds.values()) or 1
        print()
        for kind, count in kinds.items():
            bar = "█" * max(1, round(count / widest * 26))
            print(f"  {kind:<10} {bar} {count}")
    return 0


def cmd_prune(args) -> int:
    index = Index(args.db)
    gone = index.prune_missing()
    print(f"dropped {len(gone)} rows whose file no longer exists")
    return 0


def cmd_doctor(args) -> int:
    try:
        from .ocr import Engine

        engine = Engine()
    except RuntimeError as error:
        print(f"✗ {error}")
        return 1

    print("✓ Vision            available, on-device, no key and no download")
    roots = default_roots()
    print(f"✓ default folders   {', '.join(short(str(r), width=28) for r in roots) or 'none'}")
    all_images = list(images(roots))
    shots = list(images(roots, screenshots_only=True))
    print(f"✓ found             {len(all_images)} images, {len(shots)} of them screenshots")
    if shots:
        _, _, lines = engine.read(shots[0])
        print(f"✓ read a sample     {len(lines)} lines from {short(shots[0].name, width=40)}")
    return 0


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shot", description="find a screenshot by what is written in it"
    )
    parser.add_argument("--version", action="version", version=f"shot {__version__}")
    parser.add_argument("--db", default=str(default_path()), help="index path")
    sub = parser.add_subparsers(dest="command")

    demo = sub.add_parser("demo", help="see what it does, with no pictures of your own")
    demo.add_argument("query", nargs="?")
    demo.set_defaults(func=cmd_demo, limit=3, kind=None, open=False)

    scan = sub.add_parser("scan", help="read images and index what they say")
    scan.add_argument("paths", nargs="*", help="folders (default: Desktop, Downloads)")
    scan.add_argument("--screenshots", action="store_true", help="only files named like one")
    scan.add_argument("--jobs", type=int, default=4)
    scan.add_argument("--fast", action="store_true", help="quicker, worse with small text")
    scan.add_argument("--force", action="store_true", help="re-read even if unchanged")
    scan.set_defaults(func=cmd_scan)

    find = sub.add_parser("find", help="search by what is written in the picture")
    find.add_argument("query", nargs="+")
    find.add_argument("--kind", help="chat, terminal, error, web, settings, document, receipt")
    find.add_argument("--limit", type=int, default=10)
    find.add_argument("-o", "--open", action="store_true", help="open the top hit")
    find.set_defaults(func=cmd_find)

    show = sub.add_parser("show", help="print all the text found in one image")
    show.add_argument("path")
    show.set_defaults(func=cmd_show)

    dupes = sub.add_parser("dupes", help="identical and near-identical pictures")
    dupes.add_argument("--near", type=int, default=NEAR, help="bits of difference allowed")
    dupes.add_argument("--limit", type=int, default=20)
    dupes.set_defaults(func=cmd_dupes)

    secrets = sub.add_parser("secrets", help="screenshots that appear to contain credentials")
    secrets.add_argument("--limit", type=int, default=20)
    secrets.set_defaults(func=cmd_secrets)

    rename = sub.add_parser("rename", help="name files after what is in them")
    rename.add_argument("--apply", action="store_true", help="actually do it")
    rename.add_argument("--kind")
    rename.add_argument("--limit", type=int, default=25)
    rename.set_defaults(func=cmd_rename)

    def filing_args(p):
        p.add_argument("--root", help="where to file them (default ~/Desktop/Screenshots)")
        p.add_argument("--by", choices=["day", "month", "year", "flat"], default="month")

    organise = sub.add_parser("organise", aliases=["organize"],
                              help="file screenshots into dated folders, named by content")
    filing_args(organise)
    organise.add_argument("--apply", action="store_true", help="actually move them")
    organise.add_argument("--from", dest="source",
                          help="only screenshots loose in this folder")
    organise.add_argument("--recursive", action="store_true",
                          help="include subfolders too (they may already be organised)")
    organise.add_argument("--keep-names", action="store_true", help="file them, do not rename")
    organise.add_argument("--kind")
    organise.set_defaults(func=cmd_organise)

    watch = sub.add_parser("watch", help="file every new screenshot as you take it")
    filing_args(watch)
    watch.add_argument("--folder", help="where screenshots land (default ~/Desktop)")
    watch.add_argument("--interval", type=float, default=3.0)
    watch.add_argument("--apply", action="store_true", help="actually move them")
    watch.set_defaults(func=cmd_watch)

    wi = sub.add_parser("watch-install", help="run the watcher at login")
    filing_args(wi)
    wi.add_argument("--folder")
    wi.set_defaults(func=cmd_watch_install)

    sub.add_parser("watch-uninstall", help="stop and remove the watcher").set_defaults(
        func=cmd_watch_uninstall)

    sub.add_parser(
        "reclassify", help="re-apply the rules to everything, without re-reading"
    ).set_defaults(func=cmd_reclassify)
    sub.add_parser("stats", help="what is indexed").set_defaults(func=cmd_stats)
    sub.add_parser("prune", help="drop rows whose file is gone").set_defaults(func=cmd_prune)
    sub.add_parser("doctor", help="check this Mac can do it").set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    if getattr(args, "query", None) and isinstance(args.query, list):
        args.query = " ".join(args.query)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
