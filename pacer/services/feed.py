import sqlite3 as _sqlite3

from pacer.config import DB_PATH as _DB_PATH
from pacer.db import get_db


def backfill_artist_stubs() -> int:
    """Create stub artist rows for any album whose artist_id is NULL but
    discogs_artists is set. Idempotent. Returns the number of stubs created.
    """
    try:
        db = get_db()
        _owns = False
    except RuntimeError:
        db = _sqlite3.connect(_DB_PATH)
        db.row_factory = _sqlite3.Row
        _owns = True
    try:
        rows = db.execute(
            "SELECT id, artist, discogs_artists FROM albums "
            "WHERE artist_id IS NULL AND discogs_artists IS NOT NULL AND discogs_artists != ''"
        ).fetchall()
        created = 0
        for r in rows:
            first = (r["discogs_artists"] or "").split(",")[0].strip()
            if not first:
                continue
            existing = db.execute(
                "SELECT id FROM artists WHERE name = ? COLLATE NOCASE LIMIT 1",
                (first,),
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE albums SET artist_id = ? WHERE id = ?",
                    (existing["id"], r["id"]),
                )
                continue
            cur = db.execute(
                """INSERT INTO artists (spotify_id, name) VALUES (?, ?)""",
                (f"discogs-stub:{first}", first[:120]),
            )
            new_id = cur.lastrowid
            db.execute(
                "UPDATE albums SET artist_id = ? WHERE id = ?",
                (new_id, r["id"]),
            )
            created += 1
            print(f"[backfill] Created stub artist {first!r} (id={new_id}) for album id={r['id']}")
        if created:
            db.commit()
        return created
    finally:
        if _owns:
            db.close()


def get_timeline(offset=0, limit=20):
    """
    Get unified feed timeline: posts + activities + reposts, sorted by created_at DESC.
    Returns list of dicts with type, id, user info, content, and metadata.
    """
    db = get_db()
    items = db.execute("""
        SELECT * FROM (
            SELECT 'post' as item_type, p.id, p.user_id, p.body, p.song_id, p.album_id,
                   NULL as rating_stars, NULL as activity_type, p.created_at,
                   u.username, u.display_name, u.avatar_emoji, u.profile_pic_cid,
                   p.image_cid, NULL as playlist_id
            FROM posts p
            JOIN users u ON p.user_id = u.id
            UNION ALL
            SELECT 'activity' as item_type, a.id, a.user_id, NULL as body, a.song_id, a.album_id,
                   a.rating_stars, a.type as activity_type, a.created_at,
                   u.username, u.display_name, u.avatar_emoji, u.profile_pic_cid,
                   NULL as image_cid, a.playlist_id
            FROM activities a
            JOIN users u ON a.user_id = u.id
            UNION ALL
            SELECT 'repost' as item_type, r.id, r.user_id, NULL as body,
                   COALESCE(p.song_id, a.song_id) as song_id,
                   COALESCE(p.album_id, a.album_id) as album_id,
                   a.rating_stars, a.type as activity_type, r.created_at,
                   u.username, u.display_name, u.avatar_emoji, u.profile_pic_cid,
                   NULL as image_cid, NULL as playlist_id
            FROM reposts r
            JOIN users u ON r.user_id = u.id
            LEFT JOIN posts p ON r.post_id = p.id
            LEFT JOIN activities a ON r.activity_id = a.id
        ) ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset)).fetchall()

    # Enrich with counts and song/album info
    result = []
    for item in items:
        item_dict = dict(item)
        item_type = item_dict["item_type"]
        item_id = item_dict["id"]

        # Get counts
        if item_type == "post":
            item_dict["like_count"] = db.execute(
                "SELECT COUNT(*) as c FROM likes WHERE post_id = ?", (item_id,)
            ).fetchone()["c"]
            item_dict["reply_count"] = db.execute(
                "SELECT COUNT(*) as c FROM replies WHERE post_id = ?", (item_id,)
            ).fetchone()["c"]
            item_dict["repost_count"] = db.execute(
                "SELECT COUNT(*) as c FROM reposts WHERE post_id = ?", (item_id,)
            ).fetchone()["c"]
        elif item_type == "activity":
            item_dict["like_count"] = db.execute(
                "SELECT COUNT(*) as c FROM likes WHERE activity_id = ?", (item_id,)
            ).fetchone()["c"]
            item_dict["reply_count"] = db.execute(
                "SELECT COUNT(*) as c FROM replies WHERE activity_id = ?", (item_id,)
            ).fetchone()["c"]
            item_dict["repost_count"] = db.execute(
                "SELECT COUNT(*) as c FROM reposts WHERE activity_id = ?", (item_id,)
            ).fetchone()["c"]
        else:
            item_dict["like_count"] = 0
            item_dict["reply_count"] = 0
            item_dict["repost_count"] = 0

        # Get song/album info if attached
        if item_dict.get("song_id"):
            item_dict["song"] = db.execute(
                "SELECT id, title, artist, spotify_id, spotify_image FROM songs WHERE id = ?",
                (item_dict["song_id"],)
            ).fetchone()
        if item_dict.get("album_id"):
            item_dict["album"] = db.execute(
                "SELECT id, name, artist, spotify_id, spotify_image FROM albums WHERE id = ?",
                (item_dict["album_id"],)
            ).fetchone()

        if item_dict.get("playlist_id"):
            item_dict["playlist"] = db.execute(
                "SELECT id, name FROM playlists WHERE id = ?",
                (item_dict["playlist_id"],)
            ).fetchone()
            # Get playlist tracks
            item_dict["playlist_tracks"] = db.execute("""
                SELECT s.id, s.title, s.artist, s.spotify_id FROM playlist_tracks pt
                JOIN songs s ON pt.song_id = s.id
                WHERE pt.playlist_id = ?
                ORDER BY pt.position
            """, (item_dict["playlist_id"],)).fetchall()

        result.append(item_dict)

    return result


def create_activity(user_id, activity_type, song_id=None, album_id=None, rating_stars=None, playlist_id=None):
    """Insert an activity record into the feed."""
    db = get_db()
    db.execute(
        "INSERT INTO activities (user_id, type, song_id, album_id, rating_stars, playlist_id) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, activity_type, song_id, album_id, rating_stars, playlist_id)
    )
    db.commit()


def has_user_liked(user_id, item_type, item_id):
    """Check if user has liked a post or activity."""
    if not user_id:
        return False
    db = get_db()
    if item_type == "post":
        row = db.execute("SELECT id FROM likes WHERE user_id = ? AND post_id = ?", (user_id, item_id)).fetchone()
    else:
        row = db.execute("SELECT id FROM likes WHERE user_id = ? AND activity_id = ?", (user_id, item_id)).fetchone()
    return row is not None


def has_user_reposted(user_id, item_type, item_id):
    """Check if user has reposted a post or activity."""
    if not user_id:
        return False
    db = get_db()
    if item_type == "post":
        row = db.execute("SELECT id FROM reposts WHERE user_id = ? AND post_id = ?", (user_id, item_id)).fetchone()
    else:
        row = db.execute("SELECT id FROM reposts WHERE user_id = ? AND activity_id = ?", (user_id, item_id)).fetchone()
    return row is not None


def get_replies(item_type, item_id):
    """Get replies for a post or activity."""
    db = get_db()
    if item_type == "post":
        return db.execute("""
            SELECT r.*, u.username, u.display_name, u.avatar_emoji
            FROM replies r JOIN users u ON r.user_id = u.id
            WHERE r.post_id = ?
            ORDER BY r.created_at ASC
        """, (item_id,)).fetchall()
    else:
        return db.execute("""
            SELECT r.*, u.username, u.display_name, u.avatar_emoji
            FROM replies r JOIN users u ON r.user_id = u.id
            WHERE r.activity_id = ?
            ORDER BY r.created_at ASC
        """, (item_id,)).fetchall()
