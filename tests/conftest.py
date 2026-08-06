"""Shared test fixtures for the Darkhorse test suite."""

import pytest
from unittest.mock import patch
from webapp import create_app, db as _db, User


@pytest.fixture(scope="session")
def app():
    """Create the Flask app once per test session with an in-memory SQLite DB."""
    import os
    os.environ["FLASK_ENV"] = "testing"
    os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"
    # Supabase env vars intentionally omitted — app should start gracefully

    application = create_app()
    application.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
        SERVER_NAME="localhost",
    )

    # Recreate tables for in-memory DB
    with application.app_context():
        _db.drop_all()
        _db.create_all()

    yield application


@pytest.fixture()
def client(app):
    """A fresh test client for each test. Rolls back DB changes after."""
    with app.app_context():
        _db.session.begin_nested()
        yield app.test_client()
        _db.session.rollback()


@pytest.fixture()
def logged_in_client(app, client):
    """A test client that simulates an authenticated Supabase session.

    Sets fake session tokens and patches both pyjwt.get_unverified_header
    and pyjwt.decode so the before_request hook resolves g.user on every request.
    """
    with app.app_context():
        # Ensure local User record exists (mirrors _ensure_local_user behavior)
        user = User.query.get("test-uuid-1234")
        if not user:
            user = User(id="test-uuid-1234", email="test@example.com")
            _db.session.add(user)
            _db.session.commit()

    fake_payload = {
        "sub": "test-uuid-1234",
        "email": "test@example.com",
        "user_metadata": {},
        "aud": "authenticated",
    }

    with client.session_transaction() as sess:
        sess["sb_access_token"] = "fake-token"
        sess["sb_refresh_token"] = "fake-refresh"

    with patch("webapp.supabase_auth.pyjwt.get_unverified_header", return_value={"alg": "HS256"}), \
         patch("webapp.supabase_auth.pyjwt.decode", return_value=fake_payload):
        yield client
