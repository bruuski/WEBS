"""Unit tests for slim Spotify service, especially lookup_spotify_preview."""


def test_lookup_preview_cache_hit_skips_api(temp_db, monkeypatch):
    """Pre-populate cache; no API call should be made."""
    from datetime import datetime
    import pacer.services.spotify as spotify
    import sqlite3

    now = datetime.utcnow().isoformat(timespec="seconds")
    con = sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO spotify_preview_cache
           (artist, title, spotify_id, preview_url, fetched_at)
           VALUES (?, ?, ?, ?, ?)""",
        ("Radiohead", "karma police", "abc123",
         "https://p.scdn.co/mp3-preview/abc.mp3", now),
    )
    con.commit()
    con.close()

    called = {"n": 0}
    def fake_get(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not hit network on cache hit")
    monkeypatch.setattr(spotify.requests, "get", fake_get)

    result = spotify.lookup_spotify_preview("Radiohead", "Karma Police")
    assert result is not None
    assert result["spotify_id"] == "abc123"
    assert result["preview_url"] == "https://p.scdn.co/mp3-preview/abc.mp3"
    assert called["n"] == 0


def test_lookup_preview_cache_miss_fetches_and_caches(temp_db, monkeypatch):
    """Empty cache → API call → cache write."""
    import pacer.services.spotify as spotify
    import sqlite3

    fake_response = {
        "tracks": {
            "items": [
                {
                    "id": "newid",
                    "preview_url": "https://p.scdn.co/mp3-preview/new.mp3",
                    "external_urls": {"spotify": "https://open.spotify.com/track/newid"},
                }
            ]
        }
    }
    class FakeResp:
        status_code = 200
        text = ""
        def ok(self): return True
        def json(self): return fake_response

    monkeypatch.setattr(spotify, "spotify_configured", lambda: True)
    monkeypatch.setattr(spotify, "get_app_spotify_token", lambda: "fake-token")
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: FakeResp())

    result = spotify.lookup_spotify_preview("New Artist", "New Song")
    assert result is not None
    assert result["spotify_id"] == "newid"
    assert result["preview_url"] == "https://p.scdn.co/mp3-preview/new.mp3"

    # Verify cache was written
    con = sqlite3.connect(temp_db)
    row = con.execute(
        "SELECT * FROM spotify_preview_cache WHERE artist=? AND title=?",
        ("new artist", "new song"),
    ).fetchone()
    assert row is not None
    assert row[3] == "newid"  # spotify_id column
    con.close()


def test_lookup_preview_negative_result_caches(temp_db, monkeypatch):
    """When Spotify returns 0 items, still cache (NULL spotify_id) to avoid re-querying."""
    import pacer.services.spotify as spotify
    import sqlite3

    fake_response = {"tracks": {"items": []}}
    class FakeResp:
        status_code = 200
        text = ""
        def ok(self): return True
        def json(self): return fake_response

    monkeypatch.setattr(spotify, "spotify_configured", lambda: True)
    monkeypatch.setattr(spotify, "get_app_spotify_token", lambda: "fake-token")
    monkeypatch.setattr(spotify.requests, "get", lambda *a, **kw: FakeResp())

    result = spotify.lookup_spotify_preview("Obscure", "Lost Track")
    assert result is None

    con = sqlite3.connect(temp_db)
    row = con.execute(
        "SELECT * FROM spotify_preview_cache WHERE artist=? AND title=?",
        ("obscure", "lost track"),
    ).fetchone()
    assert row is not None
    assert row[3] is None  # spotify_id column NULL
    con.close()


def test_lookup_preview_returns_none_without_artist_or_title():
    import pacer.services.spotify as spotify
    assert spotify.lookup_spotify_preview("", "Song") is None
    assert spotify.lookup_spotify_preview("Artist", "") is None
    assert spotify.lookup_spotify_preview(None, "Song") is None


def test_lookup_preview_returns_none_when_spotify_unconfigured(monkeypatch):
    import pacer.services.spotify as spotify
    monkeypatch.setattr(spotify, "spotify_configured", lambda: False)
    assert spotify.lookup_spotify_preview("Artist", "Song") is None


def test_lookup_preview_returns_none_when_no_token(temp_db, monkeypatch):
    import pacer.services.spotify as spotify
    monkeypatch.setattr(spotify, "spotify_configured", lambda: True)
    monkeypatch.setattr(spotify, "get_app_spotify_token", lambda: None)
    assert spotify.lookup_spotify_preview("Artist", "Song") is None
