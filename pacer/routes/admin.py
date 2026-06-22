"""Admin routes for database inspection."""

from flask import Blueprint, render_template, abort, request
from pacer.db import get_db
from pacer.helpers import current_user

bp = Blueprint("admin", __name__)


def admin_required():
    user = current_user()
    if not user or user["id"] != 1:
        abort(403)
    return user


@bp.route("/admin")
def dashboard():
    admin_required()
    db = get_db()
    tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    stats = {}
    for t in tables:
        name = t["name"]
        count = db.execute(f"SELECT COUNT(*) as c FROM [{name}]").fetchone()["c"]
        stats[name] = count

    # Discogs cache stats
    cache_stats = {}
    if "spotify_preview_cache" in stats:
        row = db.execute(
            "SELECT COUNT(*) as n, MIN(fetched_at) as oldest, MAX(fetched_at) as newest "
            "FROM spotify_preview_cache"
        ).fetchone()
        cache_stats["spotify_preview_cache"] = {
            "rows": row["n"],
            "oldest": row["oldest"],
            "newest": row["newest"],
        }
    if "artists" in stats:
        row = db.execute(
            "SELECT COUNT(*) as n, COUNT(discogs_id) as with_discogs "
            "FROM artists"
        ).fetchone()
        cache_stats["artists"] = {
            "rows": row["n"],
            "with_discogs_id": row["with_discogs"],
        }

    return render_template(
        "admin/dashboard.html",
        tables=tables, stats=stats, cache_stats=cache_stats,
    )


@bp.route("/admin/table/<table_name>")
def view_table(table_name):
    admin_required()
    db = get_db()
    # Validate table exists
    valid = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone()
    if not valid:
        abort(404)
    page = request.args.get("page", 1, type=int)
    per_page = 50
    offset = (page - 1) * per_page
    rows = db.execute(f"SELECT * FROM [{table_name}] LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    total = db.execute(f"SELECT COUNT(*) as c FROM [{table_name}]").fetchone()["c"]
    columns = [desc[0] for desc in db.execute(f"SELECT * FROM [{table_name}] LIMIT 1").description] if rows else []
    return render_template("admin/table.html", table_name=table_name, rows=rows, columns=columns, page=page, per_page=per_page, total=total)


@bp.route("/admin/sql", methods=["GET", "POST"])
def run_sql():
    admin_required()
    results = None
    columns = None
    query = ""
    error = None
    if request.method == "POST":
        query = request.form.get("query", "").strip()
        if query:
            db = get_db()
            try:
                cursor = db.execute(query)
                if query.upper().startswith("SELECT"):
                    results = cursor.fetchall()
                    columns = [desc[0] for desc in cursor.description] if results else []
                else:
                    db.commit()
                    results = [{"affected_rows": cursor.rowcount}]
                    columns = ["affected_rows"]
            except Exception as e:
                error = str(e)
    return render_template("admin/sql.html", query=query, results=results, columns=columns, error=error)
