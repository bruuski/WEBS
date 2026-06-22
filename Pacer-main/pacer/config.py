import os
import logging
import warnings

from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# Detect production environment (Railway / Heroku / generic)
IS_PRODUCTION = bool(
    os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("RENDER")
    or os.environ.get("DYNO")  # Heroku
    or os.environ.get("FLASK_ENV") == "production"
    or os.environ.get("PACER_ENV") == "production"
)

# Persistent volume for SQLite DB + future user uploads. On Railway, mount
# a volume at /data and set DATA_DIR=/data. Locally we default to the project
# root so `python run.py` Just Works.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(APP_ROOT, ".."))
# Ensure DATA_DIR exists at import time so DB writes never fail on a fresh
# volume mount.
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "pacer.db")

SECRET_KEY = os.environ.get("PACER_SECRET", "dev-secret-change-me")
if SECRET_KEY == "dev-secret-change-me":
    if IS_PRODUCTION:
        # Refuse to boot in production with the placeholder secret. The
        # PACER_SECRET env var is documented in .env.example / DEPLOYMENT.md.
        raise RuntimeError(
            "PACER_SECRET is set to the placeholder 'dev-secret-change-me'. "
            "Set PACER_SECRET to a long random string before deploying."
        )
    warnings.warn(
        "PACER_SECRET is using the placeholder default. "
        "Set PACER_SECRET in .env or your platform's env vars before deploying.",
        stacklevel=2,
    )

# Spotify redirect URI. Locally we default to 127.0.0.1:5000; in production
# we derive it from RAILWAY_PUBLIC_DOMAIN / RENDER_EXTERNAL_URL / PUBLIC_URL
# so the user doesn't have to hard-code it. The Spotify dashboard still
# needs the same URI added under "Redirect URIs".
_RAILWAY_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
_RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
_PUBLIC_URL = os.environ.get("PUBLIC_URL")
if os.environ.get("SPOTIFY_REDIRECT_URI"):
    SPOTIFY_REDIRECT_URI = os.environ["SPOTIFY_REDIRECT_URI"]
elif _RAILWAY_DOMAIN:
    SPOTIFY_REDIRECT_URI = f"https://{_RAILWAY_DOMAIN}/spotify/callback"
elif _RENDER_URL:
    SPOTIFY_REDIRECT_URI = f"{_RENDER_URL.rstrip('/')}/spotify/callback"
elif _PUBLIC_URL:
    SPOTIFY_REDIRECT_URI = f"{_PUBLIC_URL.rstrip('/')}/spotify/callback"
else:
    SPOTIFY_REDIRECT_URI = "http://127.0.0.1:5000/spotify/callback"

SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_TRENDING_PLAYLIST = os.environ.get("SPOTIFY_TRENDING_PLAYLIST", "37i9dQZF1DXcBWIGoYBM5M")

# Discogs (OAuth 1.0a server-to-server)
DISCOGS_CONSUMER_KEY    = os.environ.get("DISCOGS_CONSUMER_KEY", "")
DISCOGS_CONSUMER_SECRET = os.environ.get("DISCOGS_CONSUMER_SECRET", "")
DISCOGS_USER_AGENT      = os.environ.get(
    "DISCOGS_USER_AGENT",
    "Pacer/1.0 +https://github.com/0xzhepyr/Pacer",
)

# Pinata (optional, for IPFS uploads of profile pics / post images)
PINATA_API_KEY    = os.environ.get("PINATA_API_KEY", "")
PINATA_SECRET_KEY = os.environ.get("PINATA_SECRET_KEY", "")
PINATA_GATEWAY_URL = os.environ.get("PINATA_GATEWAY_URL", "https://gateway.pinata.cloud/ipfs/")

logging.getLogger("pacer.config").info(
    "Pacer config loaded. production=%s, data_dir=%s, redirect_uri=%s",
    IS_PRODUCTION, DATA_DIR, SPOTIFY_REDIRECT_URI,
)
