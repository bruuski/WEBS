"""TuneSpace -- a MySpace-flavored music rating blog."""
import os
import re
import sqlite3
import secrets
import hashlib
from datetime import datetime
from functools import wraps

from flask import (
    Flask, g, request, redirect, url_for, session,
    render_template, flash, abort,
)

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, "tunespace.db")

app = Flask(__name__)
app.secret_key = os.environ.get("TUNESPACE_SECRET", "glitter-gel-pen-2006")


# ---------- database ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    display_name  TEXT,
    mood          TEXT DEFAULT 'bouncy',
    headline      TEXT DEFAULT 'woo :)',
    about_me      TEXT DEFAULT '',
    fav_bands     TEXT DEFAULT '',
    location      TEXT DEFAULT 'somewhere on the internet',
    age           INTEGER,
    avatar_emoji  TEXT DEFAULT '★',
    theme         TEXT DEFAULT 'pink',
    created_at    TEXT NOT NULL,
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS songs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    artist      TEXT NOT NULL,
    album       TEXT,
    year        INTEGER,
    genre       TEXT,
    link        TEXT,
    submitted_by INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ratings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    song_id   INTEGER NOT NULL REFERENCES songs(id),
    user_id   INTEGER NOT NULL REFERENCES users(id),
    stars     INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    review    TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(song_id, user_id)
);

CREATE TABLE IF NOT EXISTS bulletins (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL REFERENCES users(id),
    subject   TEXT NOT NULL,
    body      TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  INTEGER NOT NULL REFERENCES users(id),
    author_id   INTEGER NOT NULL REFERENCES users(id),
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


# ---------- auth helpers ----------

def hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(
        password.encode(), salt=salt.encode(), n=16384, r=8, p=1, dklen=32
    ).hex()


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    row = get_db().execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return row


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            flash("U gotta log in first ✿", "warn")
            return redirect(url_for("login", next=request.path))
        return fn(*a, **kw)
    return wrapper


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "now": datetime.utcnow(),
    }


@app.template_filter("stars")
def stars_filter(value):
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return "no ratings yet"
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


@app.template_filter("datefmt")
def datefmt(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    return dt.strftime("%m/%d/%Y %I:%M %p").lstrip("0")


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")


# ---------- routes ----------

@app.route("/")
def home():
    db = get_db()
    top_songs = db.execute("""
        SELECT s.*, u.username AS submitter,
               COALESCE(AVG(r.stars), 0) AS avg_stars,
               COUNT(r.id) AS rating_count
        FROM songs s
        JOIN users u ON u.id = s.submitted_by
        LEFT JOIN ratings r ON r.song_id = s.id
        GROUP BY s.id
        ORDER BY avg_stars DESC, rating_count DESC, s.id DESC
        LIMIT 10
    """).fetchall()
    fresh_songs = db.execute("""
        SELECT s.*, u.username AS submitter
        FROM songs s JOIN users u ON u.id = s.submitted_by
        ORDER BY s.id DESC LIMIT 6
    """).fetchall()
    bulletins = db.execute("""
        SELECT b.*, u.username FROM bulletins b
        JOIN users u ON u.id = b.user_id
        ORDER BY b.id DESC LIMIT 8
    """).fetchall()
    online_users = db.execute("""
        SELECT id, username, avatar_emoji, mood FROM users
        ORDER BY last_login DESC NULLS LAST, id DESC LIMIT 12
    """).fetchall()
    counts = db.execute("""
        SELECT (SELECT COUNT(*) FROM users)   AS users,
               (SELECT COUNT(*) FROM songs)   AS songs,
               (SELECT COUNT(*) FROM ratings) AS ratings
    """).fetchone()
    return render_template(
        "home.html",
        top_songs=top_songs,
        fresh_songs=fresh_songs,
        bulletins=bulletins,
        online_users=online_users,
        counts=counts,
    )


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        display_name = (request.form.get("display_name") or "").strip() or username
        location = (request.form.get("location") or "").strip() or "somewhere on the internet"
        age_raw = request.form.get("age") or ""
        fav_bands = (request.form.get("fav_bands") or "").strip()
        theme = request.form.get("theme") or "pink"

        if not USERNAME_RE.match(username):
            flash("Username must be 3-20 chars, letters/numbers/underscore only.", "warn")
            return render_template("signup.html")
        if len(password) < 4:
            flash("Password too short, c'mon.", "warn")
            return render_template("signup.html")
        try:
            age = int(age_raw) if age_raw else None
        except ValueError:
            age = None

        salt = secrets.token_hex(16)
        pw_hash = hash_password(password, salt)
        db = get_db()
        try:
            cur = db.execute(
                """INSERT INTO users
                   (username, password_hash, password_salt, display_name,
                    location, age, fav_bands, theme, created_at, last_login)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (username, pw_hash, salt, display_name, location, age,
                 fav_bands, theme,
                 datetime.utcnow().isoformat(timespec="seconds"),
                 datetime.utcnow().isoformat(timespec="seconds")),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("That username is already taken :(", "warn")
            return render_template("signup.html")
        session["user_id"] = cur.lastrowid
        flash("Welcome to TuneSpace!! ♡", "ok")
        return redirect(url_for("profile", username=username))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not row or hash_password(password, row["password_salt"]) != row["password_hash"]:
            flash("Wrong username or password, sry.", "warn")
            return render_template("login.html")
        session["user_id"] = row["id"]
        get_db().execute(
            "UPDATE users SET last_login = ? WHERE id = ?",
            (datetime.utcnow().isoformat(timespec="seconds"), row["id"]),
        )
        get_db().commit()
        flash(f"hey {row['username']} :)", "ok")
        return redirect(request.args.get("next") or url_for("home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("logged out. bye!! 〜(￣▽￣〜)", "ok")
    return redirect(url_for("home"))


@app.route("/u/<username>", methods=["GET", "POST"])
def profile(username):
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not user:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to leave a comment.", "warn")
            return redirect(url_for("login"))
        body = (request.form.get("body") or "").strip()
        if body:
            db.execute(
                "INSERT INTO comments (profile_id, author_id, body, created_at) VALUES (?,?,?,?)",
                (user["id"], session["user_id"], body[:1000],
                 datetime.utcnow().isoformat(timespec="seconds")),
            )
            db.commit()
        return redirect(url_for("profile", username=username))

    ratings = db.execute("""
        SELECT r.*, s.title, s.artist FROM ratings r
        JOIN songs s ON s.id = r.song_id
        WHERE r.user_id = ?
        ORDER BY r.id DESC LIMIT 25
    """, (user["id"],)).fetchall()
    submitted = db.execute("""
        SELECT s.*, COALESCE(AVG(r.stars), 0) AS avg_stars, COUNT(r.id) AS rating_count
        FROM songs s LEFT JOIN ratings r ON r.song_id = s.id
        WHERE s.submitted_by = ?
        GROUP BY s.id ORDER BY s.id DESC LIMIT 25
    """, (user["id"],)).fetchall()
    comments = db.execute("""
        SELECT c.*, u.username, u.avatar_emoji FROM comments c
        JOIN users u ON u.id = c.author_id
        WHERE c.profile_id = ? ORDER BY c.id DESC LIMIT 50
    """, (user["id"],)).fetchall()
    top_friends = db.execute("""
        SELECT id, username, avatar_emoji FROM users
        WHERE id != ? ORDER BY RANDOM() LIMIT 8
    """, (user["id"],)).fetchall()
    avg_given = db.execute(
        "SELECT AVG(stars) AS a FROM ratings WHERE user_id = ?", (user["id"],)
    ).fetchone()["a"]
    return render_template(
        "profile.html",
        user=user, ratings=ratings, submitted=submitted,
        comments=comments, top_friends=top_friends, avg_given=avg_given,
    )


@app.route("/profile/edit", methods=["GET", "POST"])
@login_required
def edit_profile():
    user = current_user()
    db = get_db()
    if request.method == "POST":
        fields = {
            "display_name": (request.form.get("display_name") or "").strip()[:60],
            "headline":     (request.form.get("headline") or "").strip()[:120],
            "mood":         (request.form.get("mood") or "").strip()[:30],
            "about_me":     (request.form.get("about_me") or "").strip()[:4000],
            "fav_bands":    (request.form.get("fav_bands") or "").strip()[:1000],
            "location":     (request.form.get("location") or "").strip()[:80],
            "avatar_emoji": (request.form.get("avatar_emoji") or "★")[:4],
            "theme":         request.form.get("theme") or "pink",
        }
        try:
            fields["age"] = int(request.form.get("age") or 0) or None
        except ValueError:
            fields["age"] = user["age"]
        db.execute(
            """UPDATE users SET display_name=?, headline=?, mood=?, about_me=?,
               fav_bands=?, location=?, avatar_emoji=?, theme=?, age=? WHERE id=?""",
            (*fields.values(), user["id"]),
        )
        db.commit()
        flash("profile updated ✿", "ok")
        return redirect(url_for("profile", username=user["username"]))
    return render_template("edit_profile.html", user=user)


@app.route("/songs")
def browse():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "top")
    db = get_db()
    params = []
    where = ""
    if q:
        where = "WHERE s.title LIKE ? OR s.artist LIKE ? OR s.album LIKE ? OR s.genre LIKE ?"
        like = f"%{q}%"
        params = [like, like, like, like]
    order = {
        "top":   "avg_stars DESC, rating_count DESC, s.id DESC",
        "new":   "s.id DESC",
        "hot":   "rating_count DESC, avg_stars DESC",
        "title": "s.title COLLATE NOCASE ASC",
    }.get(sort, "avg_stars DESC")
    rows = db.execute(f"""
        SELECT s.*, u.username AS submitter,
               COALESCE(AVG(r.stars), 0) AS avg_stars,
               COUNT(r.id) AS rating_count
        FROM songs s
        JOIN users u ON u.id = s.submitted_by
        LEFT JOIN ratings r ON r.song_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY {order}
        LIMIT 100
    """, params).fetchall()
    return render_template("browse.html", songs=rows, q=q, sort=sort)


@app.route("/songs/new", methods=["GET", "POST"])
@login_required
def submit_song():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        artist = (request.form.get("artist") or "").strip()
        if not title or not artist:
            flash("Title and artist are required.", "warn")
            return render_template("submit_song.html")
        album = (request.form.get("album") or "").strip()
        genre = (request.form.get("genre") or "").strip()
        link = (request.form.get("link") or "").strip()
        try:
            year = int(request.form.get("year") or 0) or None
        except ValueError:
            year = None
        db = get_db()
        cur = db.execute(
            """INSERT INTO songs (title, artist, album, year, genre, link, submitted_by, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (title[:120], artist[:120], album[:120], year, genre[:60],
             link[:300], session["user_id"],
             datetime.utcnow().isoformat(timespec="seconds")),
        )
        db.commit()
        flash("song added!! get it rated ★", "ok")
        return redirect(url_for("song_detail", song_id=cur.lastrowid))
    return render_template("submit_song.html")


@app.route("/songs/<int:song_id>", methods=["GET", "POST"])
def song_detail(song_id):
    db = get_db()
    song = db.execute("""
        SELECT s.*, u.username AS submitter FROM songs s
        JOIN users u ON u.id = s.submitted_by WHERE s.id = ?
    """, (song_id,)).fetchone()
    if not song:
        abort(404)

    if request.method == "POST":
        if not session.get("user_id"):
            flash("Log in to rate songs.", "warn")
            return redirect(url_for("login", next=request.path))
        try:
            stars = int(request.form.get("stars") or 0)
        except ValueError:
            stars = 0
        if stars < 1 or stars > 5:
            flash("Pick a rating between 1 and 5 ★", "warn")
            return redirect(url_for("song_detail", song_id=song_id))
        review = (request.form.get("review") or "").strip()[:1500]
        db.execute("""
            INSERT INTO ratings (song_id, user_id, stars, review, created_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(song_id, user_id) DO UPDATE SET
              stars = excluded.stars,
              review = excluded.review,
              created_at = excluded.created_at
        """, (song_id, session["user_id"], stars, review,
              datetime.utcnow().isoformat(timespec="seconds")))
        db.commit()
        flash("rating saved 〜♪", "ok")
        return redirect(url_for("song_detail", song_id=song_id))

    stats = db.execute("""
        SELECT COALESCE(AVG(stars), 0) AS avg_stars, COUNT(*) AS n
        FROM ratings WHERE song_id = ?
    """, (song_id,)).fetchone()
    histogram = {i: 0 for i in range(1, 6)}
    for row in db.execute("SELECT stars, COUNT(*) c FROM ratings WHERE song_id=? GROUP BY stars", (song_id,)):
        histogram[row["stars"]] = row["c"]
    max_h = max(histogram.values()) or 1
    reviews = db.execute("""
        SELECT r.*, u.username, u.avatar_emoji FROM ratings r
        JOIN users u ON u.id = r.user_id
        WHERE r.song_id = ? AND r.review != ''
        ORDER BY r.id DESC
    """, (song_id,)).fetchall()
    my_rating = None
    if session.get("user_id"):
        my_rating = db.execute(
            "SELECT * FROM ratings WHERE song_id=? AND user_id=?",
            (song_id, session["user_id"]),
        ).fetchone()
    return render_template(
        "song.html", song=song, stats=stats, histogram=histogram,
        max_h=max_h, reviews=reviews, my_rating=my_rating,
    )


@app.route("/bulletins/new", methods=["POST"])
@login_required
def post_bulletin():
    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()
    if subject and body:
        db = get_db()
        db.execute(
            "INSERT INTO bulletins (user_id, subject, body, created_at) VALUES (?,?,?,?)",
            (session["user_id"], subject[:120], body[:2000],
             datetime.utcnow().isoformat(timespec="seconds")),
        )
        db.commit()
        flash("bulletin posted ✿", "ok")
    return redirect(url_for("home"))


# ---------- seed ----------

def seed_demo():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.execute("SELECT COUNT(*) c FROM users")
    if cur.fetchone()["c"] > 0:
        db.close()
        return
    users = [
        ("tom",       "myspace", "Tom",        "Santa Monica, CA",  29, "★", "blue",   "woo :)",                  "the original.", "Beatles, Superdrag, Jackson 5, Weezer, Radiohead"),
        ("brunette",  "password","brunette",   "Anywhere, USA",     25, "♥", "pink",   "People say that before you die your whole life flashes...","just lookin' for good tunes.","Tegan and Sara, Death Cab"),
        ("joey4eva",  "password","joey ♥",     "Florida",           18, "✿", "pink",   "I ♥ JOEY",                "Florida sunshine state of mind.", "*NSYNC, Backstreet Boys, Britney"),
        ("xkamalx",   "password","kamal",      "Brooklyn, NY",      22, "✦", "neon",   "catch up clean up touch it","u2 / gomez / sugar drunk.",     "U2, Gomez, Sugar Drunk, I love lamp"),
        ("duztin",    "password","Dustyn",     "California",        24, "☆", "blue",   "Hello, Dustynn Cruise!",  "horny mood. typical.",         "Mr. Woodcock OST, Flow Johnson"),
        ("hide_codes","password","Layouts Co.","METAIRIE, Louisiana",18, "✪", "lime",   "Myspace Hide Codes is Myspace Hide Codes","need a fresh layout? click here!", "Avril, Ashlee, Hilary"),
    ]
    salt0 = secrets.token_hex(16)
    now = datetime.utcnow().isoformat(timespec="seconds")
    user_ids = {}
    for u, pw, dn, loc, age, emoji, theme, hl, about, bands in users:
        salt = secrets.token_hex(16)
        h = hash_password(pw, salt)
        c = db.execute(
            """INSERT INTO users
               (username,password_hash,password_salt,display_name,location,age,
                avatar_emoji,theme,headline,about_me,fav_bands,created_at,last_login)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (u, h, salt, dn, loc, age, emoji, theme, hl, about, bands, now, now),
        )
        user_ids[u] = c.lastrowid

    songs = [
        ("Such Great Heights", "The Postal Service", "Give Up", 2003, "indie",     "https://example.com/sgh",   "brunette"),
        ("Hey Ya!",            "OutKast",            "Speakerboxxx/The Love Below", 2003, "hip-hop", "https://example.com/heyya", "tom"),
        ("Mr. Brightside",     "The Killers",        "Hot Fuss", 2003, "rock",      "https://example.com/mb",    "duztin"),
        ("Since U Been Gone",  "Kelly Clarkson",     "Breakaway", 2004, "pop",      "https://example.com/sbg",   "joey4eva"),
        ("Float On",           "Modest Mouse",       "Good News for People Who Love Bad News", 2004, "indie", "https://example.com/floaton","xkamalx"),
        ("Crazy In Love",      "Beyoncé",            "Dangerously in Love", 2003, "r&b",  "https://example.com/cil","hide_codes"),
        ("Karma Police",       "Radiohead",          "OK Computer", 1997, "alt-rock", "https://example.com/kp",  "tom"),
        ("Maps",               "Yeah Yeah Yeahs",    "Fever to Tell", 2003, "indie",   "https://example.com/maps","brunette"),
        ("Hollaback Girl",     "Gwen Stefani",       "Love. Angel. Music. Baby.", 2004, "pop", "https://example.com/hbg","joey4eva"),
        ("Take Me Out",        "Franz Ferdinand",    "Franz Ferdinand", 2004, "rock",  "https://example.com/tmo","xkamalx"),
    ]
    song_ids = []
    for t, a, al, y, g, l, u in songs:
        c = db.execute(
            """INSERT INTO songs (title,artist,album,year,genre,link,submitted_by,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (t, a, al, y, g, l, user_ids[u], now),
        )
        song_ids.append(c.lastrowid)

    import random
    rng = random.Random(7)
    reviews_pool = [
        "absolute banger!! ⭐",
        "this song lives in my head rent free",
        "ehhh kinda mid tbh",
        "10/10 makes me wanna cry & dance at the same time",
        "best song of the decade no contest",
        "my friend put this on a burned cd 4 me <3",
        "skipped after 30sec sry",
        "iconic. period.",
        "",
        "",
    ]
    for sid in song_ids:
        raters = rng.sample(list(user_ids.values()), rng.randint(3, 5))
        for uid in raters:
            stars = rng.choices([2,3,4,5], weights=[1,3,5,4])[0]
            db.execute(
                """INSERT INTO ratings (song_id,user_id,stars,review,created_at)
                   VALUES (?,?,?,?,?)""",
                (sid, uid, stars, rng.choice(reviews_pool), now),
            )

    bulletins = [
        ("brunette",  "catch up, clean up, blog up, touch it!", "new pics up come comment me back ♥"),
        ("xkamalx",   "UK How We Operate Pre-order",            "Gomez new album drops -- pre-order info inside!"),
        ("joey4eva",  "If you open someone's bulletin that says HAHA Funny shit!!!",
                      "...your mom will get a bf in 7 days. repost or else."),
        ("hide_codes","New bloggy blog",                        "check out my new layout codes!! free for everyone."),
        ("tom",       "MySpace... I mean TuneSpace tips",       "Edit your profile, add songs, rate em. Easy!"),
    ]
    for u, s, b in bulletins:
        db.execute(
            "INSERT INTO bulletins (user_id,subject,body,created_at) VALUES (?,?,?,?)",
            (user_ids[u], s, b, now),
        )

    comments = [
        ("brunette",  "joey4eva", "omg ur page is so cute!!! ♥♥"),
        ("brunette",  "tom",       "thx 4 the add :)"),
        ("xkamalx",   "duztin",    "saw u rate Float On 5 stars... based"),
        ("joey4eva",  "hide_codes","luv the layout girl!!"),
        ("tom",       "brunette",  "thx for being a tunespace user!"),
        ("duztin",    "xkamalx",   "we should start a band"),
    ]
    for profile_u, author_u, body in comments:
        db.execute(
            "INSERT INTO comments (profile_id,author_id,body,created_at) VALUES (?,?,?,?)",
            (user_ids[profile_u], user_ids[author_u], body, now),
        )

    db.commit()
    db.close()


@app.cli.command("init-db")
def init_db_cmd():
    """flask --app app init-db"""
    init_db()
    seed_demo()
    print("DB ready at", DB_PATH)


if __name__ == "__main__":
    init_db()
    seed_demo()
    app.run(host="127.0.0.1", port=5000, debug=True)
