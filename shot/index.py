"""The index: one SQLite file, full-text search over what the pictures say.

SQLite's FTS5 does the ranking, which means BM25 and a highlighted snippet for
free and no second process to run. The Porter stemmer is turned on so that
searching *running* finds *ran* — on OCR text, where you are recalling the
gist of something you saw once, that matters more than exactness.

User queries are rewritten before they reach FTS5. Typing `error: can't`
should search for those words, not raise a syntax error about an unterminated
string, and someone hunting a screenshot should never have to learn a query
language to do it.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from .hashing import to_signed, to_unsigned
from .model import Line, Match, Shot

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS shots (
    path    TEXT PRIMARY KEY,
    size    INTEGER NOT NULL,
    mtime   REAL NOT NULL,
    digest  TEXT NOT NULL DEFAULT '',
    phash   INTEGER NOT NULL DEFAULT 0,
    width   INTEGER NOT NULL DEFAULT 0,
    height  INTEGER NOT NULL DEFAULT 0,
    kind    TEXT NOT NULL DEFAULT 'unknown',
    title   TEXT NOT NULL DEFAULT '',
    text    TEXT NOT NULL DEFAULT '',
    -- Where each run of text sat on the picture. Reading a picture costs most
    -- of a second; deciding what it is costs nothing. Keeping the geometry
    -- means every rule in this tool can be improved and applied to everything
    -- already indexed, without reading a single image again.
    lines   TEXT NOT NULL DEFAULT '',
    scanned REAL NOT NULL DEFAULT 0,
    error   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS shots_digest ON shots(digest);

CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
    path UNINDEXED,
    title,
    body,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def default_path() -> Path:
    return Path.home() / ".shot" / "index.db"


def fts_query(text: str, *, prefix: bool = True) -> str:
    """Turn what a person typed into something FTS5 will accept.

    A quoted phrase survives as a phrase. Everything else becomes words, each
    quoted so that punctuation cannot be read as an operator, and ANDed. The
    last word gets a ``*`` so that search narrows as you type rather than
    finding nothing until you finish the word.
    """
    phrases = re.findall(r'"([^"]+)"', text)
    rest = re.sub(r'"[^"]*"', " ", text)
    # An apostrophe splits "can't" into "can" and "t", and a required "t"
    # matches nothing, so a stray letter would empty the whole result set.
    words = [w for w in _WORD.findall(rest) if len(w) > 1 or w.isdigit()]

    terms = [f'"{phrase}"' for phrase in phrases if phrase.strip()]
    for index, word in enumerate(words):
        last = index == len(words) - 1
        terms.append(f'"{word}"*' if prefix and last and len(word) > 2 else f'"{word}"')
    return " AND ".join(terms)


class Index:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10.0)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self._migrate()
        self.db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    def _migrate(self) -> None:
        """Add columns a newer version wants, without discarding an old index.

        Throwing the index away is a five-minute rescan; there is no excuse
        for making the user pay it because a column was added.
        """
        have = {row["name"] for row in self.db.execute("PRAGMA table_info(shots)")}
        if "lines" not in have:
            self.db.execute("ALTER TABLE shots ADD COLUMN lines TEXT NOT NULL DEFAULT ''")
        self.db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.db.commit()

    # ------------------------------------------------------------- writing

    def upsert(self, shot: Shot) -> None:
        text = shot.text or "\n".join(line.text for line in shot.lines)
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO shots "
                "(path,size,mtime,digest,phash,width,height,kind,title,text,lines,"
                "scanned,error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    shot.path, shot.size, shot.mtime, shot.digest, to_signed(shot.phash),
                    shot.width, shot.height, shot.kind, shot.title, text,
                    dump_lines(shot.lines), shot.scanned, shot.error,
                ),
            )
            # FTS5 has no upsert, so the old row goes first or the same picture
            # is found twice under one path.
            self.db.execute("DELETE FROM search WHERE path = ?", (shot.path,))
            self.db.execute(
                "INSERT INTO search (path, title, body) VALUES (?,?,?)",
                (shot.path, shot.title, text),
            )

    def move(self, old: str, new: str) -> None:
        """Follow a rename without reading the picture again."""
        with self.db:
            self.db.execute("UPDATE shots SET path = ? WHERE path = ?", (new, old))
            self.db.execute("UPDATE search SET path = ? WHERE path = ?", (new, old))

    def forget(self, path: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM shots WHERE path = ?", (path,))
            self.db.execute("DELETE FROM search WHERE path = ?", (path,))

    def prune_missing(self) -> list[str]:
        """Drop rows whose picture is gone. Returns what was dropped."""
        gone = [row["path"] for row in self.db.execute("SELECT path FROM shots")
                if not Path(row["path"]).exists()]
        for path in gone:
            self.forget(path)
        return gone

    # ------------------------------------------------------------- reading

    def is_current(self, path: str, size: int, mtime: float) -> bool:
        """Has this exact file already been read?"""
        row = self.db.execute(
            "SELECT size, mtime, error FROM shots WHERE path = ?", (path,)
        ).fetchone()
        if row is None or row["error"]:
            return False
        return row["size"] == size and abs(row["mtime"] - mtime) < 1e-6

    def by_digest(self, digest: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM shots WHERE digest = ? AND digest != '' LIMIT 1", (digest,)
        ).fetchone()

    def search(self, query: str, *, limit: int = 20, kind: str | None = None) -> list[Match]:
        prepared = fts_query(query)
        if not prepared:
            return []
        sql = (
            "SELECT s.path, s.kind, s.mtime, s.title, bm25(search, 3.0, 1.0) AS rank, "
            "snippet(search, 2, '\x02', '\x03', '…', 14) AS snip "
            "FROM search JOIN shots s ON s.path = search.path "
            "WHERE search MATCH ?"
        )
        params: list[object] = [prepared]
        if kind:
            sql += " AND s.kind = ?"
            params.append(kind)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        try:
            rows = self.db.execute(sql, params).fetchall()
        except sqlite3.OperationalError as error:
            raise ValueError(f"could not search for {query!r}: {error}") from error

        return [
            Match(
                path=row["path"],
                score=-float(row["rank"]),  # bm25 is negative; smaller is better
                snippet=row["snip"] or "",
                kind=row["kind"],
                mtime=row["mtime"],
                title=row["title"],
            )
            for row in rows
        ]

    def text_of(self, path: str) -> str | None:
        row = self.db.execute("SELECT text FROM shots WHERE path = ?", (path,)).fetchone()
        return row["text"] if row else None

    def phashes(self) -> list[tuple[str, int]]:
        return [
            (row["path"], to_unsigned(row["phash"]))
            for row in self.db.execute(
                "SELECT path, phash FROM shots WHERE phash != 0 AND error = ''"
            )
        ]

    def digests(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for row in self.db.execute(
            "SELECT path, digest FROM shots WHERE digest != '' ORDER BY path"
        ):
            groups.setdefault(row["digest"], []).append(row["path"])
        return {d: paths for d, paths in groups.items() if len(paths) > 1}

    def texts(self) -> Iterator[tuple[str, str]]:
        for row in self.db.execute("SELECT path, text FROM shots WHERE text != ''"):
            yield row["path"], row["text"]

    def rows(self, *, kind: str | None = None) -> list[sqlite3.Row]:
        if kind:
            return self.db.execute(
                "SELECT * FROM shots WHERE kind = ? ORDER BY mtime DESC", (kind,)
            ).fetchall()
        return self.db.execute("SELECT * FROM shots ORDER BY mtime DESC").fetchall()

    def stats(self) -> dict[str, object]:
        row = self.db.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(size),0) bytes, "
            "COALESCE(SUM(LENGTH(text)),0) chars, "
            "SUM(CASE WHEN error != '' THEN 1 ELSE 0 END) failed FROM shots"
        ).fetchone()
        kinds = {
            r["kind"]: r["n"]
            for r in self.db.execute(
                "SELECT kind, COUNT(*) n FROM shots GROUP BY kind ORDER BY n DESC"
            )
        }
        return {
            "count": row["n"], "bytes": row["bytes"], "chars": row["chars"],
            "failed": row["failed"] or 0, "kinds": kinds,
        }

    def reclassify(self, classify, title_of) -> int:
        """Re-run the rules over every picture already read.

        Editing a rule should fix last month's screenshots too, and it can,
        because the only irreversible part — looking at the picture — was
        saved. Rows indexed before the geometry was kept fall back to the flat
        text, which is enough to reclassify but not to re-title.
        """
        changed = 0
        updates: list[tuple[str, str, str]] = []
        for row in self.db.execute("SELECT path, kind, title, lines, text FROM shots"):
            lines = load_lines(row["lines"], row["text"])
            if not lines:
                continue
            kind = classify(lines)
            title = title_of(lines, kind) if row["lines"] else row["title"]
            if (kind, title) != (row["kind"], row["title"]):
                updates.append((kind, title, row["path"]))
        if updates:
            with self.db:
                self.db.executemany(
                    "UPDATE shots SET kind = ?, title = ? WHERE path = ?", updates
                )
                self.db.executemany(
                    "UPDATE search SET title = ? WHERE path = ?",
                    [(title, path) for _, title, path in updates],
                )
            changed = len(updates)
        return changed

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *_) -> None:
        self.close()


def dump_lines(lines: list[Line]) -> str:
    """Compact JSON: coordinates rounded, because four decimals is a pixel."""
    if not lines:
        return ""
    return json.dumps(
        [
            [ln.text, round(ln.confidence, 3), round(ln.x, 4), round(ln.y, 4),
             round(ln.width, 4), round(ln.height, 4)]
            for ln in lines
        ],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def load_lines(packed: str, fallback_text: str = "") -> list[Line]:
    """Geometry when it was kept, otherwise the flat text, otherwise nothing."""
    if packed:
        try:
            return [
                Line(text=t, confidence=c, x=x, y=y, width=w, height=h)
                for t, c, x, y, w, h in json.loads(packed)
            ]
        except (ValueError, TypeError):
            pass
    return [Line(text=t, confidence=1.0) for t in fallback_text.split("\n") if t]


def shot_from(row: sqlite3.Row) -> Shot:
    return Shot(
        path=row["path"], size=row["size"], mtime=row["mtime"], digest=row["digest"],
        phash=to_unsigned(row["phash"]), width=row["width"], height=row["height"],
        kind=row["kind"], title=row["title"], text=row["text"],
        # sqlite3.Row's `in` tests values, not column names, so .keys() is
        # required here and the obvious simplification would be a silent bug.
        lines=load_lines(
            row["lines"] if "lines" in row.keys() else "",  # noqa: SIM118
            row["text"],
        ),
        scanned=row["scanned"], error=row["error"],
    )
