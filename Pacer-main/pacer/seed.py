"""Seed the database with demo data (runs at startup, outside Flask request context)."""

import random
import secrets
import sqlite3
from datetime import datetime

from pacer.config import DB_PATH
from pacer.helpers import hash_password


def seed_demo():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cur = db.execute("SELECT COUNT(*) c FROM users")
    if cur.fetchone()["c"] > 0:
        db.close()
        return
    users = [
        ("tom",       "myspace",  "Tom",        "Santa Monica, CA",  29, "\u25c9", "sky",     "the original.",                      "i'm here to help.",                                            "Beatles, Superdrag, Radiohead"),
        ("brunette",  "password", "brunette",   "Anywhere, USA",     25, "\u2726", "sky",     "27 years old, still rating.",        "moody indie & sad-girl rock, mostly.",                         "Tegan and Sara, Mitski, Phoebe Bridgers"),
        ("joey",      "password", "joey",       "Florida",           22, "\u273f", "sunset",  "florida sunshine state of mind.",    "ex-boyband stan turned hyperpop convert.",                     "100 gecs, Charli XCX, Caroline Polachek"),
        ("kamal",     "password", "kamal",      "Brooklyn, NY",      24, "\u266a", "cyber",   "catch up. clean up. blog up.",       "writes too many words about three-minute songs.",              "U2, Gomez, Big Thief, Black Country, New Road"),
        ("dustyn",    "password", "Dustyn",     "California",        24, "\u2605", "sky",     "be careful what you put on shuffle.","yacht rock apologist.",                                        "Steely Dan, Toro y Moi, Mac DeMarco"),
        ("layouts",   "password", "layouts",    "Metairie, LA",      28, "\u25a1", "cyber",   "code in the morning, drone at night.","makes weird little instrumental loops.",                      "Tim Hecker, Grouper, Aphex Twin"),
        ("anon",      "password", "anon",       "/mu/sic",           19, "?", "cyber",   ">be me >rate songs >mfw",            "no waifu, no laifu. only ratings.",                            "Death Grips, Black Midi, JPEGMAFIA"),
    ]
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
        ("Such Great Heights",  "The Postal Service",   "Give Up",                                  2003, "indie",    None, "brunette"),
        ("Hey Ya!",             "OutKast",              "Speakerboxxx/The Love Below",              2003, "hip-hop",  None, "tom"),
        ("Mr. Brightside",      "The Killers",          "Hot Fuss",                                 2003, "rock",     None, "dustyn"),
        ("Since U Been Gone",   "Kelly Clarkson",       "Breakaway",                                2004, "pop",      None, "joey"),
        ("Float On",            "Modest Mouse",         "Good News for People Who Love Bad News",   2004, "indie",    None, "kamal"),
        ("Crazy In Love",       "Beyonc\u00e9",              "Dangerously in Love",                      2003, "r&b",      None, "layouts"),
        ("Karma Police",        "Radiohead",            "OK Computer",                              1997, "alt-rock", None, "tom"),
        ("Maps",                "Yeah Yeah Yeahs",      "Fever to Tell",                            2003, "indie",    None, "brunette"),
        ("Hollaback Girl",      "Gwen Stefani",         "Love. Angel. Music. Baby.",                2004, "pop",      None, "joey"),
        ("Take Me Out",         "Franz Ferdinand",      "Franz Ferdinand",                          2004, "rock",     None, "kamal"),
        ("Not Allowed",         "TV Girl",              "French Exit",                              2014, "indie",    None, "brunette"),
        ("DUCKWORTH.",          "Kendrick Lamar",       "DAMN.",                                    2017, "hip-hop",  None, "anon"),
    ]
    song_ids = []
    for t, a, al, y, g, l, u in songs:
        # Spotify metadata is no longer fetched at seed time. Discogs covers +
        # Spotify preview URLs are filled lazily on first access (Phase 3).
        c = db.execute(
            """INSERT INTO songs
               (title,artist,album,year,genre,link,submitted_by,created_at,
                spotify_id,spotify_url,spotify_image,spotify_preview_url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t, a, al, y, g, l, user_ids[u], now,
             None, None, None, None),
        )
        song_ids.append(c.lastrowid)

    rng = random.Random(7)
    reviews_pool = [
        "absolute banger. headphones-on, eyes-closed material.",
        ">be me\n>hear this song\n>cry\n>repeat",
        "kind of mid honestly. structure's fine, vocals are doing too much.",
        "10/10 makes me wanna cry & dance at the same time",
        "best song of the decade no contest. fight me.",
        "the production sits right between maximalist and tasteful. love it.",
        ">tfw no chorus this good in my life",
        "skipped after 30sec. sorry.",
        "iconic. period.",
        "this would be a 10 if not for the bridge. that bridge is a 4.",
        "",
        "",
    ]
    for sid in song_ids:
        raters = rng.sample(list(user_ids.values()), rng.randint(3, 6))
        for uid in raters:
            stars = rng.choices([2, 3, 4, 5], weights=[1, 3, 5, 4])[0]
            db.execute(
                """INSERT INTO ratings (song_id,user_id,stars,review,created_at)
                   VALUES (?,?,?,?,?)""",
                (sid, uid, stars, rng.choice(reviews_pool), now),
            )

    bulletins = [
        ("brunette", "new TV Girl rate just dropped",        "no notes. perfect 9.0."),
        ("kamal",    "Pitchfork is wrong about the new BCNR","change my mind in the comments."),
        ("joey",     "hyperpop is real music",                ">be me\n>defend Charli\n>get bullied\n>still right"),
        ("layouts",  "playlist: studio bg loops",             "uploaded 12 ambient loops. take em or leave em."),
        ("tom",      "Pacer is live",                         "trending tracks, new look, same ratings."),
        ("anon",     "rate my taste",                         ">>1\nstop projecting"),
    ]
    for u, s, b in bulletins:
        db.execute(
            "INSERT INTO bulletins (user_id,subject,body,created_at) VALUES (?,?,?,?)",
            (user_ids[u], s, b, now),
        )

    comments = [
        ("brunette", "joey",    "your taste is so unhinged i love it"),
        ("brunette", "tom",     "thanks for the add"),
        ("kamal",    "dustyn",  "we are gonna disagree about steely dan forever"),
        ("joey",     "layouts", "send me ur drone loops pls"),
        ("tom",      "anon",    "less greentext, more reviews"),
        ("anon",     "tom",     ">no\n>>1\nyou first"),
    ]
    for profile_u, author_u, body in comments:
        db.execute(
            "INSERT INTO comments (profile_id,author_id,body,created_at) VALUES (?,?,?,?)",
            (user_ids[profile_u], user_ids[author_u], body, now),
        )

    seed_threads = [
        ("brunette", "what's the best album of the last 5 years?",
         "going to bat for Punisher. annual replay every fall, every fall it still hits.\n"
         "what's yours? defend your pick."),
        ("kamal", "is hyperpop dead?",
         ">say hyperpop is dead\n>get told to listen to the new 100 gecs\n>turns out it was fine\n"
         "honest take: the scene's mainstream era is over, the experimental wing is healthier than ever."),
        ("anon", "rate my last.fm",
         ">3 plays of mclusky\n>500 plays of one Carly Rae Jepsen song\n"
         "be honest. no mercy."),
        ("dustyn", "yacht rock starter pack",
         "for friends new to the genre. ranked:\n"
         "1. Aja - Steely Dan\n"
         "2. Christopher Cross s/t\n"
         "3. Off the Wall\n"
         "fight me on the order."),
        ("layouts", "ambient album recommendations",
         "I've been on a Tim Hecker kick for months. need fresh stuff.\n"
         "drone, modular, field recording \u2014 anything goes. drop names."),
    ]
    thread_ids = {}
    for u, subj, body in seed_threads:
        c = db.execute(
            "INSERT INTO threads (user_id, subject, body, created_at) VALUES (?,?,?,?)",
            (user_ids[u], subj, body, now),
        )
        thread_ids[subj] = c.lastrowid

    seed_replies = [
        ("what's the best album of the last 5 years?", "joey",    "obvious answer is Charli XCX - BRAT. sorry not sorry."),
        ("what's the best album of the last 5 years?", "kamal",   "Black Country, New Road - Ants From Up There. closes the case."),
        ("what's the best album of the last 5 years?", "anon",    ">>1\nBRAT is fine but it isn't even her best."),
        ("is hyperpop dead?",                          "joey",    "hyperpop didn't die, it just got distributed across mainstream pop production. listen to any top 40 track lately."),
        ("is hyperpop dead?",                          "tom",     "kinda agree. the boundary moved."),
        ("rate my last.fm",                            "brunette","this is a cry for help."),
        ("rate my last.fm",                            "kamal",   "the carly rae fixation is correct, the mclusky shame is not."),
        ("yacht rock starter pack",                    "kamal",   "putting Off the Wall in yacht rock is a crime"),
        ("yacht rock starter pack",                    "tom",     "actually Off the Wall has yacht rock energy throughout. hot take respected."),
        ("ambient album recommendations",              "brunette","Grouper - Ruins. recorded in a tiny house in Portugal. unbeatable."),
        ("ambient album recommendations",              "anon",    "Stars of the Lid - The Tired Sounds of. don't sleep on it (but also do)."),
    ]
    for subj, author, body in seed_replies:
        tid = thread_ids.get(subj)
        if not tid:
            continue
        db.execute(
            "INSERT INTO thread_replies (thread_id, user_id, body, created_at) VALUES (?,?,?,?)",
            (tid, user_ids[author], body, now),
        )

    db.commit()
    db.close()
