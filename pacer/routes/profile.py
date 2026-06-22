"""Profile view and edit routes."""

from datetime import datetime

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for,
)

from pacer.db import get_db
from pacer.helpers import current_user, login_required
from pacer.services.feed import create_activity

bp = Blueprint("profile", __name__)


# ---------- Upload ----------

@bp.route("/profile/upload", methods=["POST"])
@login_required
def upload_file():
    from pacer.services.pinata import upload_to_pinata, pinata_configured
    if not pinata_configured():
        flash("File upload not configured")
        return redirect(url_for("profile.edit_profile"))
    user = current_user()
    db = get_db()
    upload_type = request.form.get("upload_type")
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


# ---------- Pin / Unpin ----------

@bp.route("/profile/pin/<int:song_id>", methods=["POST"])
@login_required
def pin_song(song_id):
    user = current_user()
    db = get_db()
    song = db.execute("SELECT id FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not song:
        abort(404)
    count = db.execute("SELECT COUNT(*) as c FROM pinned_songs WHERE user_id = ?", (user["id"],)).fetchone()
    if count["c"] >= 6:
        flash("Maximum 6 pinned songs")
        return redirect(request.referrer or url_for("feed.home"))
    max_pos = db.execute("SELECT MAX(position) as mp FROM pinned_songs WHERE user_id = ?", (user["id"],)).fetchone()
    next_pos = (max_pos["mp"] or 0) + 1
    db.execute("INSERT OR IGNORE INTO pinned_songs (user_id, song_id, position) VALUES (?, ?, ?)", (user["id"], song_id, next_pos))
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


# ---------- Playlists ----------

@bp.route("/profile/playlists/mine", methods=["GET"])
@login_required
def my_playlists():
    """Return current user's playlists as JSON."""
    user = current_user()
    db = get_db()
    playlists = db.execute(
        "SELECT id, name FROM playlists WHERE user_id = ? ORDER BY created_at DESC",
        (user["id"],)
    ).fetchall()
    return jsonify([{"id": p["id"], "name": p["name"]} for p in playlists])


@bp.route("/profile/playlists/new", methods=["GET", "POST"])
@login_required
def new_playlist():
    if request.method == "GET":
        return render_template("playlist_new.html")
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    if not name:
        flash("Playlist name required")
        return redirect(url_for("profile.new_playlist"))
    user = current_user()
    db = get_db()
    cur = db.execute("INSERT INTO playlists (user_id, name, description) VALUES (?, ?, ?)", (user["id"], name, description))
    db.commit()
    playlist_id = cur.lastrowid

    # Add songs if provided (comma-separated Spotify IDs)
    # Spotify-track deep links removed; numeric local song_ids are still accepted.
    song_ids_str = request.form.get("song_ids", "").strip()
    if song_ids_str:
        position = 1
        for raw_id in song_ids_str.split(","):
            raw_id = raw_id.strip()
            if raw_id.isdigit():
                song_id = int(raw_id)
                db.execute(
                    "INSERT OR IGNORE INTO playlist_tracks (playlist_id, song_id, position) VALUES (?, ?, ?)",
                    (playlist_id, song_id, position)
                )
                position += 1
            # Non-numeric (Spotify) IDs are silently skipped.
        db.commit()

    create_activity(user["id"], "playlist_create", playlist_id=playlist_id)
    return redirect(url_for("profile.view_playlist", playlist_id=playlist_id))


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
    playlist = db.execute("SELECT * FROM playlists WHERE id = ? AND user_id = ?", (playlist_id, user["id"])).fetchone()
    if not playlist:
        abort(403)
    song_id = request.form.get("song_id", type=int)
    if not song_id:
        flash("No song specified")
        return redirect(request.referrer or url_for("feed.home"))
    max_pos = db.execute("SELECT MAX(position) as mp FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,)).fetchone()
    next_pos = (max_pos["mp"] or 0) + 1
    db.execute("INSERT OR IGNORE INTO playlist_tracks (playlist_id, song_id, position) VALUES (?, ?, ?)", (playlist_id, song_id, next_pos))
    db.commit()
    flash("Song added to playlist")
    return redirect(url_for("profile.view_playlist", playlist_id=playlist_id))


@bp.route("/profile/playlists/<int:playlist_id>/remove", methods=["POST"])
@login_required
def remove_from_playlist(playlist_id):
    user = current_user()
    db = get_db()
    playlist = db.execute("SELECT * FROM playlists WHERE id = ? AND user_id = ?", (playlist_id, user["id"])).fetchone()
    if not playlist:
        abort(403)
    song_id = request.form.get("song_id", type=int)
    db.execute("DELETE FROM playlist_tracks WHERE playlist_id = ? AND song_id = ?", (playlist_id, song_id))
    db.commit()
    flash("Song removed")
    return redirect(url_for("profile.view_playlist", playlist_id=playlist_id))


@bp.route("/u/<username>", methods=["GET", "POST"])
def profile(username):
    db = get_db()
    profile_user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not profile_user:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to leave a comment.", "warn")
            return redirect(url_for("auth.login"))
        body = (request.form.get("body") or "").strip()
        if body:
            db.execute(
                "INSERT INTO comments (profile_id, author_id, body, created_at) VALUES (?,?,?,?)",
                (profile_user["id"], session["user_id"], body[:1000],
                 datetime.utcnow().isoformat(timespec="seconds")),
            )
            db.commit()
        return redirect(url_for("profile.profile", username=username))

    ratings = db.execute("""
        SELECT r.*, s.title, s.artist FROM ratings r
        JOIN songs s ON s.id = r.song_id
        WHERE r.user_id = ?
        ORDER BY r.id DESC LIMIT 25
    """, (profile_user["id"],)).fetchall()
    submitted = db.execute("""
        SELECT s.*, COALESCE(AVG(r.stars), 0) AS avg_stars, COUNT(r.id) AS rating_count
        FROM songs s LEFT JOIN ratings r ON r.song_id = s.id
        WHERE s.submitted_by = ?
        GROUP BY s.id ORDER BY s.id DESC LIMIT 25
    """, (profile_user["id"],)).fetchall()
    comments = db.execute("""
        SELECT c.*, u.username, u.avatar_emoji FROM comments c
        JOIN users u ON u.id = c.author_id
        WHERE c.profile_id = ? ORDER BY c.id DESC LIMIT 50
    """, (profile_user["id"],)).fetchall()
    top_friends = db.execute("""
        SELECT id, username, avatar_emoji FROM users
        WHERE id != ? ORDER BY RANDOM() LIMIT 8
    """, (profile_user["id"],)).fetchall()
    avg_given = db.execute(
        "SELECT AVG(stars) AS a FROM ratings WHERE user_id = ?", (profile_user["id"],)
    ).fetchone()["a"]

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

    # User's posts and activities for feed
    user_posts = db.execute("""
        SELECT * FROM (
            SELECT 'post' as item_type, p.id, p.user_id, p.body, p.song_id, p.album_id,
                   NULL as rating_stars, NULL as activity_type, p.created_at, p.image_cid,
                   u.username, u.display_name, u.avatar_emoji, u.profile_pic_cid
            FROM posts p
            JOIN users u ON p.user_id = u.id
            WHERE p.user_id = ?
            UNION ALL
            SELECT 'activity' as item_type, a.id, a.user_id, NULL as body, a.song_id, a.album_id,
                   a.rating_stars, a.type as activity_type, a.created_at, NULL as image_cid,
                   u.username, u.display_name, u.avatar_emoji, u.profile_pic_cid
            FROM activities a
            JOIN users u ON a.user_id = u.id
            WHERE a.user_id = ?
        ) ORDER BY created_at DESC
        LIMIT 20
    """, (profile_user["id"], profile_user["id"])).fetchall()

    user_feed = []
    for item in user_posts:
        item_dict = dict(item)
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
        # Get counts
        if item_dict["item_type"] == "post":
            item_dict["like_count"] = db.execute("SELECT COUNT(*) as c FROM likes WHERE post_id = ?", (item_dict["id"],)).fetchone()["c"]
            item_dict["reply_count"] = db.execute("SELECT COUNT(*) as c FROM replies WHERE post_id = ?", (item_dict["id"],)).fetchone()["c"]
            item_dict["repost_count"] = db.execute("SELECT COUNT(*) as c FROM reposts WHERE post_id = ?", (item_dict["id"],)).fetchone()["c"]
        else:
            item_dict["like_count"] = db.execute("SELECT COUNT(*) as c FROM likes WHERE activity_id = ?", (item_dict["id"],)).fetchone()["c"]
            item_dict["reply_count"] = db.execute("SELECT COUNT(*) as c FROM replies WHERE activity_id = ?", (item_dict["id"],)).fetchone()["c"]
            item_dict["repost_count"] = db.execute("SELECT COUNT(*) as c FROM reposts WHERE activity_id = ?", (item_dict["id"],)).fetchone()["c"]
        item_dict["user_liked"] = False
        item_dict["user_reposted"] = False
        if current_user():
            from pacer.services.feed import has_user_liked, has_user_reposted
            item_dict["user_liked"] = has_user_liked(current_user()["id"], item_dict["item_type"], item_dict["id"])
            item_dict["user_reposted"] = has_user_reposted(current_user()["id"], item_dict["item_type"], item_dict["id"])
        user_feed.append(item_dict)

    return render_template(
        "profile.html",
        user=profile_user, ratings=ratings, submitted=submitted,
        comments=comments, top_friends=top_friends, avg_given=avg_given,
        pinned_songs=pinned_songs, playlists=playlists, recent_reviews=recent_reviews,
        user_feed=user_feed,
    )


@bp.route("/profile/palette", methods=["POST"])
@login_required
def set_palette():
    user = current_user()
    db = get_db()
    palette = request.form.get("palette", "modern")
    if palette not in ("modern", "win98", "clean"):
        palette = "modern"
    db.execute("UPDATE users SET palette = ? WHERE id = ?", (palette, user["id"]))
    db.commit()
    return jsonify({"ok": True, "palette": palette})


@bp.route("/profile/edit", methods=["GET", "POST"])
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
            "avatar_emoji": (request.form.get("avatar_emoji") or "\u25c9")[:4],
            "theme":         request.form.get("theme") or "sky",
            "status_message": (request.form.get("status_message") or "").strip()[:200],
        }
        try:
            fields["age"] = int(request.form.get("age") or 0) or None
        except ValueError:
            fields["age"] = user["age"]

        # Handle background preset (clears custom background_cid)
        background_preset = (request.form.get("background_preset") or "").strip() or None
        fields["background_preset"] = background_preset

        set_clause = ", ".join(f"{k}=?" for k in fields.keys())
        params = list(fields.values()) + [user["id"]]

        # If a preset is chosen, clear the custom background CID
        if background_preset:
            set_clause += ", background_cid=NULL"

        db.execute(f"UPDATE users SET {set_clause} WHERE id=?", params)
        db.commit()
        flash("Profile updated.", "ok")
        return redirect(url_for("profile.profile", username=user["username"]))
    return render_template("edit_profile.html", user=user)
