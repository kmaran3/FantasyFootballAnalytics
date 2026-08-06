"""Tests that every page on the site loads without crashing.

Unauthenticated requests should redirect to login (302).
Authenticated requests should return 200.
"""


# ── Public pages (no auth required) ──────────────────────────


def test_about_page(client):
    resp = client.get("/about")
    assert resp.status_code == 200
    assert b"about" in resp.data.lower()


def test_contact_page(client):
    resp = client.get("/contact")
    assert resp.status_code == 200
    assert b"contact" in resp.data.lower()


# ── Auth-protected pages redirect when logged out ────────────


def test_home_requires_login(client):
    resp = client.get("/home", follow_redirects=False)
    assert resp.status_code == 302


def test_rankings_requires_login(client):
    resp = client.get("/rankings/ppr", follow_redirects=False)
    assert resp.status_code == 302


def test_mockdraft_requires_login(client):
    resp = client.get("/mockdraft", follow_redirects=False)
    assert resp.status_code == 302


def test_draft_board_requires_login(client):
    resp = client.get("/draft-board", follow_redirects=False)
    assert resp.status_code == 302


def test_my_drafts_requires_login(client):
    resp = client.get("/my_drafts", follow_redirects=False)
    assert resp.status_code == 302


def test_player_profile_requires_login(client):
    resp = client.get("/player/TestPlayer", follow_redirects=False)
    assert resp.status_code == 302


# ── Authenticated page loads ─────────────────────────────────


def test_home_page(logged_in_client):
    resp = logged_in_client.get("/home")
    assert resp.status_code == 200


def test_rankings_ppr(logged_in_client):
    resp = logged_in_client.get("/rankings/ppr")
    assert resp.status_code == 200
    assert b"rankings" in resp.data.lower() or b"Rankings" in resp.data


def test_rankings_half_ppr(logged_in_client):
    resp = logged_in_client.get("/rankings/half-ppr")
    assert resp.status_code == 200


def test_rankings_standard(logged_in_client):
    resp = logged_in_client.get("/rankings/standard")
    assert resp.status_code == 200


def test_mockdraft_page(logged_in_client):
    resp = logged_in_client.get("/mockdraft")
    assert resp.status_code == 200
    assert b"mock" in resp.data.lower() or b"draft" in resp.data.lower()


def test_draft_board_page(logged_in_client):
    resp = logged_in_client.get("/draft-board")
    assert resp.status_code == 200
    assert b"draft" in resp.data.lower()


def test_my_drafts_page(logged_in_client):
    resp = logged_in_client.get("/my_drafts")
    assert resp.status_code == 200


def test_user_rankings_page(logged_in_client):
    resp = logged_in_client.get("/user_rankings")
    assert resp.status_code == 200
