# Pacer

A music ratings + reviews site with a Spotify-powered trending feed. Y2K / Windows-98 aesthetic — chrome italic brand, a Napster-cat-meets-Spotify logo, sky-and-clouds wallpaper, beveled gray windows for every panel, a 7-segment LCD readout for the song score, Post-It featured reviews, threaded posts with greentext, and a working Win98 taskbar (Start menu + live clock). Flask + SQLite, no build step.

## Features

- Sign up / log in (scrypt-hashed passwords)
- Profile with avatar, mood, headline, About Me, favorite artists, and three themes (sky / sunset / cyber)
- **Trending tracks** on the home page, pulled live from Spotify's "Today's Top Hits" (with a 10-minute cache and a New Releases fallback)
- Click any trending cover to land on the rating page for that track — Pacer auto-creates the local song record from Spotify metadata on first click
- Rate any track 1–5 stars and write a review (one rating per user per song, editable)
- Pitchfork-style decimal score `7.8/10` derived from the average, rendered as a red 7-segment LCD
- 4chan-style threaded posts (`>` becomes greentext, `>>` becomes a quotelink) on profiles and bulletins
- Genius-style featured review block on each track page (styled here as a Post-It note)
- Browse / search / sort the chart (top rated, hottest, newest, A–Z)
- Embedded Spotify player on any track that has a `spotify_id`
- "Connect Spotify" on your own profile → shows your last-4-weeks top tracks
- Win98 taskbar with a real Start menu and a live clock
- **Blog** — a community thread board where logged-in users start their own threads (subject + body) and others reply; recent threads also show up in a column on the home page

The dedicated "submit a track" page has been removed — tracks enter the local DB the first time someone clicks a Spotify trending pick.

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>. The first run creates `pacer.db` and seeds demo users and songs.

## Spotify configuration

Spotify is optional. Without these vars, the trending grid and search widget show a "not configured" notice but the rest of the app works.

```bash
export SPOTIFY_CLIENT_ID=xxx
export SPOTIFY_CLIENT_SECRET=xxx
export SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/spotify/callback   # default
export SPOTIFY_TRENDING_PLAYLIST=37i9dQZF1DXcBWIGoYBM5M               # default = Today's Top Hits
```

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Add `http://127.0.0.1:5000/spotify/callback` (or whatever your host is) as a Redirect URI.
3. Copy the Client ID and Client Secret into the env vars above.
4. Restart the app.

**Capabilities:**
- Trending feed and track search both use the Client Credentials flow (no per-user login needed).
- "Connect Spotify" on a profile uses the Authorization Code flow and stores access + refresh tokens per user.
- The "Your top tracks" widget on your own profile calls `/me/top/tracks` with the user's stored token.

## Demo accounts

All passwords are `password` except `tom` which is `myspace`:

- `tom`, `brunette`, `joey`, `kamal`, `dustyn`, `layouts`, `anon`

## Project layout

```
app.py             # routes, schema, migrations, seed, Spotify integration
requirements.txt
static/
  style.css        # Y2K Win98 / Bliss-sky theme
  spotify.js       # search widget (open-on-Spotify mode)
templates/
  base.html        # masthead with cat-logo, taskbar, start menu
  home.html        # trending grid + chart + bulletins
  signup.html
  login.html
  profile.html
  edit_profile.html
  browse.html
  song.html
  blog_list.html
  blog_thread.html
```
