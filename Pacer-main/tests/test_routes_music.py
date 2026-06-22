"""Integration tests for music routes with Discogs enrichment."""


def test_find_or_create_song_returns_existing_by_spotify_id(temp_db, monkeypatch):
    """If song already in DB by spotify_id, return it (no Discogs call)."""
    import pacer.routes.music as music
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'test', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at, spotify_id, spotify_image)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01', 'spotify-abc', 'image.jpg')"""
    )
    con.commit()
    con.close()

    called = {"n": 0}
    def fake(*a, **kw):
        called["n"] += 1
        raise AssertionError("should not call Discogs when song exists")
    monkeypatch.setattr(music.discogs, "find_release_by_artist_title", fake)

    result = music.find_or_create_song_from_spotify({
        "id": "spotify-abc", "name": "Airbag",
        "artists": "Radiohead", "image": "image.jpg",
    })
    assert result["id"] == 1
    assert called["n"] == 0


def test_find_or_create_song_creates_with_discogs_metadata(temp_db, monkeypatch):
    """New song → Discogs lookup → row inserted with discogs_release_id."""
    import pacer.routes.music as music
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'test', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(music.discogs, "find_release_by_artist_title",
                        lambda a, t: {"discogs_id": 999})
    monkeypatch.setattr(music.discogs, "get_release",
                        lambda rid: {
                            "id": 999, "title": "OK Computer", "year": 1997,
                            "country": "UK", "label": "Parlophone",
                            "catalog_no": "NODATA01", "format": ["CD"],
                            "genres": ["Rock"], "styles": ["Alternative Rock"],
                            "tracklist": [], "artists": ["Radiohead"],
                            "master_id": 0, "master_url": "", "release_url": "",
                            "cover_image": "x", "thumb": "y",
                        })
    monkeypatch.setattr(music.discogs, "find_artist_by_name",
                        lambda n: {"id": 1, "title": "Radiohead"})
    monkeypatch.setattr(music.discogs, "get_artist", lambda aid: {
        "id": 1, "name": "Radiohead", "real_name": "Radiohead",
        "profile": "English rock band", "urls": [], "aliases": [],
        "members": [], "name_variations": [], "images": [],
        "discogs_url": "https://www.discogs.com/artist/1",
    })
    monkeypatch.setattr(music, "lookup_spotify_preview",
                        lambda a, t: {"spotify_id": "spotify-xyz",
                                      "preview_url": "https://preview.mp3",
                                      "spotify_url": "https://open.spotify.com/track/spotify-xyz"})

    result = music.find_or_create_song_from_spotify({
        "id": "spotify-xyz", "name": "Airbag",
        "artists": "Radiohead", "image": "image.jpg",
    })
    assert result["spotify_id"] == "spotify-xyz"
    assert result["discogs_release_id"] == 999
    assert result["title"] == "Airbag"

    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    row = con.execute("SELECT * FROM songs WHERE spotify_id = ?", ("spotify-xyz",)).fetchone()
    assert row is not None
    assert row["discogs_release_id"] == 999
    assert row["title"] == "Airbag"
    styles = con.execute("SELECT style FROM song_styles WHERE song_id = ?", (row["id"],)).fetchall()
    assert ("Alternative Rock",) in [tuple(r) for r in styles]
    con.close()


def test_find_or_create_song_handles_no_discogs_match(temp_db, monkeypatch):
    """When Discogs returns no match, save song without metadata."""
    import pacer.routes.music as music
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'test', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(music.discogs, "find_release_by_artist_title", lambda a, t: None)
    monkeypatch.setattr(music, "lookup_spotify_preview", lambda a, t: None)

    result = music.find_or_create_song_from_spotify({
        "id": "spotify-orphan", "name": "Obscure Track",
        "artists": "Unknown Artist", "image": "image.jpg",
    })
    assert result["spotify_id"] == "spotify-orphan"
    assert result["discogs_release_id"] is None

    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    row = con.execute("SELECT * FROM songs WHERE spotify_id = ?", ("spotify-orphan",)).fetchone()
    assert row is not None
    assert row["discogs_release_id"] is None
    con.close()


def test_feed_home_persists_trending_songs(temp_db, client, monkeypatch):
    """Homepage trending items get persisted as songs (with Discogs enrichment)."""
    from pacer.routes import music
    from pacer.routes import feed
    import pacer.db as db

    # Need at least one user for find_or_create_song_from_spotify to work
    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    # Stub fetch_spotify_trending so we don't hit the network. Patch the
    # symbol where feed.py imported it from to avoid circular import issues.
    from pacer.services import spotify
    monkeypatch.setattr(spotify, "fetch_spotify_trending", lambda limit=6: [
        {"id": "sp-1", "name": "Airbag", "artists": "Radiohead", "image": "img.jpg", "url": "u1"},
        {"id": "sp-2", "name": "Idioteque", "artists": "Radiohead", "image": "img.jpg", "url": "u2"},
    ])
    # Also rebind in the feed module since the import was bound at import time
    monkeypatch.setattr(feed, "fetch_spotify_trending", lambda limit=6: [
        {"id": "sp-1", "name": "Airbag", "artists": "Radiohead", "image": "img.jpg", "url": "u1"},
        {"id": "sp-2", "name": "Idioteque", "artists": "Radiohead", "image": "img.jpg", "url": "u2"},
    ])

    # Stub Discogs to return None (no enrichment; songs still get persisted)
    monkeypatch.setattr(music.discogs, "find_release_by_artist_title", lambda a, t: None)
    monkeypatch.setattr(music, "lookup_spotify_preview", lambda a, t: None)

    resp = client.get("/")
    assert resp.status_code == 200

    # Verify both songs were persisted
    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    rows = con.execute(
        "SELECT * FROM songs WHERE spotify_id IN ('sp-1', 'sp-2') ORDER BY spotify_id"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["title"] == "Airbag"
    assert rows[0]["artist"] == "Radiohead"
    assert rows[1]["title"] == "Idioteque"
    con.close()


def test_song_detail_renders_catalog_panel(temp_db, client, monkeypatch):
    """Song with discogs_release_id → catalog panel rendered."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at,
                              spotify_id, spotify_image, discogs_release_id)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01',
                   'sp-abc', 'img.jpg', 12345)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 12345, "title": "OK Computer", "year": 1997, "country": "UK",
        "label": "Parlophone", "catalog_no": "NODATA01", "format": ["CD", "Album"],
        "genres": ["Rock"], "styles": ["Alternative Rock", "Art Rock"],
        "tracklist": [], "artists": ["Radiohead"],
        "master_id": 0, "master_url": "", "release_url": "https://www.discogs.com/release/12345",
        "cover_image": "", "thumb": "",
    })

    resp = client.get("/songs/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Catalog Info" in body
    assert "Parlophone" in body
    assert "Alternative Rock" in body
    assert "https://www.discogs.com/release/12345" in body


def test_song_detail_without_discogs_metadata(temp_db, client, monkeypatch):
    """Song without discogs_release_id → no catalog panel rendered."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at, spotify_id)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01', 'sp-abc')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)

    resp = client.get("/songs/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Catalog Info" not in body


def test_album_detail_renders_tracklist_from_discogs(temp_db, client, monkeypatch):
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO albums (id, name, artist, created_at, spotify_id, discogs_release_id)
           VALUES (1, 'OK Computer', 'Radiohead', '2026-01-01', '', 12345)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 12345, "title": "OK Computer", "year": 1997, "country": "UK",
        "label": "Parlophone", "catalog_no": "NODATA01", "format": ["CD"],
        "genres": ["Rock"], "styles": ["Alternative Rock"],
        "tracklist": [
            {"position": "1", "title": "Airbag", "duration": "4:44", "artists": ["Radiohead"]},
            {"position": "2", "title": "Paranoid Android", "duration": "6:23", "artists": ["Radiohead"]},
        ],
        "artists": ["Radiohead"], "master_id": 0, "master_url": "",
        "release_url": "https://www.discogs.com/release/12345",
        "cover_image": "", "thumb": "",
    })

    resp = client.get("/albums/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Airbag" in body
    assert "Paranoid Android" in body
    assert "4:44" in body
    assert "Parlophone" in body
    assert "https://www.discogs.com/release/12345" in body


def test_artist_detail_renders_discogs_bio(temp_db, client, monkeypatch):
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO artists (id, name, spotify_id, discogs_id)
           VALUES (1, 'Radiohead', 'discogs:3840', 3840)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_artist", lambda did: {
        "id": 3840, "name": "Radiohead", "real_name": "Radiohead",
        "profile": "English rock band from Abingdon, Oxfordshire.",
        "urls": ["https://radiohead.com"], "aliases": ["Atoms For Peace"],
        "members": ["Thom Yorke", "Jonny Greenwood"],
        "name_variations": ["Radio Head"],
        "images": [], "discogs_url": "https://www.discogs.com/artist/3840",
    })
    # NOTE: fetch_artist_top_tracks / fetch_artist_albums do not exist in
    # pacer.services.discogs and are not called by artist_detail. Plan deviation.

    resp = client.get("/artists/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "English rock band" in body
    assert "Thom Yorke" in body
    assert "Atoms For Peace" in body
    assert "https://www.discogs.com/artist/3840" in body


def test_browse_filters_by_style(temp_db, client):
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at)
           VALUES (1, 'Airbag', 'Radiohead', 1, '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at)
           VALUES (2, 'Black Sabbath', 'Black Sabbath', 1, '2026-01-01')"""
    )
    con.execute("INSERT INTO song_styles (song_id, style) VALUES (1, 'Shoegaze')")
    con.execute("INSERT INTO song_styles (song_id, style) VALUES (2, 'Heavy Metal')")
    con.commit()
    con.close()

    resp = client.get("/songs?style=Shoegaze")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Airbag" in body
    assert "Black Sabbath" not in body


def test_search_proxies_to_discogs_with_preview_badge(temp_db, client, monkeypatch):
    import pacer.db as db
    from pacer.routes import spotify as spotify_route
    from pacer.services import discogs

    # Pre-seed a user (so DB has a submitter for new songs)
    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(spotify_route.discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(spotify_route.discogs, "search_releases", lambda q, per_page=20, page=1: [
        {
            "discogs_id": 12345, "title": "Radiohead - OK Computer", "year": 1997,
            "country": "UK", "label": "Parlophone", "format": ["CD", "Album"],
            "thumb": "https://example.com/ok.jpg", "cover_image": "https://example.com/ok-large.jpg",
            "genre": ["Rock"], "style": ["Alternative Rock"], "uri": "", "resource_url": "",
        }
    ])
    monkeypatch.setattr(spotify_route.discogs, "get_release", lambda rid: {
        "id": 12345, "title": "OK Computer", "year": 1997, "country": "UK",
        "label": "Parlophone", "catalog_no": "X", "format": ["CD"],
        "genres": ["Rock"], "styles": ["Alternative Rock"],
        "tracklist": [{"position": "1", "title": "Airbag", "duration": "4:44", "artists": ["Radiohead"]}],
        "artists": ["Radiohead"], "master_id": 0, "master_url": "",
        "release_url": "", "cover_image": "", "thumb": "",
    })
    # Patch the imported reference in the route module so the call inside
    # spotify_search sees the mock.
    monkeypatch.setattr(spotify_route, "lookup_spotify_preview",
                        lambda a, t: {"spotify_id": "sp-xyz",
                                      "preview_url": "https://preview.mp3",
                                      "spotify_url": "https://open.spotify.com/track/sp-xyz"})

    resp = client.get("/spotify/search?q=Radiohead")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["discogs_id"] == 12345
    assert item["title"] == "Radiohead - OK Computer"
    assert item["label"] == "Parlophone"
    assert item["has_preview"] is True
    assert item["spotify_id"] == "sp-xyz"


def test_search_returns_empty_when_query_missing(client):
    resp = client.get("/spotify/search")
    assert resp.status_code == 200
    assert resp.get_json() == {"items": []}


def test_search_returns_503_when_discogs_not_configured(client, monkeypatch):
    from pacer.routes import spotify as spotify_route
    monkeypatch.setattr(spotify_route.discogs, "discogs_configured", lambda: False)
    resp = client.get("/spotify/search?q=anything")
    assert resp.status_code == 503
    assert "error" in resp.get_json()


def test_search_falls_back_to_cover_image_when_thumb_empty(temp_db, client, monkeypatch):
    """When Discogs search returns thumb='', the route should upgrade it
    to cover_image from the full release fetch (which it already does to
    grab the first track for preview lookup)."""
    import pacer.db as db
    from pacer.routes import spotify as spotify_route

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(spotify_route.discogs, "discogs_configured", lambda: True)
    # search returns an empty thumb (some older / obscure releases)
    monkeypatch.setattr(spotify_route.discogs, "search_releases", lambda q, per_page=20, page=1: [
        {
            "discogs_id": 99999, "title": "An Old Record - Forgotten Album", "year": 1970,
            "country": "US", "label": "OldLabel", "format": ["Vinyl"],
            "thumb": "", "cover_image": "", "genre": [], "style": [],
            "uri": "", "resource_url": "",
        }
    ])
    # ...but the full release has a cover_image
    monkeypatch.setattr(spotify_route.discogs, "get_release", lambda rid: {
        "id": 99999, "title": "Forgotten Album", "year": 1970, "country": "US",
        "label": "OldLabel", "catalog_no": "X", "format": ["Vinyl"],
        "genres": [], "styles": [],
        "tracklist": [{"position": "1", "title": "Track One", "duration": "3:00", "artists": ["An Old Record"]}],
        "artists": ["An Old Record"], "master_id": 0, "master_url": "",
        "release_url": "", "cover_image": "https://example.com/cover.jpg", "thumb": "",
    })
    monkeypatch.setattr(spotify_route, "lookup_spotify_preview", lambda a, t: None)

    resp = client.get("/spotify/search?q=old")
    assert resp.status_code == 200
    item = resp.get_json()["items"][0]
    assert item["thumb"] == "https://example.com/cover.jpg", \
        "thumb should be upgraded to cover_image when search returned empty"


def test_search_upgrades_to_cover_image_when_available(temp_db, client, monkeypatch):
    """When the full release fetch returns a higher-res cover_image, prefer
    it over the smaller search thumb (we're already paying for the call)."""
    import pacer.db as db
    from pacer.routes import spotify as spotify_route

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(spotify_route.discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(spotify_route.discogs, "search_releases", lambda q, per_page=20, page=1: [
        {
            "discogs_id": 12345, "title": "Artist - Album", "year": 2020,
            "country": "US", "label": "L", "format": ["CD"],
            "thumb": "https://example.com/thumb.jpg", "cover_image": "https://example.com/cover.jpg",
            "genre": [], "style": [], "uri": "", "resource_url": "",
        }
    ])
    monkeypatch.setattr(spotify_route.discogs, "get_release", lambda rid: {
        "id": 12345, "title": "Album", "year": 2020, "country": "US",
        "label": "L", "catalog_no": "X", "format": ["CD"],
        "genres": [], "styles": [], "tracklist": [],
        "artists": ["Artist"], "master_id": 0, "master_url": "",
        "release_url": "", "cover_image": "https://example.com/cover.jpg", "thumb": "",
    })
    monkeypatch.setattr(spotify_route, "lookup_spotify_preview", lambda a, t: None)

    resp = client.get("/spotify/search?q=artist")
    assert resp.status_code == 200
    item = resp.get_json()["items"][0]
    # The route prefers cover_image from the full release (higher res)
    assert item["thumb"] == "https://example.com/cover.jpg"


def test_album_detail_renders_styles_and_artist_link(temp_db, client):
    """Album page should render Discogs styles as chips and link to the artist page."""
    import pacer.db as db

    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    # Seed a user
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    # Seed an artist
    con.execute(
        """INSERT INTO artists (id, spotify_id, name)
           VALUES (1, 'discogs-stub:The Weeknd', 'The Weeknd')"""
    )
    # Seed an album linked to that artist
    con.execute(
        """INSERT INTO albums (id, name, artist, year, created_at, discogs_release_id,
                               label, format, country, catalog_no, cover_image,
                               submitted_by, artist_id, discogs_artists)
           VALUES (4, 'After Hours', 'The Weeknd', 2020, '2026-01-01', 15961158,
                   'XO', 'Vinyl', 'Europe', '00602508818400',
                   'https://example.com/cover.jpg', 1, 1, 'The Weeknd')"""
    )
    # Seed styles
    con.executemany(
        "INSERT INTO album_styles (album_id, style) VALUES (4, ?)",
        [("Contemporary R&B",), ("Disco",), ("New Wave",), ("Pop Rap",), ("Synth-pop",), ("Synthwave",)],
    )
    con.commit()
    con.close()

    resp = client.get("/albums/4")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Style chips rendered
    assert "Contemporary R&amp;B" in body or "Contemporary R&B" in body
    assert "Synth-pop" in body
    assert "Disco" in body
    # Style chip is a link
    assert "style=Synth-pop" in body or "/songs?style=Synth-pop" in body
    # Artist link to the artist page
    assert "/artists/1" in body


def test_artist_detail_enriches_stub_via_discogs(temp_db, client, monkeypatch):
    """Stub artists (no discogs_id) should be auto-enriched from Discogs on first visit."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    # Seed a stub artist (no discogs_id)
    con.execute(
        """INSERT INTO artists (id, spotify_id, name) VALUES (1, 'discogs-stub:Sex Pistols', 'Sex Pistols')"""
    )
    con.commit()
    con.close()

    # Stub the Discogs service
    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "find_artist_by_name", lambda name: {"id": 16435, "thumb": "https://example.com/p.jpg"})
    monkeypatch.setattr(discogs, "get_artist", lambda did: {
        "id": 16435, "name": "Sex Pistols", "real_name": "Sex Pistols",
        "profile": "English punk rock band formed in London in 1975.",
        "members": [{"name": "Johnny Rotten", "id": 164360}],
        "aliases": [], "urls": ["https://www.sexpistolsofficial.com/"],
        "images": [], "discogs_url": "",
    })

    resp = client.get("/artists/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Sex Pistols" in body
    # Bio should now be rendered
    assert "English punk rock band" in body

    # The local row should have been updated with the real discogs_id
    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    row = con.execute("SELECT discogs_id, image_url FROM artists WHERE id = 1").fetchone()
    assert row["discogs_id"] == 16435
    con.close()


def test_album_detail_renders_video_thumbnails(temp_db, client, monkeypatch):
    """Album page should render YouTube video thumbnails from Discogs."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO artists (id, spotify_id, name) VALUES (1, 'discogs-stub:Sex Pistols', 'Sex Pistols')"""
    )
    con.execute(
        """INSERT INTO albums (id, name, artist, year, created_at, discogs_release_id,
                               submitted_by, artist_id, discogs_artists)
           VALUES (5, 'Never Mind The Bollocks', 'Sex Pistols', 1977, '2026-01-01', 9008451, 1, 1, 'Sex Pistols')"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 9008451, "title": "Never Mind The Bollocks", "year": 1977,
        "country": "UK", "label": "Virgin", "catalog_no": "V 2086",
        "format": ["LP", "Album"],
        "genres": ["Rock"], "styles": ["Punk"],
        "tracklist": [{"position": "1", "title": "Holidays In The Sun", "duration": "3:22", "artists": []}],
        "artists": ["Sex Pistols"],
        "master_id": 30000, "master_url": "", "release_url": "https://www.discogs.com/release/9008451",
        "cover_image": "", "thumb": "",
        "videos": [
            {
                "id": "dQw4w9WgXcQ",
                "title": "Sex Pistols - Never Mind The Bollocks [Full Album]",
                "duration": 2745,
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "thumb": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
            },
            {
                "id": "abc123XYZ",
                "title": "Anarchy in the U.K.",
                "duration": 220,
                "url": "https://www.youtube.com/watch?v=abc123XYZ",
                "thumb": "https://i.ytimg.com/vi/abc123XYZ/hqdefault.jpg",
            },
        ],
    })

    resp = client.get("/albums/5")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Both videos rendered
    assert "dQw4w9WgXcQ" in body
    assert "abc123XYZ" in body
    # Thumbnails use ytimg.com
    assert "ytimg.com" in body
    # YouTube watch links
    assert "youtube.com/watch?v=dQw4w9WgXcQ" in body
    assert "youtube.com/watch?v=abc123XYZ" in body
    # Duration rendered
    assert "45:45" in body  # 2745 sec = 45:45


def test_song_detail_renders_video_thumbnails(temp_db, client, monkeypatch):
    """Song page should render YouTube video thumbnails when the song's release has videos."""
    import pacer.db as db
    from pacer.services import discogs

    con = db.sqlite3.connect(temp_db)
    con.row_factory = db.sqlite3.Row
    con.execute(
        """INSERT INTO users (id, username, password_hash, password_salt, created_at)
           VALUES (1, 'tester', 'h', 's', '2026-01-01')"""
    )
    con.execute(
        """INSERT INTO songs (id, title, artist, submitted_by, created_at, discogs_release_id)
           VALUES (1, 'Holidays In The Sun', 'Sex Pistols', 1, '2026-01-01', 9008451)"""
    )
    con.commit()
    con.close()

    monkeypatch.setattr(discogs, "discogs_configured", lambda: True)
    monkeypatch.setattr(discogs, "get_release", lambda rid: {
        "id": 9008451, "title": "Never Mind The Bollocks", "year": 1977,
        "country": "UK", "label": "Virgin", "catalog_no": "V 2086",
        "format": ["LP"], "genres": ["Rock"], "styles": ["Punk"],
        "tracklist": [], "artists": ["Sex Pistols"],
        "master_id": 30000, "master_url": "", "release_url": "",
        "cover_image": "", "thumb": "",
        "videos": [
            {
                "id": "VIDEO1",
                "title": "Anarchy in the U.K. (Official Video)",
                "duration": 220,
                "url": "https://www.youtube.com/watch?v=VIDEO1",
                "thumb": "https://i.ytimg.com/vi/VIDEO1/hqdefault.jpg",
            },
        ],
    })

    resp = client.get("/songs/1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "VIDEO1" in body
    assert "ytimg.com" in body
    assert "Anarchy" in body
