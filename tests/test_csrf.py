"""Tests that verify CSRF protection is enforced on all POST/PUT/DELETE endpoints.

These tests use a client with WTF_CSRF_ENABLED=True to mirror production behavior.
Every mutating endpoint should reject requests without an X-CSRFToken header.
"""

import json
import re
from unittest.mock import patch, MagicMock


def _get_csrf_token(csrf_client, url="/rankings/ppr"):
    """Fetch a page and extract the CSRF token from the rendered HTML."""
    resp = csrf_client.get(url)
    match = re.search(r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)', resp.data.decode())
    if match:
        return match.group(1)
    # Fall back to hidden input field
    match = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)', resp.data.decode())
    if match:
        return match.group(1)
    # Fall back to JS-embedded token
    match = re.search(r"csrf_token\(\)\s*\}\}'?\s*\)?", resp.data.decode())
    # Generate token from the session
    from flask_wtf.csrf import generate_csrf
    with csrf_client.session_transaction():
        pass
    resp2 = csrf_client.get(url)
    match = re.search(r'["\']X-CSRFToken["\'],\s*["\']([^"\']+)', resp2.data.decode())
    if match:
        return match.group(1)
    return None


def _post_json(client, url, data=None, csrf_token=None):
    """POST JSON with optional CSRF token."""
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRFToken"] = csrf_token
    return client.post(url, data=json.dumps(data or {}), headers=headers)


def _put_json(client, url, data=None, csrf_token=None):
    headers = {"Content-Type": "application/json"}
    if csrf_token:
        headers["X-CSRFToken"] = csrf_token
    return client.put(url, data=json.dumps(data or {}), headers=headers)


def _delete(client, url, csrf_token=None):
    headers = {}
    if csrf_token:
        headers["X-CSRFToken"] = csrf_token
    return client.delete(url, headers=headers)


# ── Tests: requests WITHOUT CSRF token should be rejected ──────


def test_save_ranking_rejected_without_csrf(csrf_client):
    """POST /save_rankings without CSRF token should fail."""
    resp = _post_json(csrf_client, "/save_rankings", {
        "name": "Test", "ranking_type": "PPR", "ranking": "[]",
    })
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"


def test_update_ranking_rejected_without_csrf(csrf_client):
    """PUT /update_ranking/<id> without CSRF token should fail."""
    resp = _put_json(csrf_client, "/update_ranking/1", {"ranking": "[]"})
    assert resp.status_code == 400


def test_delete_ranking_rejected_without_csrf(csrf_client):
    """DELETE /delete_ranking/<id> without CSRF token should fail."""
    resp = _delete(csrf_client, "/delete_ranking/1")
    assert resp.status_code == 400


def test_sleeper_lookup_rejected_without_csrf(csrf_client):
    """POST /draft-board/sleeper/lookup without CSRF token should fail."""
    resp = _post_json(csrf_client, "/draft-board/sleeper/lookup", {"username": "test"})
    assert resp.status_code == 400


def test_espn_lookup_rejected_without_csrf(csrf_client):
    """POST /draft-board/espn/lookup without CSRF token should fail."""
    resp = _post_json(csrf_client, "/draft-board/espn/lookup", {"league_id": "123"})
    assert resp.status_code == 400


def test_draft_board_save_rejected_without_csrf(csrf_client):
    """POST /draft-board/save without CSRF token should fail."""
    resp = _post_json(csrf_client, "/draft-board/save", {"source": "manual"})
    assert resp.status_code == 400


def test_draft_board_reset_rejected_without_csrf(csrf_client):
    """POST /draft-board/reset without CSRF token should fail."""
    resp = csrf_client.post("/draft-board/reset")
    assert resp.status_code == 400


def test_draft_board_league_delete_rejected_without_csrf(csrf_client):
    """DELETE /draft-board/leagues/<id> without CSRF token should fail."""
    resp = _delete(csrf_client, "/draft-board/leagues/test-league")
    assert resp.status_code == 400


def test_mockdraft_save_rejected_without_csrf(csrf_client):
    """POST /mockdraft/save without CSRF token should fail."""
    resp = _post_json(csrf_client, "/mockdraft/save", {"draft_type": "snake"})
    assert resp.status_code == 400


def test_my_drafts_delete_rejected_without_csrf(csrf_client):
    """DELETE /my_drafts/<id>/delete without CSRF token should fail."""
    resp = _delete(csrf_client, "/my_drafts/1/delete")
    assert resp.status_code == 400


def test_ai_suggest_rejected_without_csrf(csrf_client):
    """POST /draft-board/ai-suggest without CSRF token should fail."""
    resp = _post_json(csrf_client, "/draft-board/ai-suggest", {"mode": "in_draft"})
    assert resp.status_code == 400


def test_leagues_save_rejected_without_csrf(csrf_client):
    """POST /draft-board/leagues/save without CSRF token should fail."""
    resp = _post_json(csrf_client, "/draft-board/leagues/save", {"league_id": "test"})
    assert resp.status_code == 400


# ── Tests: requests WITH valid CSRF token should succeed ───────


def test_save_ranking_accepted_with_csrf(csrf_client):
    """POST /save_rankings with valid CSRF token should succeed."""
    from flask_wtf.csrf import generate_csrf
    # Get a page to establish session, then generate token
    csrf_client.get("/rankings/ppr")
    with csrf_client.session_transaction() as sess:
        token = generate_csrf()

    resp = _post_json(csrf_client, "/save_rankings", {
        "name": "CSRF Test", "ranking_type": "PPR",
        "ranking": json.dumps([{"name": "Player A", "rank": 1}]),
    }, csrf_token=token)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.data}"


def test_sleeper_lookup_accepted_with_csrf(csrf_client):
    """POST /draft-board/sleeper/lookup with valid CSRF token should pass CSRF check."""
    csrf_client.get("/rankings/ppr")
    from flask_wtf.csrf import generate_csrf
    with csrf_client.session_transaction() as sess:
        token = generate_csrf()

    def _mock_get(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/leagues/" in url:
            resp.json.return_value = []
        else:
            resp.json.return_value = {"user_id": "123", "display_name": "test"}
        return resp

    with patch("webapp.views.requests.get", side_effect=_mock_get):
        resp = _post_json(csrf_client, "/draft-board/sleeper/lookup",
                          {"username": "testuser"}, csrf_token=token)
    # Should not be 400 (CSRF rejection) — any other status is fine
    assert resp.status_code != 400, f"CSRF should have passed but got 400"


def test_draft_board_save_accepted_with_csrf(csrf_client):
    """POST /draft-board/save with valid CSRF token should succeed."""
    csrf_client.get("/rankings/ppr")
    from flask_wtf.csrf import generate_csrf
    with csrf_client.session_transaction() as sess:
        token = generate_csrf()

    resp = _post_json(csrf_client, "/draft-board/save", {
        "source": "manual",
        "league_id": "test",
        "draft_id": "test",
        "settings": "{}",
        "state": "{}",
        "last_pick": 0,
    }, csrf_token=token)
    assert resp.status_code != 400, f"CSRF should have passed but got 400"
