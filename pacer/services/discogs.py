"""Discogs API client for Pacer.

Uses OAuth 1.0a server-to-server auth (no user redirect).
In-memory TTL caches for artist (7d), release (30d), master (30d).
All network failures return None — never raise to the caller.
"""
import os
import time
import logging

import requests
from requests_oauthlib import OAuth1Session

from pacer import config

# Re-exported as module attributes so tests can monkeypatch these
# (e.g. `monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "...")`)
CONSUMER_KEY    = config.DISCOGS_CONSUMER_KEY
CONSUMER_SECRET = config.DISCOGS_CONSUMER_SECRET
USER_AGENT      = config.DISCOGS_USER_AGENT

BASE_URL = "https://api.discogs.com"
REQUEST_TIMEOUT = 8

# Cache TTLs (seconds)
ARTIST_TTL  = 7 * 24 * 3600
RELEASE_TTL = 30 * 24 * 3600

# Module-level cache: discogs_id -> (normalized_data, expires_at_epoch)
_artist_cache: dict[int, tuple[dict, float]] = {}
_release_cache: dict[int, tuple[dict, float]] = {}
_master_cache: dict[int, tuple[dict, float]] = {}

log = logging.getLogger("pacer.discogs")


def discogs_configured() -> bool:
    return bool(CONSUMER_KEY and CONSUMER_SECRET)


def _oauth() -> OAuth1Session:
    return OAuth1Session(
        CONSUMER_KEY,
        client_secret=CONSUMER_SECRET,
        resource_owner_key=None,
        resource_owner_secret=None,
    )


def _request(path: str, params: dict | None = None) -> dict | None:
    """Signed GET with timeout, User-Agent, and graceful error handling.

    Returns parsed JSON dict on success, or None on any failure.
    Never raises — callers can always safely use the return value.
    """
    if not discogs_configured():
        return None
    try:
        session = _oauth()
        resp = session.get(
            BASE_URL + path,
            params=params or {},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        log.warning("network error on %s: %s", path, e)
        return None

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "60")
        log.warning("rate limited on %s (retry after %ss)", path, retry_after)
        return None
    if not resp.ok:
        log.warning("%s on %s: %s", resp.status_code, path, resp.text[:200])
        return None
    return resp.json()


def search_releases(query: str, per_page: int = 20, page: int = 1) -> list[dict]:
    """Search releases. Returns list of normalized dicts (empty on failure)."""
    data = _request("/database/search", {
        "q": query, "type": "release",
        "per_page": per_page, "page": page,
    })
    if not data:
        return []
    out = []
    for r in data.get("results", []):
        labels = r.get("label") or [""]
        out.append({
            "discogs_id":   r.get("id"),
            "title":        r.get("title", ""),
            "year":         r.get("year"),
            "country":      r.get("country"),
            "label":        labels[0] if labels else "",
            "format":       r.get("format", []),
            "thumb":        r.get("thumb"),
            "cover_image":  r.get("cover_image"),
            "genre":        r.get("genre", []),
            "style":        r.get("style", []),
            "uri":          r.get("uri"),
            "resource_url": r.get("resource_url"),
        })
    return out


def search_masters(query: str, per_page: int = 20) -> list[dict]:
    """Search master releases (release-grouped)."""
    data = _request("/database/search", {"q": query, "type": "master", "per_page": per_page})
    return data.get("results", []) if data else []


def search_artists(query: str, per_page: int = 20) -> list[dict]:
    """Search artists."""
    data = _request("/database/search", {"q": query, "type": "artist", "per_page": per_page})
    return data.get("results", []) if data else []


def get_artist(discogs_id: int) -> dict | None:
    """Fetch artist by id with 7-day in-memory cache.

    Returns normalized dict or None on failure.
    """
    now = time.time()
    if discogs_id in _artist_cache and _artist_cache[discogs_id][1] > now:
        return _artist_cache[discogs_id][0]

    data = _request(f"/artists/{discogs_id}")
    if not data:
        return None

    normalized = {
        "id":              data.get("id"),
        "name":            data.get("name"),
        "real_name":       data.get("realname"),
        "profile":         data.get("profile"),
        "urls":            data.get("urls", []),
        "aliases":         [a.get("name") for a in (data.get("aliases") or [])],
        "members":         [m.get("name") for m in (data.get("members") or [])],
        "name_variations": data.get("namevariations", []),
        "images":          data.get("images", []),
        "discogs_url":     data.get("uri"),
    }
    _artist_cache[discogs_id] = (normalized, now + ARTIST_TTL)
    return normalized


def _youtube_id_from_uri(uri: str) -> str | None:
    """Extract YouTube video id from a watch URL.

    Examples:
      https://www.youtube.com/watch?v=dQw4w9WgXcQ -> dQw4w9WgXcQ
      https://youtu.be/dQw4w9WgXcQ -> dQw4w9WgXcQ
      https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s -> dQw4w9WgXcQ
    """
    import re
    if not uri:
        return None
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,15})", uri)
    return m.group(1) if m else None


def get_release(release_id: int) -> dict | None:
    """Fetch release by id with 30-day in-memory cache."""
    now = time.time()
    if release_id in _release_cache and _release_cache[release_id][1] > now:
        return _release_cache[release_id][0]

    data = _request(f"/releases/{release_id}")
    if not data:
        return None

    labels = data.get("labels") or [{}]
    label_obj = labels[0] if labels else {}
    images = data.get("images") or [{}]
    image_obj = images[0] if images else {}

    normalized = {
        "id":            data.get("id"),
        "title":         data.get("title"),
        "year":          data.get("year"),
        "country":       data.get("country"),
        "label":         label_obj.get("name"),
        "catalog_no":    label_obj.get("catno"),
        "format":        [f.get("name") for f in (data.get("formats") or [])],
        "genres":        data.get("genres", []),
        "styles":        data.get("styles", []),
        "tracklist":     [
            {
                "position": t.get("position"),
                "title":    t.get("title"),
                "duration": t.get("duration"),
                "artists":  [a.get("name") for a in (t.get("artists") or [])],
            }
            for t in (data.get("tracklist") or [])
        ],
        "artists":       [a.get("name") for a in (data.get("artists") or [])],
        "master_id":     data.get("master_id"),
        "master_url":    data.get("master_url"),
        "release_url":   data.get("uri"),
        "cover_image":   image_obj.get("uri"),
        "thumb":         image_obj.get("uri150"),
        "videos":        [
            {
                "id":       _youtube_id_from_uri(v.get("uri")),
                "title":    v.get("title") or v.get("description") or "",
                "duration": v.get("duration"),
                "url":      v.get("uri"),
                "thumb":    (f"https://i.ytimg.com/vi/{_youtube_id_from_uri(v.get('uri'))}/hqdefault.jpg"
                             if _youtube_id_from_uri(v.get("uri")) else None),
            }
            for v in (data.get("videos") or [])
            if _youtube_id_from_uri(v.get("uri"))
        ],
    }
    _release_cache[release_id] = (normalized, now + RELEASE_TTL)
    return normalized


def get_master(master_id: int) -> dict | None:
    """Fetch master release (release-grouped) with 30-day cache."""
    now = time.time()
    if master_id in _master_cache and _master_cache[master_id][1] > now:
        return _master_cache[master_id][0]

    data = _request(f"/masters/{master_id}")
    if not data:
        return None

    normalized = {
        "id":           data.get("id"),
        "title":        data.get("title"),
        "year":         data.get("year"),
        "main_release": data.get("main_release"),
        "artists":      [a.get("name") for a in (data.get("artists") or [])],
        "genres":       data.get("genres", []),
        "styles":       data.get("styles", []),
        "tracklist":    [
            {
                "position": t.get("position"),
                "title":    t.get("title"),
                "duration": t.get("duration"),
            }
            for t in (data.get("tracklist") or [])
        ],
        "discogs_url":  data.get("uri"),
    }
    _master_cache[master_id] = (normalized, now + RELEASE_TTL)
    return normalized


def find_release_by_artist_title(artist: str, title: str) -> dict | None:
    """Search Discogs and return best matching release.

    Prefers result whose title contains BOTH artist and title substrings.
    Falls back to first result. Returns None when no results.
    """
    artist_l = (artist or "").lower()
    title_l  = (title or "").lower()
    results = search_releases(f"{artist} {title}", per_page=5)
    if not results:
        return None
    for r in results:
        if artist_l in r["title"].lower() and title_l in r["title"].lower():
            return r
    return results[0]


def find_artist_by_name(name: str) -> dict | None:
    """Return first matching artist from search, or None."""
    results = search_artists(name, per_page=5)
    return results[0] if results else None
