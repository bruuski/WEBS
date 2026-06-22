"""Shared pytest fixtures for Pacer tests."""
import os
import pytest
import tempfile

# Set test env BEFORE importing app
os.environ.setdefault("PACER_SECRET", "test-secret")
os.environ.setdefault("SPOTIFY_CLIENT_ID", "")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "")
os.environ.setdefault("DISCOGS_CONSUMER_KEY", "")
os.environ.setdefault("DISCOGS_CONSUMER_SECRET", "")


@pytest.fixture
def temp_db(monkeypatch):
    """Create a temp DB path; init_db writes to it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from pacer import config
    monkeypatch.setattr(config, "DB_PATH", path)
    from pacer import db
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    yield path
    import gc, time
    gc.collect()
    time.sleep(0.05)
    if os.path.exists(path):
        try:
            os.remove(path)
        except PermissionError:
            pass  # Windows file-handle lag; safe to ignore in tests


@pytest.fixture
def app(temp_db):
    """Flask app with isolated DB."""
    from pacer import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()
