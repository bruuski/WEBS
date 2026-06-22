"""Blog routes – threads, replies, and bulletins."""

from datetime import datetime

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

from pacer.db import get_db
from pacer.helpers import login_required

bp = Blueprint("blog", __name__)


@bp.route("/blog")
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


@bp.route("/blog/new", methods=["POST"])
@login_required
def blog_new():
    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not subject or not body:
        flash("Subject and body are required.", "warn")
        return redirect(url_for("blog.blog_list"))

    image_cid = (request.form.get("image_cid") or "").strip() or None
    song_id_raw = (request.form.get("song_id") or "").strip()
    song_id = None
    if song_id_raw:
        if song_id_raw.isdigit():
            song_id = int(song_id_raw)
        # Spotify-track deep links removed; non-numeric song_id is ignored.

    db = get_db()
    cur = db.execute(
        "INSERT INTO threads (user_id, subject, body, created_at, image_cid, song_id) VALUES (?,?,?,?,?,?)",
        (session["user_id"], subject[:140], body[:5000],
         datetime.utcnow().isoformat(timespec="seconds"),
         image_cid, song_id),
    )
    db.commit()
    flash("Thread posted.", "ok")
    return redirect(url_for("blog.blog_thread", thread_id=cur.lastrowid))


@bp.route("/blog/<int:thread_id>", methods=["GET", "POST"])
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
            return redirect(url_for("auth.login", next=request.path))
        body = (request.form.get("body") or "").strip()
        if body:
            image_cid = (request.form.get("image_cid") or "").strip() or None
            song_id_raw = (request.form.get("song_id") or "").strip()
            song_id = None
            if song_id_raw:
                if song_id_raw.isdigit():
                    song_id = int(song_id_raw)
                # Spotify-track deep links removed; non-numeric song_id is ignored.
            db.execute(
                "INSERT INTO thread_replies (thread_id, user_id, body, created_at, image_cid, song_id) VALUES (?,?,?,?,?,?)",
                (thread_id, session["user_id"], body[:5000],
                 datetime.utcnow().isoformat(timespec="seconds"),
                 image_cid, song_id),
            )
            db.commit()
        return redirect(url_for("blog.blog_thread", thread_id=thread_id))

    replies = db.execute("""
        SELECT r.*, u.username, u.avatar_emoji
        FROM thread_replies r JOIN users u ON u.id = r.user_id
        WHERE r.thread_id = ? ORDER BY r.id ASC
    """, (thread_id,)).fetchall()
    return render_template("blog_thread.html", thread=thread, replies=replies)


@bp.route("/bulletins/new", methods=["POST"])
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
    return redirect(url_for("feed.home"))
