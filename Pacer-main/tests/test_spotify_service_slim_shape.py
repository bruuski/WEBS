"""Structural test for the slimmed pacer.services.spotify module.

Task 2.2 removed 8 deprecated Spotify functions and kept only:
- spotify_configured
- get_app_spotify_token
- refresh_user_spotify_token
- fetch_spotify_trending
- lookup_spotify_preview

Phase 12 also removed ``fetch_spotify_playlist`` since the playlist-import
flow is being replaced with Discogs-only attach UX.
"""

import pacer.services.spotify as spotify


def test_kept_functions_exist():
    """All kept functions must be importable."""
    for name in (
        "spotify_configured",
        "get_app_spotify_token",
        "refresh_user_spotify_token",
        "fetch_spotify_trending",
        "lookup_spotify_preview",
    ):
        assert hasattr(spotify, name), f"missing kept function: {name}"
        assert callable(getattr(spotify, name))


def test_deprecated_functions_removed():
    """The 8 deprecated functions must be gone, plus fetch_spotify_playlist."""
    for name in (
        "_spotify_lookup_track",
        "backfill_covers_from_spotify",
        "_find_or_create_song_from_spotify",
        "_find_or_create_album_from_spotify",
        "_fetch_album_tracks",
        "find_or_create_artist",
        "fetch_artist",
        "fetch_artist_top_tracks",
        "fetch_artist_albums",
        "fetch_spotify_playlist",
    ):
        assert not hasattr(spotify, name), f"deprecated function still present: {name}"


def test_album_tracks_cache_removed():
    """_album_tracks_cache was only used by the removed _fetch_album_tracks."""
    assert not hasattr(spotify, "_album_tracks_cache")


def test_slim_module_keeps_only_requested_responsibilities():
    """No surprise public functions beyond the kept set."""
    allowed = {
        # helpers
        "spotify_configured",
        "get_app_spotify_token",
        # per-user OAuth
        "refresh_user_spotify_token",
        # trending
        "fetch_spotify_trending",
        # preview lookup
        "lookup_spotify_preview",
    }
    public = {
        n for n in dir(spotify)
        if not n.startswith("_")
        and callable(getattr(spotify, n))
    }
    extras = public - allowed
    assert not extras, f"unexpected public callables: {extras}"
