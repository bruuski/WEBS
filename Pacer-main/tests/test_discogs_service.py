"""Unit tests for the Discogs API service."""


def test_discogs_configured_returns_false_when_empty(monkeypatch):
    """When DISCOGS_CONSUMER_KEY and SECRET are empty, returns False."""
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "")
    from pacer.services import discogs
    assert discogs.discogs_configured() is False


def test_discogs_configured_returns_true_when_set(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "test-key")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "test-secret")
    from pacer.services import discogs
    assert discogs.discogs_configured() is True


def test_request_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "")
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result is None


def test_request_handles_network_exception(monkeypatch):
    """If requests.get raises, _request returns None (no exception)."""
    import requests

    def boom(*a, **kw):
        raise requests.RequestException("boom")

    class FakeSession:
        def get(self, *a, **kw):
            return boom()

    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "fake")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "fake")
    monkeypatch.setattr("pacer.services.discogs._oauth", lambda: FakeSession())
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result is None


def test_request_returns_none_on_429(monkeypatch):
    """Rate limit → return None, caller falls back to cache."""
    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "60"}
        text = "Too Many Requests"
        def ok(self): return False
        def json(self): return {}

    class FakeSession:
        def get(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "fake")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "fake")
    monkeypatch.setattr("pacer.services.discogs._oauth", lambda: FakeSession())
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result is None


def test_request_returns_parsed_json_on_200(monkeypatch):
    class FakeResp:
        status_code = 200
        headers = {}
        text = ""
        def ok(self): return True
        def json(self): return {"results": [{"id": 1}]}

    class FakeSession:
        def get(self, *a, **kw): return FakeResp()

    monkeypatch.setattr("pacer.services.discogs.CONSUMER_KEY", "fake")
    monkeypatch.setattr("pacer.services.discogs.CONSUMER_SECRET", "fake")
    monkeypatch.setattr("pacer.services.discogs._oauth", lambda: FakeSession())
    from pacer.services import discogs
    result = discogs._request("/database/search", {"q": "test"})
    assert result == {"results": [{"id": 1}]}


def test_search_releases_returns_normalized_list(monkeypatch):
    fake_response = {
        "results": [
            {
                "id": 12345,
                "title": "Radiohead - OK Computer",
                "year": 1997,
                "country": "US",
                "label": ["Parlophone"],
                "format": ["CD", "Album"],
                "thumb": "https://example.com/thumb.jpg",
                "cover_image": "https://example.com/cover.jpg",
                "genre": ["Electronic", "Rock"],
                "style": ["Alternative Rock", "Art Rock"],
                "uri": "https://www.discogs.com/release/12345",
                "resource_url": "https://api.discogs.com/releases/12345",
            }
        ]
    }
    monkeypatch.setattr(
        "pacer.services.discogs._request",
        lambda path, params=None: fake_response if "search" in path else None,
    )
    from pacer.services import discogs
    results = discogs.search_releases("radiohead", per_page=5)
    assert len(results) == 1
    r = results[0]
    assert r["discogs_id"] == 12345
    assert r["title"] == "Radiohead - OK Computer"
    assert r["year"] == 1997
    assert r["country"] == "US"
    assert r["label"] == "Parlophone"
    assert r["format"] == ["CD", "Album"]
    assert r["thumb"] == "https://example.com/thumb.jpg"
    assert r["cover_image"] == "https://example.com/cover.jpg"
    assert r["genre"] == ["Electronic", "Rock"]
    assert r["style"] == ["Alternative Rock", "Art Rock"]
    assert r["uri"] == "https://www.discogs.com/release/12345"


def test_search_releases_returns_empty_when_no_results(monkeypatch):
    monkeypatch.setattr(
        "pacer.services.discogs._request", lambda path, params=None: {"results": []}
    )
    from pacer.services import discogs
    assert discogs.search_releases("zzznotfound") == []


def test_search_releases_returns_empty_when_request_fails(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: None)
    from pacer.services import discogs
    assert discogs.search_releases("anything") == []


def test_search_artists_returns_list(monkeypatch):
    monkeypatch.setattr(
        "pacer.services.discogs._request",
        lambda path, params=None: {"results": [{"id": 99, "title": "Radiohead"}]}
        if "type" in (params or {}) and (params or {}).get("type") == "artist" else None,
    )
    from pacer.services import discogs
    results = discogs.search_artists("radiohead")
    assert len(results) == 1
    assert results[0]["id"] == 99


def test_get_artist_returns_normalized_dict(monkeypatch):
    fake = {
        "id": 3840,
        "name": "Radiohead",
        "realname": "Radiohead",
        "profile": "Radiohead are an English rock band from Abingdon...",
        "urls": ["https://radiohead.com", "https://example.com"],
        "aliases": [{"name": "Atoms For Peace"}],
        "members": [{"name": "Thom Yorke"}, {"name": "Jonny Greenwood"}],
        "namevariations": ["Radio Head", "RADIOHEAD"],
        "images": [{"uri": "https://example.com/radiohead.jpg", "uri150": "https://example.com/r150.jpg"}],
        "uri": "https://www.discogs.com/artist/3840-Radiohead",
    }
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._artist_cache.clear()
    result = discogs.get_artist(3840)
    assert result["id"] == 3840
    assert result["name"] == "Radiohead"
    assert result["real_name"] == "Radiohead"
    assert "Radiohead are an English" in result["profile"]
    assert result["urls"] == ["https://radiohead.com", "https://example.com"]
    assert result["aliases"] == ["Atoms For Peace"]
    assert result["members"] == ["Thom Yorke", "Jonny Greenwood"]
    assert result["name_variations"] == ["Radio Head", "RADIOHEAD"]
    assert result["discogs_url"] == "https://www.discogs.com/artist/3840-Radiohead"


def test_get_artist_uses_cache(monkeypatch):
    """Second call within TTL does not hit _request."""
    call_count = {"n": 0}

    def counting_request(path, params=None):
        call_count["n"] += 1
        return {"id": 1, "name": "X", "realname": "", "profile": "",
                "urls": [], "aliases": [], "members": [], "namevariations": [],
                "images": [], "uri": ""}

    monkeypatch.setattr("pacer.services.discogs._request", counting_request)
    from pacer.services import discogs
    discogs._artist_cache.clear()
    discogs.get_artist(1)
    discogs.get_artist(1)
    discogs.get_artist(1)
    assert call_count["n"] == 1


def test_get_artist_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: None)
    from pacer.services import discogs
    discogs._artist_cache.clear()
    assert discogs.get_artist(999) is None


def test_get_release_returns_normalized_dict(monkeypatch):
    fake = {
        "id": 12345,
        "title": "Radiohead - OK Computer",
        "year": 1997,
        "country": "UK",
        "labels": [{"name": "Parlophone", "catno": "NODATA01"}],
        "formats": [{"name": "CD"}, {"name": "Album"}],
        "genres": ["Electronic", "Rock"],
        "styles": ["Alternative Rock", "Art Rock"],
        "tracklist": [
            {"position": "1", "title": "Airbag", "duration": "4:44", "artists": [{"name": "Radiohead"}]},
            {"position": "2", "title": "Paranoid Android", "duration": "6:23", "artists": [{"name": "Radiohead"}]},
        ],
        "artists": [{"name": "Radiohead"}],
        "master_id": 40260,
        "master_url": "https://api.discogs.com/masters/40260",
        "uri": "https://www.discogs.com/release/12345",
        "images": [{"uri": "https://example.com/cover.jpg", "uri150": "https://example.com/150.jpg"}],
    }
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._release_cache.clear()
    r = discogs.get_release(12345)
    assert r["id"] == 12345
    assert r["title"] == "Radiohead - OK Computer"
    assert r["year"] == 1997
    assert r["country"] == "UK"
    assert r["label"] == "Parlophone"
    assert r["catalog_no"] == "NODATA01"
    assert r["format"] == ["CD", "Album"]
    assert r["genres"] == ["Electronic", "Rock"]
    assert r["styles"] == ["Alternative Rock", "Art Rock"]
    assert len(r["tracklist"]) == 2
    assert r["tracklist"][0]["position"] == "1"
    assert r["tracklist"][0]["title"] == "Airbag"
    assert r["tracklist"][0]["duration"] == "4:44"
    assert r["artists"] == ["Radiohead"]
    assert r["master_id"] == 40260
    assert r["master_url"] == "https://api.discogs.com/masters/40260"
    assert r["release_url"] == "https://www.discogs.com/release/12345"
    assert r["cover_image"] == "https://example.com/cover.jpg"


def test_get_release_handles_missing_labels(monkeypatch):
    fake = {"id": 1, "title": "X", "year": 2020, "country": "US",
            "labels": [], "formats": [], "genres": [], "styles": [],
            "tracklist": [], "artists": [], "master_id": 0, "master_url": "",
            "uri": "", "images": []}
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._release_cache.clear()
    r = discogs.get_release(1)
    assert r["label"] is None
    assert r["catalog_no"] is None
    assert r["format"] == []


def test_get_release_uses_cache(monkeypatch):
    call_count = {"n": 0}
    def counting(path, params=None):
        call_count["n"] += 1
        return {"id": 1, "title": "X", "year": 2020, "country": "US",
                "labels": [], "formats": [], "genres": [], "styles": [],
                "tracklist": [], "artists": [], "master_id": 0, "master_url": "",
                "uri": "", "images": []}
    monkeypatch.setattr("pacer.services.discogs._request", counting)
    from pacer.services import discogs
    discogs._release_cache.clear()
    discogs.get_release(1)
    discogs.get_release(1)
    assert call_count["n"] == 1


def test_get_master_returns_normalized_dict(monkeypatch):
    fake = {
        "id": 40260,
        "title": "OK Computer",
        "year": 1997,
        "main_release": 12345,
        "artists": [{"name": "Radiohead"}],
        "genres": ["Rock"],
        "styles": ["Alternative Rock"],
        "tracklist": [
            {"position": "1", "title": "Airbag", "duration": "4:44"},
            {"position": "2", "title": "Paranoid Android", "duration": "6:23"},
        ],
        "uri": "https://www.discogs.com/master/40260",
    }
    monkeypatch.setattr("pacer.services.discogs._request", lambda path, params=None: fake)
    from pacer.services import discogs
    discogs._master_cache.clear()
    m = discogs.get_master(40260)
    assert m["id"] == 40260
    assert m["title"] == "OK Computer"
    assert m["year"] == 1997
    assert m["main_release"] == 12345
    assert m["artists"] == ["Radiohead"]
    assert m["styles"] == ["Alternative Rock"]
    assert len(m["tracklist"]) == 2
    assert m["discogs_url"] == "https://www.discogs.com/master/40260"


def test_find_release_by_artist_title_prefers_exact(monkeypatch):
    fake_results = [
        {
            "discogs_id": 1, "title": "Radiohead - OK Computer", "year": 1997,
            "country": "US", "label": "Parlophone", "format": ["CD"],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        },
        {
            "discogs_id": 2, "title": "Some Other Album", "year": 2000,
            "country": "US", "label": "X", "format": [],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        },
    ]
    monkeypatch.setattr("pacer.services.discogs.search_releases", lambda q, per_page=20, page=1: fake_results)
    from pacer.services import discogs
    match = discogs.find_release_by_artist_title("Radiohead", "OK Computer")
    assert match is not None
    assert match["discogs_id"] == 1


def test_find_release_by_artist_title_falls_back_to_first(monkeypatch):
    fake_results = [
        {
            "discogs_id": 99, "title": "Different Album", "year": 2010,
            "country": "US", "label": "X", "format": [],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        },
    ]
    monkeypatch.setattr("pacer.services.discogs.search_releases", lambda q, per_page=20, page=1: fake_results)
    from pacer.services import discogs
    match = discogs.find_release_by_artist_title("Nonexistent", "Stuff")
    assert match["discogs_id"] == 99


def test_find_release_by_artist_title_returns_none_when_no_results(monkeypatch):
    monkeypatch.setattr("pacer.services.discogs.search_releases", lambda q, per_page=20, page=1: [])
    from pacer.services import discogs
    assert discogs.find_release_by_artist_title("X", "Y") is None


def test_find_artist_by_name_returns_first(monkeypatch):
    monkeypatch.setattr(
        "pacer.services.discogs.search_artists",
        lambda q, per_page=20: [{"id": 1, "title": "Radiohead"}],
    )
    from pacer.services import discogs
    assert discogs.find_artist_by_name("Radiohead")["id"] == 1
