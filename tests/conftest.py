"""Shared test fixtures for the Darkhorse test suite."""

import pytest
from webapp import create_app, db as _db, User


@pytest.fixture(scope="session")
def app():
    """Create the Flask app once per test session with an in-memory SQLite DB."""
    import os
    os.environ["FLASK_ENV"] = "testing"
    os.environ["SECRET_KEY"] = "test-secret-key-not-for-prod"

    application = create_app()
    application.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        WTF_CSRF_ENABLED=False,
        LOGIN_DISABLED=False,
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
    """A test client that is already authenticated."""
    with app.app_context():
        user = User.query.get("testuser")
        if not user:
            user = User(id="testuser", email="test@example.com")
            user.set_password("TestPass123")
            _db.session.add(user)
            _db.session.commit()

        # Log in via the login endpoint
        client.post(
            "/",
            data={"username": "testuser", "password": "TestPass123"},
            follow_redirects=True,
        )
        yield client
