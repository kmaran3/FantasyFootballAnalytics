"""Tests for authentication: login page, register page, logout, protected routes.

Note: These tests validate route behavior and rendering. Actual Supabase
sign_in/sign_up calls are mocked since we don't have credentials in CI.
"""

from unittest.mock import patch, MagicMock


def test_login_page_loads(client):
    """GET / renders the login form with email field."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"email" in resp.data.lower()


def test_register_page_loads(client):
    """GET /register renders the registration form."""
    resp = client.get("/register")
    assert resp.status_code == 200
    assert b"register" in resp.data.lower() or b"sign up" in resp.data.lower()


def test_login_invalid_credentials(client):
    """POST / with bad credentials shows error flash."""
    with patch("webapp.supabase_auth.sign_in", side_effect=Exception("Invalid")):
        resp = client.post(
            "/",
            data={"email": "bad@example.com", "password": "WrongPass999"},
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert b"invalid" in resp.data.lower() or b"error" in resp.data.lower()


def test_login_redirects_authenticated_user(logged_in_client):
    """GET / when already logged in redirects to /home."""
    resp = logged_in_client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/home" in resp.headers.get("Location", "")


def test_logout(logged_in_client):
    """GET /logout redirects to login page."""
    with patch("webapp.supabase_auth.sign_out"):
        resp = logged_in_client.get("/logout", follow_redirects=False)
    assert resp.status_code in (302, 303)


def test_protected_route_redirects_unauthenticated(client):
    """GET /home without auth redirects to login."""
    resp = client.get("/home", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/" in resp.headers.get("Location", "")


def test_login_next_param_validated(client):
    """Open redirect: next=https://evil.com should be ignored."""
    mock_resp = MagicMock()
    mock_resp.user = MagicMock(id="uuid-123", email="ok@test.com", user_metadata={})
    mock_resp.session = MagicMock(access_token="tok", refresh_token="ref")

    with patch("webapp.supabase_auth.sign_in", return_value=mock_resp):
        with patch("webapp.views._ensure_local_user"):
            resp = client.post(
                "/?next=https://evil.com",
                data={"email": "ok@test.com", "password": "GoodPass123"},
                follow_redirects=False,
            )
    # Should redirect to /home, NOT to evil.com
    location = resp.headers.get("Location", "")
    assert "evil.com" not in location
    assert "/home" in location


def test_social_login_invalid_provider(client):
    """GET /login/github returns 404 (only google/apple allowed)."""
    resp = client.get("/login/github")
    assert resp.status_code == 404
