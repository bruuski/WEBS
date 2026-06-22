"""Pacer application factory."""

import click
from flask import Flask

from pacer.config import SECRET_KEY
from pacer.db import close_db, init_db
from pacer.helpers import register_template_utils
from pacer.seed import seed_demo


def create_app():
    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="../templates",
    )
    app.secret_key = SECRET_KEY

    # teardown
    app.teardown_appcontext(close_db)

    # template filters & context processor
    register_template_utils(app)

    # blueprints
    from pacer.routes.auth import bp as auth_bp
    from pacer.routes.profile import bp as profile_bp
    from pacer.routes.music import bp as music_bp
    from pacer.routes.blog import bp as blog_bp
    from pacer.routes.spotify import bp as spotify_bp
    from pacer.routes.feed import bp as feed_bp
    from pacer.routes.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(music_bp)
    app.register_blueprint(blog_bp)
    app.register_blueprint(spotify_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(admin_bp)

    # Health check (for Railway / uptime monitors). Touches the DB to make
    # sure the persistent volume is mounted and reachable.
    @app.route("/healthz")
    def healthz():
        from pacer.config import DB_PATH, IS_PRODUCTION
        import os
        info = {
            "status": "ok",
            "production": IS_PRODUCTION,
            "db_path": DB_PATH,
            "db_exists": os.path.exists(DB_PATH),
        }
        try:
            from pacer.db import get_db
            db = get_db()
            db.execute("SELECT 1").fetchone()
            info["db_reachable"] = True
        except Exception as exc:  # pragma: no cover - defensive
            info["status"] = "degraded"
            info["db_reachable"] = False
            info["db_error"] = str(exc)
            return info, 500
        return info, 200

    # CLI command
    @app.cli.command("init-db")
    @click.option("--seed/--no-seed", default=True, help="Seed demo data")
    def init_db_command(seed):
        """Initialize the database, and optionally seed demo data."""
        init_db()
        if seed:
            seed_demo()
        click.echo("Database initialized.")

    @app.cli.command("backfill-artists")
    def backfill_artists_cmd():
        """Create stub artist rows for any album with NULL artist_id."""
        from pacer.services.feed import backfill_artist_stubs
        n = backfill_artist_stubs()
        click.echo(f"Done. Created {n} stub artist(s).")

    return app
