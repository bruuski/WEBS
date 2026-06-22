# Pacer — Discogs-First Data Layer (Spotify for Preview & Trending) — Design Spec

**Date:** 2026-06-10
**Status:** Approved
**Stack:** Flask + Blueprints, SQLite, Discogs API (OAuth 1.0a), Spotify Web API (slim, client credentials), HTMX, Pinata/IPFS

---

## Overview

Mengganti **lapisan data utama** Pacer (artist, album, track metadata, genre/style, label, format) dari **Spotify ke Discogs**. Spotify tetap digunakan hanya untuk **dua hal**: 30-detik audio preview URL dan featured playlist "Today's Top Hits" untuk trending. Pacer menjadi "Discogs-native" dalam hal katalog musik — lebih kaya untuk diskusi (genre/style presisi, label, format, country, master release) — tapi tetap playful dengan audio preview Spotify dan UI Win98 modern/clean yang sudah ada.

Motivasi:

- Data metadata lebih kaya (Discogs punya style/genre presisi, label, format, country, multiple pressings)
- Mengurangi ketergantungan pada approval Spotify & rate-limit yang lebih ketat untuk app baru

---

## 1. Goals & Scope

### In-Scope

1. **Service baru** `pacer/services/discogs.py` — OAuth 1.0a signed requests, dengan caching in-memory (artist 7d, release/master 30d)
2. **Service revisi** `pacer/services/spotify.py` — dipersempit hanya untuk: trending fetch, `lookup_spotify_preview(artist, title)` (cache 30d di DB), app token, `fetch_spotify_playlist` (untuk import)
3. **Schema migration** di `pacer/db.py` — 3 tabel baru (`song_styles`, `album_styles`, `spotify_preview_cache`) + 14 ALTER TABLE
4. **Routes** yang terdampak: `music.browse`, `music.song_detail`, `music.album_detail`, `music.artist_detail`, `music.track_from_spotify`, `music.album_from_spotify`, `spotify_bp.search`
5. **Search** berubah: input dari `database/search` Discogs, audio preview di-fetch per-track dari Spotify
6. **Filter style** di browse → filter by Discogs `styles` (multi-value via `song_styles`)
7. **Tombol** "Open on Discogs" di song & album page

### Out-of-Scope (iterasi berikut)

- User OAuth Discogs (wantlist, collection sync, marketplace)
- Audio preview selain 30-detik Spotify snippet
- Trending dari sumber lain (Billboard, Last.fm, dll)
- Perubahan mini-player logic
- Perubahan import playlist (tetap Spotify)

### Kriteria Sukses

- Halaman song menampilkan data Discogs (artist profile, styles, label, format, year, country) untuk semua song yang punya match
- Audio preview (30-detik Spotify embed) tetap jalan untuk ≥95% song yang punya preview
- Search box menggunakan Discogs sebagai primary source dengan preview badge per-track
- Trending grid di homepage masih render dengan preview play
- Filter `?style=Shoegaze` di `/songs` mengembalikan hanya song dengan tag style tersebut
- Graceful degradation: kalau Discogs down/429, song page tetap load (panel sembunyi, no error)
- Existing demo accounts & seeded songs tetap jalan (backfill Discogs ID on first access — lazy)
- Zero regression di forum/blog/feed/auth/admin

---

## 2. Arsitektur

### Diagram

```
┌──────────────────────────────────────────────────────────┐
│ Browser (HTMX-boosted navigation, 3-theme CSS)           │
└──────────┬───────────────────────────────────────────────┘
           ▼
┌──────────────────────────────────────────────────────────┐
│ Flask App Factory (pacer/__init__.py)                    │
│   7 blueprints: auth | profile | music | feed | blog | spotify | admin
└─────┬─────────────┬─────────────┬───────────────┬────────┘
      ▼             ▼             ▼               ▼
┌──────────┐ ┌──────────┐ ┌──────────┐  ┌────────────────┐
│ music.py │ │ profile  │ │ feed.py  │  │ spotify_bp.py  │
│ browse   │ │ profile  │ │ timeline │  │ search (proxy  │
│ song/    │ │ playlists│ │ posts    │  │ ke discogs)    │
│ album/   │ │ uploads  │ │          │  │ connect (uauth)│
│ artist   │ │          │ │          │  │                │
└────┬─────┘ └────┬─────┘ └────┬─────┘  └────┬───────────┘
     │            │            │              │
     ▼            ▼            ▼              ▼
┌─────────────────────────────────────────────────────┐
│ SERVICES LAYER (business logic)                     │
│                                                     │
│  ┌─────────────────┐      ┌────────────────────┐   │
│  │ services/spotify│      │ services/discogs   │   │
│  │  (SLIM)         │      │  (BARU, primary)   │   │
│  │                 │      │                    │   │
│  │ • fetch_        │      │ • search_releases  │   │
│  │   trending      │      │ • search_artists   │   │
│  │ • lookup_       │◄─────┤ • get_release      │   │
│  │   spotify_      │ get  │ • get_master       │   │
│  │   preview       │pre-  │ • get_artist       │   │
│  │ • get_app_      │ view │ • find_release     │   │
│  │   token         │ URL  │   _by_artist_title │   │
│  │ • fetch_        │      │                    │   │
│  │   spotify_      │      │ (OAuth 1.0a signed │   │
│  │   playlist      │      │  requests)         │   │
│  └─────────────────┘      └────────────────────┘   │
│                                                     │
│  ┌──────────────┐  ┌────────────┐                   │
│  │ services/    │  │ services/  │                   │
│  │ pinata       │  │ feed       │                   │
│  └──────────────┘  └────────────┘                   │
└─────────────────────────┬───────────────────────────┘
                          ▼
        ┌────────────────────────────────────┐
        │ SQLite (pacer.db)                  │
        │  + new tables:                     │
        │    song_styles (M2M)               │
        │    album_styles (M2M)              │
        │    spotify_preview_cache           │
        │  + new columns (14 ALTER TABLE)    │
        └────────────────────────────────────┘
```

### Layer Changes

| Layer | Status |
|---|---|
| `pacer/routes/feed.py` (X-style feed) | Stabil |
| `pacer/routes/blog.py` | Stabil |
| `pacer/routes/auth.py` | Stabil |
| `pacer/routes/admin.py` | Stabil (reflect schema otomatis) |
| `pacer/routes/profile.py` | Stabil (playlist import tetap pakai Spotify 2-step) |
| `pacer/routes/music.py` | **Berubah signifikan** |
| `pacer/routes/spotify.py` | **Berubah** (search jadi proxy ke Discogs) |
| `pacer/services/spotify.py` | **Diperkecil (slim)** |
| `pacer/services/discogs.py` | **BARU** |
| `pacer/db.py` | **Schema migration** |
| `pacer/seed.py` | Berubah minimal (demo songs backfill on first access) |
| Templates (song, album, artist, browse, search) | **Berubah** |
| `templates/base.html`, `home.html`, `static/player.js` | Stabil |

### Alur Data — Tiap Use Case

**Homepage trending:**

```
feed.home() →
  fetch_spotify_trending(limit=12)                   # Spotify
  → tiap item: find_or_create_song_from_spotify
      - if exists: return id
      - else: lookup Discogs by title+artist → upsert artist + release
              set songs.discogs_release_id
              if no Discogs match: simpan song tanpa metadata
  → render home.html
```

**User search:**

```
spotify_bp.search() →
  discogs.search_releases(q, per_page=12)             # Discogs primary
  → tiap release: spotify.lookup_spotify_preview(artist, title)  # cached
                  if no preview: tampilkan tanpa play button
  → return JSON
```

**Song page:**

```
music.song_detail(song_id) →
  song = SELECT * FROM songs WHERE id = ?
  if song.discogs_release_id:
    release = discogs.get_release(song.discogs_release_id, cache)  # 30d
  if song.artist_id:
    artist = discogs.get_artist(song.artist.discogs_id, cache)    # 7d
  preview_embed = f"https://open.spotify.com/embed/track/{song['spotify_id']}"
  → render song.html dengan "Catalog" panel (graceful: sembunyi kalau data None)
```

**Browse by genre:**

```
music.browse(?style=Shoegaze) →
  JOIN songs × song_styles WHERE style = ?
  ORDER BY Wilson-score rating
  → render browse.html dengan style chip filter
```

### Caching Strategy

| Tipe data | TTL | Lokasi |
|---|---|---|
| Discogs artist (profile, members, URLs) | 7 hari | in-memory dict `_artist_cache` |
| Discogs release (label, format, tracklist) | 30 hari | in-memory dict `_release_cache` |
| Discogs master (variants) | 30 hari | in-memory dict `_master_cache` |
| Spotify preview URL (artist+title → spotify_id+preview) | 30 hari | DB `spotify_preview_cache` |
| Spotify trending playlist | 10 menit | in-memory |
| Spotify app token | 1 jam | in-memory |

### Failure Modes

- **Discogs 401/403** → log warning, song page tampilkan tanpa panel
- **Discogs 429** → backoff, return None, fall back ke cache
- **Discogs timeout (8s)** → return None, gak error
- **Spotify down** → trending empty, search kasih pesan "Trending not available"
- **Discogs returns 0** → song page tetap load, search kasih "No results"

---

## 3. Data Model

### Prinsip

- **Backward-compat**: Semua kolom baru nullable atau dengan default. Existing `pacer.db` dari versi lama tidak perlu di-reset
- **Dual-ID**: Song & album punya `spotify_id` (untuk preview) DAN `discogs_release_id` (untuk metadata). Keduanya nullable
- **Multi-style**: Genre di Discogs multi-value ("Shoegaze", "Dream Pop"). Tabel M2M supaya query `WHERE style = ?` efisien
- **Migration order**: CREATE TABLE baru dulu, ALTER TABLE existing di akhir (atomic per `init_db()`)

### Tabel Baru

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

### ALTER TABLE — Kolom Baru

```sql
-- artists: keep spotify_id legacy, add Discogs primary
ALTER TABLE artists ADD COLUMN discogs_id INTEGER UNIQUE;
ALTER TABLE artists ADD COLUMN real_name TEXT;
ALTER TABLE artists ADD COLUMN profile_text TEXT;
ALTER TABLE artists ADD COLUMN aliases TEXT;
ALTER TABLE artists ADD COLUMN members TEXT;
ALTER TABLE artists ADD COLUMN urls TEXT;
ALTER TABLE artists ADD COLUMN namevariations TEXT;

-- songs: keep spotify_id for preview, add Discogs
ALTER TABLE songs ADD COLUMN discogs_release_id INTEGER;
ALTER TABLE songs ADD COLUMN discogs_master_id  INTEGER;
ALTER TABLE songs ADD COLUMN position_in_release INTEGER;
ALTER TABLE songs ADD COLUMN duration_ms INTEGER;
ALTER TABLE songs ADD COLUMN discogs_artists    TEXT;

-- albums: full Discogs takeover
ALTER TABLE albums ADD COLUMN discogs_release_id INTEGER UNIQUE;
ALTER TABLE albums ADD COLUMN discogs_master_id  INTEGER;
ALTER TABLE albums ADD COLUMN label             TEXT;
ALTER TABLE albums ADD COLUMN format            TEXT;
ALTER TABLE albums ADD COLUMN country           TEXT;
ALTER TABLE albums ADD COLUMN catalog_no        TEXT;
ALTER TABLE albums ADD COLUMN release_url       TEXT;
ALTER TABLE albums ADD COLUMN master_url        TEXT;
```

### Catatan

- `songs.genre` lama (string tunggal) di-deprecate — diabaikan di UI baru, sumber kebenaran pindah ke `song_styles`
- `artists.spotify_id` lama tetap dipakai (backward compat untuk legacy queries)
- `albums.artist_id` lama (FK ke `artists.id`) tetap, di-backfill saat upgrade
- Backfill **tidak** dilakukan di `init_db()` — dilakukan lazy on-demand saat user akses song/album page

### Final Relasi

```
users ─┬─ ratings ── songs ─┬─ song_styles
       │                   ├─ playlist_tracks ── playlists
       │                   └─ activities / posts
       ├─ comments ── users (wall)
       ├─ bulletins
       ├─ pinned_songs ── songs
       ├─ albums ─┬─ album_ratings
       │         ├─ album_styles
       └─ artists ─┬─ songs (artist_id)
                  └─ albums (artist_id)

spotify_preview_cache (lookup table, no FK)
threads ── thread_replies
```

---

## 4. Service Layer

### 4.1 `pacer/services/discogs.py` (BARU)

Module-level cache + OAuth 1.0a client. Tanggung jawab:

- Search releases, masters, artists
- Get detail: artist, release, master
- High-level: find_release_by_artist_title(artist, title) — heuristic match

Struktur internal:

```python
import os, time, requests
from requests_oauthlib import OAuth1Session
from pacer.config import DB_PATH

CONSUMER_KEY    = os.environ.get("DISCOGS_CONSUMER_KEY", "")
CONSUMER_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")
USER_AGENT      = os.environ.get("DISCOGS_USER_AGENT", "Pacer/1.0 +https://github.com/0xzhepyr/Pacer")
BASE_URL        = "https://api.discogs.com"

ARTIST_TTL  = 7 * 24 * 3600
RELEASE_TTL = 30 * 24 * 3600

_artist_cache:  dict[int, tuple[dict, float]]  = {}
_release_cache: dict[int, tuple[dict, float]]  = {}
_master_cache:  dict[int, tuple[dict, float]]  = {}

def discogs_configured() -> bool: ...
def _oauth() -> OAuth1Session: ...
def _request(path, params=None) -> dict | None:
    # Signed GET, User-Agent, timeout=8
    # Handle 429 (return None), 4xx/5xx (return None), exception (return None)

def search_releases(query, per_page=20, page=1) -> list[dict]:
    # Returns list of normalized dicts:
    # {discogs_id, title, year, country, label, format, thumb, cover_image,
    #  genre, style, uri, resource_url}

def search_masters(query, per_page=20) -> list[dict]: ...
def search_artists(query, per_page=20) -> list[dict]: ...

def get_artist(discogs_id) -> dict | None:
    # 7d in-memory cache
    # Returns: {id, name, real_name, profile, urls, aliases, members,
    #           name_variations, images, discogs_url}

def get_release(release_id) -> dict | None:
    # 30d in-memory cache
    # Returns: {id, title, year, country, label, catalog_no, format,
    #           genres, styles, tracklist[], artists, master_id,
    #           master_url, release_url, cover_image, thumb}

def get_master(master_id) -> dict | None:
    # 30d in-memory cache
    # Returns: {id, title, year, main_release, artists, genres, styles,
    #           tracklist[], discogs_url}

def find_release_by_artist_title(artist, title) -> dict | None:
    # High-level: search + heuristic match
    # Prefer result whose title contains BOTH artist AND title substrings

def find_artist_by_name(name) -> dict | None:
    # First result from search_artists
```

### 4.2 `pacer/services/spotify.py` (SLIM REVISI)

Yang **dipertahankan**:

- `spotify_configured()`
- `get_app_spotify_token()` (Client Credentials)
- `fetch_spotify_trending(limit=12)` (Trending playlist, gak berubah)
- `fetch_spotify_playlist(playlist_id_or_url)` (untuk import playlist — 2-step flow yang baru)
- `refresh_user_spotify_token(user_id)` (untuk "Connect Spotify" OAuth)
- Module-level cache `_trending_cache`, `_app_token`, `_album_tracks_cache`

Yang **BARU**:

```python
def lookup_spotify_preview(artist: str, title: str) -> dict | None:
    """Find Spotify track by artist+title. Cached for 30 days.

    Returns dict {spotify_id, preview_url, spotify_url} or None.
    Negative results (no match) are also cached to avoid re-querying.
    """
    # 1. cek spotify_preview_cache (artist|title)
    # 2. jika miss, fetch dari Spotify /v1/search?type=track
    # 3. cache result (positive OR negative)
    # 4. return {spotify_id, preview_url, spotify_url} or None
```

Yang **DIHAPUS** (dipindah ke logika Discogs-first di music.py):

- `_spotify_lookup_track`
- `_find_or_create_song_from_spotify`
- `_find_or_create_album_from_spotify`
- `_fetch_album_tracks`
- `find_or_create_artist`
- `fetch_artist`
- `fetch_artist_top_tracks`
- `fetch_artist_albums`

### 4.3 High-level Helper untuk music.py

```python
# Taruh inline di music.py atau di pacer/services/discogs_lookup.py

def find_or_create_song_from_spotify(spotify_meta: dict) -> dict:
    """Given a Spotify trending result, persist a songs row with
    both spotify_id and (when possible) discogs_release_id.
    """
    # 1. cek DB by spotify_id → return if exists
    # 2. lookup Discogs by title+artist via discogs.find_release_by_artist_title
    # 3. jika ada: get_release → upsert artist + release
    # 4. jika gak ada: simpan song tanpa Discogs metadata (panel sembunyi)
    # 5. cache preview via spotify.lookup_spotify_preview
```

### 4.4 Dependency Baru

```
Flask==3.0.3
requests>=2.31
python-dotenv>=1.0.0
gunicorn>=22.0.0
requests-oauthlib>=1.3.1   # BARU (untuk OAuth 1.0a signed requests)
```

OAuth 1.0a server-to-server **tidak butuh user redirect** — cukup consumer key/secret. `requests-oauthlib` cukup, gak perlu Flask-Dance.

---

## 5. Routes & UI

### 5.1 `pacer/routes/music.py` (REVISI SIGNIFIKAN)

```python
@bp.route("/songs/<int:song_id>")
def song_detail(song_id):
    song = db.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not song:
        abort(404)

    # Discogs enrichment (graceful: None kalau gak ada / Discogs down)
    catalog = None
    if song["discogs_release_id"]:
        catalog = discogs.get_release(song["discogs_release_id"])
    artist_info = None
    if song["artist_id"]:
        artist_info = _safe_discogs_artist_for(song["artist_id"])

    # Spotify preview embed
    preview_embed = None
    if song["spotify_id"]:
        preview_embed = f"https://open.spotify.com/embed/track/{song['spotify_id']}"

    # ... ratings, histogram, reviews, my_rating (sama seperti sebelumnya)

    return render_template(
        "song.html", song=song, catalog=catalog, artist_info=artist_info,
        preview_embed=preview_embed, ...
    )
```

`album_detail` dan `artist_detail` mengikuti pola yang sama.

### 5.2 `pacer/routes/spotify.py` — SEARCH BERUBAH

```python
@bp.route("/spotify/search")
def search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})
    if not discogs.discogs_configured():
        return jsonify({"error": "Search not configured. Set DISCOGS_* env vars."}), 503

    results = discogs.search_releases(q, per_page=12)
    enriched = []
    for r in results:
        # Title = "Artist - Album"; parse untuk lookup preview per-artist
        artist, _album = _parse_discogs_title(r["title"])
        # Untuk preview, kita coba lookup 1 track pertama dari release
        release = discogs.get_release(r["discogs_id"])
        first_track = (release or {}).get("tracklist", [{}])[0].get("title")
        preview = spotify.lookup_spotify_preview(artist, first_track or r["title"])
        enriched.append({
            "discogs_id":   r["discogs_id"],
            "title":        r["title"],
            "year":         r["year"],
            "country":      r["country"],
            "label":        r["label"],
            "format":       r["format"],
            "thumb":        r["thumb"],
            "has_preview":  bool(preview and preview.get("preview_url")),
            "spotify_id":   preview["spotify_id"] if preview else None,
        })
    return jsonify({"items": enriched})
```

### 5.3 Template Changes

**`templates/song.html` — tambahan "Catalog" panel:**

```html
{% if catalog %}
<aside class="catalog-panel">
  <h3>Catalog Info</h3>
  <dl>
    <dt>Label</dt><dd>{{ catalog.label or '—' }}</dd>
    <dt>Format</dt><dd>{{ catalog.format|join(', ') or '—' }}</dd>
    <dt>Year</dt><dd>{{ catalog.year or '—' }}</dd>
    <dt>Country</dt><dd>{{ catalog.country or '—' }}</dd>
    <dt>Catalog #</dt><dd>{{ catalog.catalog_no or '—' }}</dd>
  </dl>

  <h4>Style</h4>
  <div class="style-chips">
    {% for s in catalog.styles %}
      <a href="{{ url_for('music.browse') }}?style={{ s }}" class="chip">{{ s }}</a>
    {% endfor %}
  </div>

  {% if catalog.release_url %}
  <a href="{{ catalog.release_url }}" target="_blank" rel="noopener" class="ext-link">
    Open on Discogs ↗
  </a>
  {% endif %}
</aside>
{% endif %}
```

**`templates/album.html` — tracklist dari Discogs:**

```html
{% if catalog %}
<section class="album-catalog">
  <h3>Tracklist</h3>
  <ol>
    {% for track in catalog.tracklist %}
    <li>
      <span class="pos">{{ track.position }}</span>
      <span class="title">{{ track.title }}</span>
      <span class="duration">{{ track.duration or '' }}</span>
    </li>
    {% endfor %}
  </ol>
  <p>Label: {{ catalog.label }} · Format: {{ catalog.format|join(', ') }} · {{ catalog.year }} · {{ catalog.country }}</p>
  <a href="{{ catalog.release_url }}" target="_blank" rel="noopener">View on Discogs ↗</a>
</section>
{% endif %}
```

**`templates/artist.html` — bio & profile:**

```html
{% if artist.real_name %}<p class="realname">aka {{ artist.real_name }}</p>{% endif %}
{% if artist.profile %}<div class="profile-text">{{ artist.profile }}</div>{% endif %}
{% if artist.members %}<p>Members: {{ artist.members|join(', ') }}</p>{% endif %}
{% if artist.aliases %}<p>Also known as: {{ artist.aliases|join(', ') }}</p>{% endif %}
```

**`templates/browse.html` — filter by style:**

```html
<form method="GET" class="filter-bar">
  <input type="text" name="q" placeholder="Search…" value="{{ q }}">
  <select name="style">
    <option value="">All styles</option>
    {% for s in available_styles %}
      <option value="{{ s }}" {% if style == s %}selected{% endif %}>{{ s }}</option>
    {% endfor %}
  </select>
  <select name="sort">…</select>
  <button>Filter</button>
</form>
```

**`templates/search.html`** — UI gak banyak berubah, items sekarang punya `thumb` (Discogs) + `format` + `year` + `has_preview` boolean

### 5.4 CSS

Class names baru: `.catalog-panel`, `.style-chips`, `.chip`, `.filter-bar`, `.ext-link`. Ditambah ke `static/style.css` untuk tiap theme (Modern / Win98 / Clean) — chip styling beda per theme via `body.theme-*` rule.

### 5.5 Yang Tidak Berubah

- `pacer/routes/auth.py`, `feed.py`, `blog.py`, `admin.py`
- `pacer/routes/profile.py` (playlist import tetap Spotify 2-step)
- `templates/base.html`, `home.html`
- `static/player.js`

---

## 6. Error Handling, Testing & Rollout

### 6.1 Error Handling

| Skenario | Perilaku | Fallback |
|---|---|---|
| Discogs env vars not set | `discogs_configured()` returns False | Song page: panel sembunyi. Search: 503 dengan pesan. Admin hint. |
| Discogs 401 (key invalid) | Log error, return None | Panel sembunyi |
| Discogs 429 (rate limit) | Return None, log | Pakai cache in-memory. Kalau cache miss → panel sembunyi |
| Discogs 5xx | Return None | Panel sembunyi |
| Discogs timeout (8s) | Return None | Panel sembunyi |
| Discogs no match | `find_release_by_artist_title` returns None | Song page tetap load, panel sembunyi |
| Spotify not configured | Trending empty, preview kosong | Tampilan tetap load, tanpa audio |
| Spotify 401 (token expired) | `get_app_spotify_token()` returns None | Trending cache lama dipakai sampai expired |
| Cache miss + API down | Both None | Panel sembunyi. User tidak melihat error. |
| DB migration gagal | Exception di `init_db()` | `run.py` crash dengan stack trace (gak silent) |

### 6.2 Observability

- Log semua Discogs call ke stdout dengan prefix `[discogs]`: status code, path, latency
- Log Spotify call yang gagal: `[spotify]`
- Admin dashboard: tambah panel "Cache stats" (jumlah `spotify_preview_cache` rows, `artists.cached_at` age distribution)

### 6.3 Testing Strategy (TDD)

**Unit tests (`tests/test_discogs_service.py`):**

- `test_search_releases_with_mocked_response` — mock `_request`, verify normalize
- `test_get_artist_uses_cache` — call 2x, second call tidak hit network
- `test_get_release_uses_cache` — sama
- `test_rate_limit_returns_none` — mock 429, verify returns None (no exception)
- `test_unconfigured_returns_none` — kosongkan env, verify False
- `test_find_release_prefers_exact_match` — kasih 2 results, verify exact match dipilih

**Unit tests (`tests/test_spotify_service_slim.py`):**

- `test_lookup_preview_cache_hit` — pre-populate `spotify_preview_cache`, verify no API call
- `test_lookup_preview_cache_miss_fetches` — empty cache, mock Spotify, verify cache write
- `test_lookup_preview_negative_caches` — Spotify returns no items, verify cache row inserted (NULL spotify_id)
- `test_lookup_preview_no_artist_returns_none` — defensive
- `test_fetch_spotify_trending_unchanged` — regression

**Integration tests (`tests/test_routes_music.py`):**

- `test_song_detail_with_discogs_metadata` — seed song with `discogs_release_id`, mock Discogs, verify panel rendered
- `test_song_detail_without_discogs_metadata` — song without release_id, verify panel sembunyi
- `test_browse_filter_by_style` — seed songs dengan `song_styles`, query `?style=Shoegaze`, verify only matching
- `test_artist_detail_with_bio` — seed artist with discogs_id, verify bio rendered
- `test_album_detail_with_tracklist` — seed album with tracklist, verify rendered

**E2E / Manual:**

- Run dev server, login, buka homepage, klik trending → song page → "Catalog" panel muncul dengan data Discogs
- Search "Radiohead" → results dari Discogs, klik → song page
- Filter browse `?style=Shoegaze` → list filter
- Stop Discogs (mock 503) → song page tetap load tanpa panel
- Trending tanpa Spotify config → homepage trending grid empty tapi gak error

### 6.4 Rollout Strategy (5 Phase)

```
Phase 1: Foundation (1-2 hari)
  - Tambah requests-oauthlib ke requirements
  - Schema migration di db.py (3 tabel baru + 14 ALTER TABLE)
  - pacer/services/discogs.py (basic client)
  - Environment variable documentation di README
  ✓ Verifikasi: db upgrade dari versi lama tanpa error, schema baru ada

Phase 2: Slim Spotify (0.5 hari)
  - Hapus fungsi lama dari pacer/services/spotify.py
  - Tambah lookup_spotify_preview
  ✓ Verifikasi: trending tetap jalan, semua existing test pass

Phase 3: Music routes migration (2-3 hari)
  - Update music.py: song_detail, album_detail, artist_detail pakai Discogs
  - Tambah find_or_create_song_from_discogs helper
  - Update templates: song.html, album.html, artist.html
  ✓ Verifikasi: song page punya Catalog panel, data akurat

Phase 4: Search & browse (1 hari)
  - Update spotify_bp.search() pakai Discogs
  - Update music.browse() filter by style
  - Update templates: search.html, browse.html
  ✓ Verifikasi: search dari Discogs, filter genre jalan

Phase 5: Polish & docs (0.5-1 hari)
  - Admin: cache stats panel
  - README update (env vars, fitur baru)
  - Logging
  - Manual QA semua flow
  ✓ Verifikasi: end-to-end manual test
```

### 6.5 Migration Path

- Database lama **otomatis ter-upgrade** via `init_db()` additive migrations. Tidak perlu script manual.
- `songs.genre` lama (string) di-deprecate, gak dipakai UI. Optional one-time: `INSERT INTO song_styles SELECT id, genre FROM songs WHERE genre IS NOT NULL`
- Existing demo seed songs: `discogs_release_id` NULL sampai user pertama kali akses (lazy backfill)
- Backfill eager (opsional): script `python -m pacer.cli backfill_discogs` (kalau ada)

### 6.6 Deprecation Notes

- `pacer.services.spotify._find_or_create_song_from_spotify` — **DEPRECATED**, akan dihapus di fase 3
- `songs.genre` (TEXT) — **DEPRECATED**, sumber kebenaran pindah ke `song_styles`

### 6.7 Dokumentasi

- Update `README.md` — env vars baru + fitur "Catalog" panel
- Tambah `docs/discogs-setup.md` — cara daftar app di Discogs (https://www.discogs.com/settings/developers), get consumer key/secret, rate limit notes
- Spec ini di-commit ke `docs/superpowers/specs/2026-06-10-discogs-first-data-layer-design.md`

### 6.8 Out-of-Scope (eksplisit, untuk iterasi berikut)

- User OAuth Discogs (wantlist, collection sync, marketplace)
- Import vinyl collection dari Discogs user account
- Discogs-style "master release" picker (pilih pressing)
- Multiple artist credits per track (saat ini 1 artist_id per song)
- Sales/marketplace integration
- Discogs images sebagai primary cover (sekarang pakai Spotify image untuk trending)

---

## Environment Variables (New)

```
DISCOGS_CONSUMER_KEY=xxx
DISCOGS_CONSUMER_SECRET=xxx
DISCOGS_USER_AGENT="Pacer/1.0 +https://github.com/0xzhepyr/Pacer"   # default
```

Daftar di https://www.discogs.com/settings/developers. Tanpa env vars, `discogs_configured()` returns False dan semua fitur Discogs nonaktif (graceful degradation).

---

## Implementation Order (ringkas)

1. **Foundation** — schema migration, `services/discogs.py`, env var docs
2. **Slim Spotify** — `lookup_spotify_preview`, hapus fungsi lama
3. **Music routes** — song/album/artist detail pakai Discogs
4. **Search & browse** — `?style=` filter, search via Discogs
5. **Polish & docs** — admin cache stats, README, manual QA
