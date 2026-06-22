# Phase 2: Artist Pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add artist pages with data from Spotify API — artist info, top tracks, discography, and community ratings.

**Architecture:** New `artists` table, new routes in `pacer/routes/music.py`, new template `artist.html`, extend Spotify service with artist-related functions. Link existing song/album pages to artist pages.

**Tech Stack:** Flask, SQLite, Spotify API, Jinja2, HTMX (minimal for this phase).

**Prerequisite:** Phase 1 (Architecture Refactor) must be complete.

---

## File Structure

```
pacer/
├── db.py                    (MODIFY - add artists table to SCHEMA, add migrations)
├── services/
│   └── spotify.py           (MODIFY - add artist fetch functions)
├── routes/
│   └── music.py             (MODIFY - add artist routes)
├── templates/
│   └── artist.html          (NEW - artist detail page)
├── static/
│   └── style.css            (MODIFY - add artist page styles)
```

---

## Task 1: Add artists table to database schema

**Files:**
- Modify: `pacer/db.py`

- [ ] **Step 1: Add CREATE TABLE artists to SCHEMA string**

Add after the `thread_replies` table in the SCHEMA string:

```sql
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    image_url TEXT,
    genres TEXT,
    popularity INTEGER,
    spotify_url TEXT,
    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 2: Add artist_id migration to init_db()**

Add migration for `songs.artist_id` and `albums.artist_id`:

```python
# In init_db(), after existing migrations:
song_cols = {r[1] for r in db.execute("PRAGMA table_info(songs)").fetchall()}
if "artist_id" not in song_cols:
    db.execute("ALTER TABLE songs ADD COLUMN artist_id INTEGER REFERENCES artists(id)")

album_cols = {r[1] for r in db.execute("PRAGMA table_info(albums)").fetchall()}
if "artist_id" not in album_cols:
    db.execute("ALTER TABLE albums ADD COLUMN artist_id INTEGER REFERENCES artists(id)")
```

- [ ] **Step 3: Run app to verify schema creates without error**

```bash
python run.py
```

Expected: App starts, no SQL errors.

- [ ] **Step 4: Commit**

```bash
git add pacer/db.py
git commit -m "feat(artist): add artists table and artist_id columns"
```

---

## Task 2: Add Spotify artist service functions

**Files:**
- Modify: `pacer/services/spotify.py`

- [ ] **Step 1: Add fetch_artist function**

```python
def fetch_artist(spotify_artist_id):
    """Fetch artist info from Spotify API. Returns dict or None."""
    token = get_app_spotify_token()
    if not token:
        return None
    resp = requests.get(
        f"https://api.spotify.com/v1/artists/{spotify_artist_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    return {
        "spotify_id": data["id"],
        "name": data["name"],
        "image_url": data["images"][0]["url"] if data.get("images") else None,
        "genres": ", ".join(data.get("genres", [])),
        "popularity": data.get("popularity"),
        "spotify_url": data["external_urls"].get("spotify", ""),
    }
```

- [ ] **Step 2: Add fetch_artist_top_tracks function**

```python
def fetch_artist_top_tracks(spotify_artist_id, market="US"):
    """Fetch artist's top tracks from Spotify. Returns list of track dicts."""
    token = get_app_spotify_token()
    if not token:
        return []
    resp = requests.get(
        f"https://api.spotify.com/v1/artists/{spotify_artist_id}/top-tracks",
        headers={"Authorization": f"Bearer {token}"},
        params={"market": market},
    )
    if resp.status_code != 200:
        return []
    tracks = []
    for t in resp.json().get("tracks", [])[:10]:
        tracks.append({
            "spotify_id": t["id"],
            "name": t["name"],
            "album_name": t["album"]["name"] if t.get("album") else "",
            "album_image": t["album"]["images"][0]["url"] if t.get("album", {}).get("images") else None,
            "duration_ms": t.get("duration_ms", 0),
            "preview_url": t.get("preview_url"),
            "spotify_url": t["external_urls"].get("spotify", ""),
        })
    return tracks
```

- [ ] **Step 3: Add fetch_artist_albums function**

```python
def fetch_artist_albums(spotify_artist_id, limit=50):
    """Fetch artist's albums from Spotify. Returns list of album dicts."""
    token = get_app_spotify_token()
    if not token:
        return []
    resp = requests.get(
        f"https://api.spotify.com/v1/artists/{spotify_artist_id}/albums",
        headers={"Authorization": f"Bearer {token}"},
        params={"include_groups": "album,single", "limit": limit, "market": "US"},
    )
    if resp.status_code != 200:
        return []
    albums = []
    for a in resp.json().get("items", []):
        albums.append({
            "spotify_id": a["id"],
            "name": a["name"],
            "release_date": a.get("release_date", ""),
            "image_url": a["images"][0]["url"] if a.get("images") else None,
            "total_tracks": a.get("total_tracks", 0),
            "album_type": a.get("album_type", "album"),
            "spotify_url": a["external_urls"].get("spotify", ""),
        })
    # Sort by release date descending
    albums.sort(key=lambda x: x["release_date"], reverse=True)
    return albums
```

- [ ] **Step 4: Add find_or_create_artist function**

```python
_artist_cache = {}

def find_or_create_artist(spotify_artist_id):
    """Find artist in DB or create from Spotify. Returns artist row or None."""
    from pacer.db import get_db
    db = get_db()

    # Check DB first
    artist = db.execute(
        "SELECT * FROM artists WHERE spotify_id = ?", (spotify_artist_id,)
    ).fetchone()

    if artist:
        # Check if cache is stale (older than 24 hours)
        from datetime import datetime, timedelta
        cached = datetime.fromisoformat(artist["cached_at"]) if artist["cached_at"] else None
        if cached and (datetime.now() - cached) < timedelta(hours=24):
            return artist

    # Fetch from Spotify
    data = fetch_artist(spotify_artist_id)
    if not data:
        return artist  # Return stale data if fetch fails

    if artist:
        # Update existing
        db.execute("""
            UPDATE artists SET name=?, image_url=?, genres=?, popularity=?, spotify_url=?, cached_at=CURRENT_TIMESTAMP
            WHERE spotify_id=?
        """, (data["name"], data["image_url"], data["genres"], data["popularity"], data["spotify_url"], spotify_artist_id))
    else:
        # Insert new
        db.execute("""
            INSERT INTO artists (spotify_id, name, image_url, genres, popularity, spotify_url)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (data["spotify_id"], data["name"], data["image_url"], data["genres"], data["popularity"], data["spotify_url"]))
    db.commit()

    return db.execute(
        "SELECT * FROM artists WHERE spotify_id = ?", (spotify_artist_id,)
    ).fetchone()
```

- [ ] **Step 5: Commit**

```bash
git add pacer/services/spotify.py
git commit -m "feat(artist): add Spotify artist service functions"
```

---

## Task 3: Add artist routes

**Files:**
- Modify: `pacer/routes/music.py`

- [ ] **Step 1: Add artist detail route**

```python
@bp.route("/artists/<int:artist_id>")
def artist_detail(artist_id):
    db = get_db()
    artist = db.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if not artist:
        abort(404)

    # Fetch top tracks and albums from Spotify (cached via find_or_create)
    from pacer.services.spotify import fetch_artist_top_tracks, fetch_artist_albums
    top_tracks = fetch_artist_top_tracks(artist["spotify_id"])
    albums = fetch_artist_albums(artist["spotify_id"])

    # Community stats: average rating across all songs/albums by this artist
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

    return render_template("artist.html",
        artist=artist,
        top_tracks=top_tracks,
        albums=albums,
        avg_song_rating=avg_song_rating,
        avg_album_rating=avg_album_rating,
    )
```

- [ ] **Step 2: Add auto-import artist route**

```python
@bp.route("/artist/spotify/<spotify_id>")
def artist_from_spotify(spotify_id):
    from pacer.services.spotify import find_or_create_artist
    artist = find_or_create_artist(spotify_id)
    if not artist:
        flash("Could not load artist from Spotify")
        return redirect(url_for("feed.home"))
    return redirect(url_for("music.artist_detail", artist_id=artist["id"]))
```

- [ ] **Step 3: Commit**

```bash
git add pacer/routes/music.py
git commit -m "feat(artist): add artist detail and auto-import routes"
```

---

## Task 4: Create artist template

**Files:**
- Create: `templates/artist.html`

- [ ] **Step 1: Create artist.html**

```html
{% extends "base.html" %}
{% block title %}{{ artist["name"] }} — Pacer{% endblock %}
{% block content %}
<div class="win-panel artist-page">
  <div class="artist-header">
    {% if artist["image_url"] %}
    <img src="{{ artist['image_url'] }}" alt="{{ artist['name'] }}" class="artist-photo">
    {% endif %}
    <div class="artist-info">
      <h1>{{ artist["name"] }}</h1>
      {% if artist["genres"] %}
      <div class="genre-tags">
        {% for genre in artist["genres"].split(", ") %}
        <span class="genre-tag">{{ genre }}</span>
        {% endfor %}
      </div>
      {% endif %}
      {% if artist["spotify_url"] %}
      <a href="{{ artist['spotify_url'] }}" target="_blank" class="spotify-link">Open in Spotify</a>
      {% endif %}
    </div>
  </div>

  <!-- Community Ratings -->
  <div class="win-panel">
    <div class="panel-title">Community Ratings</div>
    <div class="artist-stats">
      {% if avg_song_rating and avg_song_rating["total_ratings"] %}
      <div class="stat">
        <span class="stat-label">Songs:</span>
        <span class="stat-value">{{ avg_song_rating["avg_stars"]|score10 }}</span>
        <span class="stat-count">({{ avg_song_rating["total_ratings"] }} ratings)</span>
      </div>
      {% endif %}
      {% if avg_album_rating and avg_album_rating["total_ratings"] %}
      <div class="stat">
        <span class="stat-label">Albums:</span>
        <span class="stat-value">{{ avg_album_rating["avg_stars"]|score10 }}</span>
        <span class="stat-count">({{ avg_album_rating["total_ratings"] }} ratings)</span>
      </div>
      {% endif %}
    </div>
  </div>

  <!-- Top Tracks -->
  {% if top_tracks %}
  <div class="win-panel">
    <div class="panel-title">Top Tracks</div>
    <ol class="top-tracks-list">
      {% for track in top_tracks %}
      <li>
        <a href="{{ url_for('music.track_from_spotify', spotify_id=track['spotify_id']) }}">
          {{ track["name"] }}
        </a>
        <span class="track-album">{{ track["album_name"] }}</span>
      </li>
      {% endfor %}
    </ol>
  </div>
  {% endif %}

  <!-- Discography -->
  {% if albums %}
  <div class="win-panel">
    <div class="panel-title">Discography</div>
    <div class="album-grid">
      {% for album in albums %}
      <a href="{{ url_for('music.album_from_spotify', spotify_id=album['spotify_id']) }}" class="album-card">
        {% if album["image_url"] %}
        <img src="{{ album['image_url'] }}" alt="{{ album['name'] }}">
        {% endif %}
        <div class="album-card-name">{{ album["name"] }}</div>
        <div class="album-card-year">{{ album["release_date"][:4] }}</div>
      </a>
      {% endfor %}
    </div>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add templates/artist.html
git commit -m "feat(artist): add artist detail template"
```

---

## Task 5: Link artist from song and album pages

**Files:**
- Modify: `templates/song.html`
- Modify: `templates/album.html`

- [ ] **Step 1: Update song.html — make artist name a link**

Find the artist name display in `song.html` and wrap it:

```html
<a href="{{ url_for('music.artist_from_spotify', spotify_id=song['spotify_artist_id']) }}">{{ song["artist"] }}</a>
```

Note: This requires `spotify_artist_id` to be available. We need to store it when importing songs.

- [ ] **Step 2: Add spotify_artist_id to songs table migration**

In `pacer/db.py`, add migration:

```python
if "spotify_artist_id" not in song_cols:
    db.execute("ALTER TABLE songs ADD COLUMN spotify_artist_id TEXT")
```

- [ ] **Step 3: Update _find_or_create_song_from_spotify to store artist ID**

In `pacer/services/spotify.py`, when creating a song from Spotify, also store the artist's Spotify ID from the track data (`track["artists"][0]["id"]`).

- [ ] **Step 4: Update album.html similarly**

Add artist link in album template.

- [ ] **Step 5: Commit**

```bash
git add pacer/db.py pacer/services/spotify.py templates/song.html templates/album.html
git commit -m "feat(artist): link artist from song and album pages"
```

---

## Task 6: Add artist page CSS

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: Add artist page styles**

```css
/* Artist Page */
.artist-page { max-width: 800px; margin: 0 auto; }
.artist-header { display: flex; gap: 20px; align-items: flex-start; margin-bottom: 16px; }
.artist-photo { width: 200px; height: 200px; object-fit: cover; border: 2px solid #000; }
.artist-info h1 { margin: 0 0 8px; }
.genre-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.genre-tag { background: #c0c0c0; border: 1px solid #808080; padding: 2px 8px; font-size: 12px; }
.spotify-link { color: #1DB954; text-decoration: underline; }
.artist-stats { display: flex; gap: 24px; }
.stat-label { font-weight: bold; }
.stat-value { color: #c00; font-family: monospace; }
.stat-count { color: #666; font-size: 12px; }
.top-tracks-list { padding-left: 20px; }
.top-tracks-list li { margin-bottom: 6px; }
.track-album { color: #666; font-size: 12px; margin-left: 8px; }
.album-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; }
.album-card { text-align: center; text-decoration: none; color: inherit; }
.album-card img { width: 100%; aspect-ratio: 1; object-fit: cover; border: 2px solid #000; }
.album-card-name { font-size: 12px; font-weight: bold; margin-top: 4px; }
.album-card-year { font-size: 11px; color: #666; }
```

- [ ] **Step 2: Commit**

```bash
git add static/style.css
git commit -m "feat(artist): add artist page styles"
```

---

## Task 7: Verify artist pages end-to-end

- [ ] **Step 1: Run the app**

```bash
python run.py
```

- [ ] **Step 2: Test artist auto-import**

Visit `/artist/spotify/06HL4z0CvFAxyc27GXpf02` (Spotify ID for Taylor Swift or any known artist).

Expected: Artist page loads with name, image, genres, top tracks, discography.

- [ ] **Step 3: Test linking from song page**

Click on a song that was imported from Spotify, verify artist name links to artist page.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "feat(artist): complete artist pages implementation"
```
