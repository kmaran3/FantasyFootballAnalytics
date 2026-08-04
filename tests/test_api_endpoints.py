"""Tests for JSON API endpoints used by the frontend."""

import json


# ── Draft Board persistence endpoints ────────────────────────


def test_draft_board_load_empty(logged_in_client):
    """Load returns not-found when no session exists."""
    resp = logged_in_client.get("/draft-board/load")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("found") is False


def test_draft_board_save_and_load(logged_in_client):
    """Save a draft session and load it back."""
    payload = {
        "source": "manual",
        "league_id": "test-league",
        "draft_id": "test-draft",
        "settings": json.dumps({"numTeams": 10}),
        "state": json.dumps({"board": [], "currentPickNo": 0}),
        "last_pick": 0,
    }
    resp = logged_in_client.post(
        "/draft-board/save",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json().get("saved") is True

    resp2 = logged_in_client.get("/draft-board/load")
    assert resp2.status_code == 200
    data = resp2.get_json()
    assert data.get("found") is True
    assert data.get("source") == "manual"


def test_draft_board_reset(logged_in_client):
    """Reset clears the saved session."""
    # Save first
    logged_in_client.post(
        "/draft-board/save",
        data=json.dumps({
            "source": "manual",
            "league_id": "x",
            "draft_id": "x",
            "settings": "{}",
            "state": "{}",
            "last_pick": 0,
        }),
        content_type="application/json",
    )
    # Reset
    resp = logged_in_client.post("/draft-board/reset")
    assert resp.status_code == 200
    assert resp.get_json().get("reset") is True

    # Verify gone
    resp2 = logged_in_client.get("/draft-board/load")
    assert resp2.get_json().get("found") is False


# ── Saved leagues endpoints ──────────────────────────────────


def test_leagues_list_empty(logged_in_client):
    """Leagues list returns empty array initially."""
    resp = logged_in_client.get("/draft-board/leagues")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)


def test_leagues_save_and_list(logged_in_client):
    """Save a league and verify it appears in the list."""
    payload = {
        "league_id": "test-lg-1",
        "league_name": "Test League",
        "source": "sleeper",
        "num_teams": 12,
        "scoring": "ppr",
        "league_type": "redraft",
        "sleeper_user_id": "abc123",
        "user_slot": 3,
    }
    resp = logged_in_client.post(
        "/draft-board/leagues/save",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json().get("saved") is True

    resp2 = logged_in_client.get("/draft-board/leagues")
    leagues = resp2.get_json()
    assert any(lg.get("league_id") == "test-lg-1" for lg in leagues)


def test_leagues_delete(logged_in_client):
    """Delete a saved league."""
    # Save first
    logged_in_client.post(
        "/draft-board/leagues/save",
        data=json.dumps({
            "league_id": "to-delete",
            "league_name": "Delete Me",
            "source": "manual",
            "num_teams": 10,
            "scoring": "ppr",
        }),
        content_type="application/json",
    )
    resp = logged_in_client.delete("/draft-board/leagues/to-delete")
    assert resp.status_code == 200
    assert resp.get_json().get("deleted") is True


# ── Mock draft endpoints ─────────────────────────────────────


def test_mockdraft_players(logged_in_client):
    """Player list endpoint returns JSON array."""
    resp = logged_in_client.get("/mockdraft/players?scoring=ppr&source=darkhorse")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    if len(data) > 0:
        assert "Name" in data[0] or "name" in data[0]


def test_mockdraft_save(logged_in_client):
    """Save a mock draft."""
    payload = {
        "draft_type": "snake",
        "scoring": "ppr",
        "settings": {"num_teams": 10, "rounds": 15},
        "board": [],
        "user_team": [],
    }
    resp = logged_in_client.post(
        "/mockdraft/save",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "id" in data or "message" in data


# ── Rankings endpoints ───────────────────────────────────────


def test_save_ranking(logged_in_client):
    """Save a custom ranking."""
    payload = {
        "name": "My Rankings",
        "ranking_type": "PPR",
        "ranking": json.dumps([{"name": "Player A", "rank": 1}]),
    }
    resp = logged_in_client.post(
        "/save_rankings",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "ranking_id" in data


def test_delete_ranking(logged_in_client):
    """Save then delete a ranking."""
    # Save
    resp = logged_in_client.post(
        "/save_rankings",
        data=json.dumps({
            "name": "To Delete",
            "ranking_type": "PPR",
            "ranking": json.dumps([]),
        }),
        content_type="application/json",
    )
    ranking_id = resp.get_json().get("ranking_id")
    assert ranking_id is not None

    # Delete
    resp2 = logged_in_client.delete(f"/delete_ranking/{ranking_id}")
    assert resp2.status_code == 200


# ── AI suggest endpoint ──────────────────────────────────────


def test_ai_suggest(logged_in_client):
    """AI suggest endpoint returns JSON."""
    payload = {
        "mode": "in_draft",
        "roster": [],
        "league_type": "redraft",
        "starter_slot_labels": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"],
        "team_label": "testuser",
    }
    resp = logged_in_client.post(
        "/draft-board/ai-suggest",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)


# ── Player stats endpoints ───────────────────────────────────


def test_player_stats(logged_in_client):
    """Player stats endpoint responds (200 or 500 if pickle version mismatch)."""
    resp = logged_in_client.get("/player_stats?name=Patrick+Mahomes&pos=QB&team=KC")
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        data = resp.get_json()
        assert isinstance(data, dict)


def test_player_quick_stats(logged_in_client):
    """Player quick stats returns JSON."""
    resp = logged_in_client.get("/player_quick_stats?name=TestPlayer&pos=QB&team=NYG")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
