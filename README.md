# TuneSpace

A music ratings + reviews site with a Spotify search widget. Editorial aesthetic — Pitchfork-style scores, Genius-style featured review blocks, 4chan-style threaded posts (greentext supported), and an "online now" grid. Flask + SQLite, no build step.

## Features

- Sign up / log in (scrypt-hashed passwords)
- Profile with avatar, mood, headline, About Me, favorite artists, and three themes (mag / noir / lab)
- Submit tracks (title, artist, album, year, genre, listen URL) — or pick from Spotify search to autofill
- Rate any track 1–5 stars and write a review (one rating per user per song, editable)
- Pitchfork-style decimal score `7.8/10` derived from the average
- 4chan-style threaded posts (`>` becomes greentext, `>>` becomes a quotelink) on profiles and bulletins
- Genius-style featured review block on each track page
- Browse / search / sort the chart (top rated, hottest, newest, A–Z)
- Embedded Spotify player on any track that has a `spotify_id`
- "Connect Spotify" on your own profile → shows your last-4-weeks top tracks

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>. The first run creates `tunespace.db` and seeds demo users and songs.

## Spotify configuration

Spotify is optional. Without these vars, the search widget shows a "not configured" message but the rest of the app works.

```bash
export SPOTIFY_CLIENT_ID=xxx
export SPOTIFY_CLIENT_SECRET=xxx
export SPOTIFY_REDIRECT_URI=http://127.0.0.1:5000/spotify/callback   # default
```

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Add `http://127.0.0.1:5000/spotify/callback` (or whatever your host is) as a Redirect URI.
3. Copy the Client ID and Client Secret into the env vars above.
4. Restart the app.

**Capabilities:**
- Track search runs server-side with the Client Credentials flow (no per-user login needed).
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
  style.css        # editorial / Pitchfork / Genius / 4chan blend
  spotify.js       # search widget (autofills the submit form)
templates/
  base.html
  home.html
  signup.html
  login.html
  profile.html
  edit_profile.html
  browse.html
  submit_song.html
  song.html
```
