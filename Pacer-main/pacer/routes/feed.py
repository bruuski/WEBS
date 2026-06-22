from flask import Blueprint, request, redirect, url_for, render_template, flash, jsonify, abort
from pacer.db import get_db
from pacer.helpers import current_user, login_required
from pacer.services.feed import get_timeline, has_user_liked, has_user_reposted, get_replies
from pacer.services.spotify import fetch_spotify_trending

bp = Blueprint("feed", __name__)


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


@bp.route("/feed/more")
def feed_more():
    """HTMX endpoint: load more feed items for infinite scroll."""
    offset = request.args.get("offset", 0, type=int)
    user = current_user()
    feed_items = get_timeline(offset=offset, limit=20)

    if user:
        for item in feed_items:
            item["user_liked"] = has_user_liked(user["id"], item["item_type"], item["id"])
            item["user_reposted"] = has_user_reposted(user["id"], item["item_type"], item["id"])

    return render_template("partials/feed_list.html", feed_items=feed_items, offset=offset)


@bp.route("/feed/upload-image", methods=["POST"])
@login_required
def upload_image():
    """Upload image to Pinata, return CID as JSON."""
    from pacer.services.pinata import upload_to_pinata, pinata_configured
    if not pinata_configured():
        return jsonify({"error": "Upload not configured"}), 503
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file"}), 400
    cid = upload_to_pinata(file)
    if not cid:
        return jsonify({"error": "Upload failed. Check file type and size."}), 400
    return jsonify({"cid": cid})


@bp.route("/posts", methods=["POST"])
@login_required
def create_post():
    """Create a new post."""
    user = current_user()
    body = request.form.get("body", "").strip()
    if not body:
        flash("Post cannot be empty")
        return redirect(url_for("feed.home"))
    if len(body) > 280:
        body = body[:280]

    song_id = request.form.get("song_id", type=int) or None
    album_id = request.form.get("album_id", type=int) or None
    image_cid = request.form.get("image_cid", "").strip() or None

    db = get_db()
    db.execute(
        "INSERT INTO posts (user_id, body, song_id, album_id, image_cid) VALUES (?, ?, ?, ?, ?)",
        (user["id"], body, song_id, album_id, image_cid)
    )
    db.commit()
    return redirect(url_for("feed.home"))


@bp.route("/posts/<int:post_id>/like", methods=["POST"])
@login_required
def like_post(post_id):
    """Like a post. Returns HTMX partial."""
    user = current_user()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO likes (user_id, post_id) VALUES (?, ?)", (user["id"], post_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM likes WHERE post_id = ?", (post_id,)).fetchone()["c"]
    return render_template("partials/like_button.html", item_type="post", item_id=post_id, liked=True, count=count)


@bp.route("/posts/<int:post_id>/unlike", methods=["POST"])
@login_required
def unlike_post(post_id):
    """Unlike a post. Returns HTMX partial."""
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM likes WHERE user_id = ? AND post_id = ?", (user["id"], post_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM likes WHERE post_id = ?", (post_id,)).fetchone()["c"]
    return render_template("partials/like_button.html", item_type="post", item_id=post_id, liked=False, count=count)


@bp.route("/posts/<int:post_id>/reply", methods=["POST"])
@login_required
def reply_post(post_id):
    """Reply to a post. Returns reply partial."""
    user = current_user()
    body = request.form.get("body", "").strip()
    if not body:
        return "", 204
    song_id = request.form.get("song_id", type=int) or None
    image_cid = request.form.get("image_cid", "").strip() or None
    db = get_db()
    db.execute("INSERT INTO replies (user_id, post_id, body, song_id, image_cid) VALUES (?, ?, ?, ?, ?)", (user["id"], post_id, body, song_id, image_cid))
    db.commit()
    return render_template("partials/reply_item.html", reply={
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar_emoji": user["avatar_emoji"],
        "profile_pic_cid": user["profile_pic_cid"],
        "body": body,
        "song_id": song_id,
        "image_cid": image_cid,
        "created_at": "just now",
    })


@bp.route("/posts/<int:post_id>/repost", methods=["POST"])
@login_required
def repost_post(post_id):
    """Repost a post."""
    user = current_user()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO reposts (user_id, post_id) VALUES (?, ?)", (user["id"], post_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM reposts WHERE post_id = ?", (post_id,)).fetchone()["c"]
    return render_template("partials/repost_button.html", item_type="post", item_id=post_id, reposted=True, count=count)


@bp.route("/posts/<int:post_id>/unrepost", methods=["POST"])
@login_required
def unrepost_post(post_id):
    """Unrepost a post."""
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM reposts WHERE user_id = ? AND post_id = ?", (user["id"], post_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM reposts WHERE post_id = ?", (post_id,)).fetchone()["c"]
    return render_template("partials/repost_button.html", item_type="post", item_id=post_id, reposted=False, count=count)


@bp.route("/activities/<int:activity_id>/like", methods=["POST"])
@login_required
def like_activity(activity_id):
    """Like an activity. Returns HTMX partial."""
    user = current_user()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO likes (user_id, activity_id) VALUES (?, ?)", (user["id"], activity_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM likes WHERE activity_id = ?", (activity_id,)).fetchone()["c"]
    return render_template("partials/like_button.html", item_type="activity", item_id=activity_id, liked=True, count=count)


@bp.route("/activities/<int:activity_id>/unlike", methods=["POST"])
@login_required
def unlike_activity(activity_id):
    """Unlike an activity."""
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM likes WHERE user_id = ? AND activity_id = ?", (user["id"], activity_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM likes WHERE activity_id = ?", (activity_id,)).fetchone()["c"]
    return render_template("partials/like_button.html", item_type="activity", item_id=activity_id, liked=False, count=count)


@bp.route("/activities/<int:activity_id>/reply", methods=["POST"])
@login_required
def reply_activity(activity_id):
    """Reply to an activity. Returns reply partial."""
    user = current_user()
    body = request.form.get("body", "").strip()
    if not body:
        return "", 204
    song_id = request.form.get("song_id", type=int) or None
    image_cid = request.form.get("image_cid", "").strip() or None
    db = get_db()
    db.execute("INSERT INTO replies (user_id, activity_id, body, song_id, image_cid) VALUES (?, ?, ?, ?, ?)", (user["id"], activity_id, body, song_id, image_cid))
    db.commit()
    return render_template("partials/reply_item.html", reply={
        "username": user["username"],
        "display_name": user["display_name"],
        "avatar_emoji": user["avatar_emoji"],
        "profile_pic_cid": user["profile_pic_cid"],
        "body": body,
        "song_id": song_id,
        "image_cid": image_cid,
        "created_at": "just now",
    })


@bp.route("/activities/<int:activity_id>/repost", methods=["POST"])
@login_required
def repost_activity(activity_id):
    """Repost an activity."""
    user = current_user()
    db = get_db()
    db.execute("INSERT OR IGNORE INTO reposts (user_id, activity_id) VALUES (?, ?)", (user["id"], activity_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM reposts WHERE activity_id = ?", (activity_id,)).fetchone()["c"]
    return render_template("partials/repost_button.html", item_type="activity", item_id=activity_id, reposted=True, count=count)


@bp.route("/activities/<int:activity_id>/unrepost", methods=["POST"])
@login_required
def unrepost_activity(activity_id):
    """Unrepost an activity."""
    user = current_user()
    db = get_db()
    db.execute("DELETE FROM reposts WHERE user_id = ? AND activity_id = ?", (user["id"], activity_id))
    db.commit()
    count = db.execute("SELECT COUNT(*) as c FROM reposts WHERE activity_id = ?", (activity_id,)).fetchone()["c"]
    return render_template("partials/repost_button.html", item_type="activity", item_id=activity_id, reposted=False, count=count)


@bp.route("/posts/<int:post_id>/replies", methods=["GET"])
def get_replies_post(post_id):
    """Get replies for a post."""
    from pacer.services.feed import get_replies
    replies = get_replies("post", post_id)
    return render_template("partials/replies_list.html", replies=replies)


@bp.route("/activities/<int:activity_id>/replies", methods=["GET"])
def get_replies_activity(activity_id):
    """Get replies for an activity."""
    from pacer.services.feed import get_replies
    replies = get_replies("activity", activity_id)
    return render_template("partials/replies_list.html", replies=replies)
