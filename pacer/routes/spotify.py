"""Spotify routes: search, OAuth connect/callback/disconnect, user top tracks."""

import base64
import secrets
import time
import urllib.parse

import requests
from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from pacer.config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
from pacer.db import get_db
from pacer.helpers import current_user, login_required
from pacer.services.spotify import (
    get_app_spotify_token,
    refresh_user_spotify_token,
    search_spotify,
    spotify_configured,
)

bp = Blueprint("spotify_bp", __name__)

SPOTIFY_SCOPES = "user-read-email user-top-read user-read-currently-playing user-read-recently-played"


@bp.route("/search")
def search_page():
    """Dedicated Spotify search page."""
    return render_template("search.html")


@bp.route("/spotify/search")
def spotify_search():
    """Music search across Spotify tracks + albums + artists."""
    q = (request.args.get("q") or "").strip()
    types = (request.args.get("type") or "track,album,artist").strip()
    if not q:
        return jsonify({"items": []})
    if not spotify_configured():
        return jsonify({
            "error": "Music search isn't configured. Set SPOTIFY_CLIENT_ID and "
                     "SPOTIFY_CLIENT_SECRET environment variables."
        }), 503
    items = search_spotify(q, types=types, limit=6)
    return jsonify({"items": items})


@bp.route("/spotify/connect")
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


@bp.route("/spotify/callback")
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
    return redirect(url_for("profile.profile", username=me["username"]))


@bp.route("/spotify/disconnect", methods=["POST"])
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
    return redirect(url_for("profile.profile", username=me["username"]))


@bp.route("/me/spotify/top")
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
