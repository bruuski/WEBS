"""Spotify service: the canonical metadata source for Pacer.

Includes:
- ``get_app_spotify_token``       -- client-credentials token
- ``refresh_user_spotify_token``  -- per-user OAuth token
- ``fetch_spotify_trending``      -- trending tracks for the home page
- ``lookup_spotify_preview``      -- artist+title -> {spotify_id, preview_url} (DB-cached)
- ``search_spotify``              -- music search (tracks + albums + artists)
- ``get_track`` / ``get_album`` / ``get_album_tracks``
- ``get_artist`` / ``get_artist_top_tracks`` / ``get_artist_albums``

All metadata fetches use a small in-process TTL cache so repeated page
loads don't hit Spotify on every request. This is the primary fix for
the slow artist/album pages that the previous Discogs-first design
suffered from.
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


# ---------- metadata fetches (TTL cache) ----------
#
# All of these return a dict (or list) shaped like the templates expect, or
# None / [] on failure. They share a single in-process TTL cache so a hot
# page (e.g. /artists/<id>) only hits Spotify once every CACHE_TTL seconds.

_META_TTL = 15 * 60          # 15 minutes
_meta_cache: dict = {}       # key -> (value, expires_at)


def _meta_get(key):
    hit = _meta_cache.get(key)
    if hit and hit[1] > time.time():
        return hit[0]
    return None


def _meta_put(key, value):
    _meta_cache[key] = (value, time.time() + _META_TTL)


def _spotify_get(path, params=None):
    """Authenticated GET against api.spotify.com/v1/<path>. Returns dict or None."""
    if not spotify_configured():
        return None
    token = get_app_spotify_token()
    if not token:
        return None
    try:
        r = requests.get(
            f"https://api.spotify.com/v1/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=6,
        )
    except requests.RequestException:
        return None
    if not r.ok:
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _normalize_track(t):
    if not t:
        return None
    album = t.get("album") or {}
    images = album.get("images") or []
    artists_list = t.get("artists") or []
    return {
        "kind":              "track",
        "id":                t.get("id"),
        "spotify_id":        t.get("id"),
        "name":              t.get("name") or "",
        "title":             t.get("name") or "",
        "artists":           ", ".join(a["name"] for a in artists_list),
        "artist_id":         artists_list[0]["id"] if artists_list else None,
        "spotify_artist_id": artists_list[0]["id"] if artists_list else None,
        "album":             album.get("name"),
        "album_name":        album.get("name"),
        "album_id":          album.get("id"),
        "year":              (album.get("release_date") or "")[:4],
        "image":             images[-1]["url"] if images else None,
        "image_lg":          images[0]["url"]  if images else None,
        "url":               (t.get("external_urls") or {}).get("spotify"),
        "preview":           t.get("preview_url"),
        "preview_url":       t.get("preview_url"),
        "duration_ms":       t.get("duration_ms") or 0,
    }


def _normalize_album(a):
    if not a:
        return None
    images = a.get("images") or []
    artists_list = a.get("artists") or []
    return {
        "kind":              "album",
        "id":                a.get("id"),
        "spotify_id":        a.get("id"),
        "name":              a.get("name") or "",
        "artists":           ", ".join(ar["name"] for ar in artists_list),
        "artist":            ", ".join(ar["name"] for ar in artists_list),
        "artist_id":         artists_list[0]["id"] if artists_list else None,
        "spotify_artist_id": artists_list[0]["id"] if artists_list else None,
        "album":             a.get("name"),
        "year":              (a.get("release_date") or "")[:4],
        "image":             images[-1]["url"] if images else None,
        "image_lg":          images[0]["url"]  if images else None,
        "url":               (a.get("external_urls") or {}).get("spotify"),
        "total_tracks":      a.get("total_tracks") or 0,
        "format":            a.get("album_type"),
    }


def _normalize_artist(a):
    if not a:
        return None
    images = a.get("images") or []
    return {
        "kind":         "artist",
        "id":           a.get("id"),
        "spotify_id":   a.get("id"),
        "name":         a.get("name") or "",
        "image":        images[0]["url"] if images else None,
        "image_url":    images[0]["url"] if images else None,
        "genres":       a.get("genres") or [],
        "popularity":   a.get("popularity") or 0,
        "url":          (a.get("external_urls") or {}).get("spotify"),
        "spotify_url":  (a.get("external_urls") or {}).get("spotify"),
        "followers":    ((a.get("followers") or {}).get("total")) or 0,
    }


# ---------- public metadata functions ----------

def search_spotify(q: str, types: str = "track,album,artist", limit: int = 8):
    """Search Spotify across tracks / albums / artists. Returns list of normalized items."""
    q = (q or "").strip()
    if not q:
        return []
    cache_key = ("search", q.lower(), types, limit)
    cached = _meta_get(cache_key)
    if cached is not None:
        return cached
    data = _spotify_get("search", params={"q": q, "type": types, "limit": limit})
    if not data:
        _meta_put(cache_key, [])
        return []
    items = []
    if "track" in types:
        for t in (data.get("tracks") or {}).get("items") or []:
            items.append(_normalize_track(t))
    if "album" in types:
        for a in (data.get("albums") or {}).get("items") or []:
            items.append(_normalize_album(a))
    if "artist" in types:
        for ar in (data.get("artists") or {}).get("items") or []:
            items.append(_normalize_artist(ar))
    items = [i for i in items if i and i.get("id")]
    _meta_put(cache_key, items)
    return items


def get_track(spotify_id: str):
    """Fetch a single Spotify track."""
    if not spotify_id:
        return None
    key = ("track", spotify_id)
    cached = _meta_get(key)
    if cached is not None:
        return cached
    data = _spotify_get(f"tracks/{spotify_id}")
    norm = _normalize_track(data) if data else None
    _meta_put(key, norm)
    return norm


def get_album(spotify_id: str):
    """Fetch a single Spotify album (with tracklist baked in)."""
    if not spotify_id:
        return None
    key = ("album", spotify_id)
    cached = _meta_get(key)
    if cached is not None:
        return cached
    data = _spotify_get(f"albums/{spotify_id}")
    if not data:
        _meta_put(key, None)
        return None
    norm = _normalize_album(data)
    norm["tracks"] = [
        {
            "id":           t.get("id"),
            "spotify_id":   t.get("id"),
            "name":         t.get("name") or "",
            "title":        t.get("name") or "",
            "track_number": t.get("track_number") or 0,
            "duration_ms":  t.get("duration_ms") or 0,
            "duration":     f"{(t.get('duration_ms') or 0) // 60000}:{((t.get('duration_ms') or 0) // 1000) % 60:02d}" if t.get("duration_ms") else "",
            "artists":      ", ".join(ar["name"] for ar in (t.get("artists") or [])),
            "preview":      t.get("preview_url"),
            "preview_url":  t.get("preview_url"),
        }
        for t in ((data.get("tracks") or {}).get("items") or [])
    ]
    _meta_put(key, norm)
    return norm


def get_album_tracks(spotify_id: str):
    """Album tracklist only (when you already have album metadata cached)."""
    album = get_album(spotify_id)
    return (album or {}).get("tracks", []) if album else []


def get_artist(spotify_id: str):
    """Fetch a single Spotify artist."""
    if not spotify_id:
        return None
    key = ("artist", spotify_id)
    cached = _meta_get(key)
    if cached is not None:
        return cached
    data = _spotify_get(f"artists/{spotify_id}")
    norm = _normalize_artist(data) if data else None
    _meta_put(key, norm)
    return norm


def get_artist_top_tracks(spotify_id: str, market: str = "US", limit: int = 10):
    """Artist's top tracks (Spotify returns up to 10)."""
    if not spotify_id:
        return []
    key = ("artist_top", spotify_id, market)
    cached = _meta_get(key)
    if cached is not None:
        return cached[:limit]
    data = _spotify_get(f"artists/{spotify_id}/top-tracks", params={"market": market})
    if not data:
        _meta_put(key, [])
        return []
    tracks = [_normalize_track(t) for t in (data.get("tracks") or [])]
    tracks = [t for t in tracks if t]
    _meta_put(key, tracks)
    return tracks[:limit]


def get_artist_albums(spotify_id: str, limit: int = 20, include_groups: str = "album,single"):
    """Artist's albums, newest first."""
    if not spotify_id:
        return []
    key = ("artist_albums", spotify_id, include_groups, limit)
    cached = _meta_get(key)
    if cached is not None:
        return cached
    data = _spotify_get(
        f"artists/{spotify_id}/albums",
        params={"limit": limit, "include_groups": include_groups, "market": "US"},
    )
    if not data:
        _meta_put(key, [])
        return []
    seen_names = set()  # dedupe (Spotify returns multiple regional copies)
    albums = []
    for a in data.get("items") or []:
        norm = _normalize_album(a)
        if not norm:
            continue
        key_name = (norm["name"] or "").lower()
        if key_name in seen_names:
            continue
        seen_names.add(key_name)
        albums.append(norm)
    _meta_put(key, albums)
    return albums
