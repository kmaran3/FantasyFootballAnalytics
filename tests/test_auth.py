"""Tests for authentication: login, register, logout, guest access."""


def test_login_page_loads(client):
    """GET / renders the login form."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"login" in resp.data.lower() or b"sign in" in resp.data.lower()


def test_register_page_loads(client):
    """GET /register renders the registration form."""
    resp = client.get("/register")
    assert resp.status_code == 200
    assert b"register" in resp.data.lower() or b"sign up" in resp.data.lower()


def test_register_new_user(client, app):
    """POST /register with valid data creates a user and redirects."""
    resp = client.post(
        "/register",
        data={
            "username": "newuser",
            "email": "new@example.com",
            "password": "Abcdef1234",
            "confirm_password": "Abcdef1234",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    from webapp import User
    with app.app_context():
        assert User.query.get("newuser") is not None


def test_register_duplicate_username(client, app):
    """Registering with an existing username fails."""
    from webapp import User, db
    with app.app_context():
        if not User.query.get("dupuser"):
            u = User(id="dupuser", email="dup@example.com")
            u.set_password("TestPass123")
            db.session.add(u)
            db.session.commit()

    resp = client.post(
        "/register",
        data={
            "username": "dupuser",
            "email": "other@example.com",
            "password": "TestPass123",
            "confirm_password": "TestPass123",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"already" in resp.data.lower() or b"taken" in resp.data.lower() or b"exists" in resp.data.lower()


def test_login_valid_credentials(client, app):
    """Login with correct username/password redirects to /home."""
    from webapp import User, db
    with app.app_context():
        if not User.query.get("logintest"):
            u = User(id="logintest", email="login@example.com")
            u.set_password("TestPass123")
            db.session.add(u)
            db.session.commit()

    resp = client.post(
        "/",
        data={"username": "logintest", "password": "TestPass123"},
        follow_redirects=False,
    )
    # Should redirect to /home on success
    assert resp.status_code in (302, 303)
    assert "/home" in resp.headers.get("Location", "")


def test_login_invalid_password(client, app):
    """Login with wrong password stays on login page."""
    from webapp import User, db
    with app.app_context():
        if not User.query.get("logintest2"):
            u = User(id="logintest2", email="login2@example.com")
            u.set_password("TestPass123")
            db.session.add(u)
            db.session.commit()

    resp = client.post(
        "/",
        data={"username": "logintest2", "password": "WrongPass999"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Should show error, not redirect to home
    assert b"home" not in resp.data[:500].lower() or b"invalid" in resp.data.lower()


def test_guest_login(client):
    """GET /guest-login logs in as guest and redirects to /home."""
    resp = client.get("/guest-login", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert "/home" in resp.headers.get("Location", "")


def test_logout(logged_in_client):
    """GET /logout redirects to login page."""
    resp = logged_in_client.get("/logout", follow_redirects=False)
    assert resp.status_code in (302, 303)

    # After logout, accessing /home should redirect to login
    resp2 = logged_in_client.get("/home", follow_redirects=False)
    assert resp2.status_code in (302, 303)
