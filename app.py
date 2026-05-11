"""Pacer -- music rating + reviews + Spotify trending."""
import os
import re
import time
import base64
import sqlite3
import secrets
import hashlib
import urllib.parse
from datetime import datetime
from functools import wraps

import requests
from flask import (
    Flask, g, request, redirect, url_for, session, jsonify,
    render_template, flash, abort,
)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, "pacer.db")

app = Flask(__name__)
app.secret_key = os.environ.get("PACER_SECRET", "dev-secret-change-me")


# ---------- Spotify config ----------

SPOTIFY_CLIENT_ID     = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI  = os.environ.get("SPOTIFY_REDIRECT_URI",
                                       "http://127.0.0.1:5000/spotify/callback")
SPOTIFY_SCOPES = "user-read-email user-top-read user-read-currently-playing user-read-recently-played"


def spotify_configured():
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)


_app_token = {"value": None, "expires_at": 0}
_trending_cache = {"items": [], "expires_at": 0}

# "Today's Top Hits" -- well-known public playlist
SPOTIFY_TRENDING_PLAYLIST = os.environ.get(
    "SPOTIFY_TRENDING_PLAYLIST", "37i9dQZF1DXcBWIGoYBM5M"
)


def _spotify_lookup_track(title, artist):
    """Search Spotify for one track and return basic metadata, or None."""
    if not spotify_configured():
        return None
    token = get_app_spotify_token()
    if not token:
        return None
    q = f'track:"{title}" artist:"{artist}"'
    try:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": q, "type": "track", "limit": 1},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    items = (r.json().get("tracks") or {}).get("items") or []
    if not items:
        return None
    t = items[0]
    album = t.get("album") or {}
    images = album.get("images") or []
    return {
        "id":      t.get("id"),
        "url":     (t.get("external_urls") or {}).get("spotify"),
        "image":   images[0]["url"] if images else None,
        "preview": t.get("preview_url"),
    }


def backfill_covers_from_spotify():
    """Attach Spotify cover art to existing songs that don't have one."""
    if not spotify_configured():
        print("[pacer] Spotify not configured; cover art will be empty. "
              "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to fix.")
        return
    if not get_app_spotify_token():
        print("[pacer] Spotify token request failed; skipping cover backfill.")
        return
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, title, artist FROM songs "
        "WHERE spotify_image IS NULL OR spotify_image = ''"
    ).fetchall()
    if not rows:
        con.close()
        return
    print(f"[pacer] backfilling cover art for {len(rows)} song(s)…")
    updated = 0
    for row in rows:
        meta = _spotify_lookup_track(row["title"], row["artist"])
        if not meta or not meta.get("image"):
            continue
        con.execute(
            """UPDATE songs SET
                  spotify_id          = COALESCE(NULLIF(spotify_id,''),  ?),
                  spotify_url         = COALESCE(NULLIF(spotify_url,''), ?),
                  spotify_image       = ?,
                  spotify_preview_url = COALESCE(NULLIF(spotify_preview_url,''), ?)
               WHERE id = ?""",
            (meta["id"], meta["url"], meta["image"], meta["preview"], row["id"]),
        )
        updated += 1
    con.commit()
    con.close()
    print(f"[pacer] cover backfill done: {updated}/{len(rows)} songs updated")


def fetch_spotify_trending(limit=12):
    """Pull a few trending tracks from Spotify, with a short in-process cache."""
    if _trending_cache["items"] and _trending_cache["expires_at"] > time.time():
        return _trending_cache["items"][:limit]
    if not spotify_configured():
        return []
    token = get_app_spotify_token()
    if not token:
        return []
    fields = ("items(track(id,name,artists(name),album(name,images,release_date),"
              "external_urls,preview_url))")
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/playlists/{SPOTIFY_TRENDING_PLAYLIST}/tracks",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit, "fields": fields},
            timeout=8,
        )
    except requests.RequestException:
        return []
    if not r.ok:
        # fallback: new releases (albums)
        try:
            r2 = requests.get(
                "https://api.spotify.com/v1/browse/new-releases",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": limit},
                timeout=8,
            )
        except requests.RequestException:
            return []
        if not r2.ok:
            return []
        items = []
        for a in r2.json().get("albums", {}).get("items", []):
            images = a.get("images") or []
            items.append({
                "id":      a.get("id"),
                "name":    a.get("name"),
                "artists": ", ".join(ar["name"] for ar in a.get("artists", [])),
                "album":   a.get("name"),
                "year":    (a.get("release_date") or "")[:4],
                "image":   images[0]["url"] if images else None,
                "url":     (a.get("external_urls") or {}).get("spotify"),
                "preview": None,
                "kind":    "album",
            })
        _trending_cache.update(items=items, expires_at=time.time() + 600)
        return items[:limit]

    items = []
    for it in r.json().get("items", []):
        t = it.get("track") or {}
        if not t.get("id"):
            continue
        album = t.get("album") or {}
        images = album.get("images") or []
        items.append({
            "id":      t.get("id"),
            "name":    t.get("name"),
            "artists": ", ".join(a["name"] for a in t.get("artists", [])),
            "album":   album.get("name"),
            "year":    (album.get("release_date") or "")[:4],
            "image":   images[0]["url"] if images else None,
            "url":     (t.get("external_urls") or {}).get("spotify"),
            "preview": t.get("preview_url"),
            "kind":    "track",
        })
    _trending_cache.update(items=items, expires_at=time.time() + 600)
    return items[:limit]


def get_app_spotify_token():
    """Client-credentials token for server-side search."""
    if not spotify_configured():
        return None
    if _app_token["value"] and _app_token["expires_at"] > time.time() + 30:
        return _app_token["value"]
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"},
        timeout=8,
    )
    if not r.ok:
        return None
    d = r.json()
    _app_token["value"] = d["access_token"]
    _app_token["expires_at"] = time.time() + d.get("expires_in", 3600)
    return _app_token["value"]


# ---------- database ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    display_name  TEXT,
    mood          TEXT DEFAULT 'listening',
    headline      TEXT DEFAULT '',
    about_me      TEXT DEFAULT '',
    fav_bands     TEXT DEFAULT '',
    location      TEXT DEFAULT '',
    age           INTEGER,
    avatar_emoji  TEXT DEFAULT '◉',
    theme         TEXT DEFAULT 'sky',
    created_at    TEXT NOT NULL,
    last_login    TEXT,
    spotify_id            TEXT,
    spotify_access_token  TEXT,
    spotify_refresh_token TEXT,
    spotify_token_expires INTEGER
);

CREATE TABLE IF NOT EXISTS songs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    album       TEXT,
    year        INTEGER,
    genre       TEXT,
    link        TEXT,
    submitted_by INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    spotify_id          TEXT,
    spotify_url         TEXT,
    spotify_preview_url TEXT,
    spotify_image       TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id   INTEGER NOT NULL REFERENCES songs(id),
    user_id   INTEGER NOT NULL REFERENCES users(id),
    stars     INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    review    TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(song_id, user_id)
);

CREATE TABLE IF NOT EXISTS bulletins (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    subject   TEXT NOT NULL,
    body      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES users(id),
    author_id   INTEGER NOT NULL REFERENCES users(id),
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS albums (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id    TEXT UNIQUE,
    name          TEXT NOT NULL,
    artist        TEXT NOT NULL,
    year          INTEGER,
    spotify_url   TEXT,
    spotify_image TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS album_ratings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    album_id  INTEGER NOT NULL REFERENCES albums(id),
    user_id   INTEGER NOT NULL REFERENCES users(id),
    stars     INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    review    TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(album_id, user_id)
);

CREATE TABLE IF NOT EXISTS threads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thread_replies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id  INTEGER NOT NULL REFERENCES threads(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    # additive migrations for existing databases
    def existing(table):
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    user_cols = existing("users")
    for col, ddl in [
        ("spotify_id",            "TEXT"),
        ("spotify_access_token",  "TEXT"),
        ("spotify_refresh_token", "TEXT"),
        ("spotify_token_expires", "INTEGER"),
    ]:
        if col not in user_cols:
            con.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    song_cols = existing("songs")
    for col, ddl in [
        ("spotify_id",          "TEXT"),
        ("spotify_url",         "TEXT"),
        ("spotify_preview_url", "TEXT"),
        ("spotify_image",       "TEXT"),
    ]:
        if col not in song_cols:
            con.execute(f"ALTER TABLE songs ADD COLUMN {col} {ddl}")
    con.commit()
    con.close()


# ---------- auth helpers ----------

def hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=32
    ).hex()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            flash("Log in to continue.", "warn")
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "now": datetime.utcnow(),
        "spotify_enabled": spotify_configured(),
    }


@app.template_filter("score10")
def score10(value):
    """Convert 0-5 average to a Pitchfork-style 0.0-10.0 score."""
    try:
        return "%.1f" % (float(value or 0) * 2.0)
    except (TypeError, ValueError):
        return "0.0"


@app.template_filter("stars")
def stars_filter(value):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return "—"
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


@app.template_filter("datefmt")
def datefmt(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return dt.strftime("%m/%d/%y(%a)%H:%M")


@app.template_filter("greentext")
def greentext_filter(text):
    """4chan-style greentext for lines starting with '>'."""
    if not text:
        return ""
    from markupsafe import escape, Markup
    out = []
    for line in text.split("\n"):
        e = str(escape(line))
        if line.startswith(">") and not line.startswith(">>"):
            out.append(f'<span class="gt">{e}</span>')
        elif line.startswith(">>"):
            out.append(f'<span class="quote">{e}</span>')
        else:
            out.append(e)
    return Markup("<br>".join(out))


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


# ---------- routes ----------

@app.route("/")
def home():
    db = get_db()
    top_songs = db.execute("""
        SELECT s.*, u.username AS submitter,
               COALESCE(AVG(r.stars), 0) AS avg_stars,
               COUNT(r.id) AS rating_count
        FROM songs s
        JOIN users u ON u.id = s.submitted_by
        LEFT JOIN ratings r ON r.song_id = s.id
        GROUP BY s.id
        ORDER BY avg_stars DESC, rating_count DESC, s.id DESC
        LIMIT 10
    """).fetchall()
    fresh_songs = db.execute("""
        SELECT s.*, u.username AS submitter
        FROM songs s JOIN users u ON u.id = s.submitted_by
        ORDER BY s.id DESC LIMIT 8
    """).fetchall()
    bulletins = db.execute("""
        SELECT b.*, u.username FROM bulletins b
        JOIN users u ON u.id = b.user_id
        ORDER BY b.id DESC LIMIT 10
    """).fetchall()
    online_users = db.execute("""
        SELECT id, username, avatar_emoji, mood FROM users
        ORDER BY last_login DESC NULLS LAST, id DESC LIMIT 12
    """).fetchall()
    counts = db.execute("""
        SELECT (SELECT COUNT(*) FROM users)   AS users,
               (SELECT COUNT(*) FROM songs)   AS songs,
               (SELECT COUNT(*) FROM ratings) AS ratings
    """).fetchone()
    bnm = None
    if top_songs:
        bnm = top_songs[0]
    trending = fetch_spotify_trending(limit=12)
    recent_threads = db.execute("""
        SELECT t.id, t.subject, t.created_at, u.username,
               (SELECT COUNT(*) FROM thread_replies r WHERE r.thread_id = t.id) AS reply_count,
               COALESCE(
                 (SELECT MAX(r.created_at) FROM thread_replies r WHERE r.thread_id = t.id),
                 t.created_at
               ) AS last_activity
        FROM threads t JOIN users u ON u.id = t.user_id
        ORDER BY last_activity DESC, t.id DESC
        LIMIT 6
    """).fetchall()
    return render_template(
        "home.html",
        top_songs=top_songs,
        fresh_songs=fresh_songs,
        bulletins=bulletins,
        online_users=online_users,
        counts=counts,
        bnm=bnm,
        trending=trending,
        recent_threads=recent_threads,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        display_name = (request.form.get("display_name") or "").strip() or username
        location = (request.form.get("location") or "").strip()
        age_raw = request.form.get("age") or ""
        fav_bands = (request.form.get("fav_bands") or "").strip()
        theme = request.form.get("theme") or "sky"

        if not USERNAME_RE.match(username):
            flash("Username must be 3-20 chars, letters/numbers/underscore only.", "warn")
            return render_template("signup.html")
        if len(password) < 4:
            flash("Password too short.", "warn")
            return render_template("signup.html")
        try:
            age = int(age_raw) if age_raw else None
        except ValueError:
            age = None

        salt = secrets.token_hex(16)
        pw_hash = hash_password(password, salt)
        db = get_db()
        try:
            cur = db.execute(
                """INSERT INTO users
                   (username, password_hash, password_salt, display_name,
                    location, age, fav_bands, theme, created_at, last_login)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (username, pw_hash, salt, display_name, location, age,
                 fav_bands, theme,
                 datetime.utcnow().isoformat(timespec="seconds"),
                 datetime.utcnow().isoformat(timespec="seconds")),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Username already taken.", "warn")
            return render_template("signup.html")
        session["user_id"] = cur.lastrowid
        flash("Account created.", "ok")
        return redirect(url_for("profile", username=username))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row or hash_password(password, row["password_salt"]) != row["password_hash"]:
            flash("Wrong username or password.", "warn")
            return render_template("login.html")
        session["user_id"] = row["id"]
        get_db().execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.utcnow().isoformat(timespec="seconds"), row["id"]),
        )
        get_db().commit()
        flash(f"Welcome back, {row['username']}.", "ok")
        return redirect(request.args.get("next") or url_for("home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "ok")
    return redirect(url_for("home"))


@app.route("/u/<username>", methods=["GET", "POST"])
def profile(username):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to leave a comment.", "warn")
            return redirect(url_for("login"))
        body = (request.form.get("body") or "").strip()
        if body:
            db.execute(
                "INSERT INTO comments (profile_id, author_id, body, created_at) VALUES (?,?,?,?)",
                (user["id"], session["user_id"], body[:1000],
                 datetime.utcnow().isoformat(timespec="seconds")),
            )
            db.commit()
        return redirect(url_for("profile", username=username))

    ratings = db.execute("""
        SELECT r.*, s.title, s.artist FROM ratings r
        JOIN songs s ON s.id = r.song_id
        WHERE r.user_id = ?
        ORDER BY r.id DESC LIMIT 25
    """, (user["id"],)).fetchall()
    submitted = db.execute("""
        SELECT s.*, COALESCE(AVG(r.stars), 0) AS avg_stars, COUNT(r.id) AS rating_count
        FROM songs s LEFT JOIN ratings r ON r.song_id = s.id
        WHERE s.submitted_by = ?
        GROUP BY s.id ORDER BY s.id DESC LIMIT 25
    """, (user["id"],)).fetchall()
    comments = db.execute("""
        SELECT c.*, u.username, u.avatar_emoji FROM comments c
        JOIN users u ON u.id = c.author_id
        WHERE c.profile_id = ? ORDER BY c.id DESC LIMIT 50
    """, (user["id"],)).fetchall()
    top_friends = db.execute("""
        SELECT id, username, avatar_emoji FROM users
        WHERE id != ? ORDER BY RANDOM() LIMIT 8
    """, (user["id"],)).fetchall()
    avg_given = db.execute(
        "SELECT AVG(stars) AS a FROM ratings WHERE user_id = ?", (user["id"],)
    ).fetchone()["a"]
    return render_template(
        "profile.html",
        user=user, ratings=ratings, submitted=submitted,
        comments=comments, top_friends=top_friends, avg_given=avg_given,
    )


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    user = current_user()
    db = get_db()
    if request.method == "POST":
        fields = {
            "display_name": (request.form.get("display_name") or "").strip()[:60],
            "headline":     (request.form.get("headline") or "").strip()[:120],
            "mood":         (request.form.get("mood") or "").strip()[:30],
            "about_me":     (request.form.get("about_me") or "").strip()[:4000],
            "fav_bands":    (request.form.get("fav_bands") or "").strip()[:1000],
            "location":     (request.form.get("location") or "").strip()[:80],
            "avatar_emoji": (request.form.get("avatar_emoji") or "◉")[:4],
            "theme":         request.form.get("theme") or "sky",
        }
        try:
            fields["age"] = int(request.form.get("age") or 0) or None
        except ValueError:
            fields["age"] = user["age"]
        db.execute(
            """UPDATE users SET display_name=?, headline=?, mood=?, about_me=?,
               fav_bands=?, location=?, avatar_emoji=?, theme=?, age=? WHERE id=?""",
            (*fields.values(), user["id"]),
        )
        db.commit()
        flash("Profile updated.", "ok")
        return redirect(url_for("profile", username=user["username"]))
    return render_template("edit_profile.html", user=user)


@app.route("/songs")
def browse():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "top")
    db = get_db()
    params = []
    where = ""
    if q:
        where = "WHERE s.title LIKE ? OR s.artist LIKE ? OR s.album LIKE ? OR s.genre LIKE ?"
        like = f"%{q}%"
        params = [like, like, like, like]
    order = {
        "top":   "avg_stars DESC, rating_count DESC, s.id DESC",
        "new":   "s.id DESC",
        "hot":   "rating_count DESC, avg_stars DESC",
        "title": "s.title COLLATE NOCASE ASC",
    }.get(sort, "avg_stars DESC")
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
    return render_template("browse.html", songs=rows, q=q, sort=sort)


def _find_or_create_song_from_spotify(spotify_id):
    """Look up a song by spotify_id; create one from Spotify metadata if missing."""
    if not spotify_id:
        return None
    db = get_db()
    row = db.execute("SELECT id FROM songs WHERE spotify_id = ?", (spotify_id,)).fetchone()
    if row:
        return row["id"]
    token = get_app_spotify_token()
    if not token:
        return None
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/tracks/{spotify_id}",
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
    submitter_row = db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if not submitter_row:
        return None
    cur = db.execute(
        """INSERT INTO songs (title, artist, album, year, genre, link, submitted_by, created_at,
                              spotify_id, spotify_url, spotify_image, spotify_preview_url)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            t.get("name", "")[:120],
            ", ".join(a["name"] for a in t.get("artists", []))[:120],
            (album.get("name") or "")[:120],
            int((album.get("release_date") or "0000")[:4] or 0) or None,
            None,
            (t.get("external_urls") or {}).get("spotify"),
            submitter_row["id"],
            datetime.utcnow().isoformat(timespec="seconds"),
            t.get("id"),
            (t.get("external_urls") or {}).get("spotify"),
            images[0]["url"] if images else None,
            t.get("preview_url"),
        ),
    )
    db.commit()
    return cur.lastrowid


@app.route("/track/spotify/<spotify_id>")
def track_from_spotify(spotify_id):
    """Land on a local song page for a Spotify track, creating it if needed."""
    song_id = _find_or_create_song_from_spotify(spotify_id)
    if not song_id:
        flash("Couldn't look up that track on Spotify.", "warn")
        return redirect(url_for("home"))
    return redirect(url_for("song_detail", song_id=song_id))


# ---------- albums ----------

def _find_or_create_album_from_spotify(spotify_id):
    """Look up an album by spotify_id; create one from Spotify metadata if missing."""
    if not spotify_id:
        return None
    db = get_db()
    row = db.execute("SELECT id FROM albums WHERE spotify_id = ?", (spotify_id,)).fetchone()
    if row:
        return row["id"]
    token = get_app_spotify_token()
    if not token:
        return None
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/albums/{spotify_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    a = r.json()
    images = a.get("images") or []
    try:
        cur = db.execute(
            """INSERT INTO albums (spotify_id, name, artist, year, spotify_url, spotify_image, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                a.get("id"),
                (a.get("name") or "")[:200],
                ", ".join(ar["name"] for ar in a.get("artists", []))[:200],
                int((a.get("release_date") or "0000")[:4] or 0) or None,
                (a.get("external_urls") or {}).get("spotify"),
                images[0]["url"] if images else None,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        db.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        # raced
        row = db.execute("SELECT id FROM albums WHERE spotify_id = ?", (spotify_id,)).fetchone()
        return row["id"] if row else None


_album_tracks_cache = {}   # spotify_album_id -> (items, expires_at)


def _fetch_album_tracks(spotify_album_id):
    """Fetch the tracklist for an album from Spotify, with a short cache."""
    if not spotify_album_id:
        return []
    cached = _album_tracks_cache.get(spotify_album_id)
    if cached and cached[1] > time.time():
        return cached[0]
    if not spotify_configured():
        return []
    token = get_app_spotify_token()
    if not token:
        return []
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/albums/{spotify_album_id}/tracks",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 50},
            timeout=8,
        )
    except requests.RequestException:
        return []
    if not r.ok:
        return []
    items = []
    for t in r.json().get("items", []):
        ms = t.get("duration_ms") or 0
        items.append({
            "id":           t.get("id"),
            "name":         t.get("name"),
            "track_number": t.get("track_number"),
            "artists":      ", ".join(a["name"] for a in t.get("artists", [])),
            "duration":     f"{ms // 60000}:{(ms // 1000) % 60:02d}" if ms else "",
            "preview":      t.get("preview_url"),
            "url":          (t.get("external_urls") or {}).get("spotify"),
        })
    _album_tracks_cache[spotify_album_id] = (items, time.time() + 600)
    return items


@app.route("/album/spotify/<spotify_id>")
def album_from_spotify(spotify_id):
    """Land on a local album page for a Spotify album, creating it if needed."""
    album_id = _find_or_create_album_from_spotify(spotify_id)
    if not album_id:
        flash("Couldn't look up that album on Spotify.", "warn")
        return redirect(url_for("home"))
    return redirect(url_for("album_detail", album_id=album_id))


@app.route("/albums/<int:album_id>", methods=["GET", "POST"])
def album_detail(album_id):
    db = get_db()
    album = db.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
    if not album:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to rate albums.", "warn")
            return redirect(url_for("login", next=request.path))
        try:
            stars = int(request.form.get("stars") or 0)
        except ValueError:
            stars = 0
        if stars < 1 or stars > 5:
            flash("Pick a rating between 1 and 5.", "warn")
            return redirect(url_for("album_detail", album_id=album_id))
        review = (request.form.get("review") or "").strip()[:1500]
        db.execute("""
            INSERT INTO album_ratings (album_id, user_id, stars, review, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(album_id, user_id) DO UPDATE SET
              stars = excluded.stars,
              review = excluded.review,
              created_at = excluded.created_at
        """, (album_id, session["user_id"], stars, review,
              datetime.utcnow().isoformat(timespec="seconds")))
        db.commit()
        flash("Rating saved.", "ok")
        return redirect(url_for("album_detail", album_id=album_id))

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
    tracks = _fetch_album_tracks(album["spotify_id"]) if album["spotify_id"] else []
    return render_template(
        "album.html",
        album=album, stats=stats, histogram=histogram, max_h=max_h,
        reviews=reviews, featured=featured, my_rating=my_rating,
        tracks=tracks,
    )


@app.route("/songs/<int:song_id>", methods=["GET", "POST"])
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
            return redirect(url_for("login", next=request.path))
        try:
            stars = int(request.form.get("stars") or 0)
        except ValueError:
            stars = 0
        if stars < 1 or stars > 5:
            flash("Pick a rating between 1 and 5.", "warn")
            return redirect(url_for("song_detail", song_id=song_id))
        review = (request.form.get("review") or "").strip()[:1500]
        db.execute("""
            INSERT INTO ratings (song_id, user_id, stars, review, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(song_id, user_id) DO UPDATE SET
              stars = excluded.stars,
              review = excluded.review,
              created_at = excluded.created_at
        """, (song_id, session["user_id"], stars, review,
              datetime.utcnow().isoformat(timespec="seconds")))
        db.commit()
        flash("Rating saved.", "ok")
        return redirect(url_for("song_detail", song_id=song_id))

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
    )


# ---------- blog (user threads) ----------

@app.route("/blog")
def blog_list():
    db = get_db()
    threads = db.execute("""
        SELECT t.*, u.username, u.avatar_emoji,
               (SELECT COUNT(*) FROM thread_replies r WHERE r.thread_id = t.id) AS reply_count,
               (SELECT MAX(r.created_at) FROM thread_replies r WHERE r.thread_id = t.id) AS last_reply
        FROM threads t
        JOIN users u ON u.id = t.user_id
        ORDER BY COALESCE(
            (SELECT MAX(r.created_at) FROM thread_replies r WHERE r.thread_id = t.id),
            t.created_at
        ) DESC, t.id DESC
        LIMIT 100
    """).fetchall()
    return render_template("blog_list.html", threads=threads)


@app.route("/blog/new", methods=["POST"])
@login_required
def blog_new():
    subject = (request.form.get("subject") or "").strip()
    body    = (request.form.get("body") or "").strip()
    if not subject or not body:
        flash("Subject and body are required.", "warn")
        return redirect(url_for("blog_list"))
    db = get_db()
    cur = db.execute(
        "INSERT INTO threads (user_id, subject, body, created_at) VALUES (?,?,?,?)",
        (session["user_id"], subject[:140], body[:5000],
         datetime.utcnow().isoformat(timespec="seconds")),
    )
    db.commit()
    flash("Thread posted.", "ok")
    return redirect(url_for("blog_thread", thread_id=cur.lastrowid))


@app.route("/blog/<int:thread_id>", methods=["GET", "POST"])
def blog_thread(thread_id):
    db = get_db()
    thread = db.execute("""
        SELECT t.*, u.username, u.avatar_emoji
        FROM threads t JOIN users u ON u.id = t.user_id
        WHERE t.id = ?
    """, (thread_id,)).fetchone()
    if not thread:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to reply.", "warn")
            return redirect(url_for("login", next=request.path))
        body = (request.form.get("body") or "").strip()
        if body:
            db.execute(
                "INSERT INTO thread_replies (thread_id, user_id, body, created_at) VALUES (?,?,?,?)",
                (thread_id, session["user_id"], body[:5000],
                 datetime.utcnow().isoformat(timespec="seconds")),
            )
            db.commit()
        return redirect(url_for("blog_thread", thread_id=thread_id))

    replies = db.execute("""
        SELECT r.*, u.username, u.avatar_emoji
        FROM thread_replies r JOIN users u ON u.id = r.user_id
        WHERE r.thread_id = ? ORDER BY r.id ASC
    """, (thread_id,)).fetchall()
    return render_template("blog_thread.html", thread=thread, replies=replies)


@app.route("/bulletins/new", methods=["POST"])
@login_required
def post_bulletin():
    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()
    if subject and body:
        db = get_db()
        db.execute(
            "INSERT INTO bulletins (user_id, subject, body, created_at) VALUES (?,?,?,?)",
            (session["user_id"], subject[:120], body[:2000],
             datetime.utcnow().isoformat(timespec="seconds")),
        )
        db.commit()
        flash("Bulletin posted.", "ok")
    return redirect(url_for("home"))


# ---------- Spotify routes ----------

@app.route("/spotify/search")
def spotify_search():
    """Music search across tracks and albums on Spotify."""
    q     = (request.args.get("q") or "").strip()
    types = (request.args.get("type") or "track,album").strip()
    if not q:
        return jsonify({"items": []})
    if not spotify_configured():
        return jsonify({
            "error": "Music search isn't configured. Set SPOTIFY_CLIENT_ID and "
                     "SPOTIFY_CLIENT_SECRET environment variables."
        }), 503
    token = get_app_spotify_token()
    if not token:
        return jsonify({"error": "Couldn't get Spotify token."}), 502
    try:
        r = requests.get(
            "https://api.spotify.com/v1/search",
            headers={"Authorization": f"Bearer {token}"},
            params={"q": q, "type": types, "limit": 6},
            timeout=8,
        )
    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502
    if not r.ok:
        return jsonify({"error": "Music search error", "detail": r.text[:200]}), r.status_code

    payload = r.json()
    items = []

    # tracks
    for t in (payload.get("tracks") or {}).get("items", []) or []:
        album = t.get("album") or {}
        images = album.get("images") or []
        items.append({
            "kind":     "track",
            "id":       t.get("id"),
            "name":     t.get("name"),
            "artists":  ", ".join(a["name"] for a in t.get("artists", [])),
            "album":    album.get("name"),
            "year":     (album.get("release_date") or "")[:4],
            "image":    images[-1]["url"] if images else None,
            "image_lg": images[0]["url"]  if images else None,
            "url":      (t.get("external_urls") or {}).get("spotify"),
            "preview":  t.get("preview_url"),
        })

    # albums
    for a in (payload.get("albums") or {}).get("items", []) or []:
        images = a.get("images") or []
        items.append({
            "kind":     "album",
            "id":       a.get("id"),
            "name":     a.get("name"),
            "artists":  ", ".join(ar["name"] for ar in a.get("artists", [])),
            "album":    a.get("name"),
            "year":     (a.get("release_date") or "")[:4],
            "image":    images[-1]["url"] if images else None,
            "image_lg": images[0]["url"]  if images else None,
            "url":      (a.get("external_urls") or {}).get("spotify"),
            "preview":  None,
        })

    return jsonify({"items": items})


@app.route("/spotify/connect")
@login_required
def spotify_connect():
    if not spotify_configured():
        flash("Spotify isn't configured on this server.", "warn")
        return redirect(url_for("home"))
    state = secrets.token_urlsafe(16)
    session["spotify_oauth_state"] = state
    params = urllib.parse.urlencode({
        "client_id":     SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  SPOTIFY_REDIRECT_URI,
        "scope":         SPOTIFY_SCOPES,
        "state":         state,
        "show_dialog":   "false",
    })
    return redirect("https://accounts.spotify.com/authorize?" + params)


@app.route("/spotify/callback")
@login_required
def spotify_callback():
    if request.args.get("error"):
        flash("Spotify auth canceled.", "warn")
        return redirect(url_for("home"))
    state = request.args.get("state", "")
    saved = session.pop("spotify_oauth_state", None)
    if not saved or saved != state:
        flash("Spotify auth failed (state mismatch).", "warn")
        return redirect(url_for("home"))
    code = request.args.get("code")
    if not code:
        flash("Spotify auth failed (no code).", "warn")
        return redirect(url_for("home"))
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={
                "grant_type":   "authorization_code",
                "code":          code,
                "redirect_uri":  SPOTIFY_REDIRECT_URI,
            },
            timeout=8,
        )
    except requests.RequestException as e:
        flash(f"Spotify token exchange failed: {e}", "warn")
        return redirect(url_for("home"))
    if not r.ok:
        flash("Spotify token exchange failed.", "warn")
        return redirect(url_for("home"))
    d = r.json()
    profile_resp = requests.get(
        "https://api.spotify.com/v1/me",
        headers={"Authorization": f"Bearer {d['access_token']}"},
        timeout=8,
    )
    sp_profile = profile_resp.json() if profile_resp.ok else {}
    db = get_db()
    db.execute(
        """UPDATE users SET spotify_id=?, spotify_access_token=?,
           spotify_refresh_token=?, spotify_token_expires=? WHERE id=?""",
        (sp_profile.get("id"), d.get("access_token"),
         d.get("refresh_token"),
         int(time.time() + d.get("expires_in", 3600)),
         session["user_id"]),
    )
    db.commit()
    flash("Spotify connected.", "ok")
    me = current_user()
    return redirect(url_for("profile", username=me["username"]))


@app.route("/spotify/disconnect", methods=["POST"])
@login_required
def spotify_disconnect():
    db = get_db()
    db.execute(
        """UPDATE users SET spotify_id=NULL, spotify_access_token=NULL,
           spotify_refresh_token=NULL, spotify_token_expires=NULL WHERE id=?""",
        (session["user_id"],),
    )
    db.commit()
    flash("Spotify disconnected.", "ok")
    me = current_user()
    return redirect(url_for("profile", username=me["username"]))


def refresh_user_spotify_token(user_id):
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not row["spotify_refresh_token"]:
        return None
    if row["spotify_token_expires"] and row["spotify_token_expires"] > time.time() + 30:
        return row["spotify_access_token"]
    if not spotify_configured():
        return None
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "refresh_token",
                  "refresh_token": row["spotify_refresh_token"]},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    d = r.json()
    db.execute(
        """UPDATE users SET spotify_access_token=?, spotify_token_expires=? WHERE id=?""",
        (d["access_token"],
         int(time.time() + d.get("expires_in", 3600)),
         user_id),
    )
    db.commit()
    return d["access_token"]


@app.route("/me/spotify/top")
@login_required
def my_spotify_top():
    token = refresh_user_spotify_token(session["user_id"])
    if not token:
        return jsonify({"items": [], "connected": False})
    try:
        r = requests.get(
            "https://api.spotify.com/v1/me/top/tracks",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": 10, "time_range": "short_term"},
            timeout=8,
        )
    except requests.RequestException:
        return jsonify({"items": [], "connected": True})
    if not r.ok:
        return jsonify({"items": [], "connected": True})
    items = [
        {
            "name":    t.get("name"),
            "artists": ", ".join(a["name"] for a in t.get("artists", [])),
            "url":     (t.get("external_urls") or {}).get("spotify"),
            "image":   ((t.get("album") or {}).get("images") or [{}])[-1].get("url"),
        }
        for t in r.json().get("items", [])
    ]
    return jsonify({"items": items, "connected": True})


# ---------- seed ----------

def seed_demo():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.execute("SELECT COUNT(*) c FROM users")
    if cur.fetchone()["c"] > 0:
        db.close()
        return
    users = [
        ("tom",       "myspace",  "Tom",        "Santa Monica, CA",  29, "◉", "sky",     "the original.",                      "i'm here to help.",                                            "Beatles, Superdrag, Radiohead"),
        ("brunette",  "password", "brunette",   "Anywhere, USA",     25, "✦", "sky",     "27 years old, still rating.",        "moody indie & sad-girl rock, mostly.",                         "Tegan and Sara, Mitski, Phoebe Bridgers"),
        ("joey",      "password", "joey",       "Florida",           22, "✿", "sunset",  "florida sunshine state of mind.",    "ex-boyband stan turned hyperpop convert.",                     "100 gecs, Charli XCX, Caroline Polachek"),
        ("kamal",     "password", "kamal",      "Brooklyn, NY",      24, "♪", "cyber",   "catch up. clean up. blog up.",       "writes too many words about three-minute songs.",              "U2, Gomez, Big Thief, Black Country, New Road"),
        ("dustyn",    "password", "Dustyn",     "California",        24, "★", "sky",     "be careful what you put on shuffle.","yacht rock apologist.",                                        "Steely Dan, Toro y Moi, Mac DeMarco"),
        ("layouts",   "password", "layouts",    "Metairie, LA",      28, "□", "cyber",   "code in the morning, drone at night.","makes weird little instrumental loops.",                      "Tim Hecker, Grouper, Aphex Twin"),
        ("anon",      "password", "anon",       "/mu/sic",           19, "?", "cyber",   ">be me >rate songs >mfw",            "no waifu, no laifu. only ratings.",                            "Death Grips, Black Midi, JPEGMAFIA"),
    ]
    now = datetime.utcnow().isoformat(timespec="seconds")
    user_ids = {}
    for u, pw, dn, loc, age, emoji, theme, hl, about, bands in users:
        salt = secrets.token_hex(16)
        h = hash_password(pw, salt)
        c = db.execute(
            """INSERT INTO users
               (username,password_hash,password_salt,display_name,location,age,
                avatar_emoji,theme,headline,about_me,fav_bands,created_at,last_login)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (u, h, salt, dn, loc, age, emoji, theme, hl, about, bands, now, now),
        )
        user_ids[u] = c.lastrowid

    songs = [
        ("Such Great Heights",  "The Postal Service",   "Give Up",                                  2003, "indie",    None, "brunette"),
        ("Hey Ya!",             "OutKast",              "Speakerboxxx/The Love Below",              2003, "hip-hop",  None, "tom"),
        ("Mr. Brightside",      "The Killers",          "Hot Fuss",                                 2003, "rock",     None, "dustyn"),
        ("Since U Been Gone",   "Kelly Clarkson",       "Breakaway",                                2004, "pop",      None, "joey"),
        ("Float On",            "Modest Mouse",         "Good News for People Who Love Bad News",   2004, "indie",    None, "kamal"),
        ("Crazy In Love",       "Beyoncé",              "Dangerously in Love",                      2003, "r&b",      None, "layouts"),
        ("Karma Police",        "Radiohead",            "OK Computer",                              1997, "alt-rock", None, "tom"),
        ("Maps",                "Yeah Yeah Yeahs",      "Fever to Tell",                            2003, "indie",    None, "brunette"),
        ("Hollaback Girl",      "Gwen Stefani",         "Love. Angel. Music. Baby.",                2004, "pop",      None, "joey"),
        ("Take Me Out",         "Franz Ferdinand",      "Franz Ferdinand",                          2004, "rock",     None, "kamal"),
        ("Not Allowed",         "TV Girl",              "French Exit",                              2014, "indie",    None, "brunette"),
        ("DUCKWORTH.",          "Kendrick Lamar",       "DAMN.",                                    2017, "hip-hop",  None, "anon"),
    ]
    song_ids = []
    for t, a, al, y, g, l, u in songs:
        meta = _spotify_lookup_track(t, a) or {}
        c = db.execute(
            """INSERT INTO songs
               (title,artist,album,year,genre,link,submitted_by,created_at,
                spotify_id,spotify_url,spotify_image,spotify_preview_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t, a, al, y, g, l or meta.get("url"), user_ids[u], now,
             meta.get("id"), meta.get("url"), meta.get("image"), meta.get("preview")),
        )
        song_ids.append(c.lastrowid)

    import random
    rng = random.Random(7)
    reviews_pool = [
        "absolute banger. headphones-on, eyes-closed material.",
        ">be me\n>hear this song\n>cry\n>repeat",
        "kind of mid honestly. structure's fine, vocals are doing too much.",
        "10/10 makes me wanna cry & dance at the same time",
        "best song of the decade no contest. fight me.",
        "the production sits right between maximalist and tasteful. love it.",
        ">tfw no chorus this good in my life",
        "skipped after 30sec. sorry.",
        "iconic. period.",
        "this would be a 10 if not for the bridge. that bridge is a 4.",
        "",
        "",
    ]
    for sid in song_ids:
        raters = rng.sample(list(user_ids.values()), rng.randint(3, 6))
        for uid in raters:
            stars = rng.choices([2,3,4,5], weights=[1,3,5,4])[0]
            db.execute(
                """INSERT INTO ratings (song_id,user_id,stars,review,created_at)
                   VALUES (?,?,?,?,?)""",
                (sid, uid, stars, rng.choice(reviews_pool), now),
            )

    bulletins = [
        ("brunette", "new TV Girl rate just dropped",        "no notes. perfect 9.0."),
        ("kamal",    "Pitchfork is wrong about the new BCNR","change my mind in the comments."),
        ("joey",     "hyperpop is real music",                ">be me\n>defend Charli\n>get bullied\n>still right"),
        ("layouts",  "playlist: studio bg loops",             "uploaded 12 ambient loops. take em or leave em."),
        ("tom",      "Pacer is live",                         "trending tracks, new look, same ratings."),
        ("anon",     "rate my taste",                         ">>1\nstop projecting"),
    ]
    for u, s, b in bulletins:
        db.execute(
            "INSERT INTO bulletins (user_id,subject,body,created_at) VALUES (?,?,?,?)",
            (user_ids[u], s, b, now),
        )

    comments = [
        ("brunette", "joey",    "your taste is so unhinged i love it"),
        ("brunette", "tom",     "thanks for the add"),
        ("kamal",    "dustyn",  "we are gonna disagree about steely dan forever"),
        ("joey",     "layouts", "send me ur drone loops pls"),
        ("tom",      "anon",    "less greentext, more reviews"),
        ("anon",     "tom",     ">no\n>>1\nyou first"),
    ]
    for profile_u, author_u, body in comments:
        db.execute(
            "INSERT INTO comments (profile_id,author_id,body,created_at) VALUES (?,?,?,?)",
            (user_ids[profile_u], user_ids[author_u], body, now),
        )

    seed_threads = [
        ("brunette", "what's the best album of the last 5 years?",
         "going to bat for Punisher. annual replay every fall, every fall it still hits.\n"
         "what's yours? defend your pick."),
        ("kamal", "is hyperpop dead?",
         ">say hyperpop is dead\n>get told to listen to the new 100 gecs\n>turns out it was fine\n"
         "honest take: the scene's mainstream era is over, the experimental wing is healthier than ever."),
        ("anon", "rate my last.fm",
         ">3 plays of mclusky\n>500 plays of one Carly Rae Jepsen song\n"
         "be honest. no mercy."),
        ("dustyn", "yacht rock starter pack",
         "for friends new to the genre. ranked:\n"
         "1. Aja - Steely Dan\n"
         "2. Christopher Cross s/t\n"
         "3. Off the Wall\n"
         "fight me on the order."),
        ("layouts", "ambient album recommendations",
         "I've been on a Tim Hecker kick for months. need fresh stuff.\n"
         "drone, modular, field recording — anything goes. drop names."),
    ]
    thread_ids = {}
    for u, subj, body in seed_threads:
        c = db.execute(
            "INSERT INTO threads (user_id, subject, body, created_at) VALUES (?,?,?,?)",
            (user_ids[u], subj, body, now),
        )
        thread_ids[subj] = c.lastrowid

    seed_replies = [
        ("what's the best album of the last 5 years?", "joey",    "obvious answer is Charli XCX - BRAT. sorry not sorry."),
        ("what's the best album of the last 5 years?", "kamal",   "Black Country, New Road - Ants From Up There. closes the case."),
        ("what's the best album of the last 5 years?", "anon",    ">>1\nBRAT is fine but it isn't even her best."),
        ("is hyperpop dead?",                          "joey",    "hyperpop didn't die, it just got distributed across mainstream pop production. listen to any top 40 track lately."),
        ("is hyperpop dead?",                          "tom",     "kinda agree. the boundary moved."),
        ("rate my last.fm",                            "brunette","this is a cry for help."),
        ("rate my last.fm",                            "kamal",   "the carly rae fixation is correct, the mclusky shame is not."),
        ("yacht rock starter pack",                    "kamal",   "putting Off the Wall in yacht rock is a crime"),
        ("yacht rock starter pack",                    "tom",     "actually Off the Wall has yacht rock energy throughout. hot take respected."),
        ("ambient album recommendations",              "brunette","Grouper - Ruins. recorded in a tiny house in Portugal. unbeatable."),
        ("ambient album recommendations",              "anon",    "Stars of the Lid - The Tired Sounds of. don't sleep on it (but also do)."),
    ]
    for subj, author, body in seed_replies:
        tid = thread_ids.get(subj)
        if not tid:
            continue
        db.execute(
            "INSERT INTO thread_replies (thread_id, user_id, body, created_at) VALUES (?,?,?,?)",
            (tid, user_ids[author], body, now),
        )

    db.commit()
    db.close()


@app.cli.command("init-db")
def init_db_cmd():
    init_db()
    seed_demo()
    backfill_covers_from_spotify()
    print("DB ready at", DB_PATH)


if __name__ == "__main__":
    init_db()
    seed_demo()
    backfill_covers_from_spotify()
    app.run(host="127.0.0.1", port=5000, debug=True)
