"""Tests that the app boots and core configuration is correct."""


def test_app_creates_successfully(app):
    """App factory runs without errors."""
    assert app is not None


def test_app_is_testing(app):
    """TESTING flag is set."""
    assert app.config["TESTING"] is True


def test_database_tables_exist(app):
    """All expected tables are created."""
    from webapp import db
    with app.app_context():
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        assert "user" in tables
        assert "user_ranking" in tables
        assert "mock_draft" in tables
        assert "saved_league" in tables
        assert "draft_board_session" in tables


def test_security_headers(logged_in_client):
    """Responses include security headers."""
    resp = logged_in_client.get("/home")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "X-Frame-Options" in resp.headers
