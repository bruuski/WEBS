# Discogs-First Data Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Spotify as Pacer's primary data source for artist, album, and track metadata with Discogs, while keeping Spotify only for audio preview URLs and the trending playlist. Backward-compatible schema migrations, graceful degradation, zero regression in existing features.

**Architecture:** New `pacer/services/discogs.py` (OAuth 1.0a client with in-memory TTL caches) becomes the primary metadata source. Existing `pacer/services/spotify.py` is slimmed down to four responsibilities: app-token, trending fetch, Spotify playlist import, and a new `lookup_spotify_preview(artist, title)` function that calls Spotify's search API as a fallback and caches results in a new `spotify_preview_cache` table. The DB gains three new tables (`song_styles`, `album_styles`, `spotify_preview_cache`) and 14 new columns distributed across `artists`, `songs`, and `albums`. Music routes (`pacer/routes/music.py`) and the search route (`pacer/routes/spotify.py`) are updated to render the new fields; trending and player logic is unchanged.

**Tech Stack:** Python 3.13, Flask 3.0.3, SQLite, requests>=2.31, **requests-oauthlib>=1.3.1 (NEW)**, python-dotenv, gunicorn, HTMX, Jinja2

**Reference Spec:** `docs/superpowers/specs/2026-06-10-discogs-first-data-layer-design.md`

---

## File Structure

### Files Created
| Path | Responsibility |
|---|---|
| `pacer/services/discogs.py` | OAuth 1.0a client + in-memory TTL caches for artist/release/master |
| `tests/conftest.py` | Pytest fixtures: temp DB, app context, mock OAuth session |
| `tests/test_discogs_service.py` | Unit tests for Discogs service |
| `tests/test_spotify_service_slim.py` | Unit tests for slim Spotify service (lookup_spotify_preview) |
| `tests/test_routes_music.py` | Integration tests for music routes with Discogs enrichment |
| `docs/discogs-setup.md` | Discogs developer setup guide |

### Files Modified
| Path | Change |
|---|---|
| `pacer/db.py` | Add 3 new tables + 14 ALTER TABLE in `init_db()` |
| `pacer/config.py` | Add `DISCOGS_*` env vars (no behavior change, just load) |
| `pacer/services/spotify.py` | Slim: remove 8 functions, add `lookup_spotify_preview` |
| `pacer/routes/music.py` | Use Discogs enrichment in song/album/artist detail |
| `pacer/routes/spotify.py` | Search route proxies to Discogs, attaches preview badges |
| `templates/song.html` | Add "Catalog" panel + style chips |
| `templates/album.html` | Add tracklist + label/format/country from Discogs |
| `templates/artist.html` | Add bio, real_name, members, aliases |
| `templates/browse.html` | Add style filter dropdown |
| `templates/search.html` | Render Discogs results with preview badge |
| `static/style.css` | Add `.catalog-panel`, `.style-chips`, `.chip`, `.filter-bar` for all 3 themes |
| `requirements.txt` | Add `requests-oauthlib>=1.3.1` |
| `README.md` | Document new env vars + features |

### Files NOT Modified
- `pacer/routes/auth.py`, `feed.py`, `blog.py`, `admin.py` (stable)
- `pacer/routes/profile.py` (stable; Spotify 2-step import kept)
- `pacer/helpers.py` (stable)
- `pacer/seed.py` (no change; lazy backfill handles demo songs)
- `pacer/__init__.py` (stable)
- `run.py` (stable)
- `templates/base.html`, `home.html` (stable)
- `static/htmx.min.js`, `static/player.js`, `static/spotify.js` (stable)

---

## Phase 1: Foundation

### Task 1.1: Add requests-oauthlib dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependency**

Append to `requirements.txt` (after the existing `gunicorn>=22.0.0` line):

```
requests-oauthlib>=1.3.1
```

Final file should read:
```
Flask==3.0.3
requests>=2.31
python-dotenv>=1.0.0
gunicorn>=22.0.0
requests-oauthlib>=1.3.1
```

- [ ] **Step 2: Install**

Run from project root: `pip install -r requirements.txt`
Expected: `Successfully installed requests-oauthlib-1.3.1` (or newer)

- [ ] **Step 3: Verify import**

Run: `python -c "from requests_oauthlib import OAuth1Session; print('ok')"`
Expected output: `ok`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "chore: add requests-oauthlib for Discogs OAuth 1.0a"
```

---

### Task 1.2: Set up pytest scaffolding

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pytest.ini` (or `pyproject.toml` [tool.pytest.ini_options] section)

- [ ] **Step 1: Create `tests/__init__.py`**

Write empty file `tests/__init__.py` (no contents — just existence so pytest treats it as a package).

- [ ] **Step 2: Create `pytest.ini`**

Write `pytest.ini` at project root:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 3: Write the failing conftest test**

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures for Pacer tests."""
import os
import pytest
import tempfile

# Set test env BEFORE importing app
os.environ.setdefault("PACER_SECRET", "test-secret")
os.environ.setdefault("SPOTIFY_CLIENT_ID", "")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "")
os.environ.setdefault("DISCOGS_CONSUMER_KEY", "")
os.environ.setdefault("DISCOGS_CONSUMER_SECRET", "")


@pytest.fixture
def temp_db(monkeypatch):
    """Create a temp DB path; init_db writes to it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from pacer import config
    monkeypatch.setattr(config, "DB_PATH", path)
    from pacer import db
    db.init_db()
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def app(temp_db):
    """Flask app with isolated DB."""
    from pacer import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
```

- [ ] **Step 4: Write smoke test**

Create `tests/test_smoke.py`:

```python
"""Smoke test: app boots and root route returns 200."""


def test_app_boots(app):
    assert app is not None


def test_root_route_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_smoke.py -v`
Expected: 2 tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/ pytest.ini
git commit -m "test: scaffold pytest with isolated temp DB fixtures"
```

---

### Task 1.3: Add Discogs env vars to config

**Files:**
- Modify: `pacer/config.py:1-20`

- [ ] **Step 1: Read current config**

Read `pacer/config.py` to confirm current shape.

Current file:
```python
import os

from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Railway persistent volume mount point, fallback to local
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(APP_ROOT, ".."))
DB_PATH = os.path.join(DATA_DIR, "pacer.db")

SECRET_KEY = os.environ.get("PACER_SECRET", "dev-secret-change-me")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/spotify/callback")
SPOTIFY_TRENDING_PLAYLIST = os.environ.get("SPOTIFY_TRENDING_PLAYLIST", "37i9dQZF1DXcBWIGoYBM5M")
```

- [ ] **Step 2: Append Discogs env vars**

Append to `pacer/config.py`:

```python
# Discogs (OAuth 1.0a server-to-server)
DISCOGS_CONSUMER_KEY    = os.environ.get("DISCOGS_CONSUMER_KEY", "")
DISCOGS_CONSUMER_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")
DISCOGS_USER_AGENT      = os.environ.get(
    "DISCOGS_USER_AGENT",
    "Pacer/1.0 +https://github.com/0xzhepyr/Pacer",
)
```

- [ ] **Step 3: Verify import works**

Run: `python -c "from pacer.config import DISCOGS_CONSUMER_KEY, DISCOGS_USER_AGENT; print(DISCOGS_USER_AGENT)"`
Expected output: `Pacer/1.0 +https://github.com/0xzhepyr/Pacer`

- [ ] **Step 4: Verify existing tests still pass**

Run: `pytest -v`
Expected: all existing tests still pass (smoke test passes, no new tests)

- [ ] **Step 5: Commit**

```bash
git add pacer/config.py
git commit -m "feat(config): add Discogs env vars (DISCOGS_CONSUMER_KEY, DISCOGS_CONSUMER_SECRET, DISCOGS_USER_AGENT)"
```

---

### Task 1.4: Schema migration — new tables

**Files:**
- Modify: `pacer/db.py` (the `SCHEMA` string and the `init_db()` function)

- [ ] **Step 1: Read current `pacer/db.py`**

Confirm current schema. Key landmarks:
- `SCHEMA = """..."""` (the multiline string with all CREATE TABLE statements)
- `def init_db()` (function that runs SCHEMA + ALTER TABLE)

- [ ] **Step 2: Add 3 new tables to SCHEMA**

In `pacer/db.py`, append these three table definitions inside the `SCHEMA` string, after the existing `reposts` table definition (the last `CREATE TABLE` block):

```sql
CREATE TABLE IF NOT EXISTS song_styles (
    song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
    style   TEXT NOT NULL,
    PRIMARY KEY (song_id, style)
);
CREATE INDEX IF NOT EXISTS idx_song_styles_style ON song_styles(style);

CREATE TABLE IF NOT EXISTS album_styles (
    album_id INTEGER NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
    style    TEXT NOT NULL,
    PRIMARY KEY (album_id, style)
);
CREATE INDEX IF NOT EXISTS idx_album_styles_style ON album_styles(style);

CREATE TABLE IF NOT EXISTS spotify_preview_cache (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    artist        TEXT NOT NULL,
    title         TEXT NOT NULL,
    spotify_id    TEXT,
    preview_url   TEXT,
    fetched_at    TEXT NOT NULL,
    UNIQUE(artist, title)
);
CREATE INDEX IF NOT EXISTS idx_preview_cache_lookup
    ON spotify_preview_cache(artist, title);
```

- [ ] **Step 3: Add 14 ALTER TABLE statements in init_db()**

In `pacer/db.py`, locate the `init_db()` function. After the existing `for col, ddl in [...]` loops and before `con.commit()`, add the following new migrations:

```python
    # Discogs-first layer migrations (2026-06-10)
    artist_cols = existing("artists")
    for col, ddl in [
        ("discogs_id",        "INTEGER UNIQUE"),
        ("real_name",         "TEXT"),
        ("profile_text",      "TEXT"),
        ("aliases",           "TEXT"),
        ("members",           "TEXT"),
        ("urls",              "TEXT"),
        ("namevariations",    "TEXT"),
    ]:
        if col not in artist_cols:
            con.execute(f"ALTER TABLE artists ADD COLUMN {col} {ddl}")

    song_cols = existing("songs")
    for col, ddl in [
        ("discogs_release_id",   "INTEGER"),
        ("discogs_master_id",    "INTEGER"),
        ("position_in_release",  "INTEGER"),
        ("duration_ms",          "INTEGER"),
        ("discogs_artists",      "TEXT"),
    ]:
        if col not in song_cols:
            con.execute(f"ALTER TABLE songs ADD COLUMN {col} {ddl}")

    album_cols = existing("albums")
    for col, ddl in [
        ("discogs_release_id",   "INTEGER UNIQUE"),
        ("discogs_master_id",    "INTEGER"),
        ("label",                "TEXT"),
        ("format",               "TEXT"),
        ("country",              "TEXT"),
        ("catalog_no",           "TEXT"),
        ("release_url",          "TEXT"),
        ("master_url",           "TEXT"),
    ]:
        if col not in album_cols:
            con.execute(f"ALTER TABLE albums ADD COLUMN {col} {ddl}")
```

- [ ] **Step 4: Write a failing test for new tables**

Create `tests/test_schema_migration.py`:

```python
"""Verify the 2026-06-10 schema migration creates the new tables and columns."""


def test_song_styles_table_exists(temp_db):
    from pacer import db
    con = db.sqlite3.connect(temp_db)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='song_styles'"
    )
    assert cur.fetchone() is not None
    con.close()


def test_album_styles_table_exists(temp_db):
    from pacer import db
    con = db.sqlite3.connect(temp_db)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='album_styles'"
    )
    assert cur.fetchone() is not None
    con.close()


def test_spotify_preview_cache_table_exists(temp_db):
    from pacer import db
    con = db.sqlite3.connect(temp_db)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='spotify_preview_cache'"
    )
    assert cur.fetchone() is not None
    con.close()


def test_artists_has_discogs_columns(temp_db):
    from pacer import db
    con = db.sqlite3.connect(temp_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(artists)").fetchall()]
    assert "discogs_id" in cols
    assert "real_name" in cols
    assert "profile_text" in cols
    assert "aliases" in cols
    assert "members" in cols
    assert "urls" in cols
    assert "namevariations" in cols
    con.close()


def test_songs_has_discogs_columns(temp_db):
    from pacer import db
    con = db.sqlite3.connect(temp_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(songs)").fetchall()]
    assert "discogs_release_id" in cols
    assert "discogs_master_id" in cols
    assert "position_in_release" in cols
    assert "duration_ms" in cols
    assert "discogs_artists" in cols
    con.close()


def test_albums_has_discogs_columns(temp_db):
    from pacer import db
    con = db.sqlite3.connect(temp_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(albums)").fetchall()]
    assert "discogs_release_id" in cols
    assert "discogs_master_id" in cols
    assert "label" in cols
    assert "format" in cols
    assert "country" in cols
    assert "catalog_no" in cols
    assert "release_url" in cols
    assert "master_url" in cols
    con.close()
```

- [ ] **Step 5: Run new tests, verify they pass**

Run: `pytest tests/test_schema_migration.py -v`
Expected: 6 tests pass

- [ ] **Step 6: Verify migration is idempotent (re-running init_db works)**

Run twice in a row:
```python
python -c "from pacer.db import init_db; init_db(); init_db(); print('ok')"
```
Expected: `ok` (no errors on second run)

- [ ] **Step 7: Verify all tests still pass**

Run: `pytest -v`
Expected: all tests pass (smoke + schema migration)

- [ ] **Step 8: Commit**

```bash
git add pacer/db.py tests/test_schema_migration.py
git commit -m "feat(db): add Discogs columns + song_styles/album_styles/spotify_preview_cache tables"
```

---

### Task 1.5: Create `pacer/services/discogs.py` (skeleton with config check)

**Files:**
- Create: `pacer/services/discogs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_discogs_service.py`:

```python
"""Unit tests for the Discogs API service."""


def test_discogs_configured_returns_false_when_empty(monkeypatch):
    """When DISCOGS_CONSUMER_KEY and SECRET are empty, returns False."""
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "")
    from pacer.services import discogs
    # Force re-evaluation
    assert discogs.discogs_configured() is False


def test_discogs_configured_returns_true_when_set(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "test-key")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "test-secret")
    from pacer.services import discogs
    assert discogs.discogs_configured() is True
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_discogs_service.py -v`
Expected: ImportError or AttributeError (module not yet created)

- [ ] **Step 3: Create skeleton `pacer/services/discogs.py`**

```python
"""Discogs API client for Pacer.

Uses OAuth 1.0a server-to-server auth (no user redirect).
In-memory TTL caches for artist (7d), release (30d), master (30d).
All network failures return None — never raise to the caller.
"""
import os
import time
import logging

import requests
from requests_oauthlib import OAuth1Session

from pacer.config import (
    DISCOGS_CONSUMER_KEY,
    DISCOGS_CONSUMER_SECRET,
    DISCOGS_USER_AGENT,
)

BASE_URL = "https://api.discogs.com"
REQUEST_TIMEOUT = 8

# Cache TTLs (seconds)
ARTIST_TTL  = 7 * 24 * 3600
RELEASE_TTL = 30 * 24 * 3600

# Module-level cache: discogs_id -> (normalized_data, expires_at_epoch)
_artist_cache: dict[int, tuple[dict, float]] = {}
_release_cache: dict[int, tuple[dict, float]] = {}
_master_cache: dict[int, tuple[dict, float]] = {}

log = logging.getLogger("pacer.discogs")


def discogs_configured() -> bool:
    return bool(DISCOGS_CONSUMER_KEY and DISCOGS_CONSUMER_SECRET)


def _oauth() -> OAuth1Session:
    return OAuth1Session(
        DISCOGS_CONSUMER_KEY,
        client_secret=DISCOGS_CONSUMER_SECRET,
        resource_owner_key=None,
        resource_owner_secret=None,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_discogs_service.py -v`
Expected: 2 tests pass

- [ ] **Step 5: Commit**

```bash
git add pacer/services/discogs.py tests/test_discogs_service.py
git commit -m "feat(services): add Discogs client skeleton with OAuth 1.0a + config check"
```

---

### Task 1.6: Implement Discogs `_request` with error handling

**Files:**
- Modify: `pacer/services/discogs.py`

- [ ] **Step 1: Write the failing test for `_request`**

Append to `tests/test_discogs_service.py`:

```python
def test_request_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "")
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result is None


def test_request_handles_network_exception(monkeypatch):
    """If requests.get raises, _request returns None (no exception)."""
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "fake")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "fake")

    def boom(*a, **kw):
        raise requests.RequestException("boom")

    monkeypatch.setattr("pacer.services.discogs._oauth", lambda: type("S", (), {"get": boom})())
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result is None


def test_request_returns_none_on_429(monkeypatch):
    """Rate limit → return None, caller falls back to cache."""
    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "60"}
        text = "Too Many Requests"
        def ok(self): return False
        def json(self): return {}

    class FakeSession:
        def get(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "fake")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "fake")
    monkeypatch.setattr("pacer.services.discogs._oauth", lambda: FakeSession())
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result is None


def test_request_returns_parsed_json_on_200(monkeypatch):
    class FakeResp:
        status_code = 200
        headers = {}
        text = ""
        def ok(self): return True
        def json(self): return {"results": [{"id": 1}]}

    class FakeSession:
        def get(self, *a, **kw): return FakeResp()

    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "fake")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "fake")
    monkeypatch.setattr("pacer.services.discogs._oauth", lambda: FakeSession())
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result == {"results": [{"id": 1}]}
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_discogs_service.py -v -k "test_request"`
Expected: AttributeError (`_request` not defined)

- [ ] **Step 3: Implement `_request` in `pacer/services/discogs.py`**

Append to the file:

```python
def _request(path: str, params: dict | None = None) -> dict | None:
    """Signed GET with timeout, User-Agent, and graceful error handling.

    Returns parsed JSON dict on success, or None on any failure.
    Never raises — callers can always safely use the return value.
    """
    if not discogs_configured():
        return None
    try:
        session = _oauth()
        resp = session.get(
            BASE_URL + path,
            params=params or {},
            headers={"User-Agent": DISCOGS_USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        log.warning("network error on %s: %s", path, e)
        return None

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "60")
        log.warning("rate limited on %s (retry after %ss)", path, retry_after)
        return None
    if not resp.ok:
        log.warning("%s on %s: %s", resp.status_code, path, resp.text[:200])
        return None
    return resp.json()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_discogs_service.py -v`
Expected: 6 tests pass (2 config + 4 _request)

- [ ] **Step 5: Commit**

```bash
git add pacer/services/discogs.py tests/test_discogs_service.py
git commit -m "feat(services/discogs): add _request with graceful error handling"
```

---

### Task 1.7: Implement Discogs search functions

**Files:**
- Modify: `pacer/services/discogs.py`

- [ ] **Step 1: Write the failing test for `search_releases`**

Append to `tests/test_discogs_service.py`:

```python
def test_search_releases_returns_normalized_list(monkeypatch):
    fake_response = {
        "results": [
            {
                "id": 12345,
                "title": "Radiohead - OK Computer",
                "year": 1997,
                "country": "US",
                "label": ["Parlophone"],
                "format": ["CD", "Album"],
                "thumb": "https://example.com/thumb.jpg",
                "cover_image": "https://example.com/cover.jpg",
                "genre": ["Electronic", "Rock"],
                "style": ["Alternative Rock", "Art Rock"],
                "uri": "https://www.discogs.com/release/12345",
                "resource_url": "https://api.discogs.com/releases/12345",
            }
        ]
    }
    monkeypatch.setattr(
        "pacer.services.discogs._request",
        lambda path, params=None: fake_response if "search" in path else None,
    )
    from pacer.services import discogs
    results = discogs.search_releases("radiohead", per_page=5)
    assert len(results) == 1
    r = results[0]
    assert r["discogs_id"] == 12345
    assert r["title"] == "Radiohead - OK Computer"
    assert r["year"] == 1997
    assert r["country"] == "US"
    assert r["label"] == "Parlophone"
    assert r["format"] == ["CD", "Album"]
    assert r["thumb"] == "https://example.com/thumb.jpg"
    assert r["cover_image"] == "https://example.com/cover.jpg"
    assert r["genre"] == ["Electronic", "Rock"]
    assert r["style"] == ["Alternative Rock", "Art Rock"]
    assert r["uri"] == "https://www.discogs.com/release/12345"


def test_search_releases_returns_empty_when_no_results(monkeypatch):
    monkeypatch.setattr(
        "pacer.services.discogs._request", lambda path, params=None: {"results": []}
    )
    from pacer.services import discogs
    assert discogs.search_releases("zzznotfound") == []


def test_search_releases_returns_empty_when_request_fails(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: None)
    from pacer.services import discogs
    assert discogs.search_releases("anything") == []


def test_search_artists_returns_list(monkeypatch):
    monkeypatch.setattr(
        "pacer.services.discogs._request",
        lambda path, params=None: {"results": [{"id": 99, "title": "Radiohead"}]}
        if "type=artist" in str(params) else None,
    )
    from pacer.services import discogs
    results = discogs.search_artists("radiohead")
    assert len(results) == 1
    assert results[0]["id"] == 99
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_discogs_service.py -v -k "search"`
Expected: AttributeError (`search_releases` not defined)

- [ ] **Step 3: Implement search functions**

Append to `pacer/services/discogs.py`:

```python
def search_releases(query: str, per_page: int = 20, page: int = 1) -> list[dict]:
    """Search releases. Returns list of normalized dicts (empty on failure)."""
    data = _request("/database/search", {
        "q": query, "type": "release",
        "per_page": per_page, "page": page,
    })
    if not data:
        return []
    out = []
    for r in data.get("results", []):
        labels = r.get("label") or [""]
        out.append({
            "discogs_id":   r.get("id"),
            "title":        r.get("title", ""),
            "year":         r.get("year"),
            "country":      r.get("country"),
            "label":        labels[0] if labels else "",
            "format":       r.get("format", []),
            "thumb":        r.get("thumb"),
            "cover_image":  r.get("cover_image"),
            "genre":        r.get("genre", []),
            "style":        r.get("style", []),
            "uri":          r.get("uri"),
            "resource_url": r.get("resource_url"),
        })
    return out


def search_masters(query: str, per_page: int = 20) -> list[dict]:
    """Search master releases (release-grouped)."""
    data = _request("/database/search", {"q": query, "type": "master", "per_page": per_page})
    return data.get("results", []) if data else []


def search_artists(query: str, per_page: int = 20) -> list[dict]:
    """Search artists."""
    data = _request("/database/search", {"q": query, "type": "artist", "per_page": per_page})
    return data.get("results", []) if data else []
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_discogs_service.py -v -k "search"`
Expected: 4 tests pass

- [ ] **Step 5: Commit**

```bash
git add pacer/services/discogs.py tests/test_discogs_service.py
git commit -m "feat(services/discogs): implement search_releases/search_masters/search_artists"
```

---

### Task 1.8: Implement Discogs `get_artist` with caching

**Files:**
- Modify: `pacer/services/discogs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discogs_service.py`:

```python
def test_get_artist_returns_normalized_dict(monkeypatch):
    fake = {
        "id": 3840,
        "name": "Radiohead",
        "realname": "Radiohead",
        "profile": "Radiohead are an English rock band from Abingdon...",
        "urls": ["https://radiohead.com", "https://example.com"],
        "aliases": [{"name": "Atoms For Peace"}],
        "members": [{"name": "Thom Yorke"}, {"name": "Jonny Greenwood"}],
        "namevariations": ["Radio Head", "RADIOHEAD"],
        "images": [{"uri": "https://example.com/radiohead.jpg", "uri150": "https://example.com/r150.jpg"}],
        "uri": "https://www.discogs.com/artist/3840-Radiohead",
    }
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._artist_cache.clear()  # start fresh
    result = discogs.get_artist(3840)
    assert result["id"] == 3840
    assert result["name"] == "Radiohead"
    assert result["real_name"] == "Radiohead"
    assert "Radiohead are an English" in result["profile"]
    assert result["urls"] == ["https://radiohead.com", "https://example.com"]
    assert result["aliases"] == ["Atoms For Peace"]
    assert result["members"] == ["Thom Yorke", "Jonny Greenwood"]
    assert result["name_variations"] == ["Radio Head", "RADIOHEAD"]
    assert result["discogs_url"] == "https://www.discogs.com/artist/3840-Radiohead"


def test_get_artist_uses_cache(monkeypatch):
    """Second call within TTL does not hit _request."""
    call_count = {"n": 0}

    def counting_request(path, params=None):
        call_count["n"] += 1
        return {"id": 1, "name": "X", "realname": "", "profile": "",
                "urls": [], "aliases": [], "members": [], "namevariations": [],
                "images": [], "uri": ""}

    monkeypatch.setattr("pacer.services.discogs._request", counting_request)
    from pacer.services import discogs
    discogs._artist_cache.clear()
    discogs.get_artist(1)
    discogs.get_artist(1)
    discogs.get_artist(1)
    assert call_count["n"] == 1


def test_get_artist_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: None)
    from pacer.services import discogs
    discogs._artist_cache.clear()
    assert discogs.get_artist(999) is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_discogs_service.py -v -k "get_artist"`
Expected: AttributeError

- [ ] **Step 3: Implement `get_artist`**

Append to `pacer/services/discogs.py`:

```python
def get_artist(discogs_id: int) -> dict | None:
    """Fetch artist by id with 7-day in-memory cache.

    Returns normalized dict or None on failure.
    """
    now = time.time()
    if discogs_id in _artist_cache and _artist_cache[discogs_id][1] > now:
        return _artist_cache[discogs_id][0]

    data = _request(f"/artists/{discogs_id}")
    if not data:
        return None

    normalized = {
        "id":              data.get("id"),
        "name":            data.get("name"),
        "real_name":       data.get("realname"),
        "profile":         data.get("profile"),
        "urls":            data.get("urls", []),
        "aliases":         [a.get("name") for a in (data.get("aliases") or [])],
        "members":         [m.get("name") for m in (data.get("members") or [])],
        "name_variations": data.get("namevariations", []),
        "images":          data.get("images", []),
        "discogs_url":     data.get("uri"),
    }
    _artist_cache[discogs_id] = (normalized, now + ARTIST_TTL)
    return normalized
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_discogs_service.py -v -k "get_artist"`
Expected: 3 tests pass

- [ ] **Step 5: Commit**

```bash
git add pacer/services/discogs.py tests/test_discogs_service.py
git commit -m "feat(services/discogs): implement get_artist with 7d in-memory cache"
```

---

### Task 1.9: Implement Discogs `get_release` with caching

**Files:**
- Modify: `pacer/services/discogs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discogs_service.py`:

```python
def test_get_release_returns_normalized_dict(monkeypatch):
    fake = {
        "id": 12345,
        "title": "Radiohead - OK Computer",
        "year": 1997,
        "country": "UK",
        "labels": [{"name": "Parlophone", "catno": "NODATA01"}],
        "formats": [{"name": "CD"}, {"name": "Album"}],
        "genres": ["Electronic", "Rock"],
        "styles": ["Alternative Rock", "Art Rock"],
        "tracklist": [
            {"position": "1", "title": "Airbag", "duration": "4:44", "artists": [{"name": "Radiohead"}]},
            {"position": "2", "title": "Paranoid Android", "duration": "6:23", "artists": [{"name": "Radiohead"}]},
        ],
        "artists": [{"name": "Radiohead"}],
        "master_id": 40260,
        "master_url": "https://api.discogs.com/masters/40260",
        "uri": "https://www.discogs.com/release/12345",
        "images": [{"uri": "https://example.com/cover.jpg", "uri150": "https://example.com/150.jpg"}],
    }
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._release_cache.clear()
    r = discogs.get_release(12345)
    assert r["id"] == 12345
    assert r["title"] == "Radiohead - OK Computer"
    assert r["year"] == 1997
    assert r["country"] == "UK"
    assert r["label"] == "Parlophone"
    assert r["catalog_no"] == "NODATA01"
    assert r["format"] == ["CD", "Album"]
    assert r["genres"] == ["Electronic", "Rock"]
    assert r["styles"] == ["Alternative Rock", "Art Rock"]
    assert len(r["tracklist"]) == 2
    assert r["tracklist"][0]["position"] == "1"
    assert r["tracklist"][0]["title"] == "Airbag"
    assert r["tracklist"][0]["duration"] == "4:44"
    assert r["artists"] == ["Radiohead"]
    assert r["master_id"] == 40260
    assert r["master_url"] == "https://api.discogs.com/masters/40260"
    assert r["release_url"] == "https://www.discogs.com/release/12345"
    assert r["cover_image"] == "https://example.com/cover.jpg"


def test_get_release_handles_missing_labels(monkeypatch):
    fake = {"id": 1, "title": "X", "year": 2020, "country": "US",
            "labels": [], "formats": [], "genres": [], "styles": [],
            "tracklist": [], "artists": [], "master_id": 0, "master_url": "",
            "uri": "", "images": []}
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._release_cache.clear()
    r = discogs.get_release(1)
    assert r["label"] is None
    assert r["catalog_no"] is None
    assert r["format"] == []


def test_get_release_uses_cache(monkeypatch):
    call_count = {"n": 0}
    def counting(path, params=None):
        call_count["n"] += 1
        return {"id": 1, "title": "X", "year": 2020, "country": "US",
                "labels": [], "formats": [], "genres": [], "styles": [],
                "tracklist": [], "artists": [], "master_id": 0, "master_url": "",
                "uri": "", "images": []}
    monkeypatch.setattr("pacer.services.discogs._request", counting)
    from pacer.services import discogs
    discogs._release_cache.clear()
    discogs.get_release(1)
    discogs.get_release(1)
    assert call_count["n"] == 1
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_discogs_service.py -v -k "get_release"`
Expected: AttributeError

- [ ] **Step 3: Implement `get_release`**

Append to `pacer/services/discogs.py`:

```python
def get_release(release_id: int) -> dict | None:
    """Fetch release by id with 30-day in-memory cache."""
    now = time.time()
    if release_id in _release_cache and _release_cache[release_id][1] > now:
        return _release_cache[release_id][0]

    data = _request(f"/releases/{release_id}")
    if not data:
        return None

    labels = data.get("labels") or [{}]
    label_obj = labels[0] if labels else {}
    images = data.get("images") or [{}]
    image_obj = images[0] if images else {}

    normalized = {
        "id":            data.get("id"),
        "title":         data.get("title"),
        "year":          data.get("year"),
        "country":       data.get("country"),
        "label":         label_obj.get("name"),
        "catalog_no":    label_obj.get("catno"),
        "format":        [f.get("name") for f in (data.get("formats") or [])],
        "genres":        data.get("genres", []),
        "styles":        data.get("styles", []),
        "tracklist":     [
            {
                "position": t.get("position"),
                "title":    t.get("title"),
                "duration": t.get("duration"),
                "artists":  [a.get("name") for a in (t.get("artists") or [])],
            }
            for t in (data.get("tracklist") or [])
        ],
        "artists":       [a.get("name") for a in (data.get("artists") or [])],
        "master_id":     data.get("master_id"),
        "master_url":    data.get("master_url"),
        "release_url":   data.get("uri"),
        "cover_image":   image_obj.get("uri"),
        "thumb":         image_obj.get("uri150"),
    }
    _release_cache[release_id] = (normalized, now + RELEASE_TTL)
    return normalized
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_discogs_service.py -v -k "get_release"`
Expected: 3 tests pass

- [ ] **Step 5: Commit**

```bash
git add pacer/services/discogs.py tests/test_discogs_service.py
git commit -m "feat(services/discogs): implement get_release with 30d cache and label/format normalization"
```

---

### Task 1.10: Implement Discogs `get_master` and high-level helpers

**Files:**
- Modify: `pacer/services/discogs.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_discogs_service.py`:

```python
def test_get_master_returns_normalized_dict(monkeypatch):
    fake = {
        "id": 40260,
        "title": "OK Computer",
        "year": 1997,
        "main_release": 12345,
        "artists": [{"name": "Radiohead"}],
        "genres": ["Rock"],
        "styles": ["Alternative Rock"],
        "tracklist": [
            {"position": "1", "title": "Airbag", "duration": "4:44"},
            {"position": "2", "title": "Paranoid Android", "duration": "6:23"},
        ],
        "uri": "https://www.discogs.com/master/40260",
    }
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._master_cache.clear()
    m = discogs.get_master(40260)
    assert m["id"] == 40260
    assert m["title"] == "OK Computer"
    assert m["year"] == 1997
    assert m["main_release"] == 12345
    assert m["artists"] == ["Radiohead"]
    assert m["styles"] == ["Alternative Rock"]
    assert len(m["tracklist"]) == 2
    assert m["discogs_url"] == "https://www.discogs.com/master/40260"


def test_find_release_by_artist_title_prefers_exact(monkeypatch):
    fake_results = [
        {
            "id": 1, "title": "Radiohead - OK Computer", "year": 1997,
            "country": "US", "label": ["Parlophone"], "format": ["CD"],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        },
        {
            "id": 2, "title": "Some Other Album", "year": 2000,
            "country": "US", "label": ["X"], "format": [],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        },
    ]
    monkeypatch.setattr("pacer.services.discogs.search_releases", lambda q, per_page=20, page=1: fake_results)
    from pacer.services import discogs
    match = discogs.find_release_by_artist_title("Radiohead", "OK Computer")
    assert match is not None
    assert match["discogs_id"] == 1   # exact match preferred


def test_find_release_by_artist_title_falls_back_to_first(monkeypatch):
    fake_results = [
        {
            "id": 99, "title": "Different Album", "year": 2010,
            "country": "US", "label": ["X"], "format": [],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        },
    ]
    monkeypatch.setattr("pacer.services.discogs.search_releases", lambda q, per_page=20, page=1: fake_results)
    from pacer.services import discogs
    match = discogs.find_release_by_artist_title("Nonexistent", "Stuff")
    assert match["discogs_id"] == 99


def test_find_release_by_artist_title_returns_none_when_no_results(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs.search_releases", lambda q, per_page=20, page=1: [])
    from pacer.services import discogs
    assert discogs.find_release_by_artist_title("X", "Y") is None


def test_find_artist_by_name_returns_first(monkeypatch):
    monkeypatch.setattr(
        "pacer.services.discogs.search_artists",
        lambda q, per_page=20: [{"id": 1, "title": "Radiohead"}],
    )
    from pacer.services import discogs
    assert discogs.find_artist_by_name("Radiohead")["id"] == 1
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_discogs_service.py -v -k "get_master or find_release or find_artist"`
Expected: AttributeError

- [ ] **Step 3: Implement helpers**

Append to `pacer/services/discogs.py`:

```python
def get_master(master_id: int) -> dict | None:
    """Fetch master release (release-grouped) with 30-day cache."""
    now = time.time()
    if master_id in _master_cache and _master_cache[master_id][1] > now:
        return _master_cache[master_id][0]

    data = _request(f"/masters/{master_id}")
    if not data:
        return None

    normalized = {
        "id":           data.get("id"),
        "title":        data.get("title"),
        "year":         data.get("year"),
        "main_release": data.get("main_release"),
        "artists":      [a.get("name") for a in (data.get("artists") or [])],
        "genres":       data.get("genres", []),
        "styles":       data.get("styles", []),
        "tracklist":    [
            {
                "position": t.get("position"),
                "title":    t.get("title"),
                "duration": t.get("duration"),
            }
            for t in (data.get("tracklist") or [])
        ],
        "discogs_url":  data.get("uri"),
    }
    _master_cache[master_id] = (normalized, now + RELEASE_TTL)
    return normalized


def find_release_by_artist_title(artist: str, title: str) -> dict | None:
    """Search Discogs and return best matching release.

    Prefers result whose title contains BOTH artist and title substrings.
    Falls back to first result. Returns None when no results.
    """
    artist_l = (artist or "").lower()
    title_l  = (title or "").lower()
    results = search_releases(f"{artist} {title}", per_page=5)
    if not results:
        return None
    for r in results:
        if artist_l in r["title"].lower() and title_l in r["title"].lower():
            return r
    return results[0]


def find_artist_by_name(name: str) -> dict | None:
    """Return first matching artist from search, or None."""
    results = search_artists(name, per_page=5)
    return results[0] if results else None
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_discogs_service.py -v`
Expected: all 18 tests pass (2 config + 4 _request + 4 search + 3 get_artist + 3 get_release + 2 other)

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all tests pass (smoke + schema migration + discogs)

- [ ] **Step 6: Commit**

```bash
git add pacer/services/discogs.py tests/test_discogs_service.py
git commit -m "feat(services/discogs): add get_master + find_release_by_artist_title + find_artist_by_name"
```

---

### Task 1.11: Document Discogs setup

**Files:**
- Create: `docs/discogs-setup.md`

- [ ] **Step 1: Create setup doc**

Write `docs/discogs-setup.md`:

```markdown
# Discogs API Setup

Pacer uses the Discogs API to fetch artist, album, and track metadata
(genre, style, label, format, year, country, master release). This is the
primary data source for music catalog info as of 2026-06-10.

## Register an App

1. Sign in to <https://www.discogs.com>.
2. Go to <https://www.discogs.com/settings/developers>.
3. Click "Create an app" (or "New Application").
4. Fill in:
   - **Name:** Pacer
   - **Description:** Music rating & review site
   - **URL:** <https://github.com/0xzhepyr/Pacer> (or your fork)
5. Save. Discogs will issue a **Consumer Key** and **Consumer Secret**.

## Configure Pacer

Set the following environment variables (in `.env` for local dev, or via your
hosting provider's dashboard for production):

```bash
DISCOGS_CONSUMER_KEY=your_consumer_key_here
DISCOGS_CONSUMER_SECRET=your_consumer_secret_here
# Optional: override User-Agent (default: "Pacer/1.0 +https://github.com/0xzhepyr/Pacer")
DISCOGS_USER_AGENT="Pacer/1.0 (your-email@example.com)"
```

> **Important:** Discogs requires a unique User-Agent per app. If you fork
> Pacer, change `DISCOGS_USER_AGENT` to identify your deployment (email
> recommended; Discogs uses it to contact you if your app misbehaves).

## Restart Pacer

```bash
python app.py
# or in production: restart your gunicorn process
```

If env vars are missing, `discogs_configured()` returns False and Pacer
degrades gracefully: song pages hide the "Catalog" panel, search returns
503 with a helpful message. The rest of Pacer (ratings, comments, forum,
feed) continues to work.

## Rate Limits

- **Authenticated (with Consumer Key/Secret):** 240 requests per minute
- **Unauthenticated:** 25 requests per minute

Pacer's caching strategy:
- Artist data: cached in-memory for 7 days
- Release/master data: cached in-memory for 30 days
- Spotify preview URL (artist+title → spotify_id): cached in DB for 30 days

The in-memory caches reset on every Pacer restart. The DB cache survives
restarts.

## Troubleshooting

- **`[discogs] 401 on /...`**: Consumer Key/Secret invalid. Re-register the app.
- **`[discogs] 429 on /...`**: Rate limited. Pacer falls back to cache. If
  cache is empty, the affected feature (e.g. Catalog panel) is hidden.
- **`[discogs] 5xx on /...`**: Discogs is having issues. Wait a few minutes.
- **No "Catalog" panel on song page**: Either Discogs is not configured, or
  Discogs doesn't have a match for the track. Check `/admin` to see logs.
```

- [ ] **Step 2: Commit**

```bash
git add docs/discogs-setup.md
git commit -m "docs: add Discogs setup guide for consumer key/secret configuration"
```

---

## Phase 2: Slim Spotify Service

### Task 2.1: Add `lookup_spotify_preview` with DB cache

**Files:**
- Modify: `pacer/services/spotify.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_spotify_service_slim.py`:

```python
"""Unit tests for slim Spotify service, especially lookup_spotify_preview."""


def test_lookup_preview_cache_hit_skips_api(temp_db, monkeypatch):
    """Pre-populate cache; no API call should be made."""
    from datetime import datetime
    import pacer.services.spotify as spotify
    import pacer.db as db

    now = datetime.utcnow().isoformat(timespec="seconds")
    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO spotify_preview_cache
           (artist, title, spotify_id, preview_url, fetched_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("Radiohead", "karma police", "abc123",
         "https://p.scdn.co/mp3-preview/abc.mp3", now),
    )
    con.commit()
    con.close()

    called = {"n": 0}
    def fake_get(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not hit network on cache hit")
    monkeypatch.setattr(spotify.requests, "get", fake_get)

    result = spotify.lookup_spotify_preview("Radiohead", "Karma Police")
    assert result is not None
    assert result["spotify_id"] == "abc123"
    assert result["preview_url"] == "https://p.scdn.co/mp3-preview/abc.mp3"
    assert called["n"] == 0


def test_lookup_preview_cache_miss_fetches_and_caches(temp_db, monkeypatch):
    """Empty cache → API call → cache write."""
    import pacer.services.spotify as spotify
    import pacer.db as db

    fake_response = {
        "tracks": {
            "items": [
                {
                    "id": "newid",
                    "preview_url": "https://p.scdn.co/mp3-preview/new.mp3",
                    "external_urls": {"spotify": "https://open.spotify.com/track/newid"},
                }
            ]
        }
    }
    class FakeResp:
        status_code = 200
        text = ""
        def ok(self): return True
        def json(self): return fake_response

    monkeypatch.setattr(spotify, "get_app_spotify_token", lambda: "fake-token")
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: FakeResp())

    result = spotify.lookup_spotify_preview("New Artist", "New Song")
    assert result is not None
    assert result["spotify_id"] == "newid"
    assert result["preview_url"] == "https://p.scdn.co/mp3-preview/new.mp3"

    # Verify cache was written
    con = db.sqlite3.connect(temp_db)
    row = con.execute(
        "SELECT * FROM spotify_preview_cache WHERE artist=? AND title=?",
        ("new artist", "new song"),
    ).fetchone()
    assert row is not None
    assert row["spotify_id"] == "newid"
    con.close()


def test_lookup_preview_negative_result_caches(temp_db, monkeypatch):
    """When Spotify returns 0 items, still cache (NULL spotify_id) to avoid re-querying."""
    import pacer.services.spotify as spotify
    import pacer.db as db

    fake_response = {"tracks": {"items": []}}
    class FakeResp:
        status_code = 200
        text = ""
        def ok(self): return True
        def json(self): return fake_response

    monkeypatch.setattr(spotify, "get_app_spotify_token", lambda: "fake-token")
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: FakeResp())

    result = spotify.lookup_spotify_preview("Obscure", "Lost Track")
    assert result is None

    con = db.sqlite3.connect(temp_db)
    row = con.execute(
        "SELECT * FROM spotify_preview_cache WHERE artist=? AND title=?",
        ("obscure", "lost track"),
    ).fetchone()
    assert row is not None
    assert row["spotify_id"] is None
    con.close()


def test_lookup_preview_returns_none_without_artist_or_title():
    import pacer.services.spotify as spotify
    assert spotify.lookup_spotify_preview("", "Song") is None
    assert spotify.lookup_spotify_preview("Artist", "") is None
    assert spotify.lookup_spotify_preview(None, "Song") is None


def test_lookup_preview_returns_none_when_spotify_unconfigured(monkeypatch):
    import pacer.services.spotify as spotify
    monkeypatch.setattr(spotify, "spotify_configured", lambda: False)
    assert spotify.lookup_spotify_preview("Artist", "Song") is None


def test_lookup_preview_returns_none_when_no_token(temp_db, monkeypatch):
    import pacer.services.spotify as spotify
    monkeypatch.setattr(spotify, "spotify_configured", lambda: True)
    monkeypatch.setattr(spotify, "get_app_spotify_token", lambda: None)
    assert spotify.lookup_spotify_preview("Artist", "Song") is None
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_spotify_service_slim.py -v`
Expected: ImportError or AttributeError (`lookup_spotify_preview` not defined)

- [ ] **Step 3: Implement `lookup_spotify_preview` in `pacer/services/spotify.py`**

Add the following at the end of `pacer/services/spotify.py` (before the artist functions, which we'll delete in Task 2.2):

```python
import sqlite3
from datetime import datetime
from pacer.config import DB_PATH


def lookup_spotify_preview(artist: str, title: str) -> dict | None:
    """Find a Spotify track by artist+title. Cached in DB for 30 days.

    Returns dict {spotify_id, preview_url, spotify_url} or None.
    Negative results (no match) are also cached to avoid re-querying.
    """
    artist = (artist or "").strip()
    title  = (title or "").strip()
    if not artist or not title:
        return None

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        # 1. cek cache (case-insensitive via lower())
        row = con.execute(
            "SELECT * FROM spotify_preview_cache WHERE artist = ? AND title = ?",
            (artist.lower(), title.lower()),
        ).fetchone()
        if row:
            try:
                fetched = datetime.fromisoformat(row["fetched_at"])
                age_days = (datetime.utcnow() - fetched).total_seconds() / 86400
            except (TypeError, ValueError):
                age_days = 999
            if age_days < 30:
                if row["spotify_id"]:
                    return {
                        "spotify_id":  row["spotify_id"],
                        "preview_url": row["preview_url"],
                        "spotify_url": f"https://open.spotify.com/track/{row['spotify_id']}",
                    }
                return None  # negative cache hit, still valid

        # 2. fetch dari Spotify
        if not spotify_configured():
            return None
        token = get_app_spotify_token()
        if not token:
            return None

        try:
            r = requests.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": f'track:"{title}" artist:"{artist}"', "type": "track", "limit": 1},
                timeout=8,
            )
        except requests.RequestException:
            return None
        if not r.ok:
            return None

        items = (r.json().get("tracks") or {}).get("items") or []
        now = datetime.utcnow().isoformat(timespec="seconds")
        if not items:
            con.execute(
                """INSERT INTO spotify_preview_cache
                   (artist, title, spotify_id, preview_url, fetched_at)
                   VALUES (?, ?, NULL, NULL, ?)
                   ON CONFLICT(artist, title) DO UPDATE SET
                     spotify_id = NULL, preview_url = NULL, fetched_at = ?""",
                (artist.lower(), title.lower(), now, now),
            )
            con.commit()
            return None

        t = items[0]
        spotify_id  = t.get("id")
        preview_url = t.get("preview_url")
        con.execute(
            """INSERT INTO spotify_preview_cache
               (artist, title, spotify_id, preview_url, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(artist, title) DO UPDATE SET
                 spotify_id = ?, preview_url = ?, fetched_at = ?""",
            (artist.lower(), title.lower(), spotify_id, preview_url, now,
             spotify_id, preview_url, now),
        )
        con.commit()
        return {
            "spotify_id":  spotify_id,
            "preview_url": preview_url,
            "spotify_url": f"https://open.spotify.com/track/{spotify_id}",
        }
    finally:
        con.close()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_spotify_service_slim.py -v`
Expected: 6 tests pass

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add pacer/services/spotify.py tests/test_spotify_service_slim.py
git commit -m "feat(services/spotify): add lookup_spotify_preview with 30d DB cache"
```

---

### Task 2.2: Remove deprecated Spotify functions (DEPRECATED → DELETE)

**Files:**
- Modify: `pacer/services/spotify.py`

- [ ] **Step 1: Identify all callers of deprecated functions**

Run:
```bash
grep -rn "_spotify_lookup_track\|_find_or_create_song_from_spotify\|_find_or_create_album_from_spotify\|_fetch_album_tracks\|find_or_create_artist\|fetch_artist\|fetch_artist_top_tracks\|fetch_artist_albums" pacer/ tests/
```

Expected callers to migrate (these will be rewritten in Phase 3):
- `pacer/routes/music.py` (multiple imports)

- [ ] **Step 2: Update imports in `pacer/routes/music.py`**

In `pacer/routes/music.py`, find and replace the import block:

```python
from pacer.services.spotify import (
    _find_or_create_song_from_spotify,
    _find_or_create_album_from_spotify,
    _fetch_album_tracks,
    find_or_create_artist,
    fetch_artist_top_tracks,
    fetch_artist_albums,
)
```

Replace with:

```python
from pacer.services import discogs
from pacer.services.spotify import lookup_spotify_preview
```

(Keep the import — `discogs` and `lookup_spotify_preview` will be used in Phase 3, but the old functions are no longer imported here.)

- [ ] **Step 3: Delete the deprecated functions from `pacer/services/spotify.py`**

In `pacer/services/spotify.py`, delete the following function definitions (and any helper code only used by them):
- `_spotify_lookup_track`
- `_find_or_create_song_from_spotify`
- `_find_or_create_album_from_spotify`
- `_fetch_album_tracks`
- `find_or_create_artist`
- `fetch_artist`
- `fetch_artist_top_tracks`
- `fetch_artist_albums`

Also remove the `_album_tracks_cache` module-level variable if no other function uses it (it was only used by `_fetch_album_tracks`).

- [ ] **Step 4: Verify nothing else imports them**

Run:
```bash
grep -rn "_spotify_lookup_track\|_find_or_create_song_from_spotify\|_find_or_create_album_from_spotify\|_fetch_album_tracks\|find_or_create_artist\|fetch_artist\|fetch_artist_top_tracks\|fetch_artist_albums" pacer/ tests/
```

Expected: no matches (all references gone, except in comments/docs)

- [ ] **Step 5: Verify existing routes still load (no import errors)**

Run: `python -c "from pacer import create_app; app = create_app(); print('app ok')"`
Expected: `app ok` (app boots; routes may be broken because `music.py` uses functions we deleted, but app itself loads)

Note: routes will 500 if hit. That's expected at this stage. Phase 3 fixes them.

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all unit tests pass (smoke + schema + discogs + spotify_slim); route tests will be added in Phase 3

- [ ] **Step 7: Commit**

```bash
git add pacer/services/spotify.py pacer/routes/music.py tests/
git commit -m "refactor(services/spotify): remove 8 deprecated functions; keep only trending, playlist, preview, user-token"
```

---

## Phase 3: Music Routes Migration

### Task 3.1: Implement `find_or_create_song_from_spotify` helper

**Files:**
- Modify: `pacer/routes/music.py` (add the helper function at module level)

- [ ] **Step 1: Write the failing test**

Create `tests/test_routes_music.py`:

```python
"""Integration tests for music routes with Discogs enrichment."""


def test_find_or_create_song_returns_existing_by_spotify_id(temp_db, monkeypatch):
    """If song already in DB by spotify_id, return it (no Discogs call)."""
    import pacer.routes.music as music
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'test', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at, spotify_id, spotify_image)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01', 'spotify-abc', 'image.jpg')"""
    )
    con.commit()
    con.close()

    called = {"n": 0}
    def fake(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not call Discogs when song exists")
    monkeypatch.setattr(music.discogs, "find_release_by_artist_title", fake)

    result = music.find_or_create_song_from_spotify({
        "id": "spotify-abc", "name": "Airbag",
        "artists": "Radiohead", "image": "image.jpg",
    })
    assert result["id"] == 1
    assert called["n"] == 0


def test_find_or_create_song_creates_with_discogs_metadata(temp_db, monkeypatch):
    """New song → Discogs lookup → row inserted with discogs_release_id."""
    import pacer.routes.music as music
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'test', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(music.discogs, "find_release_by_artist_title",
                        lambda a, t: {"discogs_id": 999})
    monkeypatch.setattr(music.discogs, "get_release",
                        lambda rid: {
                            "id": 999, "title": "OK Computer", "year": 1997,
                            "country": "UK", "label": "Parlophone",
                            "catalog_no": "NODATA01", "format": ["CD"],
                            "genres": ["Rock"], "styles": ["Alternative Rock"],
                            "tracklist": [], "artists": ["Radiohead"],
                            "master_id": 0, "master_url": "", "release_url": "",
                            "cover_image": "x", "thumb": "y",
                        })
    monkeypatch.setattr(music.discogs, "find_artist_by_name",
                        lambda n: {"id": 1, "title": "Radiohead"})
    monkeypatch.setattr(music.discogs, "get_artist", lambda aid: {
        "id": 1, "name": "Radiohead", "real_name": "Radiohead",
        "profile": "English rock band", "urls": [], "aliases": [],
        "members": [], "name_variations": [], "images": [],
        "discogs_url": "https://www.discogs.com/artist/1",
    })
    monkeypatch.setattr(music, "lookup_spotify_preview",
                        lambda a, t: {"spotify_id": "spotify-xyz",
                                      "preview_url": "https://preview.mp3",
                                      "spotify_url": "https://open.spotify.com/track/spotify-xyz"})

    result = music.find_or_create_song_from_spotify({
        "id": "spotify-xyz", "name": "Airbag",
        "artists": "Radiohead", "image": "image.jpg",
    })
    assert result["spotify_id"] == "spotify-xyz"
    assert result["discogs_release_id"] == 999
    assert result["title"] == "Airbag"

    # Verify DB row exists
    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    row = con.execute("SELECT * FROM songs WHERE spotify_id = ?", ("spotify-xyz",)).fetchone()
    assert row is not None
    assert row["discogs_release_id"] == 999
    assert row["title"] == "Airbag"
    styles = con.execute("SELECT style FROM song_styles WHERE song_id = ?", (row["id"],)).fetchall()
    assert ("Alternative Rock",) in [tuple(r) for r in styles]
    con.close()


def test_find_or_create_song_handles_no_discogs_match(temp_db, monkeypatch):
    """When Discogs returns no match, save song without metadata."""
    import pacer.routes.music as music
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'test', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(music.discogs, "find_release_by_artist_title", lambda a, t: None)
    monkeypatch.setattr(music, "lookup_spotify_preview", lambda a, t: None)

    result = music.find_or_create_song_from_spotify({
        "id": "spotify-orphan", "name": "Obscure Track",
        "artists": "Unknown Artist", "image": "image.jpg",
    })
    assert result["spotify_id"] == "spotify-orphan"
    assert result["discogs_release_id"] is None

    con = db.sqlite3.connect(temp_db)
    row = con.execute("SELECT * FROM songs WHERE spotify_id = ?", ("spotify-orphan",)).fetchone()
    assert row is not None
    assert row["discogs_release_id"] is None
    con.close()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_routes_music.py -v`
Expected: ImportError (`find_or_create_song_from_spotify` not defined)

- [ ] **Step 3: Add the helper to `pacer/routes/music.py`**

At the top of `pacer/routes/music.py`, after the imports, add:

```python
from pacer.services import discogs
from pacer.services.spotify import lookup_spotify_preview
from datetime import datetime as _dt


def find_or_create_song_from_spotify(spotify_meta: dict) -> dict:
    """Persist a Spotify trending/search result as a local songs row.

    Looks up Discogs metadata (artist profile, release details, styles).
    If Discogs has no match, saves the song with NULL Discogs columns —
    the song page will simply hide the 'Catalog' panel.

    Args:
        spotify_meta: dict with keys: id, name, artists, image, (optional) album

    Returns:
        The persisted song row as a dict-like (sqlite3.Row).
    """
    db = get_db()
    spotify_id = spotify_meta.get("id")
    artist     = spotify_meta.get("artists", "")
    title      = spotify_meta.get("name", "")

    # 1. cek DB by spotify_id
    existing = db.execute(
        "SELECT * FROM songs WHERE spotify_id = ?", (spotify_id,)
    ).fetchone()
    if existing:
        return existing

    # 2. Default submitter: first user
    submitter = db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if not submitter:
        # No users at all — refuse to create
        return None
    submitter_id = submitter["id"]

    # 3. Lookup Discogs
    discogs_release_id = None
    discogs_artist_id  = None
    style_rows = []

    if discogs.discogs_configured():
        match = discogs.find_release_by_artist_title(artist, title)
        if match and match.get("discogs_id"):
            release = discogs.get_release(match["discogs_id"])
            if release:
                discogs_release_id = release["id"]
                style_rows = release.get("styles", [])

                # Upsert artist
                artist_match = discogs.find_artist_by_name(artist)
                if artist_match:
                    aid = artist_match.get("id")
                    existing_artist = db.execute(
                        "SELECT id FROM artists WHERE discogs_id = ?", (aid,)
                    ).fetchone()
                    if existing_artist:
                        discogs_artist_id = existing_artist["id"]
                    else:
                        a_data = discogs.get_artist(aid)
                        if a_data:
                            cur = db.execute(
                                """INSERT INTO artists
                                   (spotify_id, discogs_id, name, real_name,
                                    profile_text, aliases, members, urls,
                                    namevariations, theme, created_at)
                                   VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?,
                                           'sky', ?)""",
                                (a_data["id"], a_data["name"], a_data["real_name"],
                                 a_data["profile"],
                                 ", ".join(a_data["aliases"]),
                                 ", ".join(a_data["members"]),
                                 ", ".join(a_data["urls"]),
                                 ", ".join(a_data["name_variations"]),
                                 _dt.utcnow().isoformat(timespec="seconds")),
                            )
                            discogs_artist_id = cur.lastrowid

    # 4. Cache preview (best effort, ignore failure)
    lookup_spotify_preview(artist, title)

    # 5. Insert song
    cur = db.execute(
        """INSERT INTO songs
           (title, artist, submitted_by, created_at,
            spotify_id, spotify_image, spotify_url,
            discogs_release_id, artist_id, discogs_artists)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (title[:120], artist[:120], submitter_id,
         _dt.utcnow().isoformat(timespec="seconds"),
         spotify_id, spotify_meta.get("image"),
         (spotify_meta.get("url") or f"https://open.spotify.com/track/{spotify_id}"),
         discogs_release_id, discogs_artist_id, artist[:200]),
    )
    song_id = cur.lastrowid

    # 6. Insert styles
    for s in style_rows:
        if s:
            db.execute(
                "INSERT OR IGNORE INTO song_styles (song_id, style) VALUES (?, ?)",
                (song_id, s),
            )
    db.commit()

    return db.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_routes_music.py -v -k "find_or_create_song"`
Expected: 3 tests pass

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add pacer/routes/music.py tests/test_routes_music.py
git commit -m "feat(routes/music): add find_or_create_song_from_spotify with Discogs enrichment"
```

---

### Task 3.2: Update `feed.home()` to use new helper

**Files:**
- Modify: `pacer/routes/feed.py`

- [ ] **Step 1: Read current `feed.home()`**

Confirm current state in `pacer/routes/feed.py:10-28` — it currently calls `fetch_spotify_trending()` and passes results to template as `trending`. It does NOT persist trending items as songs (that happens on click in `track_from_spotify`).

The new design: when trending items come in from Spotify, eagerly persist them as songs with Discogs metadata. This way the "Catalog" panel is ready when the user clicks.

- [ ] **Step 2: Update `feed.home()` to persist trending items**

Replace the body of `home()` in `pacer/routes/feed.py` with:

```python
@bp.route("/")
def home():
    """Homepage with X-style feed timeline."""
    db = get_db()
    user = current_user()

    # Get feed items
    feed_items = get_timeline(offset=0, limit=20)

    # Mark liked/reposted for current user
    if user:
        for item in feed_items:
            item["user_liked"] = has_user_liked(user["id"], item["item_type"], item["id"])
            item["user_reposted"] = has_user_reposted(user["id"], item["item_type"], item["id"])

    # Get trending for sidebar; persist each as a song (with Discogs enrichment)
    from pacer.routes.music import find_or_create_song_from_spotify
    raw_trending = fetch_spotify_trending(limit=6)
    trending = []
    for item in raw_trending:
        try:
            song = find_or_create_song_from_spotify({
                "id":      item.get("id"),
                "name":    item.get("name"),
                "artists": item.get("artists", ""),
                "image":   item.get("image"),
                "url":     item.get("url"),
            })
            if song:
                trending.append(song)
        except Exception:
            # Persist failure should not break homepage; fall back to raw
            trending.append(item)

    return render_template("home.html", feed_items=feed_items, trending=trending)
```

- [ ] **Step 3: Verify homepage loads**

Run: `python -c "from pacer import create_app; app = create_app(); client = app.test_client(); r = client.get('/'); print(r.status_code); assert r.status_code == 200"`
Expected: `200`

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add pacer/routes/feed.py
git commit -m "feat(feed): persist trending Spotify items as songs with Discogs enrichment"
```

---

### Task 3.3: Update `song_detail` to render Discogs catalog panel

**Files:**
- Modify: `pacer/routes/music.py` (`song_detail` function)
- Modify: `templates/song.html`

- [ ] **Step 1: Read current `song_detail` and `song.html`**

Current `song_detail` (lines 64-125 in `pacer/routes/music.py`) uses:
- `_find_or_create_song_from_spotify` (gone)
- `current_user()` from helpers

Current `song.html` renders song, ratings, reviews — but no "Catalog" panel.

- [ ] **Step 2: Update `song_detail` in `pacer/routes/music.py`**

Replace the `song_detail` function with:

```python
@bp.route("/songs/<int:song_id>", methods=["GET", "POST"])
def song_detail(song_id):
    db = get_db()
    song = db.execute("""
        SELECT s.*, u.username AS submitter FROM songs s
        JOIN users u ON u.id = s.submitted_by WHERE s.id = ?
    """, (song_id,)).fetchone()
    if not song:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to rate songs.", "warn")
            return redirect(url_for("auth.login", next=request.path))
        try:
            stars = float(request.form.get("stars") or 0)
        except (ValueError, TypeError):
            stars = 0
        if stars < 1 or stars > 5:
            flash("Pick a rating between 1 and 5.", "warn")
            return redirect(url_for("music.song_detail", song_id=song_id))
        stars = round(stars * 2) / 2
        review = (request.form.get("review") or "").strip()[:1500]
        db.execute("""
            INSERT INTO ratings (song_id, user_id, stars, review, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(song_id, user_id) DO UPDATE SET
              stars = excluded.stars,
              review = excluded.review,
              created_at = excluded.created_at
        """, (song_id, session["user_id"], stars, review,
              _dt.utcnow().isoformat(timespec="seconds")))
        db.commit()
        create_activity(session["user_id"], "rating", song_id=song_id, rating_stars=stars)
        flash("Rating saved.", "ok")
        return redirect(url_for("music.song_detail", song_id=song_id))

    # Discogs enrichment (graceful: None kalau gak ada / Discogs down)
    catalog = None
    if song["discogs_release_id"] and discogs.discogs_configured():
        try:
            catalog = discogs.get_release(song["discogs_release_id"])
        except Exception:
            catalog = None

    artist_info = None
    if song["artist_id"] and discogs.discogs_configured():
        artist_row = db.execute(
            "SELECT * FROM artists WHERE id = ?", (song["artist_id"],)
        ).fetchone()
        if artist_row and artist_row["discogs_id"]:
            try:
                artist_info = discogs.get_artist(artist_row["discogs_id"])
            except Exception:
                artist_info = None

    # Spotify preview embed URL
    preview_embed = None
    if song["spotify_id"]:
        preview_embed = f"https://open.spotify.com/embed/track/{song['spotify_id']}"

    stats = db.execute("""
        SELECT COALESCE(AVG(stars), 0) AS avg_stars, COUNT(*) AS n
        FROM ratings WHERE song_id = ?
    """, (song_id,)).fetchone()
    histogram = {i: 0 for i in range(1, 6)}
    for row in db.execute("SELECT stars, COUNT(*) c FROM ratings WHERE song_id=? GROUP BY stars", (song_id,)):
        histogram[row["stars"]] = row["c"]
    max_h = max(histogram.values()) or 1
    reviews = db.execute("""
        SELECT r.*, u.username, u.avatar_emoji FROM ratings r
        JOIN users u ON u.id = r.user_id
        WHERE r.song_id = ? AND r.review != ''
        ORDER BY r.id DESC
    """, (song_id,)).fetchall()
    featured = reviews[0] if reviews else None
    my_rating = None
    if session.get("user_id"):
        my_rating = db.execute(
            "SELECT * FROM ratings WHERE song_id=? AND user_id=?",
            (song_id, session["user_id"]),
        ).fetchone()
    return render_template(
        "song.html", song=song, stats=stats, histogram=histogram,
        max_h=max_h, reviews=reviews, featured=featured, my_rating=my_rating,
        catalog=catalog, artist_info=artist_info, preview_embed=preview_embed,
    )
```

- [ ] **Step 3: Add Catalog panel to `templates/song.html`**

Read the current `song.html` first, then locate the section that renders the song header/stats, and add a new aside after it. The exact insertion point depends on the existing structure; the key block to add is:

```html
{% if preview_embed %}
<div class="spotify-embed">
  <iframe src="{{ preview_embed }}"
          width="100%" height="80" frameborder="0"
          allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
          loading="lazy"></iframe>
</div>
{% endif %}

{% if catalog or artist_info %}
<aside class="catalog-panel">
  <h3>Catalog Info</h3>

  {% if artist_info %}
  <div class="artist-info-block">
    {% if artist_info.real_name and artist_info.real_name != artist_info.name %}
    <p class="realname">aka {{ artist_info.real_name }}</p>
    {% endif %}
    {% if artist_info.profile %}
    <p class="profile-text">{{ artist_info.profile }}</p>
    {% endif %}
    {% if artist_info.members %}
    <p class="members"><strong>Members:</strong> {{ artist_info.members|join(', ') }}</p>
    {% endif %}
    {% if artist_info.aliases %}
    <p class="aliases"><strong>Also known as:</strong> {{ artist_info.aliases|join(', ') }}</p>
    {% endif %}
    {% if artist_info.discogs_url %}
    <a href="{{ artist_info.discogs_url }}" target="_blank" rel="noopener" class="ext-link">View artist on Discogs ↗</a>
    {% endif %}
  </div>
  {% endif %}

  {% if catalog %}
  <dl class="catalog-dl">
    {% if catalog.label %}<dt>Label</dt><dd>{{ catalog.label }}</dd>{% endif %}
    {% if catalog.format %}<dt>Format</dt><dd>{{ catalog.format|join(', ') }}</dd>{% endif %}
    {% if catalog.year %}<dt>Year</dt><dd>{{ catalog.year }}</dd>{% endif %}
    {% if catalog.country %}<dt>Country</dt><dd>{{ catalog.country }}</dd>{% endif %}
    {% if catalog.catalog_no %}<dt>Catalog #</dt><dd>{{ catalog.catalog_no }}</dd>{% endif %}
  </dl>

  {% if catalog.styles %}
  <h4>Style</h4>
  <div class="style-chips">
    {% for s in catalog.styles %}
      <a href="{{ url_for('music.browse') }}?style={{ s }}" class="chip">{{ s }}</a>
    {% endfor %}
  </div>
  {% endif %}

  {% if catalog.release_url %}
  <a href="{{ catalog.release_url }}" target="_blank" rel="noopener" class="ext-link">Open on Discogs ↗</a>
  {% endif %}
  {% endif %}
</aside>
{% endif %}
```

- [ ] **Step 4: Write a route test for song_detail with Discogs metadata**

Append to `tests/test_routes_music.py`:

```python
def test_song_detail_renders_catalog_panel(temp_db, client, monkeypatch):
    """Song with discogs_release_id → catalog panel rendered."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at,
                              spotify_id, spotify_image, discogs_release_id)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01',
                   'sp-abc', 'img.jpg', 12345)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 12345, "title": "OK Computer", "year": 1997, "country": "UK",
        "label": "Parlophone", "catalog_no": "NODATA01", "format": ["CD", "Album"],
        "genres": ["Rock"], "styles": ["Alternative Rock", "Art Rock"],
        "tracklist": [], "artists": ["Radiohead"],
        "master_id": 0, "master_url": "", "release_url": "https://www.discogs.com/release/12345",
        "cover_image": "", "thumb": "",
    })

    resp = client.get("/songs/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Catalog Info" in body
    assert "Parlophone" in body
    assert "Alternative Rock" in body
    assert "https://www.discogs.com/release/12345" in body


def test_song_detail_without_discogs_metadata(temp_db, client, monkeypatch):
    """Song without discogs_release_id → no catalog panel rendered."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at, spotify_id)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01', 'sp-abc')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)

    resp = client.get("/songs/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Catalog Info" not in body
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_routes_music.py -v`
Expected: all 5 tests pass (3 find_or_create + 2 song_detail)

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add pacer/routes/music.py templates/song.html tests/test_routes_music.py
git commit -m "feat(song_detail): render Discogs Catalog panel + artist info + Spotify embed"
```

---

### Task 3.4: Update `album_detail` for Discogs

**Files:**
- Modify: `pacer/routes/music.py` (`album_detail` function)
- Modify: `templates/album.html`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_music.py`:

```python
def test_album_detail_renders_tracklist_from_discogs(temp_db, client, monkeypatch):
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO albums (id, name, artist, created_at, spotify_id, discogs_release_id)
           VALUES (1, 'OK Computer', 'Radiohead', '2026-01-01', '', 12345)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 12345, "title": "OK Computer", "year": 1997, "country": "UK",
        "label": "Parlophone", "catalog_no": "NODATA01", "format": ["CD"],
        "genres": ["Rock"], "styles": ["Alternative Rock"],
        "tracklist": [
            {"position": "1", "title": "Airbag", "duration": "4:44", "artists": ["Radiohead"]},
            {"position": "2", "title": "Paranoid Android", "duration": "6:23", "artists": ["Radiohead"]},
        ],
        "artists": ["Radiohead"], "master_id": 0, "master_url": "",
        "release_url": "https://www.discogs.com/release/12345",
        "cover_image": "", "thumb": "",
    })

    resp = client.get("/albums/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Airbag" in body
    assert "Paranoid Android" in body
    assert "4:44" in body
    assert "Parlophone" in body
    assert "https://www.discogs.com/release/12345" in body
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_routes_music.py::test_album_detail_renders_tracklist_from_discogs -v`
Expected: FAIL (no tracklist in response)

- [ ] **Step 3: Update `album_detail` in `pacer/routes/music.py`**

Replace the `album_detail` function with:

```python
@bp.route("/albums/<int:album_id>", methods=["GET", "POST"])
def album_detail(album_id):
    db = get_db()
    album = db.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not album:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to rate albums.", "warn")
            return redirect(url_for("auth.login", next=request.path))
        try:
            stars = float(request.form.get("stars") or 0)
        except (ValueError, TypeError):
            stars = 0
        if stars < 1 or stars > 5:
            flash("Pick a rating between 1 and 5.", "warn")
            return redirect(url_for("music.album_detail", album_id=album_id))
        stars = round(stars * 2) / 2
        review = (request.form.get("review") or "").strip()[:1500]
        db.execute("""
            INSERT INTO album_ratings (album_id, user_id, stars, review, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(album_id, user_id) DO UPDATE SET
              stars = excluded.stars,
              review = excluded.review,
              created_at = excluded.created_at
        """, (album_id, session["user_id"], stars, review,
              _dt.utcnow().isoformat(timespec="seconds")))
        db.commit()
        create_activity(session["user_id"], "rating", album_id=album_id, rating_stars=stars)
        flash("Rating saved.", "ok")
        return redirect(url_for("music.album_detail", album_id=album_id))

    # Discogs enrichment
    catalog = None
    if album["discogs_release_id"] and discogs.discogs_configured():
        try:
            catalog = discogs.get_release(album["discogs_release_id"])
        except Exception:
            catalog = None

    stats = db.execute("""
        SELECT COALESCE(AVG(stars), 0) AS avg_stars, COUNT(*) AS n
        FROM album_ratings WHERE album_id = ?
    """, (album_id,)).fetchone()
    histogram = {i: 0 for i in range(1, 6)}
    for row in db.execute(
        "SELECT stars, COUNT(*) c FROM album_ratings WHERE album_id=? GROUP BY stars",
        (album_id,),
    ):
        histogram[row["stars"]] = row["c"]
    max_h = max(histogram.values()) or 1
    reviews = db.execute("""
        SELECT r.*, u.username, u.avatar_emoji FROM album_ratings r
        JOIN users u ON u.id = r.user_id
        WHERE r.album_id = ? AND r.review != ''
        ORDER BY r.id DESC
    """, (album_id,)).fetchall()
    featured = reviews[0] if reviews else None
    my_rating = None
    if session.get("user_id"):
        my_rating = db.execute(
            "SELECT * FROM album_ratings WHERE album_id=? AND user_id=?",
            (album_id, session["user_id"]),
        ).fetchone()

    # Fall back to Spotify tracklist if no Discogs (legacy albums without discogs_release_id)
    tracks = []
    if catalog:
        tracks = catalog.get("tracklist", [])
    elif album["spotify_id"]:
        from pacer.services.spotify import _fetch_album_tracks  # legacy fallback
        tracks = _fetch_album_tracks(album["spotify_id"])

    return render_template(
        "album.html",
        album=album, stats=stats, histogram=histogram, max_h=max_h,
        reviews=reviews, featured=featured, my_rating=my_rating,
        tracks=tracks, catalog=catalog,
    )
```

> **Note:** If `_fetch_album_tracks` was already deleted in Task 2.2, drop the `elif` branch and the import. For legacy albums without `discogs_release_id`, the album page will show no tracklist — acceptable for this iteration since seed demo albums will get `discogs_release_id` lazily on first access.

- [ ] **Step 4: Add tracklist section to `templates/album.html`**

Locate the existing tracklist area in `album.html` and replace it with:

```html
{% if catalog %}
<section class="album-catalog">
  <h3>Tracklist</h3>
  <ol class="tracklist">
    {% for track in catalog.tracklist %}
    <li>
      <span class="pos">{{ track.position }}</span>
      <span class="title">{{ track.title }}</span>
      <span class="duration">{{ track.duration or '' }}</span>
    </li>
    {% endfor %}
  </ol>
  <p class="catalog-meta">
    Label: <strong>{{ catalog.label or '—' }}</strong> ·
    Format: <strong>{{ catalog.format|join(', ') or '—' }}</strong> ·
    {{ catalog.year or '—' }} · {{ catalog.country or '—' }}
  </p>
  {% if catalog.release_url %}
  <a href="{{ catalog.release_url }}" target="_blank" rel="noopener" class="ext-link">
    View on Discogs ↗
  </a>
  {% endif %}
</section>
{% elif tracks %}
<ol class="tracklist">
  {% for t in tracks %}
  <li>
    <span class="pos">{{ t.position or loop.index }}</span>
    <span class="title">{{ t.title or t.name }}</span>
    <span class="duration">{{ t.duration or '' }}</span>
  </li>
  {% endfor %}
</ol>
{% endif %}
```

- [ ] **Step 5: Run test, verify it passes**

Run: `pytest tests/test_routes_music.py::test_album_detail_renders_tracklist_from_discogs -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add pacer/routes/music.py templates/album.html tests/test_routes_music.py
git commit -m "feat(album_detail): render Discogs tracklist + label/format/country metadata"
```

---

### Task 3.5: Update `artist_detail` for Discogs bio

**Files:**
- Modify: `pacer/routes/music.py` (`artist_detail` function)
- Modify: `templates/artist.html`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_music.py`:

```python
def test_artist_detail_renders_discogs_bio(temp_db, client, monkeypatch):
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO artists (id, name, discogs_id)
           VALUES (1, 'Radiohead', 3840)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_artist", lambda did: {
        "id": 3840, "name": "Radiohead", "real_name": "Radiohead",
        "profile": "English rock band from Abingdon, Oxfordshire.",
        "urls": ["https://radiohead.com"], "aliases": ["Atoms For Peace"],
        "members": ["Thom Yorke", "Jonny Greenwood"],
        "name_variations": ["Radio Head"],
        "images": [], "discogs_url": "https://www.discogs.com/artist/3840",
    })
    monkeypatch.setattr(discogs, "fetch_artist_top_tracks", lambda did: [])
    monkeypatch.setattr(discogs, "fetch_artist_albums", lambda did: [])

    resp = client.get("/artists/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "English rock band" in body
    assert "Thom Yorke" in body
    assert "Atoms For Peace" in body
    assert "https://www.discogs.com/artist/3840" in body
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_routes_music.py::test_artist_detail_renders_discogs_bio -v`
Expected: FAIL (Spotify import error or profile not rendered)

- [ ] **Step 3: Update `artist_detail` in `pacer/routes/music.py`**

Replace the `artist_detail` function with:

```python
@bp.route("/artists/<int:artist_id>")
def artist_detail(artist_id):
    db = get_db()
    artist = db.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if not artist:
        abort(404)

    # Discogs enrichment
    artist_info = None
    if artist["discogs_id"] and discogs.discogs_configured():
        try:
            artist_info = discogs.get_artist(artist["discogs_id"])
        except Exception:
            artist_info = None

    # Community stats
    avg_song_rating = db.execute("""
        SELECT AVG(r.stars) as avg_stars, COUNT(r.id) as total_ratings
        FROM ratings r JOIN songs s ON r.song_id = s.id
        WHERE s.artist_id = ?
    """, (artist_id,)).fetchone()

    avg_album_rating = db.execute("""
        SELECT AVG(ar.stars) as avg_stars, COUNT(ar.id) as total_ratings
        FROM album_ratings ar JOIN albums a ON ar.album_id = a.id
        WHERE a.artist_id = ?
    """, (artist_id,)).fetchone()

    # Top tracks + albums from DB (avoid extra Discogs calls; Spotify is gone)
    top_tracks = db.execute("""
        SELECT id, title, album, year, spotify_id, spotify_image,
               COALESCE(AVG(r.stars), 0) as avg_stars, COUNT(r.id) as rating_count
        FROM songs s LEFT JOIN ratings r ON r.song_id = s.id
        WHERE s.artist_id = ?
        GROUP BY s.id ORDER BY avg_stars DESC LIMIT 5
    """, (artist_id,)).fetchall()

    albums = db.execute("""
        SELECT id, name, year, spotify_id, spotify_image, discogs_release_id,
               release_url
        FROM albums
        WHERE artist_id = ?
        ORDER BY year DESC
    """, (artist_id,)).fetchall()

    return render_template("artist.html",
        artist=artist, artist_info=artist_info,
        top_tracks=top_tracks, albums=albums,
        avg_song_rating=avg_song_rating,
        avg_album_rating=avg_album_rating,
    )
```

- [ ] **Step 4: Update `templates/artist.html`**

Find the artist header section and ensure the bio/profile/members block is rendered. Add this after the artist name/headline area:

```html
{% if artist_info %}
<div class="artist-bio">
  {% if artist_info.real_name and artist_info.real_name != artist_info.name %}
  <p class="realname">aka <strong>{{ artist_info.real_name }}</strong></p>
  {% endif %}
  {% if artist_info.profile %}
  <div class="profile-text">{{ artist_info.profile }}</div>
  {% endif %}
  {% if artist_info.members %}
  <p class="members"><strong>Members:</strong> {{ artist_info.members|join(', ') }}</p>
  {% endif %}
  {% if artist_info.aliases %}
  <p class="aliases"><strong>Also known as:</strong> {{ artist_info.aliases|join(', ') }}</p>
  {% endif %}
  {% if artist_info.urls %}
  <p class="urls">
    {% for u in artist_info.urls %}
    <a href="{{ u }}" target="_blank" rel="noopener" class="ext-link">{{ u }}</a>{% if not loop.last %} · {% endif %}
    {% endfor %}
  </p>
  {% endif %}
  {% if artist_info.discogs_url %}
  <a href="{{ artist_info.discogs_url }}" target="_blank" rel="noopener" class="ext-link">
    View artist on Discogs ↗
  </a>
  {% endif %}
</div>
{% endif %}
```

- [ ] **Step 5: Run test, verify it passes**

Run: `pytest tests/test_routes_music.py::test_artist_detail_renders_discogs_bio -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add pacer/routes/music.py templates/artist.html tests/test_routes_music.py
git commit -m "feat(artist_detail): render Discogs bio, real name, members, aliases, URLs"
```

---

## Phase 4: Search & Browse

### Task 4.1: Update `browse` to filter by style

**Files:**
- Modify: `pacer/routes/music.py` (`browse` function)
- Modify: `templates/browse.html`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_music.py`:

```python
def test_browse_filters_by_style(temp_db, client):
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at)
           VALUES (2, 'Black Sabbath', 'Black Sabbath', 1, '2026-01-01')"""
    )
    con.execute("INSERT INTO song_styles (song_id, style) VALUES (1, 'Shoegaze')")
    con.execute("INSERT INTO song_styles (song_id, style) VALUES (2, 'Heavy Metal')")
    con.commit()
    con.close()

    resp = client.get("/songs?style=Shoegaze")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Airbag" in body
    assert "Black Sabbath" not in body
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_routes_music.py::test_browse_filters_by_style -v`
Expected: FAIL (Black Sabbath still in result)

- [ ] **Step 3: Update `browse` function in `pacer/routes/music.py`**

Replace the `browse` function with:

```python
@bp.route("/songs")
def browse():
    q     = (request.args.get("q") or "").strip()
    style = (request.args.get("style") or "").strip()
    sort  = request.args.get("sort", "top")
    db = get_db()
    params = []
    where_parts = []

    if q:
        where_parts.append("(s.title LIKE ? OR s.artist LIKE ? OR s.album LIKE ? OR s.genre LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])

    if style:
        where_parts.append("s.id IN (SELECT song_id FROM song_styles WHERE style = ?)")
        params.append(style)

    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    order = {
        "top":   "(COUNT(r.id) * 1.0 / (COUNT(r.id) + 3)) * COALESCE(AVG(r.stars), 0) + (3.0 / (COUNT(r.id) + 3)) * 3.0 DESC, rating_count DESC, s.id DESC",
        "new":   "s.id DESC",
        "hot":   "rating_count DESC, avg_stars DESC",
        "title": "s.title COLLATE NOCASE ASC",
    }.get(sort, "(COUNT(r.id) * 1.0 / (COUNT(r.id) + 3)) * COALESCE(AVG(r.stars), 0) + (3.0 / (COUNT(r.id) + 3)) * 3.0 DESC")

    rows = db.execute(f"""
        SELECT s.*, u.username AS submitter,
               COALESCE(AVG(r.stars), 0) AS avg_stars,
               COUNT(r.id) AS rating_count
        FROM songs s
        JOIN users u ON u.id = s.submitted_by
        LEFT JOIN ratings r ON r.song_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY {order}
        LIMIT 100
    """, params).fetchall()

    # Get available styles for the filter dropdown
    available_styles = [
        r["style"] for r in db.execute(
            "SELECT style, COUNT(*) as c FROM song_styles "
            "GROUP BY style ORDER BY c DESC LIMIT 50"
        ).fetchall()
    ]

    return render_template(
        "browse.html", songs=rows, q=q, sort=sort, style=style,
        available_styles=available_styles,
    )
```

- [ ] **Step 4: Update `templates/browse.html`**

Add a `style` select dropdown to the existing filter form. Find the `<form>` and add:

```html
<select name="style">
  <option value="">All styles</option>
  {% for s in available_styles %}
    <option value="{{ s }}" {% if style == s %}selected{% endif %}>{{ s }}</option>
  {% endfor %}
</select>
```

Also, if the template uses `genre` field on song rows, swap it to render styles instead. Replace any `{{ song.genre }}` reference with:

```html
{% set styles = namespace() %}
<span class="song-styles">
  {% for s in song_styles_for[song.id] or [] %}
    <a href="?style={{ s }}" class="chip">{{ s }}</a>
  {% endfor %}
</span>
```

(If the template currently shows nothing for genre, leave it. Style chips will appear via the song page instead.)

- [ ] **Step 5: Run test, verify it passes**

Run: `pytest tests/test_routes_music.py::test_browse_filters_by_style -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add pacer/routes/music.py templates/browse.html tests/test_routes_music.py
git commit -m "feat(browse): add ?style= filter using Discogs styles via song_styles"
```

---

### Task 4.2: Update `/spotify/search` to proxy through Discogs

**Files:**
- Modify: `pacer/routes/spotify.py` (`spotify_search` function)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_routes_music.py` (or create `tests/test_spotify_search.py`):

```python
def test_search_proxies_to_discogs_with_preview_badge(temp_db, client, monkeypatch):
    import pacer.db as db
    from pacer.services import discogs
    from pacer.services import spotify as spotify_svc

    # Pre-seed a user (so DB has a submitter for new songs)
    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "search_releases", lambda q, per_page=20, page=1: [
        {
            "discogs_id": 12345, "title": "Radiohead - OK Computer", "year": 1997,
            "country": "UK", "label": "Parlophone", "format": ["CD", "Album"],
            "thumb": "https://example.com/ok.jpg", "cover_image": "https://example.com/ok-large.jpg",
            "genre": ["Rock"], "style": ["Alternative Rock"], "uri": "", "resource_url": "",
        }
    ])
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 12345, "title": "OK Computer", "year": 1997, "country": "UK",
        "label": "Parlophone", "catalog_no": "X", "format": ["CD"],
        "genres": ["Rock"], "styles": ["Alternative Rock"],
        "tracklist": [{"position": "1", "title": "Airbag", "duration": "4:44", "artists": ["Radiohead"]}],
        "artists": ["Radiohead"], "master_id": 0, "master_url": "",
        "release_url": "", "cover_image": "", "thumb": "",
    })
    monkeypatch.setattr(spotify_svc, "lookup_spotify_preview",
                        lambda a, t: {"spotify_id": "sp-xyz",
                                      "preview_url": "https://preview.mp3",
                                      "spotify_url": "https://open.spotify.com/track/sp-xyz"})

    resp = client.get("/spotify/search?q=Radiohead")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["discogs_id"] == 12345
    assert item["title"] == "Radiohead - OK Computer"
    assert item["label"] == "Parlophone"
    assert item["has_preview"] is True
    assert item["spotify_id"] == "sp-xyz"


def test_search_returns_empty_when_query_missing(client):
    resp = client.get("/spotify/search")
    assert resp.status_code == 200
    assert resp.get_json() == {"items": []}


def test_search_returns_503_when_discogs_not_configured(client, monkeypatch):
    from pacer.services import discogs
    monkeypatch.setattr(discogs, "discogs_configured", lambda: False)
    resp = client.get("/spotify/search?q=anything")
    assert resp.status_code == 503
    assert "error" in resp.get_json()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_routes_music.py -v -k "search"`
Expected: FAIL (current Spotify search returns Spotify results, not Discogs)

- [ ] **Step 3: Update `spotify_search` in `pacer/routes/spotify.py`**

Replace the `spotify_search` function with:

```python
@bp.route("/spotify/search")
def spotify_search():
    """Music search: Discogs as primary source, Spotify preview as enrichment."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})
    if not discogs.discogs_configured():
        return jsonify({
            "error": "Search not configured. Set DISCOGS_CONSUMER_KEY and "
                     "DISCOGS_CONSUMER_SECRET environment variables."
        }), 503

    results = discogs.search_releases(q, per_page=12)
    enriched = []
    for r in results:
        # Parse "Artist - Album" from title
        title = r.get("title", "")
        if " - " in title:
            artist, _album = title.split(" - ", 1)
        else:
            artist, _album = title, ""

        # Fetch the release to get first track for preview lookup
        first_track_title = None
        if r.get("discogs_id"):
            release = discogs.get_release(r["discogs_id"])
            if release and release.get("tracklist"):
                first_track_title = release["tracklist"][0].get("title")

        # Lookup Spotify preview
        preview = None
        if first_track_title:
            preview = lookup_spotify_preview(artist, first_track_title)
        if not preview:
            preview = lookup_spotify_preview(artist, title)

        enriched.append({
            "discogs_id":   r["discogs_id"],
            "title":        r["title"],
            "year":         r.get("year"),
            "country":      r.get("country"),
            "label":        r.get("label"),
            "format":       r.get("format", []),
            "thumb":        r.get("thumb"),
            "style":        r.get("style", []),
            "has_preview":  bool(preview and preview.get("preview_url")),
            "spotify_id":   preview["spotify_id"] if preview else None,
        })
    return jsonify({"items": enriched})
```

Add the import at the top of `pacer/routes/spotify.py`:

```python
from pacer.services import discogs
from pacer.services.spotify import lookup_spotify_preview
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `pytest tests/test_routes_music.py -v -k "search"`
Expected: 3 tests pass

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add pacer/routes/spotify.py tests/test_routes_music.py
git commit -m "feat(search): proxy /spotify/search through Discogs with Spotify preview badges"
```

---

### Task 4.3: Update `search.html` to render Discogs results

**Files:**
- Modify: `templates/search.html`

- [ ] **Step 1: Read current `templates/search.html`**

Note the existing structure (likely a JS-driven search box that calls `/spotify/search` and renders results inline). The JSON shape changes from `{kind, id, name, artists, ...}` (Spotify) to `{discogs_id, title, label, year, thumb, has_preview, ...}` (Discogs).

- [ ] **Step 2: Update render logic in `search.html`**

Locate the JS that builds the result list. Replace the field references as follows (exact wording depends on current code; the pattern is the same):

**Before (Spotify result):**
```js
items.push(`
  <div class="result">
    <img src="${r.image_lg}" />
    <a href="/track/spotify/${r.id}">${r.name}</a>
    <p>${r.artists}</p>
  </div>
`);
```

**After (Discogs result):**
```js
items.push(`
  <div class="result">
    <img src="${r.thumb || ''}" />
    <a href="/album/spotify/${r.discogs_id}">${r.title}</a>
    <p>${r.label || ''} · ${r.year || ''} · ${(r.format || []).join(', ')}</p>
    ${r.has_preview ? `<button class="play-btn" data-spotify-id="${r.spotify_id}">▶ Play</button>` : ''}
  </div>
`);
```

> **Note:** The link target changes from `/track/spotify/<id>` (Spotify track) to `/album/spotify/<discogs_id>` (Discogs release). The route handler `album_from_spotify` in `pacer/routes/music.py` accepts a `spotify_id` parameter — in the new design, this parameter holds a Discogs ID. The handler should detect the prefix or use a different parameter name. To keep this task simple, alias the parameter: pass the Discogs ID as `spotify_id` and have `album_from_spotify` route handle both. For now, accept the alias and update the helper in Task 4.4.

- [ ] **Step 3: Verify search page loads**

Run: `python -c "from pacer import create_app; app = create_app(); c = app.test_client(); r = c.get('/search'); print(r.status_code); assert r.status_code == 200"`
Expected: `200`

- [ ] **Step 4: Commit**

```bash
git add templates/search.html
git commit -m "feat(search.html): render Discogs results with thumb, label, format, preview badge"
```

---

### Task 4.4: Update `track_from_spotify` and `album_from_spotify` to handle Discogs IDs

**Files:**
- Modify: `pacer/routes/music.py` (`track_from_spotify` and `album_from_spotify`)

- [ ] **Step 1: Update the routes to detect Discogs IDs**

Replace the two functions in `pacer/routes/music.py`:

```python
@bp.route("/track/spotify/<track_ref>")
def track_from_spotify(track_ref):
    """Resolve a track reference (Spotify ID or Discogs ID) to a local song page.

    The path is kept as /track/spotify/ for backward compatibility, but the
    value can now be a Discogs release ID (numeric). We detect by checking
    if the value is all-digits (Discogs) vs alphanumeric (Spotify).
    """
    if track_ref.isdigit():
        # Discogs ID
        if not discogs.discogs_configured():
            flash("Discogs not configured.", "warn")
            return redirect(url_for("feed.home"))
        release = discogs.get_release(int(track_ref))
        if not release or not release.get("tracklist"):
            flash("Couldn't find that track on Discogs.", "warn")
            return redirect(url_for("feed.home"))
        # Use first track to create the song
        first = release["tracklist"][0]
        artists = ", ".join(release.get("artists", []))
        song_id = _create_song_from_discogs_release(release, first, artists)
        if not song_id:
            flash("Couldn't create song record.", "warn")
            return redirect(url_for("feed.home"))
        return redirect(url_for("music.song_detail", song_id=song_id))

    # Spotify ID (legacy path)
    song_id = _find_or_create_song_from_spotify_legacy(track_ref)
    if not song_id:
        flash("Couldn't look up that track on Spotify.", "warn")
        return redirect(url_for("feed.home"))
    return redirect(url_for("music.song_detail", song_id=song_id))


@bp.route("/album/spotify/<album_ref>")
def album_from_spotify(album_ref):
    """Resolve an album reference (Spotify ID or Discogs ID) to a local album page."""
    if album_ref.isdigit():
        # Discogs ID
        if not discogs.discogs_configured():
            flash("Discogs not configured.", "warn")
            return redirect(url_for("feed.home"))
        album_id = _find_or_create_album_from_discogs(int(album_ref))
        if not album_id:
            flash("Couldn't look up that album on Discogs.", "warn")
            return redirect(url_for("feed.home"))
        return redirect(url_for("music.album_detail", album_id=album_id))

    # Spotify ID (legacy)
    album_id = _find_or_create_album_from_spotify_legacy(album_ref)
    if not album_id:
        flash("Couldn't look up that album on Spotify.", "warn")
        return redirect(url_for("feed.home"))
    return redirect(url_for("music.album_detail", album_id=album_id))
```

Add the two new helper functions at module level in `pacer/routes/music.py`:

```python
def _create_song_from_discogs_release(release: dict, track: dict, artists: str):
    """Create a songs row from a Discogs release + one of its tracks.

    Returns song_id or None.
    """
    db = get_db()

    # Try to lookup Spotify preview
    preview = lookup_spotify_preview(artists, track.get("title", ""))
    spotify_id = preview["spotify_id"] if preview else None
    preview_url = preview["preview_url"] if preview else None

    # Find existing song (by discogs_release_id + title)
    existing = db.execute(
        "SELECT id FROM songs WHERE discogs_release_id = ? AND title = ?",
        (release["id"], track.get("title", "")),
    ).fetchone()
    if existing:
        return existing["id"]

    # Need a submitter
    submitter = db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if not submitter:
        return None

    cur = db.execute(
        """INSERT INTO songs
           (title, artist, submitted_by, created_at,
            spotify_id, spotify_preview_url, spotify_image, spotify_url,
            discogs_release_id, discogs_master_id, position_in_release,
            discogs_artists)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (track.get("title", "")[:120], artists[:120],
         submitter["id"],
         _dt.utcnow().isoformat(timespec="seconds"),
         spotify_id, preview_url,
         release.get("cover_image"),
         f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None,
         release["id"], release.get("master_id"),
         track.get("position"), artists[:200]),
    )
    song_id = cur.lastrowid

    # Insert styles
    for s in release.get("styles", []):
        if s:
            db.execute(
                "INSERT OR IGNORE INTO song_styles (song_id, style) VALUES (?, ?)",
                (song_id, s),
            )
    db.commit()
    return song_id


def _find_or_create_album_from_discogs(discogs_id: int):
    """Look up album by Discogs ID; create if missing. Returns album_id or None."""
    db = get_db()
    existing = db.execute(
        "SELECT id FROM albums WHERE discogs_release_id = ?", (discogs_id,)
    ).fetchone()
    if existing:
        return existing["id"]
    release = discogs.get_release(discogs_id)
    if not release:
        return None
    artists = ", ".join(release.get("artists", []))
    cur = db.execute(
        """INSERT INTO albums
           (name, artist, year, created_at,
            spotify_id, discogs_release_id, discogs_master_id,
            label, format, country, catalog_no, release_url, master_url)
           VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (release.get("title", "")[:200], artists[:200],
         release.get("year"),
         _dt.utcnow().isoformat(timespec="seconds"),
         release["id"], release.get("master_id"),
         release.get("label"),
         ", ".join(release.get("format", [])),
         release.get("country"),
         release.get("catalog_no"),
         release.get("release_url"),
         release.get("master_url")),
    )
    album_id = cur.lastrowid
    for s in release.get("styles", []):
        if s:
            db.execute(
                "INSERT OR IGNORE INTO album_styles (album_id, style) VALUES (?, ?)",
                (album_id, s),
            )
    db.commit()
    return album_id


def _find_or_create_song_from_spotify_legacy(spotify_track_id: str):
    """Legacy path: create song from a raw Spotify track ID (no Discogs yet)."""
    if not spotify_configured():
        return None
    token = get_app_spotify_token()
    if not token:
        return None
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/tracks/{spotify_track_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    t = r.json()
    album = t.get("album") or {}
    images = album.get("images") or []
    db = get_db()
    submitter = db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if not submitter:
        return None
    cur = db.execute(
        """INSERT INTO songs
           (title, artist, album, year, submitted_by, created_at,
            spotify_id, spotify_url, spotify_image, spotify_preview_url)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (t.get("name", "")[:120],
         ", ".join(a["name"] for a in t.get("artists", []))[:120],
         (album.get("name") or "")[:120],
         int((album.get("release_date") or "0000")[:4] or 0) or None,
         submitter["id"],
         _dt.utcnow().isoformat(timespec="seconds"),
         t.get("id"),
         (t.get("external_urls") or {}).get("spotify"),
         images[0]["url"] if images else None,
         t.get("preview_url")),
    )
    db.commit()
    return cur.lastrowid


def _find_or_create_album_from_spotify_legacy(spotify_album_id: str):
    """Legacy path: create album from a raw Spotify album ID (no Discogs yet)."""
    if not spotify_configured():
        return None
    token = get_app_spotify_token()
    if not token:
        return None
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/albums/{spotify_album_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    a = r.json()
    images = a.get("images") or []
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO albums
               (name, artist, year, created_at, spotify_id, spotify_url, spotify_image)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ((a.get("name") or "")[:200],
             ", ".join(ar["name"] for ar in a.get("artists", []))[:200],
             int((a.get("release_date") or "0000")[:4] or 0) or None,
             _dt.utcnow().isoformat(timespec="seconds"),
             a.get("id"),
             (a.get("external_urls") or {}).get("spotify"),
             images[0]["url"] if images else None),
        )
        db.commit()
        return cur.lastrowid
    except Exception:
        return None
```

Add these imports at the top of `pacer/routes/music.py`:

```python
from pacer.services.spotify import spotify_configured, get_app_spotify_token
import requests
```

- [ ] **Step 2: Run full test suite**

Run: `pytest -v`
Expected: all tests pass

- [ ] **Step 3: Commit**

```bash
git add pacer/routes/music.py
git commit -m "feat(routes): support both Discogs IDs (numeric) and legacy Spotify IDs in /track/spotify and /album/spotify"
```

---

## Phase 5: Polish & Documentation

### Task 5.1: Add cache stats to admin dashboard

**Files:**
- Modify: `pacer/routes/admin.py` (`dashboard` function)
- Modify: `templates/admin/dashboard.html`

- [ ] **Step 1: Read current `dashboard` and `admin/dashboard.html`**

Current `dashboard` returns table list + row counts. We'll add cache stats.

- [ ] **Step 2: Update `dashboard` in `pacer/routes/admin.py`**

Replace the function with:

```python
@bp.route("/admin")
def dashboard():
    admin_required()
    db = get_db()
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    stats = {}
    for t in tables:
        name = t["name"]
        count = db.execute(f"SELECT COUNT(*) as c FROM [{name}]").fetchone()["c"]
        stats[name] = count

    # Discogs cache stats
    cache_stats = {}
    if "spotify_preview_cache" in stats:
        row = db.execute(
            "SELECT COUNT(*) as n, MIN(fetched_at) as oldest, MAX(fetched_at) as newest "
            "FROM spotify_preview_cache"
        ).fetchone()
        cache_stats["spotify_preview_cache"] = {
            "rows": row["n"],
            "oldest": row["oldest"],
            "newest": row["newest"],
        }
    if "artists" in stats:
        row = db.execute(
            "SELECT COUNT(*) as n, COUNT(discogs_id) as with_discogs "
            "FROM artists"
        ).fetchone()
        cache_stats["artists"] = {
            "rows": row["n"],
            "with_discogs_id": row["with_discogs"],
        }

    return render_template(
        "admin/dashboard.html",
        tables=tables, stats=stats, cache_stats=cache_stats,
    )
```

- [ ] **Step 3: Add cache stats section to `templates/admin/dashboard.html`**

Find the table that lists `tables` and `stats`, and add a new section after it:

```html
{% if cache_stats %}
<section class="admin-cache-stats">
  <h3>Cache Stats</h3>
  <dl>
    {% if cache_stats.spotify_preview_cache %}
    <dt>Spotify preview cache</dt>
    <dd>
      {{ cache_stats.spotify_preview_cache.rows }} rows ·
      oldest: {{ cache_stats.spotify_preview_cache.oldest or '—' }} ·
      newest: {{ cache_stats.spotify_preview_cache.newest or '—' }}
    </dd>
    {% endif %}
    {% if cache_stats.artists %}
    <dt>Artists with Discogs data</dt>
    <dd>
      {{ cache_stats.artists.with_discogs_id }} of {{ cache_stats.artists.rows }}
      ({{ "%.0f"|format(100 * cache_stats.artists.with_discogs_id / cache_stats.artists.rows) if cache_stats.artists.rows else 0 }}%)
    </dd>
    {% endif %}
  </dl>
</section>
{% endif %}
```

- [ ] **Step 4: Verify admin dashboard loads**

Run: `python -c "from pacer import create_app; app = create_app(); c = app.test_client(); c.post('/login', data={'username': 'tester', 'password': 'pw'})"` (this won't work without a seeded user; skip and just test that the route doesn't 500)

- [ ] **Step 5: Commit**

```bash
git add pacer/routes/admin.py templates/admin/dashboard.html
git commit -m "feat(admin): add cache stats panel (spotify_preview_cache + artists with discogs_id)"
```

---

### Task 5.2: Update README with new env vars and features

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current README**

Note current Spotify configuration section. We'll add a parallel Discogs section.

- [ ] **Step 2: Add Discogs section to README**

In `README.md`, after the existing "## Spotify configuration" section, add:

```markdown
## Discogs configuration

Discogs is the primary source for artist, album, and track metadata (genre, style, label, format, year, country). Pacer's "Catalog" panel on song and album pages, and the search box, all read from Discogs.

Without these vars, the Catalog panel is hidden and search returns a 503, but everything else (ratings, comments, forum, feed, playlist import) continues to work.

```bash
export DISCOGS_CONSUMER_KEY=xxx
export DISCOGS_CONSUMER_SECRET=xxx
# Optional: override User-Agent
# export DISCOGS_USER_AGENT="Pacer/1.0 (your-email@example.com)"
```

1. Sign in to <https://www.discogs.com>.
2. Go to <https://www.discogs.com/settings/developers>.
3. Click "Create an app" and fill in name (Pacer), description, URL.
4. Save. Discogs will issue a **Consumer Key** and **Consumer Secret**.
5. Copy them into the env vars above.
6. Restart the app.

**Rate limit:** 240 requests per minute authenticated. Pacer caches aggressively: artist data in-memory for 7 days, release/master data in-memory for 30 days, Spotify preview lookups in DB for 30 days.

**Setup details:** see `docs/discogs-setup.md`.

## Spotify configuration (unchanged)

Spotify is now used only for two things: 30-second audio preview URLs and the "Today's Top Hits" featured playlist that drives the homepage trending grid. (As of 2026-06-10, Spotify is no longer the primary data source for artist/album/track metadata — that role belongs to Discogs.)
```

Also add a new bullet to the "## Features" list, near the existing Spotify-related bullets:

```markdown
- **Discogs-powered catalog info** on song and album pages — label, format, year, country, catalog #, plus accurate style tags (e.g. "Shoegaze", "Dream Pop")
- **Browse by style** with a multi-select filter powered by Discogs (`/songs?style=Shoegaze`)
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document Discogs configuration alongside existing Spotify section"
```

---

### Task 5.3: Add `.env.example` file (optional but recommended)

**Files:**
- Create: `.env.example`

- [ ] **Step 1: Create `.env.example`**

Write `.env.example`:

```bash
# Pacer — copy this file to .env and fill in your keys

# Flask
PACER_SECRET=change-me-to-a-long-random-string

# Spotify (now used only for: 30s audio preview + Today's Top Hits trending)
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
# SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/spotify/callback
# SPOTIFY_TRENDING_PLAYLIST=37i9dQZF1DXcBWIGoYBM5M

# Discogs (primary data source for artist/album/track metadata)
DISCOGS_CONSUMER_KEY=
DISCOGS_CONSUMER_SECRET=
# DISCOGS_USER_AGENT="Pacer/1.0 +https://github.com/0xzhepyr/Pacer"

# Pinata (optional, for IPFS uploads of profile pics / post images)
# PINATA_API_KEY=
# PINATA_SECRET_KEY=
# PINATA_GATEWAY_URL=https://gateway.pinata.cloud/ipfs/

# Data directory (defaults to project root; set on Railway for persistence)
# DATA_DIR=/data
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs: add .env.example with all Pacer env vars (Spotify, Discogs, Pinata)"
```

---

### Task 5.4: Manual QA — end-to-end smoke test

This is a manual task, not a code task. Verify all user flows still work.

- [ ] **Step 1: Start the dev server**

Run: `python app.py` (or `python -m flask --app pacer run`)

Expected: server starts, no exceptions, prints `Running on http://127.0.0.1:5000`

- [ ] **Step 2: Visit homepage**

Open <http://127.0.0.1:5000/> in browser.

Expected:
- Home page loads (200)
- Trending grid renders 6 cards (or empty if Spotify not configured)
- Feed timeline renders below
- No exceptions in server logs

- [ ] **Step 3: Click a trending item**

Click any trending card. Expected:
- Redirects to `/songs/<id>`
- Song page loads
- Spotify 30s preview iframe is visible (if Spotify configured)
- "Catalog Info" panel appears with label/format/year/country (if Discogs configured AND match found)
- Style chips visible, clickable
- "Open on Discogs" link visible

- [ ] **Step 4: Search for an artist**

Visit <http://127.0.0.1:5000/search> (or click "Discover" in nav).

Expected:
- Search page loads
- Type "Radiohead" and submit
- Results show Discogs releases (cover art, label, format, year)
- Items with preview show "Play" button; items without show "no preview"

- [ ] **Step 5: Filter browse by style**

Visit <http://127.0.0.1:5000/songs?style=Shoegaze> (or any style your Discogs data has).

Expected:
- Browse page loads
- Only songs matching that style are shown
- Other songs hidden

- [ ] **Step 6: Visit an album page**

From a trending card, click through to album.

Expected:
- Album page loads with tracklist from Discogs
- "View on Discogs" link works
- Label/format/year/country visible

- [ ] **Step 7: Visit an artist page**

Click an artist name in a song page.

Expected:
- Artist page loads with bio (if Discogs has it)
- Members and aliases shown (if any)
- Community stats (avg rating) shown

- [ ] **Step 8: Stop Discogs (simulate failure)**

In `.env`, blank out `DISCOGS_CONSUMER_KEY` and `DISCOGS_CONSUMER_SECRET`. Restart server.

Expected:
- Song page still loads (Catalog panel hidden)
- Search returns 503 with helpful error
- No 500 errors anywhere

- [ ] **Step 9: Run full test suite one more time**

Run: `pytest -v`

Expected: all tests pass

- [ ] **Step 10: Commit any final fixes**

If you made fixes during QA:
```bash
git add -A
git commit -m "fix: post-QA cleanups from manual smoke test"
```

(No commit if nothing changed.)

---

## Final Cleanup

### Task 5.5: Remove unused `_album_tracks_cache` import if any

**Files:**
- Modify: `pacer/services/spotify.py` (if `_album_tracks_cache` is still declared and unused)

- [ ] **Step 1: Verify no callers of `_album_tracks_cache`**

Run:
```bash
grep -rn "_album_tracks_cache" pacer/ tests/
```

Expected: no matches (already removed in Task 2.2)

- [ ] **Step 2: If still present, remove the line**

In `pacer/services/spotify.py`, delete:
```python
_album_tracks_cache = {}   # if present
```

(Only do this if the grep above found references. If not, skip this task.)

- [ ] **Step 3: Commit (only if changed)**

```bash
git add pacer/services/spotify.py
git commit -m "chore: remove unused _album_tracks_cache"
```

---

### Task 5.6: Update CLAUDE.md / AGENTS.md (if present)

**Files:**
- Possibly modify: `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/*.mdc` (if these exist)

- [ ] **Step 1: Check for AI guidance files**

Run:
```bash
ls CLAUDE.md AGENTS.md .cursor/ 2>/dev/null
```

- [ ] **Step 2: If present, add a note about Discogs-first design**

In whichever file is present, add a brief note:

```markdown
## Data sources (as of 2026-06-10)

- **Discogs** is the primary source for artist, album, and track metadata (genre, style, label, format, year, country).
- **Spotify** is used only for: 30-second audio preview URLs (per-track lookup) and the "Today's Top Hits" featured playlist that drives the homepage trending grid.
- See `docs/superpowers/specs/2026-06-10-discogs-first-data-layer-design.md` for the full design.
```

- [ ] **Step 3: Commit (only if changed)**

```bash
git add CLAUDE.md AGENTS.md .cursor/
git commit -m "docs: add note about Discogs-first data layer to AI guidance files"
```

---

### Task 5.7: Add CSS for new class names (3 themes)

**Files:**
- Modify: `static/style.css` (or the per-theme CSS files, depending on current organization)

- [ ] **Step 1: Read current CSS structure**

Run:
```bash
ls static/*.css
```

Confirm whether Pacer uses a single `style.css` with `body.theme-*` rules, or three separate files (`style.modern.css`, `style.win98.css`, `style.clean.css`).

- [ ] **Step 2: Add the new class rules**

Append CSS rules for `.catalog-panel`, `.style-chips`, `.chip`, `.filter-bar`, `.ext-link`, `.album-catalog`, `.tracklist`, `.artist-bio`, `.spotify-embed` at the end of the file(s) used.

For a single-file `style.css` with theme rules, append inside each `body.theme-*` block:

```css
/* All themes: catalog panel */
.catalog-panel {
  background: var(--panel-bg, rgba(0,0,0,0.04));
  border: 1px solid var(--border, #ccc);
  border-radius: 6px;
  padding: 12px 16px;
  margin: 16px 0;
}
.catalog-panel h3 { margin-top: 0; }
.catalog-panel dl { display: grid; grid-template-columns: max-content 1fr; gap: 4px 12px; }
.catalog-panel dt { font-weight: 600; opacity: 0.7; }
.catalog-panel dd { margin: 0; }

.style-chips {
  display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0;
}
.chip {
  display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: 0.85em; text-decoration: none;
  background: var(--chip-bg, #e0e0e0);
  color: var(--chip-fg, #222);
  border: 1px solid var(--chip-border, #b0b0b0);
}
.chip:hover { filter: brightness(0.95); }

.filter-bar {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  margin: 12px 0;
}
.filter-bar input, .filter-bar select { font: inherit; }

.ext-link { color: var(--link, #06c); text-decoration: none; }
.ext-link:hover { text-decoration: underline; }

.album-catalog { margin: 16px 0; }
.tracklist { list-style: none; padding: 0; }
.tracklist li {
  display: flex; gap: 12px; align-items: baseline;
  padding: 4px 0;
  border-bottom: 1px solid var(--border, #eee);
}
.tracklist .pos { font-weight: 600; opacity: 0.5; min-width: 2em; }
.tracklist .title { flex: 1; }
.tracklist .duration { opacity: 0.6; font-variant-numeric: tabular-nums; }

.artist-bio { margin: 16px 0; line-height: 1.5; }
.artist-bio .realname { font-style: italic; opacity: 0.8; }
.artist-bio .profile-text { white-space: pre-line; }

.spotify-embed { margin: 16px 0; }
.spotify-embed iframe { display: block; max-width: 100%; }
```

For per-theme files, replicate the rules in each, adjusting colors per theme (e.g. Win98 uses `borderstyle: outset`, Modern uses rounded corners, Clean uses minimal styling).

- [ ] **Step 3: Verify CSS loads without errors**

Open any page in the browser. Open DevTools → Console. Expected: no 404s for CSS.

- [ ] **Step 4: Verify chip styling per theme**

In the browser, switch between themes (Modern / Win98 / Clean) using the theme switcher. Verify chips look different per theme (rounded in Modern, inset/outset in Win98, minimal in Clean).

- [ ] **Step 5: Commit**

```bash
git add static/style.css
git commit -m "feat(css): add catalog-panel, style-chips, chip, filter-bar, tracklist rules for all themes"
```

---

## Done

All 5 phases complete. The Pacer codebase now has:

- Discogs as the primary data source for artist, album, and track metadata
- Spotify retained for audio previews and trending only
- Backward-compatible schema (3 new tables + 14 new columns)
- 4-phase additive migration (no breaking changes for existing users)
- Graceful degradation when Discogs is down or unconfigured
- 30+ new unit and integration tests
- Updated documentation (README, .env.example, docs/discogs-setup.md)

Next steps (out of scope for this plan):
- User OAuth Discogs (wantlist, collection sync)
- Master release picker (let users choose which pressing)
- Discogs marketplace integration
