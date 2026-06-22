# AI guidance for Pacer

This file gives AI coding assistants (Cursor, Claude Code, GitHub Copilot, etc.) the architectural context they need to work on Pacer effectively.

## Data sources (as of 2026-06-10)

Pacer uses a **Discogs-first** data layer:

- **Discogs** is the primary source for artist, album, and track metadata (genre, style, label, format, year, country, catalog #, real name, members, aliases, profile, URLs).
- **Spotify** is used only for two things: 30-second audio preview URLs (per-track lookup via `lookup_spotify_preview`) and the "Today's Top Hits" featured playlist that drives the homepage trending grid.

If you are adding a feature that needs metadata (artist bio, album cover, track title, release year, genre tags), **use Discogs**, not Spotify. Use `pacer.services.discogs` for OAuth 1.0a-signed Discogs calls. Use `pacer.services.spotify` only for previews and trending.

## Schema

- Backward-compatible schema lives in `pacer/db.py`. New columns are added via `ALTER TABLE ADD COLUMN` in `init_db()`.
- Discogs-specific tables: `song_styles`, `album_styles`. New columns on `artists`, `songs`, `albums` for Discogs IDs and metadata.
- Spotify preview cache: `spotify_preview_cache` (30-day TTL, hits + misses).

## Conventions

- Routes are Flask Blueprints under `pacer/routes/`. Service modules under `pacer/services/`.
- Templates are Jinja2 in `templates/`. Use HTMX where it already is; add plain fetch/AJAX for new dynamic widgets.
- Styling is in `static/style.css` (single file with `body.theme-*` rules for sky / sunset / cyber).
- Tests are in `tests/` and run with `pytest -v`. Use the `temp_db`, `app`, and `client` fixtures in `conftest.py`.

## Reference

- Design spec: `docs/superpowers/specs/2026-06-10-discogs-first-data-layer-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-10-discogs-first-data-layer.md`
- Discogs setup walkthrough: `docs/discogs-setup.md`
- Environment variables: `.env.example`
