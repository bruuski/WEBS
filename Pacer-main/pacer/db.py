import sqlite3

from flask import g

from pacer.config import DB_PATH

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
    stars     REAL NOT NULL CHECK (stars BETWEEN 1 AND 5),
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
    stars     REAL NOT NULL CHECK (stars BETWEEN 1 AND 5),
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

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id),
    album_id INTEGER REFERENCES albums(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    type TEXT NOT NULL,
    song_id INTEGER REFERENCES songs(id),
    album_id INTEGER REFERENCES albums(id),
    rating_stars INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS likes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    post_id INTEGER REFERENCES posts(id),
    activity_id INTEGER REFERENCES activities(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, post_id),
    UNIQUE(user_id, activity_id)
);

CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    post_id INTEGER REFERENCES posts(id),
    activity_id INTEGER REFERENCES activities(id),
    body TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reposts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    post_id INTEGER REFERENCES posts(id),
    activity_id INTEGER REFERENCES activities(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, post_id),
    UNIQUE(user_id, activity_id)
);

-- Discogs-first layer tables (2026-06-10)
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
        ("artist_id",           "INTEGER REFERENCES artists(id)"),
        ("spotify_artist_id",   "TEXT"),
    ]:
        if col not in song_cols:
            con.execute(f"ALTER TABLE songs ADD COLUMN {col} {ddl}")
    album_cols = existing("albums")
    if "artist_id" not in album_cols:
        con.execute("ALTER TABLE albums ADD COLUMN artist_id INTEGER REFERENCES artists(id)")
    if "spotify_artist_id" not in album_cols:
        con.execute("ALTER TABLE albums ADD COLUMN spotify_artist_id TEXT")
    for col, ddl in [
        ("profile_pic_cid",    "TEXT"),
        ("background_cid",     "TEXT"),
        ("background_preset",  "TEXT"),
        ("status_message",     "TEXT"),
    ]:
        if col not in user_cols:
            con.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
    # Post image
    post_cols = existing("posts")
    if "image_cid" not in post_cols:
        con.execute("ALTER TABLE posts ADD COLUMN image_cid TEXT")

    # Reply song and image
    reply_cols = existing("replies")
    if "image_cid" not in reply_cols:
        con.execute("ALTER TABLE replies ADD COLUMN image_cid TEXT")
    if "song_id" not in reply_cols:
        con.execute("ALTER TABLE replies ADD COLUMN song_id INTEGER REFERENCES songs(id)")

    # Thread attachments
    thread_cols = set(existing("threads"))
    if "image_cid" not in thread_cols:
        con.execute("ALTER TABLE threads ADD COLUMN image_cid TEXT")
    if "song_id" not in thread_cols:
        con.execute("ALTER TABLE threads ADD COLUMN song_id INTEGER REFERENCES songs(id)")

    # Thread reply attachments
    treply_cols = set(existing("thread_replies"))
    if "image_cid" not in treply_cols:
        con.execute("ALTER TABLE thread_replies ADD COLUMN image_cid TEXT")
    if "song_id" not in treply_cols:
        con.execute("ALTER TABLE thread_replies ADD COLUMN song_id INTEGER REFERENCES songs(id)")

    # Palette migration
    user_cols_set = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
    if "palette" not in user_cols_set:
        con.execute("ALTER TABLE users ADD COLUMN palette TEXT DEFAULT 'modern'")

    # Activity playlist_id
    activity_cols = {r[1] for r in con.execute("PRAGMA table_info(activities)").fetchall()}
    if "playlist_id" not in activity_cols:
        con.execute("ALTER TABLE activities ADD COLUMN playlist_id INTEGER REFERENCES playlists(id)")

    # Discogs-first layer migrations (2026-06-10)
    artist_cols = existing("artists")
    for col, ddl in [
        ("discogs_id",        "INTEGER"),
        ("real_name",         "TEXT"),
        ("profile_text",      "TEXT"),
        ("aliases",           "TEXT"),
        ("members",           "TEXT"),
        ("urls",              "TEXT"),
        ("namevariations",    "TEXT"),
    ]:
        if col not in artist_cols:
            con.execute(f"ALTER TABLE artists ADD COLUMN {col} {ddl}")
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_artists_discogs_id ON artists(discogs_id)"
    )

    song_cols_discogs = existing("songs")
    for col, ddl in [
        ("discogs_release_id",   "INTEGER"),
        ("discogs_master_id",    "INTEGER"),
        ("position_in_release",  "INTEGER"),
        ("duration_ms",          "INTEGER"),
        ("discogs_artists",      "TEXT"),
    ]:
        if col not in song_cols_discogs:
            con.execute(f"ALTER TABLE songs ADD COLUMN {col} {ddl}")

    album_cols_discogs = existing("albums")
    for col, ddl in [
        ("discogs_release_id",   "INTEGER"),
        ("discogs_master_id",    "INTEGER"),
        ("label",                "TEXT"),
        ("format",               "TEXT"),
        ("country",              "TEXT"),
        ("catalog_no",           "TEXT"),
        ("release_url",          "TEXT"),
        ("master_url",           "TEXT"),
        ("cover_image",          "TEXT"),
        ("submitted_by",         "INTEGER REFERENCES users(id)"),
        ("discogs_artists",      "TEXT"),
    ]:
        if col not in album_cols_discogs:
            con.execute(f"ALTER TABLE albums ADD COLUMN {col} {ddl}")
    con.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_albums_discogs_release_id "
        "ON albums(discogs_release_id)"
    )

    con.commit()
    con.close()
