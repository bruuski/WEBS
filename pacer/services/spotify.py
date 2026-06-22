"""Slim Spotify service: only what's needed for the Discogs-first design.

Responsibilities kept:
- ``get_app_spotify_token``   -- client-credentials token for server-side calls
- ``refresh_user_spotify_token`` -- per-user OAuth token (used by /me/spotify/top)
- ``fetch_spotify_trending``  -- pull trending tracks for the home page
- ``lookup_spotify_preview``  -- artist+title → {spotify_id, preview_url}, DB-cached

Spotify is no longer the primary source for artist / album / track metadata.
Discogs is the primary source. See ``pacer/services/discogs.py``.

Discogs-first migration: 2026-06-10.
"""

import base64
import sqlite3
import time

import requests

from pacer.config import (
    DB_PATH,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI,
    SPOTIFY_TRENDING_PLAYLIST,
)

# ---------- module-level caches ----------

_app_token = {"value": None, "expires_at": 0}
_trending_cache = {"items": [], "expires_at": 0}


# ---------- helpers ----------

def spotify_configured():
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)


def get_app_spotify_token():
    """Client-credentials token for server-side search."""
    if not spotify_configured():
        return None
    if _app_token["value"] and _app_token["expires_at"] > time.time() + 30:
        return _app_token["value"]
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"},
        timeout=8,
    )
    if not r.ok:
        return None
    d = r.json()
    _app_token["value"] = d["access_token"]
    _app_token["expires_at"] = time.time() + d.get("expires_in", 3600)
    return _app_token["value"]


# ---------- user token refresh ----------

def refresh_user_spotify_token(user_id):
    """Refresh a user's Spotify access token using their stored refresh token."""
    from pacer.db import get_db

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row or not row["spotify_refresh_token"]:
        return None
    if row["spotify_token_expires"] and row["spotify_token_expires"] > time.time() + 30:
        return row["spotify_access_token"]
    if not spotify_configured():
        return None
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    try:
        r = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "refresh_token",
                  "refresh_token": row["spotify_refresh_token"]},
            timeout=8,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    d = r.json()
    db.execute(
        """UPDATE users SET spotify_access_token=?, spotify_token_expires=? WHERE id=?""",
        (d["access_token"],
         int(time.time() + d.get("expires_in", 3600)),
         user_id),
    )
    db.commit()
    return d["access_token"]


# ---------- trending ----------

def fetch_spotify_trending(limit=12):
    """Pull a few trending tracks from Spotify, with a short in-process cache."""
    if _trending_cache["items"] and _trending_cache["expires_at"] > time.time():
        return _trending_cache["items"][:limit]
    if not spotify_configured():
        return []
    token = get_app_spotify_token()
    if not token:
        return []
    fields = ("items(track(id,name,artists(name),album(name,images,release_date),"
              "external_urls,preview_url))")
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/playlists/{SPOTIFY_TRENDING_PLAYLIST}/tracks",
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": limit, "fields": fields},
            timeout=8,
        )
    except requests.RequestException:
        return []
    if not r.ok:
        # fallback: new releases (albums)
        try:
            r2 = requests.get(
                "https://api.spotify.com/v1/browse/new-releases",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": limit},
                timeout=8,
            )
        except requests.RequestException:
            return []
        if not r2.ok:
            return []
        items = []
        for a in r2.json().get("albums", {}).get("items", []):
            images = a.get("images") or []
            items.append({
                "id":      a.get("id"),
                "name":    a.get("name"),
                "artists": ", ".join(ar["name"] for ar in a.get("artists", [])),
                "album":   a.get("name"),
                "year":    (a.get("release_date") or "")[:4],
                "image":   images[0]["url"] if images else None,
                "url":     (a.get("external_urls") or {}).get("spotify"),
                "preview": None,
                "kind":    "album",
            })
        _trending_cache["items"] = items
        _trending_cache["expires_at"] = time.time() + 600
        return items[:limit]

    items = []
    for it in r.json().get("items", []):
        t = it.get("track") or {}
        if not t.get("id"):
            continue
        album = t.get("album") or {}
        images = album.get("images") or []
        items.append({
            "id":      t.get("id"),
            "name":    t.get("name"),
            "artists": ", ".join(a["name"] for a in t.get("artists", [])),
            "album":   album.get("name"),
            "year":    (album.get("release_date") or "")[:4],
            "image":   images[0]["url"] if images else None,
            "url":     (t.get("external_urls") or {}).get("spotify"),
            "preview": t.get("preview_url"),
            "kind":    "track",
        })
    _trending_cache["items"] = items
    _trending_cache["expires_at"] = time.time() + 600
    return items[:limit]


# ---------- preview lookup (DB-cached) ----------

def lookup_spotify_preview(artist: str, title: str) -> dict | None:
    """Find a Spotify track by artist+title. Cached in DB for 30 days.

    Returns dict {spotify_id, preview_url, spotify_url} or None.
    Negative results (no match) are also cached to avoid re-querying.
    """
    from datetime import datetime

    artist = (artist or "").strip()
    title  = (title or "").strip()
    if not artist or not title:
        return None

    # Read DB_PATH at call time so tests can monkeypatch it
    from pacer import config as _config
    con = sqlite3.connect(_config.DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        # 1. cek cache (case-insensitive via LOWER() on both sides)
        row = con.execute(
            "SELECT * FROM spotify_preview_cache WHERE LOWER(artist) = ? AND LOWER(title) = ?",
            (artist.lower(), title.lower()),
        ).fetchone()
        if row:
            try:
                fetched = datetime.fromisoformat(row["fetched_at"])
                age_days = (datetime.utcnow() - fetched).total_seconds() / 86400
            except (TypeError, ValueError):
                age_days = 999
            if age_days < 30:
                if row["spotify_id"]:
                    return {
                        "spotify_id":  row["spotify_id"],
                        "preview_url": row["preview_url"],
                        "spotify_url": f"https://open.spotify.com/track/{row['spotify_id']}",
                    }
                return None  # negative cache hit, still valid

        # 2. fetch dari Spotify
        if not spotify_configured():
            return None
        token = get_app_spotify_token()
        if not token:
            return None

        try:
            r = requests.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": f'track:"{title}" artist:"{artist}"', "type": "track", "limit": 1},
                timeout=8,
            )
        except requests.RequestException:
            return None
        if not r.ok:
            return None

        items = (r.json().get("tracks") or {}).get("items") or []
        now = datetime.utcnow().isoformat(timespec="seconds")
        if not items:
            con.execute(
                """INSERT INTO spotify_preview_cache
                   (artist, title, spotify_id, preview_url, fetched_at)
                   VALUES (?, ?, NULL, NULL, ?)
                   ON CONFLICT(artist, title) DO UPDATE SET
                     spotify_id = NULL, preview_url = NULL, fetched_at = ?""",
                (artist.lower(), title.lower(), now, now),
            )
            con.commit()
            return None

        t = items[0]
        spotify_id  = t.get("id")
        preview_url = t.get("preview_url")
        con.execute(
            """INSERT INTO spotify_preview_cache
               (artist, title, spotify_id, preview_url, fetched_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(artist, title) DO UPDATE SET
                 spotify_id = ?, preview_url = ?, fetched_at = ?""",
            (artist.lower(), title.lower(), spotify_id, preview_url, now,
             spotify_id, preview_url, now),
        )
        con.commit()
        return {
            "spotify_id":  spotify_id,
            "preview_url": preview_url,
            "spotify_url": f"https://open.spotify.com/track/{spotify_id}",
        }
    finally:
        con.close()
