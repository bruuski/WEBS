"""Discogs has been removed from Pacer.

This module is kept as a no-op shim so that existing imports
(``from pacer.services import discogs``) and call sites
(``discogs.discogs_configured()``, ``discogs.get_release(...)``, etc.)
do not need to be modified — they simply get falsy values and skip
their Discogs-enrichment branches.

Spotify is now the canonical metadata source (see
``pacer/services/spotify.py``).
"""
from __future__ import annotations


def discogs_configured() -> bool:
    return False


def find_release_by_artist_title(artist: str, title: str):
    return None


def find_artist_by_name(name: str):
    return None


def get_release(release_id: int):
    return None


def get_master(master_id: int):
    return None


def get_artist(artist_id: int):
    return None


def search_releases(q: str, per_page: int = 12):
    return []


def search_artists(q: str, per_page: int = 12):
    return []
