"""The index: storing, searching, and turning typed words into a query."""


from shot.hashing import MASK
from shot.index import fts_query
from shot.model import Shot


def make(path="/a.png", *, text="", title="", kind="unknown", digest="d", phash=1, mtime=1.0):
    return Shot(path=path, size=100, mtime=mtime, digest=digest, phash=phash,
                kind=kind, title=title, text=text)


# ------------------------------------------------------------ query making


def test_words_become_required_terms():
    assert fts_query("session limit", prefix=False) == '"session" AND "limit"'


def test_the_last_word_is_a_prefix_so_search_narrows_as_you_type():
    assert fts_query("turnit").endswith('"turnit"*')


def test_punctuation_cannot_become_an_operator():
    """`error: can't` must search, not raise a syntax error."""
    query = fts_query("error: can't connect")
    assert '"error"' in query and '"' in query
    assert ":" not in query.replace('"', "")


def test_a_stray_letter_is_dropped_rather_than_required():
    """The `t` from `can't` would match nothing and empty the results."""
    assert '"t"' not in fts_query("can't")


def test_a_quoted_phrase_stays_a_phrase():
    assert '"session limit"' in fts_query('"session limit" reached')


def test_an_empty_query_produces_nothing_rather_than_matching_everything():
    assert fts_query("   ") == ""


def test_digits_survive():
    assert '"2026"' in fts_query("2026 report")


# ------------------------------------------------------------- store/read


def test_a_shot_can_be_found_by_its_words(index):
    index.upsert(make(text="gentle reminder for the Turnitin check"))
    assert [m.path for m in index.search("turnitin")] == ["/a.png"]


def test_search_stems_so_running_finds_ran(index):
    index.upsert(make(text="the server was running out of memory"))
    assert index.search("run")


def test_the_snippet_marks_what_matched(index):
    index.upsert(make(text="Session limit reached, auto-resuming"))
    assert "\x02" in index.search("limit")[0].snippet


def test_the_title_outranks_the_body(index):
    index.upsert(make("/title.png", title="Turnitin report", text="unrelated words here"))
    index.upsert(make("/body.png", digest="e", text="a passing mention of turnitin midway"))
    assert index.search("turnitin")[0].path == "/title.png"


def test_results_can_be_narrowed_to_one_kind(index):
    index.upsert(make("/a.png", text="limit reached", kind="error"))
    index.upsert(make("/b.png", digest="e", text="limit reached", kind="chat"))
    assert [m.path for m in index.search("limit", kind="chat")] == ["/b.png"]


def test_nothing_matching_is_an_empty_list_not_an_error(index):
    index.upsert(make(text="hello"))
    assert index.search("kangaroo") == []


def test_re_indexing_a_path_does_not_duplicate_it(index):
    """FTS5 has no upsert; the old row has to go first."""
    index.upsert(make(text="first version"))
    index.upsert(make(text="second version"))
    assert len(index.search("version")) == 1


# ------------------------------------------------------------ incremental


def test_an_unchanged_file_does_not_need_reading_again(index):
    index.upsert(make(mtime=99.0))
    assert index.is_current("/a.png", 100, 99.0)


def test_a_changed_file_does(index):
    index.upsert(make(mtime=99.0))
    assert not index.is_current("/a.png", 101, 99.0)
    assert not index.is_current("/a.png", 100, 100.0)


def test_a_file_that_failed_last_time_is_retried(index):
    shot = make(mtime=99.0)
    shot.error = "could not decode"
    index.upsert(shot)
    assert not index.is_current("/a.png", 100, 99.0)


def test_an_unknown_file_needs_reading(index):
    assert not index.is_current("/never-seen.png", 1, 1.0)


def test_a_renamed_file_is_recognised_by_its_bytes(index):
    index.upsert(make("/old.png", digest="abc", text="hello"))
    assert index.by_digest("abc")["path"] == "/old.png"


def test_an_empty_digest_never_matches(index):
    """Or every file that failed to hash would look like every other one."""
    index.upsert(make(digest=""))
    assert index.by_digest("") is None


def test_moving_a_file_keeps_it_searchable(index):
    index.upsert(make("/old.png", text="findable words"))
    index.move("/old.png", "/new.png")
    assert [m.path for m in index.search("findable")] == ["/new.png"]


# ------------------------------------------------------------ maintenance


def test_a_full_range_hash_survives_storage(index):
    """SQLite integers are signed; dHashes are not."""
    index.upsert(make(phash=MASK))
    assert index.phashes() == [("/a.png", MASK)]


def test_duplicate_digests_are_grouped(index):
    index.upsert(make("/a.png", digest="same"))
    index.upsert(make("/b.png", digest="same"))
    index.upsert(make("/c.png", digest="other"))
    assert index.digests() == {"same": ["/a.png", "/b.png"]}


def test_forgetting_removes_it_from_search_too(index):
    index.upsert(make(text="hello"))
    index.forget("/a.png")
    assert index.search("hello") == []


def test_pruning_drops_rows_whose_picture_is_gone(index, tmp_path):
    real = tmp_path / "real.png"
    real.write_bytes(b"x")
    index.upsert(make(str(real), text="here"))
    index.upsert(make("/gone.png", digest="e", text="here"))
    assert index.prune_missing() == ["/gone.png"]
    assert len(index.search("here")) == 1


def test_stats_counts_what_is_there(index):
    index.upsert(make("/a.png", text="one", kind="chat"))
    index.upsert(make("/b.png", digest="e", text="two", kind="chat"))
    facts = index.stats()
    assert facts["count"] == 2 and facts["kinds"] == {"chat": 2}
