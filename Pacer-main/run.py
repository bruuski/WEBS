"""Entry point for Pacer.

Usage:
    - Local dev:    python run.py
    - Gunicorn:     gunicorn run:app
    - Railway:      same as gunicorn (Procfile handles it)

This module is safe to import multiple times (gunicorn workers, etc.) thanks
to init_db() being idempotent and seed_demo()'s "already seeded" check.
"""

import os

from dotenv import load_dotenv

load_dotenv()

from pacer import create_app
from pacer.config import IS_PRODUCTION
from pacer.db import init_db
from pacer.seed import seed_demo

# Initialize DB on import (needed for gunicorn). Both calls are idempotent,
# so this is safe on every worker boot.
init_db()
seed_demo()

app = create_app()


if __name__ == "__main__":
    # Dev server only. In production Railway / Heroku / etc. use gunicorn.
    host = "0.0.0.0" if IS_PRODUCTION else "127.0.0.1"
    port = int(os.environ.get("PORT", "5000"))
    debug = not IS_PRODUCTION
    app.run(host=host, port=port, debug=debug)
