"""Smoke test: app boots and root route returns 200."""


def test_app_boots(app):
    assert app is not None


def test_root_route_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
