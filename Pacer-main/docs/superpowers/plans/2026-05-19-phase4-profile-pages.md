# Phase 4: Personalizable Profile Pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend user profiles with custom profile picture and background (uploaded via Pinata/IPFS), status message, pinned songs, and user-created playlists.

**Architecture:** New Pinata service module for IPFS uploads, extend users table with new columns, new tables for playlists and pinned songs, updated profile template with richer layout, extended edit form.

**Tech Stack:** Flask, SQLite, Pinata API (IPFS), Jinja2, CSS.

**Prerequisite:** Phases 1-3 must be complete.

---

## File Structure

```
pacer/
├── db.py                    (MODIFY - add playlists, playlist_tracks, pinned_songs tables + user columns)
├── services/
│   └── pinata.py            (NEW - Pinata/IPFS upload service)
├── routes/
│   └── profile.py           (MODIFY - add upload, playlist, pin routes)
├── templates/
│   ├── profile.html         (MODIFY - new layout with sections)
│   ├── edit_profile.html    (MODIFY - add upload fields, status, background picker)
│   └── playlist.html        (NEW - playlist detail page)
├── static/
│   └── style.css            (MODIFY - profile page styles, background presets)
```

---

## Task 1: Add new tables and columns to database

**Files:**
- Modify: `pacer/db.py`

- [ ] **Step 1: Add new tables to SCHEMA**

Add after existing tables:

```sql
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER NOT NULL REFERENCES playlists(id),
    song_id INTEGER NOT NULL REFERENCES songs(id),
    position INTEGER NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(playlist_id, song_id)
);

CREATE TABLE IF NOT EXISTS pinned_songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    song_id INTEGER NOT NULL REFERENCES songs(id),
    position INTEGER NOT NULL,
    UNIQUE(user_id, song_id)
);
```

- [ ] **Step 2: Add user column migrations in init_db()**

```python
user_cols = {r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()}
for col, typedef in [
    ("profile_pic_cid", "TEXT"),
    ("background_cid", "TEXT"),
    ("background_preset", "TEXT"),
    ("status_message", "TEXT DEFAULT ''"),
]:
    if col not in user_cols:
        db.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")
```

- [ ] **Step 3: Run app to verify**

```bash
python run.py
```

Expected: No errors, new tables created.

- [ ] **Step 4: Commit**

```bash
git add pacer/db.py
git commit -m "feat(profile): add playlists, pinned_songs tables and user profile columns"
```

---

## Task 2: Create Pinata service

**Files:**
- Create: `pacer/services/pinata.py`

- [ ] **Step 1: Create pinata.py**

```python
import os
import requests

PINATA_API_KEY = os.environ.get("PINATA_API_KEY", "")
PINATA_SECRET_KEY = os.environ.get("PINATA_SECRET_KEY", "")
PINATA_GATEWAY_URL = os.environ.get("PINATA_GATEWAY_URL", "https://gateway.pinata.cloud/ipfs/")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


def pinata_configured():
    return bool(PINATA_API_KEY and PINATA_SECRET_KEY)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_to_pinata(file_storage, filename=None):
    """
    Upload a file to Pinata/IPFS.
    
    Args:
        file_storage: werkzeug FileStorage object from request.files
        filename: optional override filename
    
    Returns:
        CID string on success, None on failure
    """
    if not pinata_configured():
        return None

    if not filename:
        filename = file_storage.filename

    if not allowed_file(filename):
        return None

    # Check file size
    file_storage.seek(0, 2)  # Seek to end
    size = file_storage.tell()
    file_storage.seek(0)  # Reset to beginning

    if size > MAX_FILE_SIZE:
        return None

    try:
        resp = requests.post(
            "https://api.pinata.cloud/pinning/pinFileToIPFS",
            files={"file": (filename, file_storage, file_storage.content_type)},
            headers={
                "pinata_api_key": PINATA_API_KEY,
                "pinata_secret_api_key": PINATA_SECRET_KEY,
            },
        )
        if resp.status_code == 200:
            return resp.json().get("IpfsHash")
        return None
    except requests.RequestException:
        return None


def get_ipfs_url(cid):
    """Get the full gateway URL for a CID."""
    if not cid:
        return None
    return f"{PINATA_GATEWAY_URL}{cid}"
```

- [ ] **Step 2: Commit**

```bash
git add pacer/services/pinata.py
git commit -m "feat(profile): add Pinata/IPFS upload service"
```

---

## Task 3: Add profile upload and management routes

**Files:**
- Modify: `pacer/routes/profile.py`

- [ ] **Step 1: Add upload route**

```python
@bp.route("/profile/upload", methods=["POST"])
@login_required
def upload_file():
    from pacer.services.pinata import upload_to_pinata, pinata_configured
    
    if not pinata_configured():
        flash("File upload not configured")
        return redirect(url_for("profile.edit_profile"))

    user = current_user()
    db = get_db()
    upload_type = request.form.get("upload_type")  # "profile_pic" or "background"

    if "file" not in request.files:
        flash("No file selected")
        return redirect(url_for("profile.edit_profile"))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected")
        return redirect(url_for("profile.edit_profile"))

    cid = upload_to_pinata(file)
    if not cid:
        flash("Upload failed. Check file type (jpg/png/gif/webp) and size (max 5MB).")
        return redirect(url_for("profile.edit_profile"))

    if upload_type == "profile_pic":
        db.execute("UPDATE users SET profile_pic_cid = ? WHERE id = ?", (cid, user["id"]))
    elif upload_type == "background":
        db.execute("UPDATE users SET background_cid = ?, background_preset = NULL WHERE id = ?", (cid, user["id"]))
    
    db.commit()
    flash("Upload successful!")
    return redirect(url_for("profile.edit_profile"))
```

- [ ] **Step 2: Add pin/unpin song routes**

```python
@bp.route("/profile/pin/<int:song_id>", methods=["POST"])
@login_required
def pin_song(song_id):
    user = current_user()
    db = get_db()
    
    # Check song exists
    song = db.execute("SELECT id FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not song:
        abort(404)
    
    # Get next position
    max_pos = db.execute(
        "SELECT MAX(position) as mp FROM pinned_songs WHERE user_id = ?", (user["id"],)
    ).fetchone()
    next_pos = (max_pos["mp"] or 0) + 1
    
    # Max 6 pinned songs
    count = db.execute(
        "SELECT COUNT(*) as c FROM pinned_songs WHERE user_id = ?", (user["id"],)
    ).fetchone()
    if count["c"] >= 6:
        flash("Maximum 6 pinned songs")
        return redirect(request.referrer or url_for("feed.home"))
    
    db.execute(
        "INSERT OR IGNORE INTO pinned_songs (user_id, song_id, position) VALUES (?, ?, ?)",
        (user["id"], song_id, next_pos)
    )
    db.commit()
    flash("Song pinned!")
    return redirect(request.referrer or url_for("feed.home"))


@bp.route("/profile/unpin/<int:song_id>", methods=["POST"])
@login_required
def unpin_song(song_id):
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM pinned_songs WHERE user_id = ? AND song_id = ?", (user["id"], song_id))
    db.commit()
    flash("Song unpinned")
    return redirect(request.referrer or url_for("feed.home"))
```

- [ ] **Step 3: Add playlist CRUD routes**

```python
@bp.route("/profile/playlists/new", methods=["GET", "POST"])
@login_required
def new_playlist():
    user = current_user()
    if request.method == "GET":
        return render_template("playlist_new.html")
    
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    
    if not name:
        flash("Playlist name required")
        return redirect(url_for("profile.new_playlist"))
    
    db = get_db()
    cur = db.execute(
        "INSERT INTO playlists (user_id, name, description) VALUES (?, ?, ?)",
        (user["id"], name, description)
    )
    db.commit()
    return redirect(url_for("profile.view_playlist", playlist_id=cur.lastrowid))


@bp.route("/profile/playlists/<int:playlist_id>")
def view_playlist(playlist_id):
    db = get_db()
    playlist = db.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,)).fetchone()
    if not playlist:
        abort(404)
    
    tracks = db.execute("""
        SELECT s.*, pt.position FROM playlist_tracks pt
        JOIN songs s ON pt.song_id = s.id
        WHERE pt.playlist_id = ?
        ORDER BY pt.position
    """, (playlist_id,)).fetchall()
    
    owner = db.execute("SELECT * FROM users WHERE id = ?", (playlist["user_id"],)).fetchone()
    
    return render_template("playlist.html", playlist=playlist, tracks=tracks, owner=owner)


@bp.route("/profile/playlists/<int:playlist_id>/add", methods=["POST"])
@login_required
def add_to_playlist(playlist_id):
    user = current_user()
    db = get_db()
    
    playlist = db.execute(
        "SELECT * FROM playlists WHERE id = ? AND user_id = ?", (playlist_id, user["id"])
    ).fetchone()
    if not playlist:
        abort(403)
    
    song_id = request.form.get("song_id", type=int)
    if not song_id:
        flash("No song specified")
        return redirect(request.referrer or url_for("feed.home"))
    
    max_pos = db.execute(
        "SELECT MAX(position) as mp FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)
    ).fetchone()
    next_pos = (max_pos["mp"] or 0) + 1
    
    db.execute(
        "INSERT OR IGNORE INTO playlist_tracks (playlist_id, song_id, position) VALUES (?, ?, ?)",
        (playlist_id, song_id, next_pos)
    )
    db.commit()
    flash("Song added to playlist")
    return redirect(request.referrer or url_for("profile.view_playlist", playlist_id=playlist_id))


@bp.route("/profile/playlists/<int:playlist_id>/remove", methods=["POST"])
@login_required
def remove_from_playlist(playlist_id):
    user = current_user()
    db = get_db()
    
    playlist = db.execute(
        "SELECT * FROM playlists WHERE id = ? AND user_id = ?", (playlist_id, user["id"])
    ).fetchone()
    if not playlist:
        abort(403)
    
    song_id = request.form.get("song_id", type=int)
    db.execute(
        "DELETE FROM playlist_tracks WHERE playlist_id = ? AND song_id = ?", (playlist_id, song_id)
    )
    db.commit()
    flash("Song removed from playlist")
    return redirect(url_for("profile.view_playlist", playlist_id=playlist_id))
```

- [ ] **Step 4: Update edit_profile route to handle new fields**

Add to existing edit_profile POST handler:

```python
# In edit_profile POST:
status_message = request.form.get("status_message", "").strip()
background_preset = request.form.get("background_preset", "").strip()

db.execute("""
    UPDATE users SET status_message = ?, background_preset = ?
    WHERE id = ?
""", (status_message, background_preset if background_preset else None, user["id"]))

# If preset is chosen, clear custom background
if background_preset:
    db.execute("UPDATE users SET background_cid = NULL WHERE id = ?", (user["id"],))
```

- [ ] **Step 5: Commit**

```bash
git add pacer/routes/profile.py
git commit -m "feat(profile): add upload, pin, playlist routes"
```

---

## Task 4: Update profile template

**Files:**
- Modify: `templates/profile.html`

- [ ] **Step 1: Rewrite profile.html with new layout**

```html
{% extends "base.html" %}
{% block title %}{{ profile_user["display_name"] or profile_user["username"] }} — Pacer{% endblock %}
{% block content %}
{% set bg_url = ipfs_url(profile_user["background_cid"]) if profile_user["background_cid"] else None %}
<div class="profile-page {{ profile_user['background_preset'] or profile_user['theme'] or 'sky' }}"
     {% if bg_url %}style="background-image: url('{{ bg_url }}'); background-size: cover;"{% endif %}>

  <!-- Header -->
  <div class="profile-header">
    <div class="profile-pic-wrapper">
      {% if profile_user["profile_pic_cid"] %}
      <img src="{{ ipfs_url(profile_user['profile_pic_cid']) }}" alt="Profile" class="profile-pic">
      {% else %}
      <div class="profile-pic-emoji">{{ profile_user["avatar_emoji"] or "🎧" }}</div>
      {% endif %}
    </div>
    <div class="profile-meta">
      <h1>{{ profile_user["display_name"] or profile_user["username"] }}</h1>
      <div class="profile-username">@{{ profile_user["username"] }}</div>
      {% if profile_user["status_message"] %}
      <div class="profile-status">"{{ profile_user["status_message"] }}"</div>
      {% endif %}
    </div>
  </div>

  <!-- About -->
  <div class="win-panel">
    <div class="panel-title">About</div>
    {% if profile_user["headline"] %}<p class="profile-headline">{{ profile_user["headline"] }}</p>{% endif %}
    {% if profile_user["about_me"] %}<p>{{ profile_user["about_me"] }}</p>{% endif %}
    {% if profile_user["fav_bands"] %}<p><strong>Fav bands:</strong> {{ profile_user["fav_bands"] }}</p>{% endif %}
    {% if profile_user["location"] %}<p><strong>Location:</strong> {{ profile_user["location"] }}</p>{% endif %}
    {% if profile_user["age"] %}<p><strong>Age:</strong> {{ profile_user["age"] }}</p>{% endif %}
  </div>

  <!-- Pinned Songs -->
  {% if pinned_songs %}
  <div class="win-panel">
    <div class="panel-title">Pinned Songs</div>
    <div class="pinned-songs-grid">
      {% for song in pinned_songs %}
      <a href="{{ url_for('music.song_detail', song_id=song['id']) }}" class="pinned-song-card">
        {% if song["spotify_image"] %}
        <img src="{{ song['spotify_image'] }}" alt="{{ song['title'] }}">
        {% endif %}
        <div class="pinned-song-title">{{ song["title"] }}</div>
        <div class="pinned-song-artist">{{ song["artist"] }}</div>
      </a>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  <!-- Playlists -->
  {% if playlists %}
  <div class="win-panel">
    <div class="panel-title">Playlists</div>
    {% for pl in playlists %}
    <a href="{{ url_for('profile.view_playlist', playlist_id=pl['id']) }}" class="playlist-link">
      {{ pl["name"] }} ({{ pl["track_count"] }} tracks)
    </a>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Recent Reviews -->
  {% if recent_reviews %}
  <div class="win-panel">
    <div class="panel-title">Recent Reviews</div>
    {% for review in recent_reviews %}
    <div class="review-item">
      <a href="{{ url_for('music.song_detail', song_id=review['song_id']) }}">{{ review["title"] }}</a>
      — {{ review["stars"]|stars }} 
      {% if review["review"] %}<span class="review-text">"{{ review["review"][:80] }}"</span>{% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Wall Comments -->
  <div class="win-panel">
    <div class="panel-title">Wall</div>
    {% if current_user %}
    <form method="POST">
      <textarea name="body" placeholder="Write on {{ profile_user['display_name'] or profile_user['username'] }}'s wall..." rows="2"></textarea>
      <button type="submit" class="btn">Post</button>
    </form>
    {% endif %}
    {% for comment in comments %}
    <div class="wall-comment">
      <a href="{{ url_for('profile.profile', username=comment['author_username']) }}">{{ comment["author_name"] }}</a>:
      {{ comment["body"] }}
      <span class="comment-date">{{ comment["created_at"]|datefmt }}</span>
    </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Update profile route to pass new data**

In `routes/profile.py`, update the profile GET handler to query pinned songs, playlists, and recent reviews:

```python
# Pinned songs
pinned_songs = db.execute("""
    SELECT s.* FROM pinned_songs ps
    JOIN songs s ON ps.song_id = s.id
    WHERE ps.user_id = ?
    ORDER BY ps.position
""", (profile_user["id"],)).fetchall()

# Playlists with track count
playlists = db.execute("""
    SELECT p.*, COUNT(pt.id) as track_count
    FROM playlists p
    LEFT JOIN playlist_tracks pt ON p.id = pt.playlist_id
    WHERE p.user_id = ?
    GROUP BY p.id
    ORDER BY p.created_at DESC
""", (profile_user["id"],)).fetchall()

# Recent reviews
recent_reviews = db.execute("""
    SELECT r.*, s.title, s.artist FROM ratings r
    JOIN songs s ON r.song_id = s.id
    WHERE r.user_id = ?
    ORDER BY r.created_at DESC LIMIT 5
""", (profile_user["id"],)).fetchall()
```

- [ ] **Step 3: Register ipfs_url as template helper**

In `pacer/helpers.py`, add:

```python
from pacer.services.pinata import get_ipfs_url

def register_template_utils(app):
    # ... existing filters ...
    app.jinja_env.globals["ipfs_url"] = get_ipfs_url
```

- [ ] **Step 4: Commit**

```bash
git add templates/profile.html pacer/routes/profile.py pacer/helpers.py
git commit -m "feat(profile): update profile template with new sections"
```

---

## Task 5: Update edit profile template

**Files:**
- Modify: `templates/edit_profile.html`

- [ ] **Step 1: Extend edit form with new fields**

Add to the edit form:

```html
<!-- Status Message -->
<div class="form-group">
  <label>Status Message</label>
  <input type="text" name="status_message" value="{{ user['status_message'] or '' }}" maxlength="100" placeholder="What's your vibe?">
</div>

<!-- Profile Picture Upload -->
<div class="form-group">
  <label>Profile Picture</label>
  {% if user["profile_pic_cid"] %}
  <img src="{{ ipfs_url(user['profile_pic_cid']) }}" class="current-pfp-preview" width="80">
  {% endif %}
  <form method="POST" action="{{ url_for('profile.upload_file') }}" enctype="multipart/form-data">
    <input type="hidden" name="upload_type" value="profile_pic">
    <input type="file" name="file" accept="image/jpeg,image/png,image/gif,image/webp">
    <button type="submit" class="btn">Upload</button>
  </form>
</div>

<!-- Background -->
<div class="form-group">
  <label>Background</label>
  <select name="background_preset">
    <option value="">Custom / None</option>
    <option value="sky" {{ 'selected' if user['background_preset'] == 'sky' }}>Sky</option>
    <option value="sunset" {{ 'selected' if user['background_preset'] == 'sunset' }}>Sunset</option>
    <option value="cyber" {{ 'selected' if user['background_preset'] == 'cyber' }}>Cyber</option>
    <option value="stars" {{ 'selected' if user['background_preset'] == 'stars' }}>Stars</option>
    <option value="matrix" {{ 'selected' if user['background_preset'] == 'matrix' }}>Matrix</option>
    <option value="vaporwave" {{ 'selected' if user['background_preset'] == 'vaporwave' }}>Vaporwave</option>
    <option value="ocean" {{ 'selected' if user['background_preset'] == 'ocean' }}>Ocean</option>
  </select>
  <p>Or upload custom background:</p>
  <form method="POST" action="{{ url_for('profile.upload_file') }}" enctype="multipart/form-data">
    <input type="hidden" name="upload_type" value="background">
    <input type="file" name="file" accept="image/jpeg,image/png,image/gif,image/webp">
    <button type="submit" class="btn">Upload Background</button>
  </form>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add templates/edit_profile.html
git commit -m "feat(profile): extend edit form with upload and background options"
```

---

## Task 6: Create playlist template

**Files:**
- Create: `templates/playlist.html`
- Create: `templates/playlist_new.html`

- [ ] **Step 1: Create playlist.html**

```html
{% extends "base.html" %}
{% block title %}{{ playlist["name"] }} — Pacer{% endblock %}
{% block content %}
<div class="win-panel">
  <div class="panel-title">{{ playlist["name"] }}</div>
  <p class="playlist-meta">
    by <a href="{{ url_for('profile.profile', username=owner['username']) }}">{{ owner["display_name"] or owner["username"] }}</a>
    · {{ tracks|length }} tracks
  </p>
  {% if playlist["description"] %}
  <p>{{ playlist["description"] }}</p>
  {% endif %}

  <ol class="playlist-tracks">
    {% for track in tracks %}
    <li>
      <a href="{{ url_for('music.song_detail', song_id=track['id']) }}">{{ track["title"] }}</a>
      <span class="track-artist">{{ track["artist"] }}</span>
      {% if track["spotify_id"] %}
      <button class="btn-play-mini" onclick="playInMini('{{ track['spotify_id'] }}', '{{ track['title'] }}', '{{ track['artist'] }}')">▶</button>
      {% endif %}
      {% if current_user and current_user["id"] == playlist["user_id"] %}
      <form method="POST" action="{{ url_for('profile.remove_from_playlist', playlist_id=playlist['id']) }}" style="display:inline">
        <input type="hidden" name="song_id" value="{{ track['id'] }}">
        <button type="submit" class="btn-small">✕</button>
      </form>
      {% endif %}
    </li>
    {% endfor %}
  </ol>
</div>
{% endblock %}
```

- [ ] **Step 2: Create playlist_new.html**

```html
{% extends "base.html" %}
{% block title %}New Playlist — Pacer{% endblock %}
{% block content %}
<div class="win-panel" style="max-width: 500px; margin: 0 auto;">
  <div class="panel-title">Create Playlist</div>
  <form method="POST">
    <div class="form-group">
      <label>Name</label>
      <input type="text" name="name" required maxlength="100">
    </div>
    <div class="form-group">
      <label>Description (optional)</label>
      <textarea name="description" rows="3" maxlength="500"></textarea>
    </div>
    <button type="submit" class="btn">Create</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Commit**

```bash
git add templates/playlist.html templates/playlist_new.html
git commit -m "feat(profile): add playlist templates"
```

---

## Task 7: Add profile page CSS

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: Add profile and background preset styles**

```css
/* Profile Page */
.profile-page { padding: 16px; min-height: 80vh; }
.profile-header { display: flex; gap: 16px; align-items: center; margin-bottom: 16px; }
.profile-pic { width: 120px; height: 120px; object-fit: cover; border: 3px solid #000; }
.profile-pic-emoji { width: 120px; height: 120px; display: flex; align-items: center; justify-content: center; font-size: 64px; background: #c0c0c0; border: 3px solid #000; }
.profile-status { font-style: italic; color: #333; margin-top: 4px; }
.profile-username { color: #666; }
.pinned-songs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 8px; }
.pinned-song-card { text-align: center; text-decoration: none; color: inherit; }
.pinned-song-card img { width: 100%; aspect-ratio: 1; object-fit: cover; border: 2px solid #000; }
.pinned-song-title { font-size: 11px; font-weight: bold; margin-top: 4px; }
.pinned-song-artist { font-size: 10px; color: #666; }
.playlist-link { display: block; margin: 4px 0; }

/* Background Presets */
.stars { background: linear-gradient(to bottom, #0a0a2e, #1a1a4e); }
.matrix { background: linear-gradient(to bottom, #001100, #003300); }
.vaporwave { background: linear-gradient(135deg, #ff71ce, #b967ff, #01cdfe); }
.ocean { background: linear-gradient(to bottom, #006994, #003d5c); }
```

- [ ] **Step 2: Commit**

```bash
git add static/style.css
git commit -m "feat(profile): add profile page and background preset styles"
```

---

## Task 8: Verify profile features end-to-end

- [ ] **Step 1: Run the app**

```bash
python run.py
```

- [ ] **Step 2: Test edit profile with new fields**

Go to `/profile/edit`, verify status message and background preset dropdown work.

- [ ] **Step 3: Test file upload (if Pinata configured)**

Upload a profile picture. Verify it appears on the profile page via IPFS gateway URL.

- [ ] **Step 4: Test pinned songs**

Pin a song from a song detail page, verify it shows on profile.

- [ ] **Step 5: Test playlist creation**

Create a playlist, add songs, verify playlist page works.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "feat(profile): complete personalizable profile pages"
```
