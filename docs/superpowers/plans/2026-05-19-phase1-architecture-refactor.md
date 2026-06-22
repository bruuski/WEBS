# Phase 1: Architecture Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Refactor the monolithic `app.py` (1474 lines) into a Flask Blueprints structure without changing any existing behavior or URLs.

**Architecture:** Extract code from `app.py` into organized modules: config, db, helpers, routes (auth, profile, music, blog, spotify), services (spotify). All existing URLs and behavior remain identical.

**Tech Stack:** Flask Blueprints, SQLite, existing dependencies only.

---

## File Structure

```
pacer/
├── __init__.py          (NEW - app factory, register blueprints)
├── config.py            (NEW - env vars, constants)
├── db.py                (NEW - get_db, close_db, init_db, SCHEMA, migrations)
├── helpers.py           (NEW - hash_password, current_user, login_required, template filters)
├── routes/
│   ├── __init__.py      (NEW - empty, package marker)
│   ├── auth.py          (NEW - /login, /signup, /logout)
│   ├── profile.py       (NEW - /u/<username>, /profile/edit)
│   ├── music.py         (NEW - /songs, /songs/<id>, /albums/<id>, /track/spotify/*, /album/spotify/*)
│   ├── blog.py          (NEW - /blog, /blog/<id>, /bulletins/new)
│   └── spotify.py       (NEW - /spotify/search, /spotify/connect, /spotify/callback, /spotify/disconnect, /me/spotify/top)
├── services/
│   ├── __init__.py      (NEW - empty, package marker)
│   └── spotify.py       (NEW - Spotify API client functions)
├── seed.py              (NEW - seed_demo function)
└── run.py               (NEW - entry point)
```

Existing files kept as-is:
- `static/` (unchanged)
- `templates/` (unchanged)
- `requirements.txt` (unchanged)

---

## Task 1: Create config module

**Files:**
- Create: `pacer/config.py`

- [ ] **Step 1: Create pacer directory**

```bash
mkdir pacer
mkdir pacer/routes
mkdir pacer/services
```

- [ ] **Step 2: Create config.py**

```python
import os

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, "..", "pacer.db")

SECRET_KEY = os.environ.get("PACER_SECRET", "dev-secret-change-me")

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/spotify/callback")
SPOTIFY_TRENDING_PLAYLIST = os.environ.get("SPOTIFY_TRENDING_PLAYLIST", "37i9dQZF1DXcBWIGoYBM5M")
```

- [ ] **Step 3: Commit**

```bash
git add pacer/config.py
git commit -m "refactor: add config module"
```

---

## Task 2: Create database module

**Files:**
- Create: `pacer/db.py`
- Source: `app.py` lines 215-360

- [ ] **Step 1: Create db.py with schema and helpers**

```python
import sqlite3
from flask import g, current_app
from pacer.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    display_name TEXT,
    mood TEXT DEFAULT '',
    headline TEXT DEFAULT '',
    about_me TEXT DEFAULT '',
    fav_bands TEXT DEFAULT '',
    location TEXT DEFAULT '',
    age INTEGER,
    avatar_emoji TEXT DEFAULT '🎧',
    theme TEXT DEFAULT 'sky',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    spotify_id TEXT,
    spotify_access_token TEXT,
    spotify_refresh_token TEXT,
    spotify_token_expires REAL
);

CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT DEFAULT '',
    year INTEGER,
    genre TEXT DEFAULT '',
    link TEXT DEFAULT '',
    submitted_by INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    spotify_id TEXT,
    spotify_url TEXT,
    spotify_image TEXT,
    spotify_preview_url TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id INTEGER NOT NULL REFERENCES songs(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
    review TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(song_id, user_id)
);

CREATE TABLE IF NOT EXISTS bulletins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    body TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER NOT NULL REFERENCES users(id),
    author_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id TEXT UNIQUE,
    name TEXT NOT NULL,
    artist TEXT NOT NULL,
    year INTEGER,
    spotify_url TEXT,
    spotify_image TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS album_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id INTEGER NOT NULL REFERENCES albums(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
    review TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(album_id, user_id)
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS thread_replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)

    # Additive migrations
    cols = {r[1] for r in db.execute("PRAGMA table_info(songs)").fetchall()}
    for col, typedef in [
        ("spotify_id", "TEXT"),
        ("spotify_url", "TEXT"),
        ("spotify_image", "TEXT"),
        ("spotify_preview_url", "TEXT"),
    ]:
        if col not in cols:
            db.execute(f"ALTER TABLE songs ADD COLUMN {col} {typedef}")

    user_cols = {r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()}
    for col, typedef in [
        ("spotify_id", "TEXT"),
        ("spotify_access_token", "TEXT"),
        ("spotify_refresh_token", "TEXT"),
        ("spotify_token_expires", "REAL"),
    ]:
        if col not in user_cols:
            db.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef}")

    db.commit()
    db.close()
```

- [ ] **Step 2: Commit**

```bash
git add pacer/db.py
git commit -m "refactor: add database module with schema and helpers"
```

---

## Task 3: Create helpers module

**Files:**
- Create: `pacer/helpers.py`
- Source: `app.py` lines 363-442

- [ ] **Step 1: Create helpers.py**

```python
import hashlib
import re
from datetime import datetime
from functools import wraps
from flask import session, redirect, url_for
from markupsafe import Markup
from pacer.db import get_db

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


def hash_password(password, salt):
    return hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1
    ).hex()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)
    return wrapper


def score10(value):
    if value is None:
        return "—"
    return f"{value * 2:.1f}"


def stars_filter(value):
    if value is None:
        return ""
    full = int(round(value))
    return "★" * full + "☆" * (5 - full)


def datefmt(value):
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%m/%d/%y(%a)%H:%M")


def greentext_filter(text):
    if not text:
        return ""
    lines = text.split("\n")
    result = []
    for line in lines:
        if line.startswith(">"):
            result.append(f'<span class="greentext">{line}</span>')
        else:
            result.append(line)
    return Markup("<br>".join(result))


def register_template_utils(app):
    app.template_filter("score10")(score10)
    app.template_filter("stars")(stars_filter)
    app.template_filter("datefmt")(datefmt)
    app.template_filter("greentext")(greentext_filter)

    @app.context_processor
    def inject_globals():
        return {
            "current_user": current_user(),
            "now": datetime.now(),
            "spotify_enabled": True,
        }
```

- [ ] **Step 2: Commit**

```bash
git add pacer/helpers.py
git commit -m "refactor: add helpers module with auth, filters, context processor"
```

---

## Task 4: Create Spotify service

**Files:**
- Create: `pacer/services/__init__.py`
- Create: `pacer/services/spotify.py`
- Source: `app.py` lines 26-210, 701-847, 1233-1263

- [ ] **Step 1: Create empty __init__.py**

```python
```

- [ ] **Step 2: Create services/spotify.py**

This file contains all Spotify API interaction logic: token management, trending fetch, track/album lookup, album tracks fetch, user token refresh. Extract from `app.py` lines 26-210, 701-847, 1233-1263.

The functions to include:
- `spotify_configured()`
- `get_app_spotify_token()`
- `fetch_spotify_trending(limit=12)`
- `_spotify_lookup_track(title, artist)`
- `backfill_covers_from_spotify()`
- `_find_or_create_song_from_spotify(spotify_id)`
- `_find_or_create_album_from_spotify(spotify_id)`
- `_fetch_album_tracks(spotify_album_id)`
- `refresh_user_spotify_token(user_id)`

All functions keep their exact same logic, but import `DB_PATH` from config and `get_db` from db module where needed.

- [ ] **Step 3: Commit**

```bash
git add pacer/services/__init__.py pacer/services/spotify.py
git commit -m "refactor: extract Spotify service module"
```

---

## Task 5: Create auth routes blueprint

**Files:**
- Create: `pacer/routes/__init__.py`
- Create: `pacer/routes/auth.py`
- Source: `app.py` lines 511-583

- [ ] **Step 1: Create empty routes/__init__.py**

```python
```

- [ ] **Step 2: Create routes/auth.py**

```python
import secrets
from flask import Blueprint, request, redirect, url_for, session, render_template, flash
from pacer.db import get_db
from pacer.helpers import hash_password, current_user, USERNAME_RE

bp = Blueprint("auth", __name__)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html")
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    if not USERNAME_RE.match(username):
        flash("Username must be 3-20 chars (letters, numbers, underscore)")
        return redirect(url_for("auth.signup"))
    if len(password) < 4:
        flash("Password must be at least 4 characters")
        return redirect(url_for("auth.signup"))
    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        flash("Username taken")
        return redirect(url_for("auth.signup"))
    salt = secrets.token_hex(16)
    pw_hash = hash_password(password, salt)
    cur = db.execute(
        "INSERT INTO users (username, password_hash, password_salt, display_name) VALUES (?, ?, ?, ?)",
        (username, pw_hash, salt, username),
    )
    db.commit()
    session["user_id"] = cur.lastrowid
    return redirect(url_for("feed.home"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user or hash_password(password, user["password_salt"]) != user["password_hash"]:
        flash("Invalid credentials")
        return redirect(url_for("auth.login"))
    session["user_id"] = user["id"]
    return redirect(url_for("feed.home"))


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("feed.home"))
```

- [ ] **Step 3: Commit**

```bash
git add pacer/routes/__init__.py pacer/routes/auth.py
git commit -m "refactor: extract auth routes blueprint"
```

---

## Task 6: Create profile routes blueprint

**Files:**
- Create: `pacer/routes/profile.py`
- Source: `app.py` lines 586-666

- [ ] **Step 1: Create routes/profile.py**

Extract the `/u/<username>` and `/profile/edit` routes into a blueprint. Keep exact same logic and template rendering.

- [ ] **Step 2: Commit**

```bash
git add pacer/routes/profile.py
git commit -m "refactor: extract profile routes blueprint"
```

---

## Task 7: Create music routes blueprint

**Files:**
- Create: `pacer/routes/music.py`
- Source: `app.py` lines 669-984

- [ ] **Step 1: Create routes/music.py**

Extract routes: `/songs`, `/songs/<int:song_id>`, `/albums/<int:album_id>`, `/track/spotify/<spotify_id>`, `/album/spotify/<spotify_id>`. Import helper functions from `services/spotify.py`.

- [ ] **Step 2: Commit**

```bash
git add pacer/routes/music.py
git commit -m "refactor: extract music routes blueprint"
```

---

## Task 8: Create blog routes blueprint

**Files:**
- Create: `pacer/routes/blog.py`
- Source: `app.py` lines 989-1073

- [ ] **Step 1: Create routes/blog.py**

Extract routes: `/blog`, `/blog/new`, `/blog/<int:thread_id>`, `/bulletins/new`.

- [ ] **Step 2: Commit**

```bash
git add pacer/routes/blog.py
git commit -m "refactor: extract blog routes blueprint"
```

---

## Task 9: Create spotify routes blueprint

**Files:**
- Create: `pacer/routes/spotify.py`
- Source: `app.py` lines 1078-1292

- [ ] **Step 1: Create routes/spotify.py**

Extract routes: `/spotify/search`, `/spotify/connect`, `/spotify/callback`, `/spotify/disconnect`, `/me/spotify/top`.

- [ ] **Step 2: Commit**

```bash
git add pacer/routes/spotify.py
git commit -m "refactor: extract spotify routes blueprint"
```

---

## Task 10: Create feed routes blueprint (homepage)

**Files:**
- Create: `pacer/routes/feed.py`
- Source: `app.py` lines 450-508

- [ ] **Step 1: Create routes/feed.py**

Extract the `/` homepage route. This will later become the X-style feed, but for now it keeps the exact same behavior.

- [ ] **Step 2: Commit**

```bash
git add pacer/routes/feed.py
git commit -m "refactor: extract feed/home routes blueprint"
```

---

## Task 11: Create seed module

**Files:**
- Create: `pacer/seed.py`
- Source: `app.py` lines 1297-1459

- [ ] **Step 1: Create seed.py**

Move `seed_demo()` function to its own module.

- [ ] **Step 2: Commit**

```bash
git add pacer/seed.py
git commit -m "refactor: extract seed module"
```

---

## Task 12: Create app factory and run.py

**Files:**
- Create: `pacer/__init__.py`
- Create: `run.py`

- [ ] **Step 1: Create pacer/__init__.py (app factory)**

```python
from flask import Flask
from pacer.config import SECRET_KEY
from pacer.db import close_db, init_db
from pacer.helpers import register_template_utils


def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app.secret_key = SECRET_KEY

    # DB teardown
    app.teardown_appcontext(close_db)

    # Template filters and context processor
    register_template_utils(app)

    # Register blueprints
    from pacer.routes.auth import bp as auth_bp
    from pacer.routes.profile import bp as profile_bp
    from pacer.routes.music import bp as music_bp
    from pacer.routes.blog import bp as blog_bp
    from pacer.routes.spotify import bp as spotify_bp
    from pacer.routes.feed import bp as feed_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(music_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(spotify_bp)
    app.register_blueprint(feed_bp)

    # CLI command
    @app.cli.command("init-db")
    def init_db_cmd():
        init_db()
        from pacer.seed import seed_demo
        from pacer.services.spotify import backfill_covers_from_spotify
        seed_demo()
        backfill_covers_from_spotify()
        print("Database initialized.")

    return app
```

- [ ] **Step 2: Create run.py**

```python
from pacer import create_app
from pacer.db import init_db
from pacer.seed import seed_demo
from pacer.services.spotify import backfill_covers_from_spotify

app = create_app()

if __name__ == "__main__":
    init_db()
    seed_demo()
    backfill_covers_from_spotify()
    app.run(host="127.0.0.1", port=5000, debug=True)
```

- [ ] **Step 3: Commit**

```bash
git add pacer/__init__.py run.py
git commit -m "refactor: add app factory and entry point"
```

---

## Task 13: Verify and clean up

- [ ] **Step 1: Run the app**

```bash
python run.py
```

Expected: App starts on port 5000, no errors.

- [ ] **Step 2: Test all existing routes manually**

Visit each URL and verify it works:
- `/` (homepage)
- `/signup`, `/login`, `/logout`
- `/u/tom` (profile)
- `/songs` (browse)
- `/blog` (threads)

- [ ] **Step 3: Remove old app.py**

Once verified, delete the old monolith:

```bash
git rm app.py
git commit -m "refactor: remove old monolithic app.py"
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "refactor: complete Blueprint restructure"
```

---

## Summary

After this phase:
- Codebase is organized into focused modules
- All existing behavior and URLs are preserved
- Ready for Phase 2 (Artist Pages) to add new blueprints and models cleanly
