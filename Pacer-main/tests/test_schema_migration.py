"""Verify the 2026-06-10 schema migration creates the new tables and columns."""


def test_song_styles_table_exists(temp_db):
    import sqlite3 as _sqlite3
    from pacer import db
    con = _sqlite3.connect(temp_db)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='song_styles'"
    )
    assert cur.fetchone() is not None
    con.close()


def test_album_styles_table_exists(temp_db):
    import sqlite3 as _sqlite3
    from pacer import db
    con = _sqlite3.connect(temp_db)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='album_styles'"
    )
    assert cur.fetchone() is not None
    con.close()


def test_spotify_preview_cache_table_exists(temp_db):
    import sqlite3 as _sqlite3
    from pacer import db
    con = _sqlite3.connect(temp_db)
    cur = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='spotify_preview_cache'"
    )
    assert cur.fetchone() is not None
    con.close()


def test_artists_has_discogs_columns(temp_db):
    import sqlite3 as _sqlite3
    from pacer import db
    con = _sqlite3.connect(temp_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(artists)").fetchall()]
    assert "discogs_id" in cols
    assert "real_name" in cols
    assert "profile_text" in cols
    assert "aliases" in cols
    assert "members" in cols
    assert "urls" in cols
    assert "namevariations" in cols
    con.close()


def test_songs_has_discogs_columns(temp_db):
    import sqlite3 as _sqlite3
    from pacer import db
    con = _sqlite3.connect(temp_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(songs)").fetchall()]
    assert "discogs_release_id" in cols
    assert "discogs_master_id" in cols
    assert "position_in_release" in cols
    assert "duration_ms" in cols
    assert "discogs_artists" in cols
    con.close()


def test_albums_has_discogs_columns(temp_db):
    import sqlite3 as _sqlite3
    from pacer import db
    con = _sqlite3.connect(temp_db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(albums)").fetchall()]
    assert "discogs_release_id" in cols
    assert "discogs_master_id" in cols
    assert "label" in cols
    assert "format" in cols
    assert "country" in cols
    assert "catalog_no" in cols
    assert "release_url" in cols
    assert "master_url" in cols
    con.close()
