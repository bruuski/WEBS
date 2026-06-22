import secrets
import sqlite3
from datetime import datetime

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from pacer.db import get_db
from pacer.helpers import hash_password, USERNAME_RE

bp = Blueprint("auth", __name__)


@bp.route("/signup", methods=["GET", "POST"])
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
        return redirect(url_for("feed.home"))
    return render_template("signup.html")


@bp.route("/login", methods=["GET", "POST"])
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
        return redirect(request.args.get("next") or url_for("feed.home"))
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "ok")
    return redirect(url_for("feed.home"))
