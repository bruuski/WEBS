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
from pacer.services import discogs
from pacer.services.spotify import (
    get_app_spotify_token,
    lookup_spotify_preview,
    refresh_user_spotify_token,
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
    """Music search: Discogs as primary source, Spotify preview as enrichment."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"items": []})
    if not discogs.discogs_configured():
        return jsonify({
            "error": "Music search isn't configured. Set DISCOGS_CONSUMER_KEY and "
                     "DISCOGS_CONSUMER_SECRET environment variables."
        }), 503

    results = discogs.search_releases(q, per_page=12)
    enriched = []
    for r in results:
        # Parse "Artist - Album" from title
        title = r.get("title", "")
        if " - " in title:
            artist, _album = title.split(" - ", 1)
        else:
            artist, _album = title, ""

        # We already fetch the full release below to grab the first track title
        # for preview lookup. Reuse it to upgrade the search-thumb (often an
        # empty string for older releases) to the higher-res cover_image, so
        # the search result row can show a proportional cover.
        first_track_title = None
        cover_image = r.get("thumb") or r.get("cover_image") or ""
        if r.get("discogs_id"):
            release = discogs.get_release(r["discogs_id"])
            if release:
                if release.get("tracklist"):
                    first_track_title = release["tracklist"][0].get("title")
                if release.get("cover_image"):
                    cover_image = release["cover_image"]
                elif release.get("thumb"):
                    cover_image = release["thumb"]

        # Lookup Spotify preview
        preview = None
        if first_track_title:
            preview = lookup_spotify_preview(artist, first_track_title)
        if not preview:
            preview = lookup_spotify_preview(artist, title)

        enriched.append({
            "discogs_id":   r.get("discogs_id"),
            "title":        title,
            "year":         r.get("year"),
            "country":      r.get("country"),
            "label":        r.get("label"),
            "format":       r.get("format", []),
            "thumb":        cover_image,
            "style":        r.get("style", []),
            "has_preview":  bool(preview and preview.get("preview_url")),
            "spotify_id":   preview["spotify_id"] if preview else None,
        })
    return jsonify({"items": enriched})


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
