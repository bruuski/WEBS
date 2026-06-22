"""Auth helpers, template filters, and context processor."""

import hashlib
import re
from datetime import datetime
from functools import wraps

from flask import flash, redirect, request, session, url_for
from markupsafe import Markup, escape

from pacer.db import get_db

# ---------- auth helpers ----------

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


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
            return redirect(url_for("auth.login", next=request.path))
        return fn(*a, **kw)
    return wrapper


# ---------- template filters ----------


def score10(value):
    """Convert 0-5 average to a Pitchfork-style 0.0-10.0 score."""
    try:
        return "%.1f" % (float(value or 0) * 2.0)
    except (TypeError, ValueError):
        return "0.0"


def stars_filter(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    v = max(0.0, min(5.0, v))
    full = int(v)
    half = 1 if (v - full) >= 0.25 else 0
    empty = 5 - full - half
    return "\u2605" * full + ("\u00bd" if half else "") + "\u2606" * empty


def datefmt(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return dt.strftime("%m/%d/%y(%a)%H:%M")


def greentext_filter(text):
    """4chan-style greentext for lines starting with '>'."""
    if not text:
        return ""
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


# ---------- registration ----------


def register_template_utils(app):
    """Register all template filters and the context processor on the app."""
    app.template_filter("score10")(score10)
    app.template_filter("stars")(stars_filter)
    app.template_filter("datefmt")(datefmt)
    app.template_filter("greentext")(greentext_filter)

    from pacer.services.pinata import get_ipfs_url
    app.jinja_env.globals["ipfs_url"] = get_ipfs_url

    @app.context_processor
    def inject_globals():
        from pacer.services.spotify import spotify_configured
        return {
            "current_user": current_user(),
            "now": datetime.utcnow(),
            "spotify_enabled": spotify_configured(),
        }
