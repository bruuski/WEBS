"""Music routes: browse songs, song detail, album detail, Spotify imports."""

import sqlite3 as _sqlite3
from datetime import datetime
from datetime import datetime as _dt

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from pacer.config import DB_PATH as _DB_PATH
from pacer.db import get_db
from pacer.helpers import current_user, login_required
from pacer.services import discogs  # no-op shim, kept for legacy guards
from pacer.services.feed import create_activity
from pacer.services.spotify import (
    get_album as sp_get_album,
    get_artist as sp_get_artist,
    get_artist_albums as sp_get_artist_albums,
    get_artist_top_tracks as sp_get_artist_top_tracks,
    get_track as sp_get_track,
    lookup_spotify_preview,
    spotify_configured,
)

def find_or_create_song_from_spotify(spotify_meta: dict) -> dict | None:
    """Persist a Spotify trending/search result as a local songs row.

    Looks up Discogs metadata (artist profile, release details, styles).
    If Discogs has no match, saves the song with NULL Discogs columns —
    the song page will simply hide the 'Catalog' panel.

    Args:
        spotify_meta: dict with keys: id, name, artists, image, (optional) url

    Returns:
        The persisted song row as a sqlite3.Row, or None if no users exist
        in the DB to assign as submitter.
    """
    import sqlite3 as _sqlite3
    from datetime import datetime as _dt
    from pacer.config import DB_PATH as _DB_PATH

    # Use the Flask per-request connection when available, otherwise open a
    # direct connection. This lets the helper be called from routes (with app
    # context) and from unit tests (no app context) using the same DB_PATH.
    try:
        db = get_db()
        _owns_connection = False
    except RuntimeError:
        db = _sqlite3.connect(_DB_PATH)
        db.row_factory = _sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        _owns_connection = True

    try:
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
            return None
        submitter_id = submitter["id"]

        # 3. Lookup Discogs
        discogs_release_id = None
        discogs_artist_id  = None
        style_rows = []

        # Always call the Discogs helpers; they short-circuit to None when
        # the client is not configured (and tests can monkeypatch them).
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
                                    namevariations)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                                (f"discogs:{a_data['id']}",
                                 a_data["id"], a_data["name"], a_data["real_name"],
                                 a_data["profile"],
                                 ", ".join(a_data["aliases"]),
                                 ", ".join(a_data["members"]),
                                 ", ".join(a_data["urls"]),
                                 ", ".join(a_data["name_variations"])),
                            )
                            discogs_artist_id = cur.lastrowid

        # 4. Cache preview (best effort, ignore failure)
        try:
            lookup_spotify_preview(artist, title)
        except Exception:
            pass

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
    finally:
        if _owns_connection:
            db.close()


bp = Blueprint("music", __name__)


def _create_song_from_discogs_release(release: dict, track: dict, artists: str):
    """Create a songs row from a Discogs release + one of its tracks.

    Returns song_id or None. Callable both inside and outside Flask app context
    (matches the pattern of find_or_create_song_from_spotify).
    """
    try:
        db = get_db()
        _owns_connection = False
    except RuntimeError:
        db = _sqlite3.connect(_DB_PATH)
        db.row_factory = _sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        _owns_connection = True

    try:
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
    finally:
        if _owns_connection:
            db.close()


def _find_or_create_album_from_discogs(discogs_id: int):
    """Look up album by Discogs ID; create if missing. Returns album_id or None.

    The submitter is the first user in the DB (same convention as
    find_or_create_song_from_spotify). If no user exists, returns None.
    """
    try:
        db = get_db()
        _owns_connection = False
    except RuntimeError:
        db = _sqlite3.connect(_DB_PATH)
        db.row_factory = _sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        _owns_connection = True

    try:
        existing = db.execute(
            "SELECT id FROM albums WHERE discogs_release_id = ?", (discogs_id,)
        ).fetchone()
        if existing:
            return existing["id"]

        release = discogs.get_release(discogs_id)
        if not release:
            return None

        artists = ", ".join(release.get("artists", []))
        submitter = db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
        if not submitter:
            return None

        # Use the first track's cover_image / image to seed spotify_image
        cover = release.get("cover_image") or release.get("thumb")

        cur = db.execute(
            """INSERT INTO albums
               (name, artist, year, created_at,
                submitted_by,
                cover_image, spotify_image,
                discogs_release_id, discogs_master_id,
                label, catalog_no, country, format,
                discogs_artists)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (release.get("title", "")[:200], artists[:120],
             release.get("year"),
             _dt.utcnow().isoformat(timespec="seconds"),
             submitter["id"],
             cover, cover,
             release.get("id"), release.get("master_id"),
             release.get("label"), release.get("catalog_no"),
             release.get("country"),
             ", ".join(release.get("format", []) or []),
             artists[:200]),
        )
        album_id = cur.lastrowid

        # Insert styles into album_styles if there are any
        for s in release.get("styles", []):
            if s:
                db.execute(
                    "INSERT OR IGNORE INTO album_styles (album_id, style) VALUES (?, ?)",
                    (album_id, s),
                )
        db.commit()
        return album_id
    finally:
        if _owns_connection:
            db.close()


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
        # Round to nearest 0.5
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
              datetime.utcnow().isoformat(timespec="seconds")))
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
        # Round to nearest 0.5
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
              datetime.utcnow().isoformat(timespec="seconds")))
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

    # Tracklist: prefer Discogs catalog; fall back to empty list (Spotify fallback
    # path was removed in Task 2.2).
    tracks = []
    if catalog:
        tracks = catalog.get("tracklist", [])

    # Look up styles from album_styles table
    styles = [
        r["style"] for r in db.execute(
            "SELECT style FROM album_styles WHERE album_id = ? ORDER BY style",
            (album_id,),
        ).fetchall()
    ]

    # Look up artist row
    artist = None
    if album["artist_id"]:
        artist = db.execute(
            "SELECT * FROM artists WHERE id = ?", (album["artist_id"],)
        ).fetchone()
    # Fallback: if no artist_id but we have an artist name, try to find the
    # artist row by name (covers legacy albums from pre-Discogs-first era)
    if not artist and album["artist"]:
        artist = db.execute(
            "SELECT * FROM artists WHERE name = ? COLLATE NOCASE LIMIT 1",
            (album["artist"],),
        ).fetchone()
    # If still no artist row but we have a Discogs artist ID cached, create a
    # minimal stub so the artist link works (full enrichment happens lazily
    # when the user visits the artist page).
    if not artist and album["discogs_artists"]:
        first_discogs_artist = album["discogs_artists"].split(",")[0].strip()
        if first_discogs_artist:
            cur = db.execute(
                """INSERT INTO artists (spotify_id, name) VALUES (?, ?)""",
                (f"discogs-stub:{first_discogs_artist}", first_discogs_artist[:120]),
            )
            artist_id = cur.lastrowid
            # Link the album to the new artist
            db.execute("UPDATE albums SET artist_id = ? WHERE id = ?", (artist_id, album_id))
            db.commit()
            artist = db.execute(
                "SELECT * FROM artists WHERE id = ?", (artist_id,)
            ).fetchone()
            print(f"[album-detail] Created stub artist row for {first_discogs_artist!r} (id={artist_id})")

    return render_template(
        "album.html",
        album=album, stats=stats, histogram=histogram, max_h=max_h,
        reviews=reviews, featured=featured, my_rating=my_rating,
        tracks=tracks, catalog=catalog,
        styles=styles, artist=artist,
    )


@bp.route("/track/spotify/<ref>")
def track_from_spotify(ref):
    """Resolve a Spotify track ID to a local song page, creating the row if needed."""
    if not spotify_configured():
        flash("Spotify isn't configured on this server.", "warn")
        return redirect(url_for("music.browse"))
    track = sp_get_track(ref)
    if not track:
        flash("Couldn't look up that track on Spotify.", "warn")
        return redirect(url_for("music.browse"))
    song_row = find_or_create_song_from_spotify({
        "id":      track["spotify_id"],
        "name":    track["name"],
        "artists": track["artists"],
        "image":   track["image_lg"] or track["image"],
        "url":     track["url"],
    })
    if not song_row:
        flash("Couldn't create song record.", "warn")
        return redirect(url_for("music.browse"))
    # Also populate album/year/spotify_artist_id and link to artist row
    db = get_db()
    artist_local_id = None
    if track.get("spotify_artist_id"):
        artist_local_id = _find_or_create_artist_from_spotify(track["spotify_artist_id"])
    db.execute(
        """UPDATE songs SET
              album               = COALESCE(NULLIF(album,''), ?),
              year                = COALESCE(year, ?),
              spotify_artist_id   = COALESCE(NULLIF(spotify_artist_id,''), ?),
              spotify_preview_url = COALESCE(NULLIF(spotify_preview_url,''), ?),
              artist_id           = COALESCE(artist_id, ?)
           WHERE id = ?""",
        (
            track.get("album_name"),
            int(track["year"]) if track.get("year") and track["year"].isdigit() else None,
            track.get("spotify_artist_id"),
            track.get("preview_url"),
            artist_local_id,
            song_row["id"],
        ),
    )
    db.commit()
    return redirect(url_for("music.song_detail", song_id=song_row["id"]))


@bp.route("/album/spotify/<ref>")
def album_from_spotify(ref):
    """Resolve a Spotify album ID to a local album page, creating the row if needed."""
    if not spotify_configured():
        flash("Spotify isn't configured on this server.", "warn")
        return redirect(url_for("music.browse"))
    db = get_db()
    existing = db.execute(
        "SELECT id FROM albums WHERE spotify_id = ?", (ref,)
    ).fetchone()
    if existing:
        return redirect(url_for("music.album_detail", album_id=existing["id"]))
    album = sp_get_album(ref)
    if not album:
        flash("Couldn't look up that album on Spotify.", "warn")
        return redirect(url_for("music.browse"))
    submitter = db.execute("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if not submitter:
        flash("No users in the database yet.", "warn")
        return redirect(url_for("music.browse"))
    year = int(album["year"]) if album.get("year") and album["year"].isdigit() else None
    cur = db.execute(
        """INSERT INTO albums
           (name, artist, year, created_at, submitted_by,
            spotify_id, spotify_url, spotify_image,
            spotify_artist_id, format, cover_image)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (album["name"][:200], album["artist"][:120], year,
         datetime.utcnow().isoformat(timespec="seconds"),
         submitter["id"],
         album["spotify_id"], album["url"], album["image_lg"] or album["image"],
         album.get("spotify_artist_id"), album.get("format"),
         album["image_lg"] or album["image"]),
    )
    album_id = cur.lastrowid
    # Link to artist row (create if missing)
    if album.get("spotify_artist_id"):
        artist_id = _find_or_create_artist_from_spotify(album["spotify_artist_id"])
        if artist_id:
            db.execute("UPDATE albums SET artist_id = ? WHERE id = ?", (artist_id, album_id))
    db.commit()
    return redirect(url_for("music.album_detail", album_id=album_id))


def _find_or_create_artist_from_spotify(spotify_id: str):
    """Find or create the local artists row for a Spotify artist ID."""
    if not spotify_id:
        return None
    db = get_db()
    row = db.execute("SELECT id FROM artists WHERE spotify_id = ?", (spotify_id,)).fetchone()
    if row:
        return row["id"]
    artist = sp_get_artist(spotify_id)
    if not artist:
        return None
    try:
        cur = db.execute(
            """INSERT INTO artists (spotify_id, name, image_url, genres,
                                    popularity, spotify_url)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (artist["spotify_id"], artist["name"][:120],
             artist.get("image_url"),
             ", ".join(artist.get("genres") or [])[:200],
             artist.get("popularity") or 0,
             artist.get("spotify_url")),
        )
        db.commit()
        return cur.lastrowid
    except _sqlite3.IntegrityError:
        row = db.execute("SELECT id FROM artists WHERE spotify_id = ?", (spotify_id,)).fetchone()
        return row["id"] if row else None


@bp.route("/artists/<int:artist_id>")
def artist_detail(artist_id):
    db = get_db()
    artist = db.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
    if not artist:
        abort(404)

    # Discogs enrichment (with auto-enrichment for stub artists)
    artist_info = None
    discogs_artist_id = artist["discogs_id"]

    # Stub artist (created by album_detail backfill) — needs lazy enrichment
    is_stub = (artist["spotify_id"] or "").startswith("discogs-stub:")
    if is_stub and not discogs_artist_id and discogs.discogs_configured():
        try:
            match = discogs.find_artist_by_name(artist["name"])
            if match and (match.get("discogs_id") or match.get("id")):
                real_id = match.get("discogs_id") or match.get("id")
                # Update local row with the real Discogs id so future requests are fast
                db.execute(
                    "UPDATE artists SET discogs_id = ?, image_url = COALESCE(?, image_url) WHERE id = ?",
                    (real_id, match.get("thumb") or match.get("cover_image"), artist_id),
                )
                db.commit()
                discogs_artist_id = real_id
                print(f"[artist-detail] Enriched stub artist {artist['name']!r} -> discogs_id={real_id}")
        except Exception as e:
            print(f"[artist-detail] Stub enrichment failed for {artist['name']!r}: {e}")
            discogs_artist_id = None

    # Real fetch
    if discogs_artist_id and discogs.discogs_configured():
        try:
            artist_info = discogs.get_artist(discogs_artist_id)
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

    # Top tracks + albums: pull from Spotify when we have a spotify_id;
    # fall back to DB-only otherwise. Both Spotify calls are TTL-cached so
    # repeated views of this page don't re-fetch.
    sp_id = artist["spotify_id"] if artist["spotify_id"] and not (artist["spotify_id"] or "").startswith("discogs") else None

    top_tracks_rows = db.execute("""
        SELECT s.id, s.title, s.album, s.year, s.spotify_id, s.spotify_image,
               COALESCE(AVG(r.stars), 0) as avg_stars, COUNT(r.id) as rating_count
        FROM songs s LEFT JOIN ratings r ON r.song_id = s.id
        WHERE s.artist_id = ?
        GROUP BY s.id ORDER BY avg_stars DESC LIMIT 10
    """, (artist_id,)).fetchall()

    top_tracks = []
    if sp_id:
        sp_top = sp_get_artist_top_tracks(sp_id)
        # Template expects: spotify_id, name, album_name, duration_ms
        for t in sp_top:
            top_tracks.append({
                "spotify_id":  t["spotify_id"],
                "name":        t["name"],
                "album_name":  t["album_name"] or "",
                "duration_ms": t["duration_ms"],
            })
    # Always also expose the locally-rated tracks (which include rating averages)
    if not top_tracks:
        for r in top_tracks_rows:
            top_tracks.append({
                "spotify_id":  r["spotify_id"] or "",
                "name":        r["title"],
                "album_name":  r["album"] or "",
                "duration_ms": 0,
            })

    db_albums = db.execute("""
        SELECT id, name, year, format, spotify_id, spotify_image,
               cover_image, discogs_release_id, release_url
        FROM albums
        WHERE artist_id = ?
        ORDER BY year DESC
    """, (artist_id,)).fetchall()

    if sp_id:
        sp_albums = sp_get_artist_albums(sp_id, limit=24)
        # Merge: local rows (if any) + Spotify rows. Use Spotify shape that the
        # template already expects (cover_image / spotify_image / name / year / format).
        seen = {(r["spotify_id"] or "") for r in db_albums}
        merged = [dict(r) for r in db_albums]
        for sa in sp_albums:
            if sa["spotify_id"] in seen:
                continue
            merged.append({
                "id":                 None,           # not in local DB yet
                "name":               sa["name"],
                "year":               int(sa["year"]) if sa["year"] and sa["year"].isdigit() else None,
                "format":             sa.get("format"),
                "spotify_id":         sa["spotify_id"],
                "spotify_image":      sa["image_lg"] or sa["image"],
                "cover_image":        sa["image_lg"] or sa["image"],
                "discogs_release_id": None,
                "release_url":        sa["url"],
            })
        albums = merged
    else:
        albums = db_albums

    return render_template("artist.html",
        artist=artist, artist_info=artist_info,
        top_tracks=top_tracks, albums=albums,
        avg_song_rating=avg_song_rating,
        avg_album_rating=avg_album_rating,
    )


@bp.route("/artist/spotify/<spotify_id>")
def artist_from_spotify(spotify_id):
    """Resolve a Spotify artist ID to a local artist page, creating the row if needed."""
    if not spotify_configured():
        flash("Spotify isn't configured on this server.", "warn")
        return redirect(url_for("feed.home"))
    artist_id = _find_or_create_artist_from_spotify(spotify_id)
    if not artist_id:
        flash("Couldn't look up that artist on Spotify.", "warn")
        return redirect(url_for("feed.home"))
    return redirect(url_for("music.artist_detail", artist_id=artist_id))
