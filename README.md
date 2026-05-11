# TuneSpace

A MySpace-flavored blog where people sign up, make a profile, and rate music. Built as a single Flask app with SQLite — no build step, no JS framework, just gradients and Comic Neue.

## Features

- Sign up / log in (scrypt-hashed passwords)
- Personalize your profile: avatar emoji, mood, headline, about me, favorite bands, theme (pink / blue / lime / neon)
- Submit songs (title, artist, album, year, genre, listen URL)
- Rate any song 1–5 stars and leave a written review (one rating per user per song, editable)
- Browse / search / sort the song chart (top rated, hottest, newest, A–Z)
- Profile pages with comments, top friends, recent ratings, and submitted songs
- Front-page bulletins, "online now" panel, marquee, and (allegedly) glitter

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>.

The first run creates `tunespace.db` and seeds demo users and songs.

### Demo accounts

All passwords are `password` except `tom` which is `myspace`:

- `tom`, `brunette`, `joey4eva`, `xkamalx`, `duztin`, `hide_codes`

## Project layout

```
app.py             # routes, schema, seed
requirements.txt
static/style.css   # the entire vibe
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
